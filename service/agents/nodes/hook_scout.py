"""HookScout node — Pass 1 of the variant pipeline.

Calls Gemini with the existing assemble_hook_inventory_prompt to enumerate
hook candidates across the full script. The 5-agent variant_pipeline that
follows REQUIRES an inventory (the per-variant chain depends on a real
assigned_hook for HookAnalyst to reason about) — so on Pass 1 failure we
retry once and only then give up. The downstream pipeline returns 0
variants in the giving-up case (and the route handler's response surfaces
that as a quiet empty result; failure policy is "log loudly, drop, return
what survives").
"""

from __future__ import annotations

import logging
from typing import Dict

from config import variant_prompts

from ..llm import call_gemini_text, parse_json_response
from ..schemas import HookInventory
from ..state import PipelineState

logger = logging.getLogger(__name__)


async def _attempt_hook_inventory(
    *,
    prompt: str,
    eligible_indices_set: set,
    segments_count: int,
    label: str,
) -> Dict:
    """One attempt: call Gemini, parse, filter. Raises on any failure so the
    caller can decide whether to retry."""
    raw = await call_gemini_text(
        prompt=prompt,
        max_output_tokens=32768,
        temperature=0.5,
        label=label,
    )
    logger.info(f"{label}: raw head={raw[:300]!r}")
    parsed = parse_json_response(raw, label=label)
    inventory = HookInventory.model_validate(parsed)

    if not inventory.hooks:
        raise ValueError("Pass 1 returned no hooks")

    valid_hooks = [
        h for h in inventory.hooks
        if isinstance(h.scene, int)
        and 1 <= h.scene <= segments_count
        and h.scene in eligible_indices_set
    ]
    if len(valid_hooks) != len(inventory.hooks):
        logger.warning(
            "%s: filtered %d hooks pointing at missing/ineligible scenes",
            label, len(inventory.hooks) - len(valid_hooks),
        )
    if not valid_hooks:
        raise ValueError("Pass 1 hooks all pointed at invalid scenes")

    inventory_dict = parsed
    inventory_dict["hooks"] = [h.model_dump() for h in valid_hooks]

    logger.info(
        "%s: success — %d valid hooks (of %d emitted)",
        label, len(valid_hooks), len(inventory.hooks),
    )
    return inventory_dict


async def hook_scout(state: PipelineState) -> Dict:
    """Run Pass 1 hook inventory. Retry once on failure (the 5-agent
    variant_pipeline cannot operate without an inventory). On exhausted
    retries, return None and let downstream nodes drop all variants."""
    request_params = state["request_params"]
    shorten_video = request_params.get("shorten_video", True)
    prompt_option = request_params.get("prompt_option") or "default"

    # Aspect-ratio-only and crop-only modes don't use hooks (they include
    # all scenes); skip the inventory for them. The new 5-agent chain isn't
    # designed for these modes anyway — they should route to the legacy
    # path, which segments.py handles by checking USE_LANGGRAPH BEFORE
    # entering this graph. If we get here in those modes, just no-op.
    if not shorten_video or prompt_option == "crop-only":
        logger.info(
            "HOOK_SCOUT: skipping (shorten_video=%s, prompt_option=%s) — "
            "hook pass not applicable",
            shorten_video, prompt_option,
        )
        return {"hook_inventory": None, "hook_inventory_block": ""}

    eligible_indices = state["eligible_indices"]
    segments_count = max(eligible_indices) if eligible_indices else 0
    eligible_set = set(eligible_indices)

    prompt = variant_prompts.assemble_hook_inventory_prompt(
        segments_text=state["segments_text"],
        num_variants=state["num_variants"],
        video_language=state["video_language"],
    )

    last_err = None
    for attempt in (1, 2):
        try:
            inventory_dict = await _attempt_hook_inventory(
                prompt=prompt,
                eligible_indices_set=eligible_set,
                segments_count=segments_count,
                label=f"HOOK_SCOUT:try{attempt}",
            )
            return {"hook_inventory": inventory_dict, "hook_inventory_block": ""}
        except Exception as e:
            last_err = e
            logger.warning(
                "HOOK_SCOUT:try%d failed (%s)%s",
                attempt, e,
                " — retrying once" if attempt == 1 else " — giving up",
            )

    logger.error(
        "HOOK_SCOUT: both attempts failed (last error: %s) — pipeline will "
        "return 0 variants since the per-variant chain requires an inventory",
        last_err,
    )
    return {"hook_inventory": None, "hook_inventory_block": ""}
