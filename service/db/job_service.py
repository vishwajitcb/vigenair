"""Job service for creating and updating jobs in MongoDB."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.mongodb import get_database, get_main_loop
from db.models import Job, JobStatus, JobStage, Segment

logger = logging.getLogger(__name__)


def _run_async_on_main_loop(coro):
    """Run an async coroutine on the main event loop from a sync context.

    This is used by background tasks running in thread pools to safely
    execute async MongoDB operations on the main event loop where the
    motor client was initialized.

    Args:
        coro: The coroutine to execute.

    Returns:
        The result of the coroutine.

    Raises:
        RuntimeError: If the main event loop is not available.
    """
    main_loop = get_main_loop()
    if main_loop is None:
        raise RuntimeError(
            "Main event loop not initialized. "
            "Ensure init_db() has been called on app startup."
        )

    # Schedule the coroutine on the main loop and wait for result
    future = asyncio.run_coroutine_threadsafe(coro, main_loop)
    return future.result(timeout=30)  # 30 second timeout for safety


async def create_job_async(
    folder: str,
    name: str,
    user_id: str = "default",
    input_video_key: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new job in MongoDB (async version)."""
    db = await get_database()

    job = Job(
        folder=folder,
        name=name,
        userId=user_id,
        inputVideoKey=input_video_key,
        status=JobStatus.PROCESSING,
        stage=JobStage.UPLOADING
    )

    job_dict = job.to_dict()
    await db.jobs.insert_one(job_dict)

    logger.info(f"Created job: {folder}")
    return job_dict


def create_job_sync(
    folder: str,
    name: str,
    user_id: str = "default",
    input_video_key: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new job in MongoDB (sync wrapper).

    Safe to call from background threads - uses run_coroutine_threadsafe
    to schedule on the main event loop.
    """
    return _run_async_on_main_loop(
        create_job_async(folder, name, user_id, input_video_key)
    )


async def update_job_status_async(
    folder: str,
    status: Optional[JobStatus] = None,
    stage: Optional[JobStage] = None,
    error: Optional[str] = None,
    progress: Optional[int] = None
):
    """Update job status in MongoDB (async version)."""
    db = await get_database()

    update_data: Dict[str, Any] = {"updatedAt": datetime.utcnow()}

    if status is not None:
        update_data["status"] = status.value if hasattr(status, "value") else status
    if stage is not None:
        update_data["stage"] = stage.value if hasattr(stage, "value") else stage
    if error is not None:
        update_data["error"] = error
    if progress is not None:
        update_data["progress"] = progress

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data}
    )

    logger.info(f"Updated job status: {folder} -> {status or stage}")


def update_job_status_sync(
    folder: str,
    status: Optional[JobStatus] = None,
    stage: Optional[JobStage] = None,
    error: Optional[str] = None,
    progress: Optional[int] = None
):
    """Update job status in MongoDB (sync wrapper).

    Safe to call from background threads - uses run_coroutine_threadsafe
    to schedule on the main event loop.
    """
    _run_async_on_main_loop(
        update_job_status_async(folder, status, stage, error, progress)
    )


async def update_job_segments_async(
    folder: str,
    segments: List[Dict[str, Any]],
    thumbnail_key: Optional[str] = None
):
    """Update job segments in MongoDB (async version)."""
    db = await get_database()

    update_data: Dict[str, Any] = {
        "updatedAt": datetime.utcnow(),
        "segments": segments,
        "segmentOrder": [s.get("id", str(i)) for i, s in enumerate(segments)],
        "status": JobStatus.SEGMENTS_READY.value,
        "stage": JobStage.DONE.value
    }

    if thumbnail_key:
        update_data["thumbnailKey"] = thumbnail_key

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data}
    )

    logger.info(f"Updated segments for job: {folder} ({len(segments)} segments)")


def update_job_segments_sync(
    folder: str,
    segments: List[Dict[str, Any]],
    thumbnail_key: Optional[str] = None
):
    """Update job segments in MongoDB (sync wrapper).

    Safe to call from background threads - uses run_coroutine_threadsafe
    to schedule on the main event loop.
    """
    _run_async_on_main_loop(
        update_job_segments_async(folder, segments, thumbnail_key)
    )


async def update_job_error_async(folder: str, error: str):
    """Mark job as error in MongoDB (async version)."""
    db = await get_database()

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": {
            "updatedAt": datetime.utcnow(),
            "status": JobStatus.ERROR.value,
            "error": error
        }}
    )

    logger.error(f"Job error: {folder} - {error}")


def update_job_error_sync(folder: str, error: str):
    """Mark job as error in MongoDB (sync wrapper).

    Safe to call from background threads - uses run_coroutine_threadsafe
    to schedule on the main event loop.
    """
    _run_async_on_main_loop(update_job_error_async(folder, error))


async def get_job_async(folder: str) -> Optional[Dict[str, Any]]:
    """Get job from MongoDB (async version)."""
    db = await get_database()
    job_doc = await db.jobs.find_one({"folder": folder})

    if job_doc and "_id" in job_doc:
        del job_doc["_id"]

    return job_doc


def get_job_sync(folder: str) -> Optional[Dict[str, Any]]:
    """Get job from MongoDB (sync wrapper).

    Safe to call from background threads - uses run_coroutine_threadsafe
    to schedule on the main event loop.
    """
    return _run_async_on_main_loop(get_job_async(folder))
