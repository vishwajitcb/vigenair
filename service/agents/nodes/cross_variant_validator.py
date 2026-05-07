"""Cross-variant validator — runs ONCE at end of pipeline.

The per-variant chain (variant_pipeline._run_one_variant) already:
  * normalized segments (dedupe overlaps, reorder, recompute duration)
  * applied per-variant duration check
  * pushed survivors into MongoDB

This node performs the only remaining check that needs a global view:
de-duplication by hook_scene and angle. If a duplicate is found we
$pull it from the Mongo array AND remove it from the in-memory list
so the runner's final return reflects what the frontend will see.

First-wins on collisions: variants are walked in fan-out completion
order, which is the same order they were pushed to Mongo.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from ..persistence import remove_variant_by_storage_id  # added below
from ..state import PipelineState, VariantInProgress

logger = logging.getLogger(__name__)


async def cross_variant_validator(state: PipelineState) -> Dict:
    variants: List[VariantInProgress] = state.get("variants") or []

    seen_angles: set[str] = set()
    seen_hooks: set[int] = set()
    unique: List[VariantInProgress] = []
    folder = state.get("folder")

    for v in variants:
        angle_key = " ".join((v.get("angle") or "").lower().split())
        hook = v.get("hook_scene")
        storage_id = v.get("_storage_id")

        if angle_key and angle_key in seen_angles:
            logger.warning(
                "CROSS_VALIDATOR_DROPPED_DUP_ANGLE title=%r angle=%r id=%s",
                v.get("title"), angle_key, storage_id,
            )
            if folder and storage_id:
                try:
                    await remove_variant_by_storage_id(folder=folder, storage_id=storage_id)
                except Exception as e:
                    logger.warning("CROSS_VALIDATOR: pull failed for %s: %s", storage_id, e)
            continue

        if hook is not None and hook in seen_hooks:
            logger.warning(
                "CROSS_VALIDATOR_DROPPED_DUP_HOOK title=%r hook=%s id=%s",
                v.get("title"), hook, storage_id,
            )
            if folder and storage_id:
                try:
                    await remove_variant_by_storage_id(folder=folder, storage_id=storage_id)
                except Exception as e:
                    logger.warning("CROSS_VALIDATOR: pull failed for %s: %s", storage_id, e)
            continue

        if angle_key:
            seen_angles.add(angle_key)
        if hook is not None:
            seen_hooks.add(hook)
        unique.append(v)

    logger.info(
        "CROSS_VALIDATOR: kept %d/%d variants (dropped %d on cross-variant dupes)",
        len(unique), len(variants), len(variants) - len(unique),
    )
    return {"variants": unique}
