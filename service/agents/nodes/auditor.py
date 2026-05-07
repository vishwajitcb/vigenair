"""Auditor node — fan-out, one Gemini call per built variant.

Asks Gemini whether 0..N additional story scenes would materially raise the
dramatic stakes of the hook, and inserts approved scenes into the variant's
`segments` list. The Normalizer downstream will dedupe overlaps and reorder
per structure.

The audit prompt is inlined here (rather than imported from variant_prompts)
so the LangGraph pipeline is self-contained.

Failure policy: per-variant audit failure → log + skip (variant continues
unchanged). The audit is a polish step; missing it never drops a variant.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..llm import call_gemini_text, parse_json_response
from ..schemas import AuditResult
from ..state import PipelineState, VariantInProgress

logger = logging.getLogger(__name__)


_AUDIT_PROMPT = """**Role:** You are a senior promo editor reviewing a constructed Chai Shots OTT promo clip variant. The variant has already been built (hook locked at frame 0, story scenes selected, cliffhangers locked). Your ONLY job is to decide whether 0–{{maxInsertions}} additional **story scenes** would *materially raise the dramatic stakes of the hook* — and if so, which.

**The variant being audited:**
*   Title: {{variantTitle}}
*   Angle: {{variantAngle}}
*   Hook scene: {{variantHook}}  (plays at frame 0, LOCKED — do NOT touch)
*   Cliffhanger scenes: {{variantCliffhangers}}  (close the clip in this order, LOCKED — do NOT touch)
*   Structure: {{variantStructure}}  (hook_first | cold_open_flashback | chronological)
*   Currently selected scenes (in render order): {{variantSegments}}
*   Current estimated duration: {{variantDuration}}s
*   Available slack within duration range: up to {{slackSeconds}}s of insertions allowed.

**The ONE criterion for an insertion (apply to every candidate):**

> Does this single scene, on its own, materially raise the dramatic stakes of the hook — making the viewer care MORE about the unresolved question the cliffhanger withholds?

If the answer is anything less than a confident yes, do NOT insert it. Returning an empty list is the correct, expected answer most of the time. The Builder already picked the strongest story scenes; you are looking for at most a few high-value additions, not filler.

**Hard rejection criteria — never insert a scene that:**
*   Is a "bridge" between two existing scenes (a connector that makes the cuts feel smoother). Bridges turn the variant into a continuous show segment. We WANT the cuts to feel like cuts.
*   Orients the viewer with backstory or context-setting before the hook. The hook is a cold open. Context belongs *after* it, not before.
*   Lands a closing beat or alternate ending. Cliffhangers are locked.
*   Is atmospheric (an establishing shot, a landscape, a tonal interlude with no character POV).
*   Is pure exposition (a character explaining the plot, a flashback recap, a voiceover dump).
*   Resolves any tension — a character backing down, a question being answered, a conflict cooling off.
*   Is a spoiler (climax reveal, twist payoff, finale resolution).
*   Equals the hook_scene (already in the variant) or any cliffhanger scene (locked).

**Source script (full scene-by-scene listing):**
{{videoScript}}

**Output JSON shape (no other text, no markdown fences):**

```json
{
  "insertions": [12],
  "rationale": "Scene 12 shows the wife privately reading the suspect text she confronts him about in scene 7. It raises the stakes of the hook by proving she had real evidence before the fight, not just suspicion."
}
```

If no insertion clears the bar, return:

```json
{
  "insertions": [],
  "rationale": "Variant already builds the hook's dramatic question with its current story scenes. No additional scene materially raises the stakes."
}
```

**Field rules:**
*   `insertions`: array of integers, 1-indexed scene numbers from the source script. Must exist in the script. Must NOT include the hook_scene or any cliffhanger scene. Maximum {{maxInsertions}} insertions. Empty list is a perfectly valid — and often correct — answer.
*   `rationale`: 1–3 sentence English explanation. Each insertion's justification must explicitly say HOW it raises the dramatic stakes of the hook. If your rationale reads like "improves flow" or "bridges the cut" or "orients the viewer," reject the insertion.
*   Output ONLY the JSON object. No markdown fences, no preamble.
"""


def _assemble_audit_prompt(
    *,
    variant: Dict[str, Any],
    segments_text: str,
    slack_seconds: float,
    max_insertions: int,
) -> str:
    return (
        _AUDIT_PROMPT
        .replace("{{variantTitle}}", str(variant.get("title", "?")))
        .replace("{{variantAngle}}", str(variant.get("angle", "?")))
        .replace("{{variantHook}}", str(variant.get("hook_scene", "?")))
        .replace("{{variantCliffhangers}}", str(variant.get("cliffhanger_scenes", []) or []))
        .replace("{{variantStructure}}", str(variant.get("structure", "hook_first")))
        .replace("{{variantSegments}}", str(variant.get("segments", [])))
        .replace("{{variantDuration}}", f"{float(variant.get('estimated_duration', 0) or 0):.1f}")
        .replace("{{slackSeconds}}", f"{slack_seconds:.1f}")
        .replace("{{videoScript}}", segments_text)
        .replace("{{maxInsertions}}", str(max_insertions))
    )


def _slack_seconds(state: PipelineState, variant: VariantInProgress) -> float:
    """Available headroom under the duration cap, used to bound insertions."""
    cap = state.get("max_allowed_duration", 0.0)
    cur = float(variant.get("estimated_duration", 0.0) or 0.0)
    return max(0.0, cap - cur)


async def _audit_one(
    *,
    state: PipelineState,
    variant_idx: int,
    variant: VariantInProgress,
) -> VariantInProgress:
    """Audit one variant. Returns variant (possibly with merged insertions)
    or the original variant unchanged if anything fails."""
    label = f"AUDITOR:idx={variant_idx},title={variant.get('title')!r}"

    slack = _slack_seconds(state, variant)
    if slack <= 0.5:
        logger.info("%s: no slack (slack=%.2fs) — skipping audit", label, slack)
        return variant

    # Heuristic: max ~2 insertions per variant. Mirrors the prompt's intent.
    max_insertions = 2

    prompt = _assemble_audit_prompt(
        variant=dict(variant),
        segments_text=state["segments_text"],
        slack_seconds=slack,
        max_insertions=max_insertions,
    )

    try:
        raw = await call_gemini_text(
            prompt=prompt,
            max_output_tokens=4096,
            temperature=0.3,
            label=label,
        )
        logger.info(f"{label}: raw head={raw[:300]!r}")
        parsed = parse_json_response(raw, label=label)
        result = AuditResult.model_validate(parsed)

        # Filter insertions: must exist in eligible_indices, must not duplicate
        # hook_scene / cliffhangers / existing segments.
        eligible_set = set(state["eligible_indices"])
        existing = set(_to_int_list(variant.get("segments", [])))
        hook_scene = variant.get("hook_scene")
        cliffhangers = set(int(x) for x in (variant.get("cliffhanger_scenes") or []) if isinstance(x, int))

        clean_insertions: List[int] = []
        for ins in result.insertions[:max_insertions]:
            if ins not in eligible_set:
                logger.info("%s: dropped insertion %d (not eligible)", label, ins)
                continue
            if ins == hook_scene or ins in cliffhangers:
                logger.info("%s: dropped insertion %d (locked slot)", label, ins)
                continue
            if ins in existing:
                logger.info("%s: dropped insertion %d (already in variant)", label, ins)
                continue
            clean_insertions.append(ins)
            existing.add(ins)

        if not clean_insertions:
            logger.info("%s: 0 insertions accepted (model said: %r)", label, result.rationale)
            return variant

        # Merge insertions into segments. Order doesn't matter — Normalizer reorders.
        merged_segments = list(variant.get("segments", [])) + clean_insertions
        out: VariantInProgress = dict(variant)
        out["segments"] = merged_segments
        out["audited"] = True
        out["audit_insertions"] = clean_insertions
        logger.info(
            "%s: merged %d insertions: %s (rationale=%r)",
            label, len(clean_insertions), clean_insertions, result.rationale,
        )
        return out

    except Exception as e:
        logger.warning("%s: audit failed (%s) — keeping variant unchanged", label, e)
        return variant


def _to_int_list(seq) -> List[int]:
    """Best-effort coerce segment IDs to ints for set comparisons."""
    out: List[int] = []
    for x in seq or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


async def auditor(state: PipelineState) -> Dict:
    variants: List[VariantInProgress] = state.get("variants") or []
    if not variants:
        logger.info("AUDITOR: no variants to audit")
        return {"variants": []}

    coros = [
        _audit_one(state=state, variant_idx=i, variant=v)
        for i, v in enumerate(variants)
    ]
    results = await asyncio.gather(*coros, return_exceptions=False)

    audited_count = sum(1 for r in results if r.get("audited"))
    logger.info("AUDITOR: %d/%d variants received insertions", audited_count, len(results))
    return {"variants": list(results)}
