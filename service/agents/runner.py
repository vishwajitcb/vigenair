"""Entry point for the LangGraph variant-generation pipeline.

Two callable entry points:

  * `run_variant_pipeline(...)` — async, runs the graph and returns the
    surviving variants. Used by background tasks; can also be called by
    legacy synchronous callers if needed.
  * `run_variant_pipeline_background(...)` — wraps `run_variant_pipeline`
    in a try/except, sets variantsGenerationStatus on transitions,
    persists incrementally inside the graph, and never raises (so a
    bug or LLM failure doesn't crash the FastAPI background-task host).

The route handler in api/routes/segments.py schedules the background
variant via FastAPI's BackgroundTasks; the frontend polls the job doc
to learn when variants are ready.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config import variant_prompts

from .graph import build_graph
from .persistence import (
    mark_generation_complete,
    mark_generation_error,
    mark_generation_started,
)
from .state import PipelineState

logger = logging.getLogger(__name__)

# Compile once at import. Pure metadata; no network/auth side effects.
_GRAPH = build_graph()


# Working-state fields written by the per-variant chain. Stay server-side
# for log analysis (`docker logs ... | grep JUDGE`) but never ship to the
# frontend. Used both for the legacy sync return path and as a reference
# list — Mongo persistence already stores the storage-shape, not these.
_INTERNAL_ONLY_FIELDS = (
    "assigned_hook",
    "dramatic_question",
    "emotional_beat",
    "who_must_we_see",
    "what_must_be_at_stake",
    "story_candidates",
    "cliffhanger_candidates",
    "judge_verdict",
    "judge_rationale",
    "judge_retried",
    "_storage_id",
)


async def run_variant_pipeline(
    *,
    folder: str,
    request_params: Dict[str, Any],
    segments_text: str,
    segments_by_id: Dict[str, Dict[str, Any]],
    eligible_indices: List[int],
    num_variants: int,
    target_duration: float,
    expected_duration_range: str,
    max_allowed_duration: float,
    video_language: str,
) -> List[Dict[str, Any]]:
    """Run the agent pipeline end-to-end.

    Variants are pushed to MongoDB by the per-variant chain as they finish.
    The list returned here is the in-memory survivor set — handy for tests
    and any caller that wants to see what shipped without re-reading Mongo.
    """
    initial_state: PipelineState = {
        "folder": folder,
        "request_params": request_params,
        "segments_text": segments_text,
        "segments_by_id": segments_by_id,
        "eligible_indices": eligible_indices,
        "num_variants": num_variants,
        "target_duration": target_duration,
        "expected_duration_range": expected_duration_range,
        "max_allowed_duration": max_allowed_duration,
        "video_language": video_language,
        "score_max": variant_prompts.get_score_max(request_params.get("business_objective")),
        "hook_inventory": None,
        "hook_inventory_block": "",
        "assignment": [],
        "variants": [],
    }

    logger.info(
        "LANGGRAPH_RUN: folder=%s n=%d target=%.1fs cap=%.1fs lang=%s",
        folder, num_variants, target_duration, max_allowed_duration, video_language,
    )

    final_state = await _GRAPH.ainvoke(initial_state)

    out_variants = final_state.get("variants", []) or []
    cleaned: List[Dict[str, Any]] = []
    for v in out_variants:
        v = dict(v)
        for k in _INTERNAL_ONLY_FIELDS:
            v.pop(k, None)
        cleaned.append(v)

    logger.info("LANGGRAPH_RUN: returning %d variants", len(cleaned))
    return cleaned


async def run_variant_pipeline_background(
    *,
    folder: str,
    request_params: Dict[str, Any],
    segments_text: str,
    segments_by_id: Dict[str, Dict[str, Any]],
    eligible_indices: List[int],
    num_variants: int,
    target_duration: float,
    expected_duration_range: str,
    max_allowed_duration: float,
    video_language: str,
    generation_settings: Optional[Dict[str, Any]] = None,
) -> None:
    """Background-task entry point. Owns the full lifecycle:

      1. mark_generation_started → variantsGenerationStatus=GENERATING,
         variants=[] (clears any previous run).
      2. Run the graph. The per-variant chain pushes to Mongo as variants
         finish, so the polling frontend sees them appear live.
      3. On clean completion: mark_generation_complete with the final count.
      4. On unexpected failure: mark_generation_error.

    NEVER raises — bugs or LLM failures must not crash the FastAPI
    background-task host. All errors are logged + persisted to the job doc.
    """
    try:
        await mark_generation_started(
            folder=folder,
            generation_settings=generation_settings,
        )
    except Exception as e:
        logger.exception("LANGGRAPH_BG: mark_generation_started failed for %s: %s", folder, e)
        # If we can't even start, there's no point trying to run.
        try:
            await mark_generation_error(folder=folder, error_message=f"setup: {e}")
        except Exception:
            pass
        return

    try:
        survivors = await run_variant_pipeline(
            folder=folder,
            request_params=request_params,
            segments_text=segments_text,
            segments_by_id=segments_by_id,
            eligible_indices=eligible_indices,
            num_variants=num_variants,
            target_duration=target_duration,
            expected_duration_range=expected_duration_range,
            max_allowed_duration=max_allowed_duration,
            video_language=video_language,
        )
        await mark_generation_complete(folder=folder, variant_count=len(survivors))
    except Exception as e:
        logger.exception("LANGGRAPH_BG: pipeline failed for %s: %s", folder, e)
        try:
            await mark_generation_error(folder=folder, error_message=str(e))
        except Exception:
            pass
