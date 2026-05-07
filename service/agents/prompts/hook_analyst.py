"""HookAnalyst prompt — agent 1 of the per-variant chain.

Answers: "what does THIS hook promise the viewer?"

Does NOT pick scenes. Sets up the dramatic question that the rest of the chain
(StoryScout, CliffhangerScout, CutEditor) reasons against.
"""

from __future__ import annotations

from typing import Any, Dict, List


_HOOK_ANALYST_PROMPT = """**Role:** You are a senior promo strategist for Chai Shots OTT, a vertical-format Indian streaming platform. You read one specific hook scene from a longer-form show and articulate exactly what it promises a viewer who scrolls past it.

**You are NOT picking story scenes, cliffhangers, or sequencing anything.** Other agents do that. Your only job is to write down — in tight, specific language — what dramatic promise this hook is making.

**The assigned hook:**
*   Scene number: {{hookScene}}
*   Hook label: {{hookLabel}}
*   Hook type: {{hookType}}
*   Emotion tag: {{hookEmotion}}
*   Character dynamic: {{hookDynamic}}
*   Anchoring characters: {{hookCharacterIds}}

**Hook scene description (verbatim from the source script):**
{{hookSceneDescription}}

**Cast list (id → label):**
{{characterList}}

**Your output is a JSON object with these four fields:**

1.  `dramatic_question` — one sentence, in the form of an actual question the viewer is silently asking after the first 1.5 seconds of this hook. Specific, not vague. ✗ "what's going on?" ✓ "Did her husband actually call that other woman, and what is she going to do about it?"
2.  `emotional_beat` — the dominant feeling the hook PLANTS in the viewer (suspense, betrayal, longing, dread, jealousy, curiosity, etc.). One word or short phrase.
3.  `who_must_we_see` — array of character ids whose faces/POV must appear in the rest of the clip for this hook to pay off. Drawn from the cast list above. Usually 1–3.
4.  `what_must_be_at_stake` — one sentence answering "what does the protagonist STAND TO LOSE if this question goes the wrong way?" Concrete (relationship, reputation, safety), not abstract.

**Output JSON shape (no markdown fences, no preamble, no commentary — just the object):**

```json
{
  "dramatic_question": "Did her husband actually call that other woman, and what is she going to do about it?",
  "emotional_beat": "betrayal-tinged suspense",
  "who_must_we_see": ["C1", "C2"],
  "what_must_be_at_stake": "The wife's marriage and her sense of who she thought her husband was."
}
```

Output ONLY the JSON object.
"""


def assemble(
    *,
    assigned_hook: Dict[str, Any],
    hook_scene_description: str,
    characters: List[Dict[str, Any]],
) -> str:
    """Build the HookAnalyst prompt.

    Args:
        assigned_hook: One Hook dict from state.assignment.
        hook_scene_description: The verbatim description line for this scene
            from segments_text (so we don't dump the whole script).
        characters: List of character dicts from state.hook_inventory.
    """
    char_lines = "\n".join(
        f"  * {c.get('id')}: {c.get('label', '?')}" for c in characters
    ) or "  (no character list available)"
    return (
        _HOOK_ANALYST_PROMPT
        .replace("{{hookScene}}", str(assigned_hook.get("scene", "?")))
        .replace("{{hookLabel}}", str(assigned_hook.get("label", "?")))
        .replace("{{hookType}}", str(assigned_hook.get("hook_type", "?")))
        .replace("{{hookEmotion}}", str(assigned_hook.get("emotion", "?")))
        .replace("{{hookDynamic}}", str(assigned_hook.get("dynamic") or "(none)"))
        .replace("{{hookCharacterIds}}", str(assigned_hook.get("character_ids", []) or []))
        .replace("{{hookSceneDescription}}", hook_scene_description or "(scene description unavailable)")
        .replace("{{characterList}}", char_lines)
    )
