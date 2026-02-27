# Copyright 2024 Google LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Video upload endpoint."""

import asyncio
import logging
import math
import os
import tempfile
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

import config as ConfigService
import storage as StorageService
import utils as Utils
from api.models.responses import (
    ParallelUploadCompleteRequest,
    ParallelUploadInitiateRequest,
    ParallelUploadInitiateResponse,
    PartUploadInfo,
    ResumableUploadAbortRequest,
    ResumableUploadCompleteRequest,
    ResumableUploadCompleteResponse,
    ResumableUploadInitiateRequest,
    ResumableUploadInitiateResponse,
    UploadResponse,
    VideoInfo,
    VideoListResponse,
)
from db.job_service import (
    create_job_sync,
    update_job_status_sync,
    update_job_segments_sync,
    update_job_error_sync
)
from db.models import JobStatus, JobStage
from db.mongodb import get_database

logger = logging.getLogger(__name__)
router = APIRouter()

# GCS resumable upload chunk size must be a multiple of 256 KB
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB


def _process_video_background(folder: str, local_video_path: str, gcs_key: str):
    """Background task to process uploaded video.

    Args:
        folder: The GCS folder for this video.
        local_video_path: Path to the local video file (empty for resumable uploads).
        gcs_key: The GCS key where the video is stored.
    """
    import extractor as ExtractorService
    import json

    try:
        logger.info(f"Starting extraction for folder: {folder}")

        # Update job status - extracting audio
        update_job_status_sync(folder, stage=JobStage.EXTRACTING_AUDIO, progress=10)

        # Create trigger file object
        trigger_file = Utils.TriggerFile(gcs_key)

        # Initialize and run extractor
        bucket = os.environ.get("GCS_BUCKET")
        extractor_instance = ExtractorService.Extractor(
            gcs_bucket_name=bucket, media_file=trigger_file
        )

        # Update status - transcribing
        update_job_status_sync(folder, stage=JobStage.TRANSCRIBING, progress=30)

        extractor_instance.initial_extract()

        logger.info(f"Initial extraction completed for: {folder}")

        # Update status - analyzing video
        update_job_status_sync(folder, stage=JobStage.ANALYZING, progress=60)

        # Finalise extraction - combines analysis and creates data.json
        extractor_instance.finalise_extraction()

        logger.info(f"Extraction fully completed for: {folder}")

        # Update status - creating segments
        update_job_status_sync(folder, stage=JobStage.CREATING_SEGMENTS, progress=80)

        # Load segments from data.json and update MongoDB
        try:
            data_content = StorageService.download_file(f"{folder}/data.json", fetch_contents=True)
            if data_content:
                data = json.loads(data_content)
                segments = data if isinstance(data, list) else data.get("segments", [])

                # Convert segments to MongoDB format
                mongo_segments = []
                for i, seg in enumerate(segments):
                    mongo_segments.append({
                        "id": str(seg.get("id", i)),
                        "startTime": seg.get("start_s", seg.get("startTime", 0)),
                        "endTime": seg.get("end_s", seg.get("endTime", 0)),
                        "duration": seg.get("duration_s", seg.get("duration", 0)),
                        "description": seg.get("description", ""),
                        "keywords": seg.get("keywords", []),
                        "transcript": seg.get("transcript", "")
                    })

                # Get thumbnail key (first segment's thumbnail)
                thumbnail_key = f"{folder}/av_segments_cuts/0.jpg"

                # Update job with segments
                update_job_segments_sync(folder, mongo_segments, thumbnail_key)

                logger.info(f"Updated MongoDB with {len(mongo_segments)} segments for: {folder}")
        except Exception as seg_error:
            logger.warning(f"Failed to update segments in MongoDB: {seg_error}")
            # Still mark as complete since GCS files exist
            update_job_status_sync(
                folder,
                status=JobStatus.SEGMENTS_READY,
                stage=JobStage.DONE,
                progress=100
            )

    except Exception as e:
        logger.exception(f"Error processing video {folder}: {e}")

        # Update MongoDB with error
        update_job_error_sync(folder, str(e))

        # Write error file to GCS
        error_key = f"{folder}/error.txt"
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write(str(e))
            temp_error_path = f.name

        try:
            StorageService.upload_file(temp_error_path, error_key, overwrite=True)
        finally:
            if os.path.exists(temp_error_path):
                os.unlink(temp_error_path)

    finally:
        # Cleanup local video file
        if local_video_path and os.path.exists(local_video_path):
            os.unlink(local_video_path)


@router.post("/upload/initiate", response_model=ResumableUploadInitiateResponse)
async def initiate_resumable_upload(request: ResumableUploadInitiateRequest):
    """Initiate a GCS resumable upload and return the session URI.

    Args:
        request: ResumableUploadInitiateRequest with filename, fileSize, contentType, etc.

    Returns:
        ResumableUploadInitiateResponse with sessionUri, folder, objectKey, and chunkSize.
    """
    # Validate file extension
    file_ext = os.path.splitext(request.filename)[1].lower()
    if not file_ext or not Utils.VideoExtension.has_value(file_ext[1:]):
        raise HTTPException(
            status_code=400, detail=f"Unsupported video format: {file_ext}"
        )

    # Generate folder name (same logic as existing upload)
    timestamp = int(datetime.now().timestamp() * 1000)
    encoded_user_id = request.userId.replace("@", "_at_").replace(".", "_dot_")
    transcription_service = "w" if request.analyzeAudio else "n"

    sanitized_name = Utils.sanitise_filename(os.path.splitext(request.filename)[0])
    folder = f"{sanitized_name}--{transcription_service}--{timestamp}--{encoded_user_id}"

    object_key = f"{folder}/input{file_ext}"

    try:
        # Create a GCS resumable upload session
        session_uri = StorageService.create_resumable_upload_session(
            object_key, request.contentType
        )

        # Create MongoDB job
        try:
            create_job_sync(
                folder=folder,
                name=sanitized_name,
                user_id=request.userId,
                input_video_key=object_key,
            )
            logger.info(f"Created MongoDB job for resumable upload: {folder}")
        except Exception as db_error:
            logger.warning(f"Failed to create MongoDB job (continuing anyway): {db_error}")

        return ResumableUploadInitiateResponse(
            sessionUri=session_uri,
            folder=folder,
            objectKey=object_key,
            chunkSize=DEFAULT_CHUNK_SIZE,
            totalSize=request.fileSize,
        )

    except Exception as e:
        logger.exception(f"Error initiating resumable upload: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initiate upload: {str(e)}"
        )


@router.post("/upload/complete", response_model=ResumableUploadCompleteResponse)
async def complete_resumable_upload(
    request: ResumableUploadCompleteRequest,
    background_tasks: BackgroundTasks,
):
    """Complete a resumable upload after all chunks have been uploaded.

    The file is already in GCS at this point. This endpoint triggers
    background processing.

    Args:
        request: ResumableUploadCompleteRequest with folder and objectKey.
        background_tasks: FastAPI background tasks handler.

    Returns:
        ResumableUploadCompleteResponse with status.
    """
    try:
        logger.info(f"Resumable upload completed: {request.objectKey}")

        # Update job status
        try:
            update_job_status_sync(
                request.folder,
                stage=JobStage.EXTRACTING_AUDIO,
                progress=5,
            )
        except Exception as db_error:
            logger.warning(f"Failed to update job status: {db_error}")

        # Run in thread pool so long-running sync work doesn't block the event loop
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, _process_video_background, request.folder, "", request.objectKey
        )

        return ResumableUploadCompleteResponse(
            folder=request.folder,
            status="processing",
            message="Upload completed. Processing started.",
        )

    except Exception as e:
        logger.exception(f"Error completing resumable upload: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to complete upload: {str(e)}"
        )


@router.post("/upload/abort")
async def abort_resumable_upload(request: ResumableUploadAbortRequest):
    """Abort a resumable upload and clean up.

    GCS resumable upload sessions expire automatically, so we just
    clean up MongoDB.

    Args:
        request: ResumableUploadAbortRequest with folder and objectKey.

    Returns:
        Status dict.
    """
    # Delete MongoDB job
    try:
        db = await get_database()
        await db.jobs.delete_one({"folder": request.folder})
        logger.info(f"Deleted MongoDB job for aborted upload: {request.folder}")
    except Exception as db_error:
        logger.warning(f"Failed to delete MongoDB job: {db_error}")

    # Clean up parallel upload temp parts if applicable
    if request.numParts:
        try:
            folder = request.folder
            part_keys = [
                f"{folder}/_parts/part_{i:03d}" for i in range(request.numParts)
            ]
            StorageService.delete_files(part_keys)
            logger.info(f"Cleaned up {request.numParts} temp parts for: {folder}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to clean up temp parts: {cleanup_error}")

    return {"status": "aborted"}


# GCS resumable upload chunk size alignment (256 KB)
ALIGNMENT = 256 * 1024


@router.post("/upload/initiate-parallel", response_model=ParallelUploadInitiateResponse)
async def initiate_parallel_upload(request: ParallelUploadInitiateRequest):
    """Initiate a parallel upload with N parts using signed URLs.

    Generates signed PUT URLs for each part so the browser can upload
    directly to GCS without CORS issues (no custom headers needed).

    Args:
        request: ParallelUploadInitiateRequest with filename, fileSize, numParts, etc.

    Returns:
        ParallelUploadInitiateResponse with signed upload URLs, offsets, and sizes.
    """
    # Validate file extension
    file_ext = os.path.splitext(request.filename)[1].lower()
    if not file_ext or not Utils.VideoExtension.has_value(file_ext[1:]):
        raise HTTPException(
            status_code=400, detail=f"Unsupported video format: {file_ext}"
        )

    # Generate folder name (same logic as existing upload)
    timestamp = int(datetime.now().timestamp() * 1000)
    encoded_user_id = request.userId.replace("@", "_at_").replace(".", "_dot_")
    transcription_service = "w" if request.analyzeAudio else "n"

    sanitized_name = Utils.sanitise_filename(os.path.splitext(request.filename)[0])
    folder = f"{sanitized_name}--{transcription_service}--{timestamp}--{encoded_user_id}"

    object_key = f"{folder}/input{file_ext}"

    num_parts = max(2, min(request.numParts, 32))

    # Calculate part sizes (no alignment needed for signed URL uploads)
    base_part_size = request.fileSize // num_parts
    remainder = request.fileSize % num_parts

    try:
        parts = []
        offset = 0
        for i in range(num_parts):
            if offset >= request.fileSize:
                num_parts = i
                break
            # Distribute remainder across first N parts
            size = base_part_size + (1 if i < remainder else 0)
            part_key = f"{folder}/_parts/part_{i:03d}"

            signed_url = StorageService.get_signed_upload_url(
                part_key, content_type='application/octet-stream'
            )

            parts.append(PartUploadInfo(
                partIndex=i,
                signedUrl=signed_url,
                partKey=part_key,
                offset=offset,
                size=size,
            ))
            offset += size

        # Create MongoDB job
        try:
            create_job_sync(
                folder=folder,
                name=sanitized_name,
                user_id=request.userId,
                input_video_key=object_key,
            )
            logger.info(f"Created MongoDB job for parallel upload: {folder}")
        except Exception as db_error:
            logger.warning(f"Failed to create MongoDB job (continuing anyway): {db_error}")

        return ParallelUploadInitiateResponse(
            folder=folder,
            objectKey=object_key,
            totalSize=request.fileSize,
            numParts=num_parts,
            maxConcurrentParts=ConfigService.CONFIG_MAX_UPLOAD_CONCURRENCY,
            parts=parts,
        )

    except Exception as e:
        logger.exception(f"Error initiating parallel upload: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to initiate parallel upload: {str(e)}"
        )


@router.post("/upload/complete-parallel", response_model=ResumableUploadCompleteResponse)
async def complete_parallel_upload(
    request: ParallelUploadCompleteRequest,
    background_tasks: BackgroundTasks,
):
    """Complete a parallel composite upload by composing parts.

    Verifies all part objects exist, composes them into the final object,
    deletes temp parts, and triggers background processing.

    Args:
        request: ParallelUploadCompleteRequest with folder, objectKey, numParts.
        background_tasks: FastAPI background tasks handler.

    Returns:
        ResumableUploadCompleteResponse with status.
    """
    try:
        part_keys = [
            f"{request.folder}/_parts/part_{i:03d}" for i in range(request.numParts)
        ]

        # Determine content type from object key extension
        file_ext = os.path.splitext(request.objectKey)[1].lower()
        content_type = f"video/{file_ext[1:]}" if file_ext else "video/mp4"

        # Compose parts into final object
        StorageService.compose_objects(part_keys, request.objectKey, content_type)

        # Delete temp parts
        StorageService.delete_files(part_keys)

        logger.info(f"Parallel upload composed: {request.objectKey}")

        # Update job status
        try:
            update_job_status_sync(
                request.folder,
                stage=JobStage.EXTRACTING_AUDIO,
                progress=5,
            )
        except Exception as db_error:
            logger.warning(f"Failed to update job status: {db_error}")

        # Run in thread pool so long-running sync work doesn't block the event loop
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, _process_video_background, request.folder, "", request.objectKey
        )

        return ResumableUploadCompleteResponse(
            folder=request.folder,
            status="processing",
            message="Upload completed. Processing started.",
        )

    except Exception as e:
        logger.exception(f"Error completing parallel upload: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to complete parallel upload: {str(e)}"
        )


@router.post("/upload", response_model=UploadResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    analyse_audio: bool = Form(True),
    user_id: str = Form(default="anonymous"),
):
    """Upload a video file and trigger processing.

    Args:
        background_tasks: FastAPI background tasks handler.
        video: The video file to upload.
        analyse_audio: Whether to analyse audio for transcription.
        user_id: User identifier for tracking.

    Returns:
        UploadResponse with folder name and status.

    Raises:
        HTTPException: If video format is not supported.
    """
    # Validate file extension
    filename = video.filename or "video.mp4"
    file_ext = os.path.splitext(filename)[1].lower()

    if not file_ext or not Utils.VideoExtension.has_value(file_ext[1:]):
        raise HTTPException(
            status_code=400, detail=f"Unsupported video format: {file_ext}"
        )

    # Create folder name using existing convention
    timestamp = int(datetime.now().timestamp() * 1000)
    encoded_user_id = user_id.replace("@", "_at_").replace(".", "_dot_")
    transcription_service = "w" if analyse_audio else "n"

    sanitized_name = Utils.sanitise_filename(os.path.splitext(filename)[0])
    folder = f"{sanitized_name}--{transcription_service}--{timestamp}--{encoded_user_id}"

    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        content = await video.read()
        tmp_file.write(content)
        tmp_path = tmp_file.name

    try:
        # Upload to GCS
        gcs_key = f"{folder}/input{file_ext}"
        StorageService.upload_file(tmp_path, gcs_key)

        logger.info(f"Video uploaded to GCS: {gcs_key}")

        # Create job in MongoDB
        try:
            create_job_sync(
                folder=folder,
                name=sanitized_name,
                user_id=user_id,
                input_video_key=gcs_key
            )
            logger.info(f"Created MongoDB job: {folder}")
        except Exception as db_error:
            logger.warning(f"Failed to create MongoDB job (continuing anyway): {db_error}")

        # Run in thread pool so long-running sync work doesn't block the event loop
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, _process_video_background, folder, tmp_path, gcs_key
        )

        return UploadResponse(
            folder=folder,
            status="processing",
            message="Video uploaded successfully. Processing started.",
        )

    except Exception as e:
        # Cleanup temp file on error
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.exception(f"Error uploading video: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload video: {str(e)}")


@router.get("", response_model=VideoListResponse)
async def list_videos():
    """List all processed videos.

    Returns:
        VideoListResponse with list of video information.
    """
    try:
        bucket = os.environ.get("GCS_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="GCS_BUCKET not configured")

        # Get deleted job folders from MongoDB to exclude them
        db = await get_database()
        deleted_cursor = db.jobs.find({"deleted": True}, {"folder": 1})
        deleted_folders = set()
        async for doc in deleted_cursor:
            deleted_folders.add(doc["folder"])

        # List top-level folders in GCS
        all_objects = StorageService.list_files(prefix="")

        # Extract unique folder names and their metadata
        folders_seen = set()
        videos = []

        for key in all_objects:
            parts = key.split("/")
            if len(parts) > 1:
                folder = parts[0]
                if folder not in folders_seen and folder not in deleted_folders:
                    folders_seen.add(folder)

                    try:
                        # Parse metadata from folder name
                        metadata = Utils.VideoMetadata(folder)

                        # Check if data.json exists
                        has_data = any(
                            k.endswith("data.json") and k.startswith(f"{folder}/")
                            for k in all_objects
                        )

                        # Check if combos.json exists (renders)
                        has_renders = any(
                            k.endswith("combos.json") and k.startswith(f"{folder}/")
                            for k in all_objects
                        )

                        videos.append(
                            VideoInfo(
                                folder=folder,
                                name=metadata.video_file_name,
                                timestamp=metadata.video_timestamp,
                                user_id=metadata.encoded_user_id,
                                has_data=has_data,
                                has_renders=has_renders,
                            )
                        )
                    except ValueError:
                        # Skip folders that don't match the expected format
                        continue

        # Sort by timestamp descending (newest first)
        videos.sort(key=lambda v: v.timestamp, reverse=True)

        return VideoListResponse(videos=videos)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error listing videos: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list videos: {str(e)}")
