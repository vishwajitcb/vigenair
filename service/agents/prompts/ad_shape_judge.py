"""AdShapeJudge prompt — agent 5 of the per-variant chain.

Reads CutEditor's final variant + the source script + the HookAnalyst's
dramatic-question read, and returns a single categorical verdict:

    ad_shape_ok | off_topic | show_segment_feel | weak_open | weak_close

Plus a one-sentence rationale. Non-ok triggers ONE retry of CutEditor with the
verdict + rationale as feedback. After the retry, whatever this judge returns
is final — we don't loop further and we don't drop on quality alone.
"""

from __future__ import annotations

from typing import Any, Dict, List


_AD_SHAPE_JUDGE_PROMPT = """**Role:** You are the final ad-shape judge for a Chai Shots OTT promo clip variant. The clip has been constructed by other agents (HookAnalyst, StoryScout, CliffhangerScout, CutEditor). You decide whether it lands as an AD or whether it reads like a chunk of the show.

**Your output is one of exactly five verdicts** (no others):

1.  `ad_shape_ok` — the clip works as an ad. Hook lands, story escalates the dramatic question, cliffhanger genuinely cuts before resolution.
2.  `off_topic` — at least one story scene does NOT escalate the hook's dramatic question. The variant has filler.
3.  `show_segment_feel` — scenes are too clustered in source time. Adjacent picks read as a continuous chunk of the show, not as cuts. The viewer feels like they're watching the show, not an ad.
4.  `weak_open` — the structure or scene order buries the hook. The first 1.5 seconds don't pop.
5.  `weak_close` — the cliffhanger scene actually resolves the dramatic question, or lands on a flat beat. The ad doesn't pull a follow-up watch.

**Be honest, not generous.** A confident `ad_shape_ok` is rare. Most variants have at least one weakness. We use your verdict to decide whether to retry the CutEditor — false positives (you say ok when it isn't) waste the only retry we get.

**Inputs:**

**HookAnalyst's read of what the hook promises:**
*   Dramatic question: {{dramaticQuestion}}
*   What's at stake: {{whatMustBeAtStake}}

**The constructed variant under review:**
*   Title: {{title}}
*   Angle: {{angle}}
*   Hook scene: {{hookScene}}  (must play first)
*   Structure: {{structure}}
*   Segments (in the order CutEditor listed them — backend will reorder per structure): {{segments}}
*   Cliffhanger scenes (must close the clip): {{cliffhangerScenes}}
*   Estimated duration: {{estimatedDuration}}s
*   Description: {{description}}
*   Reasoning the editor wrote: {{reasoning}}

**Source script (1-indexed, full):**
{{videoScript}}

**Your check — apply each test in order. Stop at the FIRST verdict that fits (other than `ad_shape_ok`):**

1.  Walk through each scene in `segments` (other than the hook and cliffhangers). For each, ask: does this scene specifically escalate the dramatic question above? If you find a scene that doesn't — verdict `off_topic`.

2.  Order the segments by 1-indexed scene number ascending and look at the gaps between adjacent picks. Are most gaps small (e.g., scenes 12, 14, 16, 18)? That's the show-segment feel. If at least one transition does NOT jump >15 scene-numbers, verdict `show_segment_feel`.

3.  Read the hook scene's description. Does it land as a cold open in 1.5 seconds? Or does it require setup that hasn't been provided? If the hook genuinely cannot work as a cold open here — verdict `weak_open`.

4.  Read each cliffhanger scene. Does any of them resolve the dramatic question (a character backing down, a question being answered, a tension breaking)? If yes — verdict `weak_close`.

5.  If all four checks pass — verdict `ad_shape_ok`.

**Output JSON shape (no markdown fences, no preamble):**

```json
{
  "verdict": "off_topic",
  "rationale": "Scene 17 is a comic interlude with the friend group that doesn't touch the wife-husband dramatic question — it deflates the buildup."
}
```

The `rationale` is one sentence and must point to a specific scene number when applicable. No vague language ("feels off", "could be better"). If `verdict` is `ad_shape_ok`, the rationale states the strongest thing the variant does (one specific reason it works as an ad).

Output ONLY the JSON object.
"""


def assemble(
    *,
    analysis: Dict[str, Any],
    variant: Dict[str, Any],
    segments_text: str,
) -> str:
    return (
        _AD_SHAPE_JUDGE_PROMPT
        .replace("{{dramaticQuestion}}", str(analysis.get("dramatic_question", "?")))
        .replace("{{whatMustBeAtStake}}", str(analysis.get("what_must_be_at_stake", "?")))
        .replace("{{title}}", str(variant.get("title", "?")))
        .replace("{{angle}}", str(variant.get("angle", "?")))
        .replace("{{hookScene}}", str(variant.get("hook_scene", "?")))
        .replace("{{structure}}", str(variant.get("structure", "chronological")))
        .replace("{{segments}}", str(variant.get("segments", []) or []))
        .replace("{{cliffhangerScenes}}", str(variant.get("cliffhanger_scenes", []) or []))
        .replace("{{estimatedDuration}}", f"{float(variant.get('estimated_duration', 0) or 0):.1f}")
        .replace("{{description}}", str(variant.get("description", "?")))
        .replace("{{reasoning}}", str(variant.get("reasoning", "?")))
        .replace("{{videoScript}}", segments_text)
    )
