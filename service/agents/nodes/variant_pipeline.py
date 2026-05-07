"""Per-variant agent chain — full pipeline per variant, with live Mongo persist.

Each variant runs through (per-variant, in parallel via asyncio.gather):

    HookAnalyst -> StoryScout -> CliffhangerScout -> CutEditor -> AdShapeJudge
        -> Auditor -> Normalize -> per-variant Validate -> PUSH TO MONGO

Why everything lives in the per-variant chain (not as separate batch graph
nodes anymore): the route handler returns 202 immediately and the pipeline
runs as a background task. The frontend polls the job document. So we want
each variant to land in Mongo the moment it's ready, not at end-of-run.
The legacy batch Auditor / Normalizer nodes are obsolete now — their
per-variant logic is reused here directly.

The graph still has a final 'cross_variant_validator' node that runs once
all per-variant chains have completed, to do the cross-variant uniqueness
check (same hook scene / same angle dupes) and remove any duplicates from
Mongo. This is the only check that requires a global view.

Failure policy:
    * HookAnalyst / StoryScout / CliffhangerScout / CutEditor failure → log,
      DROP this variant. Nothing pushed.
    * AdShapeJudge failure → treat as ad_shape_ok (judge is advisory).
    * Auditor failure → variant continues unchanged (existing behavior).
    * Normalizer failure → variant continues with raw segments.
    * Per-variant duration check failure → DROP variant. Nothing pushed.
    * Cross-variant dup detection → REMOVE from Mongo (ran into rare race).

Concurrency: per-variant chains run in parallel via asyncio.gather. The global
asyncio.Semaphore in service/agents/llm.py caps total in-flight Gemini calls.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from utils.variant_segments import (
    DEFAULT_STRUCTURE,
    VALID_STRUCTURES,
    normalize_variant_segments,
)

from ..llm import call_gemini_text, parse_json_response
from ..persistence import agent_variant_to_storage, append_variant
from ..prompts import (
    ad_shape_judge,
    cliffhanger_scout,
    cut_editor,
    hook_analyst,
    story_scout,
)
from ..schemas import (
    CliffhangerScoutResult,
    CutEditorResult,
    HookAnalysis,
    JudgeVerdict,
    StoryScoutResult,
)
from ..state import PipelineState, VariantInProgress
from .auditor import _audit_one  # reused per-variant; still works fine

logger = logging.getLogger(__name__)


def _hook_scene_description(segments_text: str, hook_scene: int) -> str:
    """Best-effort extraction of one scene's line from the rendered
    `Segment N (Xs): description` block. If we can't find it, we return an
    empty string and the analyst prompt's fallback covers us."""
    needle = f"Segment {hook_scene} ("
    for line in segments_text.splitlines():
        if line.startswith(needle):
            return line
    return ""


def _scene_durations_for_candidates(
    *,
    candidates: List[int],
    segments_by_id: Dict[str, Dict[str, Any]],
) -> Dict[int, float]:
    """Build a {scene_int: duration_s} map for just the scenes CutEditor might
    pick. Keeps the prompt small (we don't dump the full duration table)."""
    out: Dict[int, float] = {}
    for sid in candidates:
        seg = segments_by_id.get(str(sid)) or {}
        dur = float(seg.get("duration_s", 0.0) or 0.0)
        out[int(sid)] = dur
    return out


async def _run_hook_analyst(
    *, label: str, variant: VariantInProgress, state: PipelineState,
) -> Optional[HookAnalysis]:
    assigned_hook = variant.get("assigned_hook") or {}
    hook_scene = assigned_hook.get("scene")
    if hook_scene is None:
        logger.warning("%s ANALYST: no assigned_hook scene — skipping", label)
        return None

    inventory = state.get("hook_inventory") or {}
    characters = inventory.get("characters", []) or []

    prompt = hook_analyst.assemble(
        assigned_hook=assigned_hook,
        hook_scene_description=_hook_scene_description(state["segments_text"], int(hook_scene)),
        characters=characters,
    )
    raw = await call_gemini_text(
        # Gemini 3 thinking mode burns budget on thought_signature tokens
        # before emitting text — give it real headroom or we get
        # finish_reason=MAX_TOKENS with no text out.
        prompt=prompt,
        max_output_tokens=16384,
        temperature=0.4,
        label=f"{label} ANALYST",
    )
    parsed = parse_json_response(raw, label=f"{label} ANALYST")
    return HookAnalysis.model_validate(parsed)


async def _run_story_scout(
    *,
    label: str,
    variant: VariantInProgress,
    state: PipelineState,
    analysis: HookAnalysis,
    cliffhanger_advisory: List[int],
) -> Optional[StoryScoutResult]:
    assigned_hook = variant.get("assigned_hook") or {}
    prompt = story_scout.assemble(
        analysis=analysis.model_dump(),
        hook_scene=int(assigned_hook.get("scene", 0)),
        cliffhanger_candidates_to_avoid=cliffhanger_advisory,
        segments_text=state["segments_text"],
    )
    raw = await call_gemini_text(
        prompt=prompt,
        max_output_tokens=24576,
        temperature=0.6,
        label=f"{label} STORY",
    )
    parsed = parse_json_response(raw, label=f"{label} STORY")
    return StoryScoutResult.model_validate(parsed)


async def _run_cliffhanger_scout(
    *,
    label: str,
    variant: VariantInProgress,
    state: PipelineState,
    analysis: HookAnalysis,
) -> Optional[CliffhangerScoutResult]:
    assigned_hook = variant.get("assigned_hook") or {}
    advisory = list(assigned_hook.get("suggested_cliffhanger_scenes", []) or [])
    prompt = cliffhanger_scout.assemble(
        analysis=analysis.model_dump(),
        hook_scene=int(assigned_hook.get("scene", 0)),
        advisory_candidates=advisory,
        segments_text=state["segments_text"],
    )
    raw = await call_gemini_text(
        prompt=prompt,
        max_output_tokens=16384,
        temperature=0.5,
        label=f"{label} CLIFF",
    )
    parsed = parse_json_response(raw, label=f"{label} CLIFF")
    return CliffhangerScoutResult.model_validate(parsed)


async def _run_cut_editor(
    *,
    label: str,
    variant: VariantInProgress,
    state: PipelineState,
    analysis: HookAnalysis,
    story_candidates_dump: List[Dict[str, Any]],
    cliffhanger_candidates_dump: List[Dict[str, Any]],
    judge_feedback: Optional[Dict[str, str]] = None,
) -> CutEditorResult:
    assigned_hook = variant.get("assigned_hook") or {}
    hook_scene = int(assigned_hook.get("scene", 0))

    candidate_scenes: List[int] = [hook_scene] + [
        int(c["scene"]) for c in story_candidates_dump
    ] + [int(c["scene"]) for c in cliffhanger_candidates_dump]
    scene_durations = _scene_durations_for_candidates(
        candidates=candidate_scenes,
        segments_by_id=state["segments_by_id"],
    )

    prompt = cut_editor.assemble(
        assigned_hook=assigned_hook,
        analysis=analysis.model_dump(),
        story_candidates=story_candidates_dump,
        cliffhanger_candidates=cliffhanger_candidates_dump,
        desired_duration=float(state["target_duration"]),
        expected_duration_range=str(state["expected_duration_range"]),
        max_duration=float(state["max_allowed_duration"]),
        scene_durations=scene_durations,
        video_language=str(state["video_language"]),
        judge_feedback=judge_feedback,
    )
    sub_label = f"{label} CUT-EDITOR" + (":retry" if judge_feedback else "")
    raw = await call_gemini_text(
        prompt=prompt,
        max_output_tokens=32768,
        temperature=0.7,
        label=sub_label,
    )
    parsed = parse_json_response(raw, label=sub_label)
    return CutEditorResult.model_validate(parsed)


async def _run_judge(
    *,
    label: str,
    variant: VariantInProgress,
    state: PipelineState,
    analysis: HookAnalysis,
) -> Optional[JudgeVerdict]:
    """Judge call. Returns None if the LLM call fails — caller treats that as
    ad_shape_ok (judge is advisory under failure)."""
    prompt = ad_shape_judge.assemble(
        analysis=analysis.model_dump(),
        variant=dict(variant),
        segments_text=state["segments_text"],
    )
    sub_label = f"{label} JUDGE"
    try:
        raw = await call_gemini_text(
            prompt=prompt,
            max_output_tokens=8192,
            temperature=0.2,
            label=sub_label,
        )
        parsed = parse_json_response(raw, label=sub_label)
        return JudgeVerdict.model_validate(parsed)
    except Exception as e:
        logger.warning("%s: judge call failed (%s) — treating as ad_shape_ok", sub_label, e)
        return None


def _merge_cut_into_variant(
    *,
    variant: VariantInProgress,
    cut: CutEditorResult,
) -> VariantInProgress:
    """Apply CutEditor output into the working variant dict. Preserves
    `assigned_hook` and any working-state fields the chain has already
    written."""
    out: VariantInProgress = dict(variant)
    out.update(cut.model_dump(exclude_none=True))
    return out


async def _run_one_variant(
    *,
    state: PipelineState,
    variant_idx: int,
    variant: VariantInProgress,
) -> Optional[VariantInProgress]:
    """Run the full 5-stage chain for one variant. Returns the final
    VariantInProgress dict, or None if any of the four mandatory stages
    (Analyst / StoryScout / CliffhangerScout / CutEditor) failed."""
    assigned_hook = variant.get("assigned_hook") or {}
    label = (
        f"V[{variant_idx}] hook={assigned_hook.get('id', 'none')}"
        f"/scene={assigned_hook.get('scene', 'none')}"
    )

    # Stage 1 — HookAnalyst
    try:
        analysis = await _run_hook_analyst(label=label, variant=variant, state=state)
        if analysis is None:
            return None
        variant = dict(variant)
        variant.update({
            "dramatic_question": analysis.dramatic_question,
            "emotional_beat": analysis.emotional_beat,
            "who_must_we_see": list(analysis.who_must_we_see),
            "what_must_be_at_stake": analysis.what_must_be_at_stake,
        })
        logger.info("%s ANALYST: ok — q=%r beat=%r", label, analysis.dramatic_question, analysis.emotional_beat)
    except Exception as e:
        logger.warning("%s ANALYST: failed (%s) — dropping variant", label, e)
        return None

    # Stages 2 & 3 — StoryScout + CliffhangerScout in parallel.
    # They both depend on Analyst's output but not on each other.
    try:
        # Pre-computing the cliffhanger advisory list to give StoryScout the
        # "do NOT include these" guidance up front. We use the assigned hook's
        # suggested_cliffhanger_scenes as a hint — the actual CliffhangerScout
        # output may differ.
        cliff_advisory = list(assigned_hook.get("suggested_cliffhanger_scenes", []) or [])

        story_task = _run_story_scout(
            label=label, variant=variant, state=state,
            analysis=analysis, cliffhanger_advisory=cliff_advisory,
        )
        cliff_task = _run_cliffhanger_scout(
            label=label, variant=variant, state=state, analysis=analysis,
        )
        story_res, cliff_res = await asyncio.gather(story_task, cliff_task)

        if story_res is None or cliff_res is None:
            logger.warning("%s SCOUT: empty result — dropping variant", label)
            return None
        if not story_res.candidates:
            logger.warning("%s STORY: no candidates returned — dropping variant", label)
            return None
        if not cliff_res.candidates:
            logger.warning("%s CLIFF: no candidates returned — dropping variant", label)
            return None

        story_candidates_dump = [c.model_dump() for c in story_res.candidates]
        cliff_candidates_dump = [c.model_dump() for c in cliff_res.candidates]
        variant["story_candidates"] = story_candidates_dump
        variant["cliffhanger_candidates"] = cliff_candidates_dump

        logger.info(
            "%s STORY: %d candidates; CLIFF: %d candidates",
            label, len(story_candidates_dump), len(cliff_candidates_dump),
        )
    except Exception as e:
        logger.warning("%s SCOUT: failed (%s) — dropping variant", label, e)
        return None

    # Stage 4 — CutEditor (first attempt)
    try:
        cut = await _run_cut_editor(
            label=label, variant=variant, state=state,
            analysis=analysis,
            story_candidates_dump=story_candidates_dump,
            cliffhanger_candidates_dump=cliff_candidates_dump,
            judge_feedback=None,
        )
        variant = _merge_cut_into_variant(variant=variant, cut=cut)
        logger.info(
            "%s CUT-EDITOR: ok — title=%r structure=%r segs=%s",
            label, variant.get("title"), variant.get("structure"), variant.get("segments"),
        )
    except Exception as e:
        logger.warning("%s CUT-EDITOR: failed (%s) — dropping variant", label, e)
        return None

    # Stage 5 — AdShapeJudge (with one CutEditor retry on non-ok)
    judge_verdict = await _run_judge(
        label=label, variant=variant, state=state, analysis=analysis,
    )

    if judge_verdict is None:
        # Judge LLM failure → accept variant as-is (judge is advisory).
        variant["judge_verdict"] = "ad_shape_ok"
        variant["judge_rationale"] = "(judge LLM call failed — accepted by default)"
        variant["judge_retried"] = False
    elif judge_verdict.verdict == "ad_shape_ok":
        variant["judge_verdict"] = judge_verdict.verdict
        variant["judge_rationale"] = judge_verdict.rationale
        variant["judge_retried"] = False
        logger.info("%s JUDGE: ok — %s", label, judge_verdict.rationale)
    else:
        # Non-ok — retry CutEditor once with the verdict as feedback.
        logger.info(
            "%s JUDGE: %s — retrying CutEditor (rationale=%r)",
            label, judge_verdict.verdict, judge_verdict.rationale,
        )
        feedback = {"verdict": judge_verdict.verdict, "rationale": judge_verdict.rationale}
        try:
            cut2 = await _run_cut_editor(
                label=label, variant=variant, state=state,
                analysis=analysis,
                story_candidates_dump=story_candidates_dump,
                cliffhanger_candidates_dump=cliff_candidates_dump,
                judge_feedback=feedback,
            )
            variant = _merge_cut_into_variant(variant=variant, cut=cut2)
            logger.info(
                "%s CUT-EDITOR:retry ok — title=%r segs=%s",
                label, variant.get("title"), variant.get("segments"),
            )
        except Exception as e:
            logger.warning(
                "%s CUT-EDITOR:retry failed (%s) — keeping original cut",
                label, e,
            )
        # Re-judge once more, then accept whatever it says.
        judge_verdict2 = await _run_judge(
            label=label, variant=variant, state=state, analysis=analysis,
        )
        if judge_verdict2 is None:
            variant["judge_verdict"] = "ad_shape_ok"
            variant["judge_rationale"] = "(second judge call failed — accepted)"
        else:
            variant["judge_verdict"] = judge_verdict2.verdict
            variant["judge_rationale"] = judge_verdict2.rationale
            logger.info(
                "%s JUDGE:final %s — %s",
                label, judge_verdict2.verdict, judge_verdict2.rationale,
            )
        variant["judge_retried"] = True

    # Stage 6 — Auditor (per-variant, reuses _audit_one). Polish step.
    # Failure here NEVER drops the variant.
    try:
        variant = await _audit_one(
            state=state, variant_idx=variant_idx, variant=variant,
        )
    except Exception as e:
        logger.warning("%s AUDITOR: unexpected failure (%s) — continuing", label, e)

    # Stage 7 — Normalize (deterministic Python: dedupe overlapping segments,
    # reorder per structure, recompute true duration). Failure falls back to
    # raw segment data so the variant is still shippable.
    structure = variant.get("structure")
    if structure not in VALID_STRUCTURES:
        if structure is not None:
            logger.warning(
                "%s NORM_INVALID_STRUCTURE got=%r — defaulting to %s",
                label, structure, DEFAULT_STRUCTURE,
            )
        structure = DEFAULT_STRUCTURE

    raw_seg_ids = variant.get("segments", [])
    # Backfill hook_scene from the first segment if missing.
    if not variant.get("hook_scene") and raw_seg_ids:
        try:
            variant["hook_scene"] = int(raw_seg_ids[0])
        except (TypeError, ValueError):
            variant["hook_scene"] = None
    try:
        ordered_ids, true_dur, _debug = normalize_variant_segments(
            segment_ids=raw_seg_ids,
            segments_by_id=state["segments_by_id"],
            hook_scene=variant.get("hook_scene"),
            structure=structure,
            variant_label=str(variant.get("title", "?")),
        )
    except Exception as norm_err:
        logger.exception("%s NORM_FAIL error=%s", label, norm_err)
        ordered_ids = [str(s) for s in raw_seg_ids]
        # Best-effort duration: sum from segments_by_id.
        true_dur = sum(
            float(state["segments_by_id"].get(str(sid), {}).get("duration_s", 0.0) or 0.0)
            for sid in raw_seg_ids
        )
    if raw_seg_ids and isinstance(raw_seg_ids[0], int):
        variant["segments"] = [int(x) for x in ordered_ids]
    else:
        variant["segments"] = ordered_ids
    variant["structure"] = structure
    variant["actual_duration"] = true_dur
    variant["estimated_duration"] = true_dur

    # Stage 8 — per-variant duration validation. Cross-variant dup checks
    # happen in the final cross_variant_validator graph node.
    max_allowed = float(state.get("max_allowed_duration", 0.0) or 0.0)
    if max_allowed and true_dur > max_allowed:
        logger.warning(
            "%s VALIDATOR_REJECTED_DURATION segs=%s dur=%.1fs cap=%.1fs",
            label, variant.get("segments"), true_dur, max_allowed,
        )
        return None

    # Stamp score_max so the storage-shape converter normalizes the score
    # the same way the frontend used to.
    score_max = state.get("score_max")
    if score_max is not None:
        variant["score_max"] = score_max

    # Stage 9 — push the variant to MongoDB live so the polling frontend
    # picks it up immediately.
    folder = state.get("folder")
    if folder:
        try:
            target_dur = float(state.get("target_duration", 0.0) or 0.0)
            storage_doc = agent_variant_to_storage(
                agent_variant=dict(variant),
                target_duration=target_dur,
            )
            # Stash the storage id back onto the working dict so the
            # cross-variant validator can identify it for $pull if it dupes.
            variant["_storage_id"] = storage_doc["id"]
            await append_variant(folder=folder, storage_variant=storage_doc)
            logger.info(
                "%s PERSIST: pushed id=%s title=%r",
                label, storage_doc["id"], storage_doc["title"],
            )
        except Exception as e:
            logger.warning("%s PERSIST: failed to push variant (%s) — keeping in memory", label, e)

    return variant


async def variant_pipeline(state: PipelineState) -> Dict:
    """Graph node: run the per-variant chain across all seeded variants in
    parallel. Drops variants that fail any of the four mandatory stages.
    Returns the surviving variants in state.variants."""
    seeded: List[VariantInProgress] = state.get("variants") or []
    if not seeded:
        logger.warning("VARIANT_PIPELINE: no seeded variants — nothing to run")
        return {"variants": []}

    coros = [
        _run_one_variant(state=state, variant_idx=i, variant=v)
        for i, v in enumerate(seeded)
    ]
    results = await asyncio.gather(*coros, return_exceptions=False)
    survived = [r for r in results if r is not None]

    # Bookkeeping for log-grep:
    retried = sum(1 for r in survived if r.get("judge_retried"))
    ok_first_try = sum(
        1 for r in survived
        if not r.get("judge_retried") and r.get("judge_verdict") == "ad_shape_ok"
    )
    logger.info(
        "VARIANT_PIPELINE: built %d/%d variants (dropped %d) — judge ok-first-try=%d retried=%d",
        len(survived), len(seeded), len(seeded) - len(survived), ok_first_try, retried,
    )
    return {"variants": survived}
