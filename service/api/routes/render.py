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

"""Video render endpoints."""

import json
import logging
import os
import tempfile

from fastapi import APIRouter, BackgroundTasks, HTTPException

import config as ConfigService
import storage as StorageService
import utils as Utils
from api.models.responses import RenderRequest, RenderResponse, RendersResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _render_variants_background(folder: str, render_data: dict):
    """Background task to render video variants."""
    import combiner as CombinerService

    try:
        logger.info(f"Starting render for folder: {folder}")

        bucket = os.environ.get("S3_BUCKET")

        # Write render request file
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as f:
            json.dump(render_data, f)
            temp_path = f.name

        # Upload render request file
        render_key = f"{folder}/{ConfigService.INPUT_RENDERING_FILE}"
        StorageService.upload_file(temp_path, render_key, overwrite=True)
        os.unlink(temp_path)

        # Create trigger file and run combiner
        trigger_file = Utils.TriggerFile(render_key)
        combiner_instance = CombinerService.Combiner(
            gcs_bucket_name=bucket, render_file=trigger_file
        )
        combiner_instance.initial_render()

        logger.info(f"Render completed for: {folder}")

    except Exception as e:
        logger.exception(f"Error rendering variants: {e}")

        # Write error file
        error_key = f"{folder}/render_error.txt"
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write(str(e))
            temp_error_path = f.name

        try:
            StorageService.upload_file(temp_error_path, error_key, overwrite=True)
        finally:
            if os.path.exists(temp_error_path):
                os.unlink(temp_error_path)


@router.post("/{folder}/render", response_model=RenderResponse)
async def render_variants(
    folder: str, request: RenderRequest, background_tasks: BackgroundTasks
):
    """Render video variants.

    Args:
        folder: The video folder name.
        request: RenderRequest with variants and settings.
        background_tasks: FastAPI background tasks handler.

    Returns:
        RenderResponse with status.
    """
    try:
        # Verify segments exist
        data_key = f"{folder}/{ConfigService.OUTPUT_DATA_FILE}"
        data_content = StorageService.download_file(data_key, fetch_contents=True)

        if not data_content:
            raise HTTPException(
                status_code=404, detail="Segments not found. Run extraction first."
            )

        # Prepare render data
        render_data = {
            "variants": request.variants,
            "settings": request.settings or {},
        }

        # Start background render task
        background_tasks.add_task(_render_variants_background, folder, render_data)

        return RenderResponse(
            folder=folder,
            status="processing",
            message=f"Rendering {len(request.variants)} variant(s)",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error starting render: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start render: {str(e)}"
        )


@router.get("/{folder}/renders", response_model=RendersResponse)
async def get_renders(folder: str):
    """Get rendered variants for a video.

    Args:
        folder: The video folder name.

    Returns:
        RendersResponse with combos.json contents.
    """
    try:
        # Try to get combos.json
        combos_key = f"{folder}/{ConfigService.OUTPUT_COMBINATIONS_FILE}"
        combos_content = StorageService.download_file(combos_key, fetch_contents=True)

        if not combos_content:
            # Check for error
            error_key = f"{folder}/render_error.txt"
            error_content = StorageService.download_file(error_key, fetch_contents=True)

            if error_content:
                return RendersResponse(
                    folder=folder,
                    error=error_content.decode("utf-8"),
                )

            raise HTTPException(
                status_code=404,
                detail="Renders not found. Submit a render request first.",
            )

        combos = json.loads(combos_content.decode("utf-8"))

        return RendersResponse(folder=folder, combos=combos)

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.exception(f"Error parsing combos JSON: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse renders data")
    except Exception as e:
        logger.exception(f"Error getting renders: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get renders: {str(e)}"
        )


@router.delete("/{folder}")
async def delete_video(folder: str):
    """Delete a video and all its associated files.

    Args:
        folder: The video folder name.

    Returns:
        Success message.
    """
    try:
        # List all files in folder
        prefix = f"{folder}/"
        files = StorageService.list_files(prefix=prefix)

        if not files:
            raise HTTPException(status_code=404, detail=f"Video not found: {folder}")

        # Delete all files
        for file_key in files:
            StorageService.delete_file(file_key)

        logger.info(f"Deleted video folder: {folder} ({len(files)} files)")

        return {"status": "success", "message": f"Deleted {folder}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting video: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete video: {str(e)}"
        )
