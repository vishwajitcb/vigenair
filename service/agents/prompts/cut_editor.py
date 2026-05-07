"""CutEditor prompt — agent 4 of the per-variant chain.

Reads HookAnalyst output + StoryScout candidates + CliffhangerScout candidates
and produces the FINAL variant body (title, angle, segments list, structure,
description, reasoning).

Soft heuristic in the prompt: "at least one transition between adjacent scenes
in the final list must jump >X scene-numbers in source time." The cuts should
FEEL like cuts, not like watching the show in order.

Supports an optional `judge_feedback` block — when AdShapeJudge rejected a
prior pass, we re-call CutEditor with the judge's verdict + rationale as
explicit feedback so the model can correct itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_CUT_EDITOR_PROMPT = """**Role:** You are the FINAL cut editor for a Chai Shots OTT promo clip variant. You decide what scenes ship, in what order, and how the clip is labeled. Other agents have done the scouting; you make the call.

**The hook (locked at frame 0 — DO NOT change):**
*   Scene: {{hookScene}}
*   Hook label: {{hookLabel}}
*   hook_type: {{hookType}}
*   emotion: {{hookEmotion}}
*   dynamic: {{hookDynamic}}
*   character_ids: {{hookCharacterIds}}

**HookAnalyst's read of what this hook promises:**
*   Dramatic question: {{dramaticQuestion}}
*   Emotional beat: {{emotionalBeat}}
*   Who must we see: {{whoMustWeSee}}
*   What's at stake: {{whatMustBeAtStake}}

**StoryScout's candidate story scenes (advisory — pick 2–4 of these for the middle of the clip):**
{{storyCandidates}}

**CliffhangerScout's candidate close scenes (advisory — pick 1–2 of these to close the clip):**
{{cliffhangerCandidates}}

**Target duration:** {{desiredDuration}}s
**Allowed range:** {{expectedDurationRange}}s
**Hard duration cap (do NOT exceed):** {{maxDuration}}s
**Per-scene duration data (for picking — `{scene: duration_s}`):**
{{sceneDurations}}

{{judgeFeedbackBlock}}

**Your decision (output a single JSON object with these fields):**

1.  `title`: 2–4 words. Punchy. May be in {{videoLanguage}}; the rest stays English.
2.  `angle`: of form `<hook_type> | <character_label> | <emotion>`. Pull values from the hook above.
3.  `hook_scene`: integer = the assigned hook's `scene`. Non-negotiable.
4.  `structure`: one of `"chronological"` or `"cold_open_flashback"`.
    *   `"chronological"` — hook is naturally early in source time, story flows forward (Setup → Conflict → Cliffhanger reads in time order).
    *   `"cold_open_flashback"` — drop the viewer into the hook first, then flash back to setup that came earlier in source time, then continue forward to the cliffhanger. Best for `conflict_fight` mid-arguments and `shocking_reveal` hooks.
    *   The Normalizer reorders the `segments` array based on this value, so you do NOT manually sequence — just pick the label and list the scenes.
5.  `segments`: 1-indexed scene numbers — list every scene the variant uses (hook + 2–4 story + 1–2 cliffhanger). Total 4–6 scenes typically. Order doesn't matter; the backend reorders.
6.  `cliffhanger_scenes`: 1 or 2 scene numbers from the CliffhangerScout candidates. Each MUST appear in `segments`. Cannot equal `hook_scene`.
7.  `description`: one sentence teaser, no spoilers, English.
8.  `reasoning`: 2–3 sentences in English explaining WHY this specific cut delivers on the dramatic question. Cite the actual scenes you picked.
9.  `estimated_duration`: float — sum the durations of the scenes you picked using the `sceneDurations` map. The backend dedupes overlaps so this may be a slight overestimate, that's expected.
10. `score`: integer — your honest scoring of how well this cut delivers on the dramatic question (0–100). Pure self-evaluation; this is not a rubric pass.

**HARD CONSTRAINTS:**
*   `segments` length must be in [4, 6].
*   `estimated_duration` must fall within the allowed range and must NOT exceed the hard cap.
*   `hook_scene` must equal the assigned hook scene.
*   Every scene in `segments` must exist in the source script and must have appeared in EITHER the StoryScout candidates OR the CliffhangerScout candidates OR be the hook scene. Do not invent scenes.
*   `cliffhanger_scenes` ⊆ `segments` and is non-empty.
*   No scene appears twice in `segments`.

**SOFT HEURISTIC — the ad-shape rule (read carefully):**

A Chai Shots promo lives or dies on whether it FEELS like an ad or a chunk of the show. The single biggest tell of "chunk of show" is when adjacent scenes in your final segments list are also adjacent in source time. Real promos cut across the runtime.

Rule: at least ONE transition between adjacent scenes in your final ordered list must jump more than {{minSourceTimeJump}} scene-numbers in source time. If your full picks are like [12, 14, 17, 20, 25] (all clustered), you have failed — pick scenes from across the script. If your picks are like [122, 7, 31, 262, 127], adjacent transitions traverse the runtime — that's the ad shape.

**Output JSON (no markdown fences, no preamble):**

```json
{
  "title": "Caught in the Act",
  "angle": "conflict_fight | Wife | betrayal",
  "hook_scene": 122,
  "structure": "cold_open_flashback",
  "segments": [122, 7, 31, 127, 262],
  "cliffhanger_scenes": [262],
  "description": "A late-night phone call. A wife with too many questions. The line gets cut before either of them flinches first.",
  "reasoning": "Hook 122 lands the betrayal punch cold. 7 and 31 jump back to plant the relationship and the lie. 127 is the unspoken-tension snap. 262 closes on her walking toward the door — we never see whether she dials, deletes, or shows him.",
  "estimated_duration": 28.5,
  "score": 82
}
```

Output ONLY the JSON object.
"""


_JUDGE_FEEDBACK_TEMPLATE = """**JUDGE FEEDBACK FROM A PRIOR ATTEMPT — READ AND CORRECT:**

A previous version of this cut was rejected by the AdShapeJudge with the following verdict:

*   verdict: `{{verdict}}`
*   rationale: {{rationale}}

What this verdict means and how to correct it:
*   `off_topic` — at least one of your story scenes did not escalate the dramatic question. Re-read the question and re-pick from StoryScout's candidates more strictly.
*   `show_segment_feel` — your scene picks were too clustered in source time. Spread your picks across the runtime so adjacent transitions traverse the script.
*   `weak_open` — the structure choice or the segment ordering buried the hook. Reconsider whether `cold_open_flashback` would land harder than `chronological`.
*   `weak_close` — your cliffhanger doesn't actually leave the dramatic question unresolved. Re-check CliffhangerScout's options — pick one that genuinely cuts before resolution.

Apply the correction and re-emit a corrected JSON object below.
"""


def assemble(
    *,
    assigned_hook: Dict[str, Any],
    analysis: Dict[str, Any],
    story_candidates: List[Dict[str, Any]],
    cliffhanger_candidates: List[Dict[str, Any]],
    desired_duration: float,
    expected_duration_range: str,
    max_duration: float,
    scene_durations: Dict[int, float],
    video_language: str,
    min_source_time_jump: int = 15,
    judge_feedback: Optional[Dict[str, str]] = None,
) -> str:
    """Build the CutEditor prompt.

    Args:
        scene_durations: Map of {scene_int: duration_s} for every scene the
            CutEditor might pick. Pre-filtered to just the candidate scenes
            (story + cliffhanger + hook) to keep the prompt small.
        min_source_time_jump: Soft threshold for the ad-shape heuristic. The
            CutEditor is told its picks must include at least one adjacent
            transition that jumps >this in source-time.
        judge_feedback: Optional {"verdict": ..., "rationale": ...} from a
            prior AdShapeJudge rejection. When set, the prompt includes the
            correction-feedback block.
    """
    if judge_feedback:
        feedback_block = (
            _JUDGE_FEEDBACK_TEMPLATE
            .replace("{{verdict}}", str(judge_feedback.get("verdict", "?")))
            .replace("{{rationale}}", str(judge_feedback.get("rationale", "?")))
        )
    else:
        feedback_block = ""

    return (
        _CUT_EDITOR_PROMPT
        .replace("{{hookScene}}", str(assigned_hook.get("scene", "?")))
        .replace("{{hookLabel}}", str(assigned_hook.get("label", "?")))
        .replace("{{hookType}}", str(assigned_hook.get("hook_type", "?")))
        .replace("{{hookEmotion}}", str(assigned_hook.get("emotion", "?")))
        .replace("{{hookDynamic}}", str(assigned_hook.get("dynamic") or "(none)"))
        .replace("{{hookCharacterIds}}", str(assigned_hook.get("character_ids", []) or []))
        .replace("{{dramaticQuestion}}", str(analysis.get("dramatic_question", "?")))
        .replace("{{emotionalBeat}}", str(analysis.get("emotional_beat", "?")))
        .replace("{{whoMustWeSee}}", str(analysis.get("who_must_we_see", []) or []))
        .replace("{{whatMustBeAtStake}}", str(analysis.get("what_must_be_at_stake", "?")))
        .replace("{{storyCandidates}}", _format_candidates(story_candidates, "escalates_because"))
        .replace("{{cliffhangerCandidates}}", _format_candidates(cliffhanger_candidates, "leaves_unresolved_because"))
        .replace("{{desiredDuration}}", f"{desired_duration:.1f}")
        .replace("{{expectedDurationRange}}", expected_duration_range)
        .replace("{{maxDuration}}", f"{max_duration:.1f}")
        .replace("{{sceneDurations}}", _format_scene_durations(scene_durations))
        .replace("{{videoLanguage}}", video_language)
        .replace("{{minSourceTimeJump}}", str(min_source_time_jump))
        .replace("{{judgeFeedbackBlock}}", feedback_block)
    )


def _format_candidates(items: List[Dict[str, Any]], reason_key: str) -> str:
    if not items:
        return "  (no candidates available — fall back to picking from script directly, but flag this in your reasoning)"
    return "\n".join(
        f"  * scene {c.get('scene', '?')}: {c.get(reason_key, '(no rationale)')}"
        for c in items
    )


def _format_scene_durations(durations: Dict[int, float]) -> str:
    if not durations:
        return "  (none)"
    return "\n".join(f"  {k}: {v:.1f}s" for k, v in sorted(durations.items()))
