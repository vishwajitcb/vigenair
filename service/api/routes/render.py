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
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

import config as ConfigService
import storage as StorageService
import utils as Utils
from api.models.responses import RenderRequest, RenderResponse, RendersResponse
from db.job_service import update_job_status_sync, update_job_error_sync
from db.models import JobStatus, JobStage

logger = logging.getLogger(__name__)
router = APIRouter()


def _transform_variants_for_combiner(folder: str, variants: list, settings: dict) -> list:
    """Transform frontend variant format to combiner format.

    Args:
        folder: The video folder name.
        variants: List of variants from frontend.
        settings: Global render settings.

    Returns:
        List of variants in combiner format.
    """
    # Load segments data to get start/end times
    data_key = f"{folder}/{ConfigService.OUTPUT_DATA_FILE}"
    data_content = StorageService.download_file(data_key, fetch_contents=True)

    if not data_content:
        raise ValueError("Segments data not found")

    data = json.loads(data_content.decode("utf-8"))

    # Handle both formats: list directly or wrapped in object
    if isinstance(data, list):
        segments_list = data
    else:
        segments_list = data.get("av_segments", data.get("segments", []))

    # Build segment lookup by ID
    segments_by_id = {}
    for seg in segments_list:
        seg_id = str(seg.get("av_segment_id", seg.get("id", "")))
        segments_by_id[seg_id] = seg

    combiner_variants = []
    for idx, variant in enumerate(variants):
        # Get segment IDs from variant
        segment_ids = variant.get("segments", [])

        # Build av_segments with full data
        av_segments = []
        for seg_id in segment_ids:
            seg_id_str = str(seg_id)
            seg_data = segments_by_id.get(seg_id_str)
            if seg_data:
                av_segments.append({
                    "av_segment_id": int(seg_id_str) if seg_id_str.isdigit() else seg_id_str,
                    "start_s": seg_data.get("start_s", seg_data.get("startTime", 0)),
                    "end_s": seg_data.get("end_s", seg_data.get("endTime", 0)),
                })

        # Build render settings
        formats = variant.get("formats", settings.get("formats", ["16:9"]))
        audio_mode = variant.get("audioMode", settings.get("audioMode", "segment"))

        render_settings = {
            "formats": formats,
            "use_music_overlay": audio_mode == "music",
            "use_continuous_audio": audio_mode == "continuous",
            "generate_image_assets": False,
            "generate_text_assets": False,
            "fade_out": False,
            "use_blanking_fill": False,
        }

        combiner_variant = {
            "variant_id": variant.get("id", idx),
            "av_segments": av_segments,
            "title": variant.get("title", f"Variant {idx + 1}"),
            "description": variant.get("description", ""),
            "score": variant.get("score", 0),
            "score_reasoning": variant.get("reasoning", ""),
            "render_settings": render_settings,
        }
        combiner_variants.append(combiner_variant)

    return combiner_variants


def _render_variants_background(folder: str, render_data: dict):
    """Background task to render video variants."""
    import combiner as CombinerService

    try:
        logger.info(f"Starting render for folder: {folder}")

        # Update status: Rendering started (0%)
        update_job_status_sync(
            folder,
            status=JobStatus.RENDERING,
            stage=JobStage.RENDER_PREPARING,
            progress=0
        )

        bucket = os.environ.get("GCS_BUCKET")

        # Transform variants to combiner format
        variants = render_data.get("variants", [])
        settings = render_data.get("settings", {})
        combiner_variants = _transform_variants_for_combiner(folder, variants, settings)

        logger.info(f"Transformed {len(combiner_variants)} variants for combiner")

        # Update progress: variants transformed (5%)
        update_job_status_sync(folder, progress=5)

        # Write render request file (combiner expects a JSON array)
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as f:
            json.dump(combiner_variants, f)
            temp_path = f.name

        # Upload render request file
        render_key = f"{folder}/{ConfigService.INPUT_RENDERING_FILE}"
        StorageService.upload_file(temp_path, render_key, overwrite=True)
        os.unlink(temp_path)

        # Update status: starting initial render (cropping phase) (10%)
        update_job_status_sync(
            folder,
            stage=JobStage.RENDER_CROPPING,
            progress=10
        )

        # Create trigger file and run combiner initial phase
        trigger_file = Utils.TriggerFile(render_key)
        combiner_instance = CombinerService.Combiner(
            gcs_bucket_name=bucket, render_file=trigger_file
        )
        combiner_instance.initial_render()

        logger.info(f"Initial render completed for: {folder}")

        # Update progress after initial render (20%)
        update_job_status_sync(folder, progress=20)

        # Calculate progress per variant (75% remaining / num_variants)
        num_variants = len(combiner_variants)
        progress_per_variant = 75 / num_variants if num_variants > 0 else 75

        # Now render each variant using the per-variant render files
        for idx, variant in enumerate(combiner_variants):
            variant_id = variant.get("variant_id", idx)
            variant_render_key = f"{folder}/{variant_id}-{num_variants}_{ConfigService.INPUT_RENDERING_FILE}"

            logger.info(f"Rendering variant {variant_id} from {variant_render_key}")

            # Update status: encoding this variant
            current_progress = 20 + int(idx * progress_per_variant)
            update_job_status_sync(
                folder,
                stage=JobStage.RENDER_ENCODING,
                progress=current_progress
            )

            variant_trigger = Utils.TriggerFile(variant_render_key)
            variant_combiner = CombinerService.Combiner(
                gcs_bucket_name=bucket, render_file=variant_trigger
            )
            variant_combiner.render()

            # Update progress after variant completes
            completed_progress = 20 + int((idx + 1) * progress_per_variant)
            update_job_status_sync(folder, progress=completed_progress)

            logger.info(f"Variant {variant_id} render completed")

        # Update status: finalizing (95%)
        update_job_status_sync(
            folder,
            stage=JobStage.RENDER_FINALIZING,
            progress=95
        )

        # Collect render results from combos.json files
        renders = []
        for idx, variant in enumerate(combiner_variants):
            variant_id = variant.get("variant_id", idx)
            combos_key = f"{folder}/{variant_id}-{num_variants}_combos.json"

            try:
                combos_content = StorageService.download_file(combos_key, fetch_contents=True)
                if combos_content:
                    combos_data = json.loads(combos_content.decode("utf-8"))
                    logger.info(f"Processing combos for variant {variant_id}: found {len(combos_data)} combos")

                    # Extract video URLs for each variant in combos
                    for combo_key, combo_info in combos_data.items():
                        if isinstance(combo_info, dict) and "variants" in combo_info:
                            # Create unique render ID using timestamp and variant_id
                            render_id = f"{variant_id}_{int(datetime.utcnow().timestamp() * 1000)}"

                            render_entry = {
                                "id": render_id,
                                "variantId": combo_info.get("variant_id", variant_id),
                                "title": combo_info.get("title", f"Variant {variant_id}"),
                                "description": combo_info.get("description", ""),
                                "formats": {},
                                "createdAt": datetime.utcnow().isoformat(),
                            }

                            # Map format URLs to S3 keys for presigned URL generation
                            for fmt, url in combo_info.get("variants", {}).items():
                                # Extract the S3 key from the URL
                                if fmt == "16:9":
                                    key = f"{folder}/combo_{variant_id}_h.mp4"
                                elif fmt == "1:1":
                                    key = f"{folder}/combo_{variant_id}_s.mp4"
                                elif fmt == "9:16":
                                    key = f"{folder}/combo_{variant_id}_v.mp4"
                                else:
                                    key = url

                                render_entry["formats"][fmt] = {"key": key}

                            renders.append(render_entry)
                            logger.info(f"Added render entry with ID {render_id} for variant {variant_id}")
            except Exception as e:
                logger.warning(f"Could not read combos for variant {variant_id}: {e}")

        # Save renders to MongoDB
        if renders:
            from db.mongodb import get_database
            import asyncio

            async def save_renders():
                db = await get_database()

                # Get existing renders
                job_doc = await db.jobs.find_one({"folder": folder})
                existing_renders = job_doc.get("renders", []) if job_doc else []

                logger.info(f"Found {len(existing_renders)} existing renders in database")
                logger.info(f"Adding {len(renders)} new renders")

                # Simply append new renders to existing ones
                # Each render has a unique ID with timestamp, so no duplicates
                all_renders = existing_renders + renders

                logger.info(f"Total renders after merge: {len(all_renders)}")

                # Update with combined list
                await db.jobs.update_one(
                    {"folder": folder},
                    {"$set": {"renders": all_renders}}
                )

            # Run async update from sync context
            from db.mongodb import get_main_loop
            main_loop = get_main_loop()
            if main_loop:
                future = asyncio.run_coroutine_threadsafe(save_renders(), main_loop)
                future.result(timeout=10)
                logger.info(f"Saved {len(renders)} render results to MongoDB (preserving existing renders)")
            else:
                logger.error("Could not save renders: main event loop not available")

        # Mark as complete (100%)
        update_job_status_sync(
            folder,
            status=JobStatus.COMPLETE,
            stage=JobStage.DONE,
            progress=100
        )

        logger.info(f"All renders completed for: {folder}")

    except Exception as e:
        logger.exception(f"Error rendering variants: {e}")

        # Update MongoDB with error status
        update_job_error_sync(folder, str(e))

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
