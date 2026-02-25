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

"""Video status endpoint."""

import logging
import os

from fastapi import APIRouter, HTTPException

import config as ConfigService
import storage as StorageService
from api.models.responses import StatusResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{folder}/status", response_model=StatusResponse)
async def get_video_status(folder: str):
    """Get the processing status of a video.

    Args:
        folder: The video folder name.

    Returns:
        StatusResponse with current processing status.
    """
    try:
        bucket = os.environ.get("GCS_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="GCS_BUCKET not configured")

        # List all files in the folder
        prefix = f"{folder}/"
        files = StorageService.list_files(prefix=prefix)

        if not files:
            raise HTTPException(status_code=404, detail=f"Video folder not found: {folder}")

        # Check for error file
        error_files = [f for f in files if f.endswith("error.txt")]
        if error_files:
            error_content = StorageService.download_file(error_files[0], fetch_contents=True)
            error_message = error_content.decode("utf-8") if error_content else "Unknown error"
            return StatusResponse(
                folder=folder,
                status="error",
                error=error_message,
                data_ready=False,
                renders_ready=False,
            )

        # Check for data.json (extraction complete)
        data_ready = any(f.endswith(ConfigService.OUTPUT_DATA_FILE) for f in files)

        # Check for combos.json (renders complete)
        renders_ready = any(f.endswith(ConfigService.OUTPUT_COMBINATIONS_FILE) for f in files)

        # Determine current stage
        if renders_ready:
            status = "complete"
            stage = "renders_complete"
        elif data_ready:
            status = "complete"
            stage = "extraction_complete"
        elif any(f.endswith(ConfigService.OUTPUT_ANALYSIS_FILE) for f in files):
            status = "processing"
            stage = "analysing_video"
        elif any(f.endswith(ConfigService.OUTPUT_SPEECH_FILE) for f in files):
            status = "processing"
            stage = "transcribing_audio"
        elif any(f.endswith("input.mp4") or f.endswith("input.mov") for f in files):
            status = "processing"
            stage = "extracting_audio"
        else:
            status = "processing"
            stage = "initializing"

        return StatusResponse(
            folder=folder,
            status=status,
            stage=stage,
            data_ready=data_ready,
            renders_ready=renders_ready,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting video status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get video status: {str(e)}"
        )
