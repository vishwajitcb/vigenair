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

import logging
import os
import tempfile
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

import storage as StorageService
import utils as Utils
from api.models.responses import UploadResponse, VideoInfo, VideoListResponse
from db.job_service import (
    create_job_sync,
    update_job_status_sync,
    update_job_segments_sync,
    update_job_error_sync
)
from db.models import JobStatus, JobStage

logger = logging.getLogger(__name__)
router = APIRouter()


def _process_video_background(folder: str, local_video_path: str, s3_key: str):
    """Background task to process uploaded video.

    Args:
        folder: The S3 folder for this video.
        local_video_path: Path to the local video file.
        s3_key: The S3 key where the video is stored.
    """
    import extractor as ExtractorService
    import json

    try:
        logger.info(f"Starting extraction for folder: {folder}")

        # Update job status - extracting audio
        update_job_status_sync(folder, stage=JobStage.EXTRACTING_AUDIO, progress=10)

        # Create trigger file object
        trigger_file = Utils.TriggerFile(s3_key)

        # Initialize and run extractor
        bucket = os.environ.get("S3_BUCKET")
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
            # Still mark as complete since S3 files exist
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

        # Write error file to S3
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
        if os.path.exists(local_video_path):
            os.unlink(local_video_path)


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
        # Upload to S3
        s3_key = f"{folder}/input{file_ext}"
        StorageService.upload_file(tmp_path, s3_key)

        logger.info(f"Video uploaded to S3: {s3_key}")

        # Create job in MongoDB
        try:
            create_job_sync(
                folder=folder,
                name=sanitized_name,
                user_id=user_id,
                input_video_key=s3_key
            )
            logger.info(f"Created MongoDB job: {folder}")
        except Exception as db_error:
            logger.warning(f"Failed to create MongoDB job (continuing anyway): {db_error}")

        # Start background processing
        background_tasks.add_task(
            _process_video_background, folder, tmp_path, s3_key
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
        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="S3_BUCKET not configured")

        # List top-level folders in S3
        all_objects = StorageService.list_files(prefix="")

        # Extract unique folder names and their metadata
        folders_seen = set()
        videos = []

        for key in all_objects:
            parts = key.split("/")
            if len(parts) > 1:
                folder = parts[0]
                if folder not in folders_seen:
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
