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

"""File access endpoints."""

import logging
import os
from typing import List

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

import storage as StorageService
from api.models.responses import FileUrlResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/url")
async def get_file_url(
    key: str = Query(..., description="The S3 object key"),
    expires_in: int = Query(3600, description="URL expiration time in seconds"),
) -> FileUrlResponse:
    """Get a presigned URL for accessing a file.

    Args:
        key: The S3 object key.
        expires_in: URL expiration time in seconds (default 1 hour).

    Returns:
        FileUrlResponse with presigned URL.
    """
    try:
        url = StorageService.get_presigned_url(key, expiration=expires_in)
        return FileUrlResponse(url=url, expires_in=expires_in)

    except Exception as e:
        logger.exception(f"Error generating presigned URL: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate URL: {str(e)}"
        )


@router.get("/list")
async def list_files(
    prefix: str = Query("", description="Prefix to filter files"),
    suffix: str = Query(None, description="Suffix to filter files"),
) -> List[str]:
    """List files in S3 bucket.

    Args:
        prefix: Prefix to filter files.
        suffix: Suffix to filter files (optional).

    Returns:
        List of file keys.
    """
    try:
        files = StorageService.list_files(prefix=prefix, suffix=suffix)
        return files

    except Exception as e:
        logger.exception(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.get("/download/{folder}/{filename:path}")
async def download_file(folder: str, filename: str):
    """Download a file from S3.

    Args:
        folder: The video folder name.
        filename: The filename within the folder.

    Returns:
        StreamingResponse with file contents.
    """
    try:
        key = f"{folder}/{filename}"

        # Get file content
        content = StorageService.download_file(key, fetch_contents=True)

        if not content:
            raise HTTPException(status_code=404, detail=f"File not found: {key}")

        # Determine content type
        ext = os.path.splitext(filename)[1].lower()
        content_types = {
            ".mp4": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".json": "application/json",
            ".txt": "text/plain",
            ".vtt": "text/vtt",
            ".srt": "text/srt",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        # Return streaming response
        def iter_content():
            yield content

        return StreamingResponse(
            iter_content(),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error downloading file: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to download file: {str(e)}"
        )


@router.get("/{folder}/segment-video/{segment_id}")
async def get_segment_video_url(
    folder: str,
    segment_id: str,
    expires_in: int = Query(3600, description="URL expiration time in seconds"),
) -> FileUrlResponse:
    """Get presigned URL for a segment video file.

    Args:
        folder: The video folder name.
        segment_id: The segment ID.
        expires_in: URL expiration time in seconds.

    Returns:
        FileUrlResponse with presigned URL.
    """
    try:
        import config as ConfigService

        # Construct segment video path
        key = f"{folder}/{ConfigService.OUTPUT_AV_SEGMENTS_DIR}/{segment_id}.mp4"

        url = StorageService.get_presigned_url(key, expiration=expires_in)
        return FileUrlResponse(url=url, expires_in=expires_in)

    except Exception as e:
        logger.exception(f"Error generating segment video URL: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate URL: {str(e)}"
        )


@router.get("/{folder}/thumbnail/{segment_id}")
async def get_segment_thumbnail_url(
    folder: str,
    segment_id: str,
    expires_in: int = Query(3600, description="URL expiration time in seconds"),
) -> FileUrlResponse:
    """Get presigned URL for a segment thumbnail.

    Args:
        folder: The video folder name.
        segment_id: The segment ID.
        expires_in: URL expiration time in seconds.

    Returns:
        FileUrlResponse with presigned URL.
    """
    try:
        import config as ConfigService

        # Construct thumbnail path
        key = f"{folder}/{ConfigService.OUTPUT_AV_SEGMENTS_DIR}/{segment_id}{ConfigService.SEGMENT_SCREENSHOT_EXT}"

        url = StorageService.get_presigned_url(key, expiration=expires_in)
        return FileUrlResponse(url=url, expires_in=expires_in)

    except Exception as e:
        logger.exception(f"Error generating thumbnail URL: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate URL: {str(e)}"
        )
