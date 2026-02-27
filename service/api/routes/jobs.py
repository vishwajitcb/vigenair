"""Job management API routes."""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from db.mongodb import get_database
from db.models import (
    Job, JobCreate, JobUpdate, JobListItem, JobStatus, JobStage,
    Variant, GenerationSettings, RenderQueueItem, Render, UIState
)
from storage.storage import get_presigned_url

logger = logging.getLogger(__name__)

router = APIRouter()


class JobListResponse(BaseModel):
    """Response model for job list."""
    jobs: List[JobListItem]
    total: int
    page: int
    pageSize: int


class JobResponse(BaseModel):
    """Response model for single job with presigned URLs."""
    job: Dict[str, Any]


# Helper functions
async def _get_job_by_folder(folder: str) -> Optional[Dict[str, Any]]:
    """Get job document by folder name."""
    db = await get_database()
    return await db.jobs.find_one({"folder": folder})


async def _generate_presigned_urls_for_job(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add presigned URLs to job data."""
    # Input video URL
    if job_data.get("inputVideoKey"):
        try:
            job_data["inputVideoUrl"] = get_presigned_url(job_data["inputVideoKey"])
        except Exception as e:
            logger.warning(f"Failed to generate presigned URL for input video: {e}")
            job_data["inputVideoUrl"] = None

    # Thumbnail URL
    if job_data.get("thumbnailKey"):
        try:
            job_data["thumbnailUrl"] = get_presigned_url(job_data["thumbnailKey"])
        except Exception as e:
            logger.warning(f"Failed to generate presigned URL for thumbnail: {e}")
            job_data["thumbnailUrl"] = None

    # Segment URLs
    folder = job_data.get("folder", "")
    for segment in job_data.get("segments", []):
        segment_id = segment.get("id")
        if segment_id:
            try:
                video_key = f"{folder}/av_segments_cuts/{segment_id}.mp4"
                thumb_key = f"{folder}/av_segments_cuts/{segment_id}.jpg"
                segment["videoUrl"] = get_presigned_url(video_key)
                segment["thumbnailUrl"] = get_presigned_url(thumb_key)
            except Exception as e:
                logger.warning(f"Failed to generate presigned URLs for segment {segment_id}: {e}")

    # Render URLs
    for render in job_data.get("renders", []):
        formats = render.get("formats", {})
        for fmt, fmt_data in formats.items():
            if isinstance(fmt_data, dict) and fmt_data.get("key"):
                try:
                    fmt_data["url"] = get_presigned_url(fmt_data["key"])
                except Exception as e:
                    logger.warning(f"Failed to generate presigned URL for render format {fmt}: {e}")

    return job_data


# Routes

@router.get("", response_model=JobListResponse)
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    search: Optional[str] = Query(None, description="Search by name"),
    sort: str = Query("createdAt", description="Sort field"),
    order: str = Query("desc", description="Sort order (asc/desc)"),
    page: int = Query(1, ge=1, description="Page number"),
    pageSize: int = Query(20, ge=1, le=100, description="Items per page")
):
    """List all jobs with pagination and filtering."""
    db = await get_database()

    # Build query - exclude soft-deleted jobs
    query: Dict[str, Any] = {"deleted": {"$ne": True}}

    if status:
        query["status"] = status

    if search:
        query["name"] = {"$regex": search, "$options": "i"}

    # Sort direction
    sort_dir = -1 if order == "desc" else 1

    # Get total count
    total = await db.jobs.count_documents(query)

    # Get paginated results
    skip = (page - 1) * pageSize
    cursor = db.jobs.find(query).sort(sort, sort_dir).skip(skip).limit(pageSize)

    jobs = []
    async for doc in cursor:
        # Generate thumbnail URL
        thumbnail_url = None
        if doc.get("thumbnailKey"):
            try:
                thumbnail_url = get_presigned_url(doc["thumbnailKey"])
            except Exception:
                pass

        jobs.append(JobListItem(
            folder=doc["folder"],
            name=doc["name"],
            status=doc.get("status", JobStatus.PROCESSING),
            stage=doc.get("stage", JobStage.UPLOADING),
            createdAt=doc.get("createdAt", datetime.utcnow()),
            error=doc.get("error"),
            thumbnailUrl=thumbnail_url,
            variantCount=len(doc.get("variants", [])),
            renderCount=len(doc.get("renders", []))
        ))

    return JobListResponse(
        jobs=jobs,
        total=total,
        page=page,
        pageSize=pageSize
    )


@router.get("/storage/usage")
async def get_storage_usage():
    """Get GCS bucket storage usage."""
    try:
        from storage.storage import get_bucket_usage
        usage = get_bucket_usage()
        return usage
    except Exception as e:
        logger.error(f"Failed to get storage usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/wipe/all")
async def wipe_all_jobs():
    """Nuclear wipe: soft-delete all jobs and delete all GCS files in background."""
    db = await get_database()

    # Get all non-deleted job folders
    cursor = db.jobs.find({"deleted": {"$ne": True}}, {"folder": 1})
    folders = []
    async for doc in cursor:
        folders.append(doc["folder"])

    # Soft-delete all jobs
    await db.jobs.update_many(
        {"deleted": {"$ne": True}},
        {"$set": {"deleted": True, "updatedAt": datetime.utcnow()}}
    )

    logger.info(f"Wipe all: soft-deleted {len(folders)} jobs")

    # Delete GCS files and temp files in parallel background threads
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _wipe_all_gcs_background, folders)
    loop.run_in_executor(None, _cleanup_temp_files)

    return {"message": f"Wiped {len(folders)} jobs", "jobsDeleted": len(folders)}


@router.get("/{folder}", response_model=JobResponse)
async def get_job(folder: str):
    """Get a single job by folder name."""
    job_doc = await _get_job_by_folder(folder)

    if not job_doc or job_doc.get("deleted"):
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    # Remove MongoDB _id
    if "_id" in job_doc:
        del job_doc["_id"]

    # Add presigned URLs
    job_doc = await _generate_presigned_urls_for_job(job_doc)

    return JobResponse(job=job_doc)


@router.post("", response_model=JobResponse)
async def create_job(job_create: JobCreate):
    """Create a new job."""
    db = await get_database()

    # Check if job already exists
    existing = await _get_job_by_folder(job_create.folder)
    if existing:
        raise HTTPException(status_code=409, detail=f"Job already exists: {job_create.folder}")

    # Create job document
    job = Job(
        folder=job_create.folder,
        name=job_create.name,
        userId=job_create.userId,
        inputVideoKey=job_create.inputVideoKey,
        status=JobStatus.PROCESSING,
        stage=JobStage.UPLOADING
    )

    job_dict = job.to_dict()

    # Insert into database
    await db.jobs.insert_one(job_dict)

    logger.info(f"Created job: {job_create.folder}")

    return JobResponse(job=job_dict)


@router.patch("/{folder}", response_model=JobResponse)
async def update_job(folder: str, job_update: JobUpdate):
    """Update a job."""
    db = await get_database()

    # Check if job exists
    existing = await _get_job_by_folder(folder)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    # Build update document
    update_data: Dict[str, Any] = {"updatedAt": datetime.utcnow()}

    # Only update fields that are provided
    update_dict = job_update.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if value is not None:
            # Handle nested Pydantic models
            if hasattr(value, "model_dump"):
                update_data[key] = value.model_dump()
            elif isinstance(value, list) and value and hasattr(value[0], "model_dump"):
                update_data[key] = [v.model_dump() if hasattr(v, "model_dump") else v for v in value]
            else:
                update_data[key] = value

    # Update in database
    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data}
    )

    # Get updated document
    updated_doc = await _get_job_by_folder(folder)
    if "_id" in updated_doc:
        del updated_doc["_id"]

    # Add presigned URLs
    updated_doc = await _generate_presigned_urls_for_job(updated_doc)

    logger.info(f"Updated job: {folder}")

    return JobResponse(job=updated_doc)


@router.delete("/{folder}")
async def delete_job(folder: str, delete_gcs_files: bool = Query(True)):
    """Soft-delete a job: sets deleted=True immediately, then removes GCS files in background."""
    db = await get_database()

    # Check if job exists
    existing = await _get_job_by_folder(folder)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    # Soft delete first - respond fast
    await db.jobs.update_one(
        {"folder": folder},
        {"$set": {"deleted": True, "updatedAt": datetime.utcnow()}}
    )

    logger.info(f"Soft-deleted job: {folder}")

    # Delete GCS files in background
    if delete_gcs_files:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _delete_gcs_files_background, folder)

    return {"message": f"Job deleted: {folder}"}


def _delete_gcs_files_background(folder: str):
    """Delete all GCS files for a job folder (runs in thread pool)."""
    try:
        from storage.storage import delete_folder
        count = delete_folder(prefix=f"{folder}/")
        logger.info(f"Background GCS cleanup: deleted {count} files for {folder}")
    except Exception as e:
        logger.error(f"Background GCS cleanup failed for {folder}: {e}")


def _wipe_all_gcs_background(folders: List[str]):
    """Delete all GCS files for multiple folders and temp files (runs in thread pool)."""
    from storage.storage import delete_folder
    total = 0
    for folder in folders:
        try:
            count = delete_folder(prefix=f"{folder}/")
            total += count
        except Exception as e:
            logger.error(f"Wipe GCS cleanup failed for {folder}: {e}")
    logger.info(f"Wipe all: deleted {total} GCS files across {len(folders)} folders")


def _cleanup_temp_files():
    """Remove leftover temp files from /tmp created during video processing."""
    import os
    import shutil
    tmp_dir = "/tmp"
    removed = 0
    for entry in os.listdir(tmp_dir):
        path = os.path.join(tmp_dir, entry)
        # Skip system directories and the vigenair config dir
        if entry.startswith("systemd-") or entry == "vigenair":
            continue
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
            removed += 1
        except Exception as e:
            logger.warning(f"Failed to remove temp file {path}: {e}")
    logger.info(f"Temp cleanup: removed {removed} entries from /tmp")


# Specialized update endpoints

class VariantsUpdate(BaseModel):
    """Model for updating variants."""
    variants: List[Variant]
    selectedVariantIndex: Optional[int] = None
    generationSettings: Optional[GenerationSettings] = None


@router.patch("/{folder}/variants")
async def update_variants(folder: str, variants_update: VariantsUpdate):
    """Update job variants after generation."""
    db = await get_database()

    # Check if job exists
    existing = await _get_job_by_folder(folder)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    # Build update
    update_data: Dict[str, Any] = {
        "updatedAt": datetime.utcnow(),
        "variants": [v.model_dump() for v in variants_update.variants]
    }

    # Update status if variants were generated
    if variants_update.variants:
        update_data["status"] = JobStatus.VARIANTS_GENERATED.value

    if variants_update.selectedVariantIndex is not None:
        update_data["selectedVariantIndex"] = variants_update.selectedVariantIndex

    if variants_update.generationSettings:
        update_data["generationSettings"] = variants_update.generationSettings.model_dump()

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": update_data}
    )

    logger.info(f"Updated {len(variants_update.variants)} variants for job: {folder}")

    return {"message": f"Updated variants for job: {folder}"}


class RenderQueueUpdate(BaseModel):
    """Model for updating render queue."""
    renderQueue: List[RenderQueueItem]


@router.patch("/{folder}/render-queue")
async def update_render_queue(folder: str, queue_update: RenderQueueUpdate):
    """Update job render queue."""
    db = await get_database()

    # Check if job exists
    existing = await _get_job_by_folder(folder)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": {
            "updatedAt": datetime.utcnow(),
            "renderQueue": [r.model_dump() for r in queue_update.renderQueue]
        }}
    )

    logger.info(f"Updated render queue for job: {folder}")

    return {"message": f"Updated render queue for job: {folder}"}


class UIStateUpdate(BaseModel):
    """Model for updating UI state."""
    ui: UIState


@router.patch("/{folder}/ui")
async def update_ui_state(folder: str, ui_update: UIStateUpdate):
    """Update job UI state."""
    db = await get_database()

    # Check if job exists
    existing = await _get_job_by_folder(folder)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Job not found: {folder}")

    await db.jobs.update_one(
        {"folder": folder},
        {"$set": {
            "updatedAt": datetime.utcnow(),
            "ui": ui_update.ui.model_dump()
        }}
    )

    return {"message": f"Updated UI state for job: {folder}"}
