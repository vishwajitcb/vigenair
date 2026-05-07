"""Per-variant Mongo persistence for the LangGraph pipeline.

The pipeline runs as a FastAPI background task (not bound to an HTTP request)
so the only way the frontend learns about progress is by polling the job doc.
This module:

  1. Converts agent-shape variants → `Variant` Pydantic shape (the same shape
     the frontend used to compute client-side, now done server-side).
  2. Pushes each successfully-validated variant onto job.variants atomically.
  3. Sets variantsGenerationStatus on lifecycle transitions.

Boundaries:
  * Called from inside the Validator node (one push per variant kept).
  * Called from runner.run_variant_pipeline before/after the graph runs
    (start = generating + reset variants, end = complete or error).

All writes use motor's main event loop via asyncio.run_coroutine_threadsafe
through db/job_service helpers so we don't accidentally cross loops.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.models import JobStatus, VariantsGenerationStatus
from db.mongodb import get_database

logger = logging.getLogger(__name__)


def _fnv1a_hex(text: str) -> str:
    """FNV-1a 32-bit, matching frontend hashVariantId in
    job-detail.js:17. Same input → same id, so a regenerated variant
    that happens to share title+segments overwrites the prior render
    (existing semantic; preserved here)."""
    h = 0x811c9dc5
    for ch in text:
        h ^= ord(ch) & 0xff
        h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) & 0xffffffff
    return f"v{h:08x}"


def _hash_variant_id(title: str, segments: List[Any]) -> str:
    """Stable id from title + sorted segment ids. Mirrors frontend exactly
    so render filenames stay consistent across regenerations."""
    seg_strs = sorted(str(s) for s in (segments or []))
    return _fnv1a_hex(f"{title or ''}|{','.join(seg_strs)}")


def _normalize_score(raw_score: Any, score_max: Any) -> float:
    """Convert agent-emitted score to the 0–5 star scale the frontend renders.
    Mirrors the normalization in frontend/js/pages/job-detail.js:287-300."""
    try:
        rs = float(raw_score) if raw_score is not None else 3.0
    except (TypeError, ValueError):
        rs = 3.0
    try:
        sm = float(score_max) if score_max else 100.0
    except (TypeError, ValueError):
        sm = 100.0
    if sm <= 0:
        sm = 100.0

    if rs <= 5 and sm == 100.0:
        # Already on a 0–5 scale (legacy / fallback).
        normalized = rs
    else:
        normalized = max(0.0, min(5.0, (rs / sm) * 5.0))
    # Round to 1 decimal place, matching frontend.
    return round(normalized * 10) / 10


def agent_variant_to_storage(
    *,
    agent_variant: Dict[str, Any],
    target_duration: float,
) -> Dict[str, Any]:
    """Convert an agent-shape variant (LangGraph output) to the storage
    shape the frontend reads from MongoDB. This is the same conversion the
    frontend used to do client-side; we now do it server-side because the
    pipeline writes directly."""
    title = agent_variant.get("title") or "Variant"
    raw_segments = agent_variant.get("segments") or []
    segments_str: List[str] = [str(s) for s in raw_segments]

    return {
        "id": _hash_variant_id(title, segments_str),
        "title": title,
        "description": agent_variant.get("description") or "",
        "score": _normalize_score(
            agent_variant.get("score"),
            agent_variant.get("score_max"),
        ),
        "reasoning": agent_variant.get("reasoning") or "",
        "segments": segments_str,
        "duration": float(
            agent_variant.get("estimated_duration")
            or agent_variant.get("actual_duration")
            or target_duration
            or 0.0
        ),
        "userModified": False,
        "angle": agent_variant.get("angle"),
        "hook_scene": agent_variant.get("hook_scene") if isinstance(agent_variant.get("hook_scene"), int) else None,
        "structure": agent_variant.get("structure"),
    }


# ---------- Lifecycle helpers (start / append / finish) ----------

async def mark_generation_started(
    *,
    folder: str,
    generation_settings: Optional[Dict[str, Any]] = None,
) -> None:
    """Reset the job's variants list and flag generation as in-progress."""
    db = await get_database()
    update_data: Dict[str, Any] = {
        "updatedAt": datetime.utcnow(),
        "variants": [],
        "selectedVariantIndex": 0,
        "variantsGenerationStatus": VariantsGenerationStatus.GENERATING.value,
    }
    if generation_settings:
        update_data["generationSettings"] = generation_settings
    # Clear any prior error so a fresh re-run shows clean state.
    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data, "$unset": {"error": ""}},
    )
    logger.info(f"VARIANT_PERSIST: started folder={folder}")


async def append_variant(
    *,
    folder: str,
    storage_variant: Dict[str, Any],
) -> None:
    """Atomically append one variant to the job's variants array.

    Uses $push so concurrent appends from the fan-out wouldn't race —
    even though our Validator node runs sequentially per request, we still
    use $push for correctness."""
    db = await get_database()
    await db.jobs.update_one(
        {"folder": folder},
        {
            "$push": {"variants": storage_variant},
            "$set": {
                "updatedAt": datetime.utcnow(),
            },
        },
    )
    logger.info(
        f"VARIANT_PERSIST: appended id={storage_variant.get('id')} "
        f"title={storage_variant.get('title')!r} folder={folder}"
    )


async def mark_generation_complete(
    *,
    folder: str,
    variant_count: int,
) -> None:
    """Flag generation as complete. If at least one variant survived, also
    bump the job status to VARIANTS_GENERATED (matches the legacy semantic
    used by the existing /jobs/{folder}/variants PATCH route)."""
    db = await get_database()
    update_data: Dict[str, Any] = {
        "updatedAt": datetime.utcnow(),
        "variantsGenerationStatus": VariantsGenerationStatus.COMPLETE.value,
    }
    if variant_count > 0:
        update_data["status"] = JobStatus.VARIANTS_GENERATED.value
    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data},
    )
    logger.info(
        f"VARIANT_PERSIST: complete folder={folder} variants={variant_count}"
    )


async def remove_variant_by_storage_id(
    *,
    folder: str,
    storage_id: str,
) -> None:
    """Remove a single variant by its `id` field. Used by the cross-variant
    validator to undo a $push when a duplicate is detected post-hoc."""
    db = await get_database()
    await db.jobs.update_one(
        {"folder": folder},
        {
            "$pull": {"variants": {"id": storage_id}},
            "$set": {"updatedAt": datetime.utcnow()},
        },
    )
    logger.info(f"VARIANT_PERSIST: pulled id={storage_id} folder={folder}")


async def mark_generation_error(
    *,
    folder: str,
    error_message: str,
) -> None:
    """Flag the run as errored so the frontend stops polling and surfaces
    the failure. Does NOT clear partial variants — the user may still get
    use out of whatever survived."""
    db = await get_database()
    await db.jobs.update_one(
        {"folder": folder},
        {
            "$set": {
                "updatedAt": datetime.utcnow(),
                "variantsGenerationStatus": VariantsGenerationStatus.ERROR.value,
                "error": error_message[:500],
            }
        },
    )
    logger.error(
        f"VARIANT_PERSIST: error folder={folder} err={error_message[:200]!r}"
    )
