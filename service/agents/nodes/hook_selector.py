"""HookSelector node — deterministic hook assignment (no LLM call).

Wraps select_hooks_for_assignment in a graph node. If hook_inventory is None
(HookScout's two attempts both failed) we seed zero variants — the 5-agent
per-variant chain requires a real assigned_hook and there's no longer a
legacy self-pick fallback. The pipeline will return 0 variants in that case,
which the route handler surfaces to the frontend as an empty result.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from config import variant_prompts

from ..state import PipelineState

logger = logging.getLogger(__name__)


def hook_selector(state: PipelineState) -> Dict:
    inventory = state.get("hook_inventory")
    num_variants = state["num_variants"]

    if not inventory or not inventory.get("hooks"):
        logger.warning(
            "HOOK_SELECTOR: no inventory — seeding 0 variants. The 5-agent "
            "chain requires HookScout output; pipeline will return empty."
        )
        return {
            "assignment": [],
            "hook_inventory_block": "",
            "variants": [],
        }

    valid_hooks: List[Dict[str, Any]] = inventory["hooks"]
    assignment = variant_prompts.select_hooks_for_assignment(valid_hooks, num_variants)

    logger.info(
        "HOOK_SELECTOR: assigned %d hooks for %d variants — %s",
        len(assignment), num_variants,
        [(h.get("id"), h.get("scene"), h.get("hook_type"), h.get("dynamic"))
         for h in assignment],
    )

    return {
        "assignment": assignment,
        "hook_inventory_block": "",
        "variants": [{"assigned_hook": h} for h in assignment],
    }
