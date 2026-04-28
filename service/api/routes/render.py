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

import asyncio
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException

import config as ConfigService
import storage as StorageService
import utils as Utils
from api.models.responses import RenderRequest, RenderResponse, RendersResponse
from db.job_service import update_job_status_sync, update_job_error_sync
from db.models import JobStatus, JobStage
from db.mongodb import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


def _transform_variants_for_combiner(
    folder: str,
    variants: list,
    settings: dict,
    output_type: str = "video",
) -> list:
    """Transform frontend variant format to combiner format.

    Args:
        folder: The video folder name.
        variants: List of variants from frontend.
        settings: Global render settings.
        output_type: Top-level output type ("video" or "xml"); applied to any
            variant that does not specify `outputType` itself.

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

        variant_output_type = variant.get("outputType") or output_type or "video"
        combiner_variant = {
            "variant_id": variant.get("id", idx),
            "av_segments": av_segments,
            "title": variant.get("title", f"Variant {idx + 1}"),
            "description": variant.get("description", ""),
            "score": variant.get("score", 0),
            "score_reasoning": variant.get("reasoning", ""),
            "render_settings": render_settings,
            "output_type": variant_output_type,
        }
        combiner_variants.append(combiner_variant)

    return combiner_variants


def _render_variant_as_xml(
    folder: str,
    bucket: str,
    variant: dict,
    num_variants: int,
    cached_video_path: str,
    source_video_key: str,
):
    """Build a Premiere Pro bundle (zip with timeline.xml + media/ + audio/) for one variant.

    For each selected segment, ffmpeg-extracts:
      - media/clip_NNN.mp4   (video + stereo AAC, frame-accurate H.264 CRF 18)
      - audio/clip_NNN.wav   (audio-only, PCM s16 stereo 48kHz)
    Then writes timeline.xml referencing those files and zips everything up.
    The zip is uploaded to GCS and surfaced as the variant's render artifact.
    """
    import shutil
    import zipfile
    from combiner.combiner import _probe_video_full_metadata
    from combiner.premiere_xml import generate_premiere_xml

    variant_id = variant.get("variant_id", 0)
    av_segments = variant.get("av_segments", [])
    if not av_segments:
        raise ValueError(f"Variant {variant_id} has no segments")
    if not cached_video_path or not os.path.exists(cached_video_path):
        raise FileNotFoundError(
            f"Source video not cached locally for XML export of variant {variant_id}"
        )

    # ---- video metadata (width/height/fps) ----
    metadata_key = f"{folder}/metadata.json"
    metadata = {}
    try:
        existing = StorageService.download_file(metadata_key, fetch_contents=True)
        if existing:
            metadata = json.loads(existing.decode("utf-8"))
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning("Could not read metadata.json; will probe")

    needs_probe = not all(
        metadata.get(k) for k in ("width", "height", "fps")
    )
    if needs_probe:
        probed = _probe_video_full_metadata(cached_video_path)
        for key, value in probed.items():
            if value or key == "has_audio":
                metadata[key] = value
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as mf:
            json.dump(metadata, mf)
            tmp_meta = mf.name
        try:
            StorageService.upload_file(tmp_meta, metadata_key, overwrite=True)
        finally:
            os.unlink(tmp_meta)

    width = int(metadata.get("width") or 1920)
    height = int(metadata.get("height") or 1080)
    fps = float(metadata.get("fps") or 30.0)

    # ---- per-segment extraction ----
    work_dir = tempfile.mkdtemp(prefix=f"xml_variant_{variant_id}_")
    media_dir = os.path.join(work_dir, "media")
    audio_dir = os.path.join(work_dir, "audio")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)

    clips_for_xml = []
    try:
        for idx, seg in enumerate(av_segments, start=1):
            seg_id = seg.get("av_segment_id", idx)
            start_s = float(seg["start_s"])
            end_s = float(seg["end_s"])
            duration_s = max(end_s - start_s, 0.0)
            if duration_s <= 0:
                continue

            clip_basename = f"clip_{idx:03d}"
            video_out = os.path.join(media_dir, f"{clip_basename}.mp4")
            audio_out = os.path.join(audio_dir, f"{clip_basename}.wav")

            # Frame-accurate extraction: -ss/-to AFTER -i forces decoding from
            # the nearest keyframe so the cut lands exactly on the requested
            # timestamp. CRF 18 is visually lossless H.264.
            Utils.execute_subprocess_commands(
                cmds=[
                    "ffmpeg", "-y", "-i", cached_video_path,
                    "-ss", f"{start_s}", "-to", f"{end_s}",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                    "-movflags", "+faststart",
                    video_out,
                ],
                description=f"extract clip {idx} (video+audio) for variant {variant_id}",
            )
            Utils.execute_subprocess_commands(
                cmds=[
                    "ffmpeg", "-y", "-i", cached_video_path,
                    "-ss", f"{start_s}", "-to", f"{end_s}",
                    "-vn",
                    "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2",
                    audio_out,
                ],
                description=f"extract clip {idx} (audio-only) for variant {variant_id}",
            )

            clips_for_xml.append({
                "video_rel_path": f"media/{clip_basename}.mp4",
                "audio_rel_path": f"audio/{clip_basename}.wav",
                "duration_s": duration_s,
                "name": f"Segment {seg_id}",
            })

        if not clips_for_xml:
            raise ValueError(f"No valid clips extracted for variant {variant_id}")

        # ---- build XML ----
        xml_string = generate_premiere_xml(
            variant_id=variant_id,
            title=variant.get("title", f"Variant {variant_id}"),
            clips=clips_for_xml,
            width=width,
            height=height,
            fps=fps,
        )
        xml_path = os.path.join(work_dir, "timeline.xml")
        with open(xml_path, "w", encoding="utf-8") as xf:
            xf.write(xml_string)

        # ---- zip the bundle ----
        zip_path = os.path.join(
            tempfile.gettempdir(),
            f"variant_{variant_id}_{int(datetime.utcnow().timestamp())}.zip",
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(xml_path, arcname="timeline.xml")
            for sub in ("media", "audio"):
                sub_dir = os.path.join(work_dir, sub)
                for fname in sorted(os.listdir(sub_dir)):
                    zf.write(
                        os.path.join(sub_dir, fname),
                        arcname=f"{sub}/{fname}",
                    )

        # ---- upload ----
        zip_key = f"{folder}/{variant_id}-{num_variants}_premiere.zip"
        try:
            StorageService.upload_file(zip_path, zip_key, overwrite=True)
        finally:
            if os.path.exists(zip_path):
                os.unlink(zip_path)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _render_variants_background(folder: str, render_data: dict):
    """Background task to render video variants."""
    import combiner as CombinerService

    shared_tmp_dir = None
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
        output_type = render_data.get("output_type") or "video"
        combiner_variants = _transform_variants_for_combiner(
            folder, variants, settings, output_type
        )

        all_xml = bool(combiner_variants) and all(
            v.get("output_type") == "xml" for v in combiner_variants
        )

        logger.info(f"Transformed {len(combiner_variants)} variants for combiner")

        # Update progress: variants transformed (5%)
        update_job_status_sync(folder, progress=5)

        # Download input video once into a shared temp dir
        shared_tmp_dir = tempfile.mkdtemp(prefix='render_shared_')
        cached_video_path = None

        video_file_name = next(
            iter(
                StorageService.filter_video_files(
                    prefix=f'{folder}/{ConfigService.INPUT_FILENAME}',
                    bucket_name=bucket,
                    first_only=True,
                )
            ), None
        )

        if video_file_name:
            cached_video_path = StorageService.download_file(
                file_path=video_file_name,
                output_dir=shared_tmp_dir,
                bucket_name=bucket,
            )
            # Fallback: try input.mp4 if input.mov not found
            if cached_video_path is None and video_file_name.endswith('input.mov'):
                mp4_name = video_file_name.rsplit('/', 1)[0] + '/input.mp4'
                cached_video_path = StorageService.download_file(
                    file_path=mp4_name,
                    output_dir=shared_tmp_dir,
                    bucket_name=bucket,
                )

        if cached_video_path:
            logger.info(f"Cached input video at: {cached_video_path}")
        else:
            logger.warning("Could not cache input video, methods will download individually")

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

        if all_xml:
            logger.info("All variants are XML exports; skipping combiner initial render.")
            update_job_status_sync(folder, progress=20)
        else:
            # Create trigger file and run combiner initial phase
            trigger_file = Utils.TriggerFile(render_key)
            combiner_instance = CombinerService.Combiner(
                gcs_bucket_name=bucket, render_file=trigger_file
            )
            combiner_instance.initial_render(cached_video_path=cached_video_path)
            logger.info(f"Initial render completed for: {folder}")
            update_job_status_sync(folder, progress=20)

        # Calculate progress per variant (75% remaining / num_variants)
        num_variants = len(combiner_variants)
        progress_per_variant = 75 / num_variants if num_variants > 0 else 75

        # Render variants — parallel if multiple, sequential if single
        def _render_single_variant(idx, variant):
            variant_id = variant.get("variant_id", idx)

            if variant.get("output_type") == "xml":
                logger.info(f"Generating Premiere XML for variant {variant_id}")
                _render_variant_as_xml(
                    folder=folder,
                    bucket=bucket,
                    variant=variant,
                    num_variants=num_variants,
                    cached_video_path=cached_video_path,
                    source_video_key=video_file_name,
                )
                logger.info(f"Variant {variant_id} XML export completed")
                return idx

            variant_render_key = f"{folder}/{variant_id}-{num_variants}_{ConfigService.INPUT_RENDERING_FILE}"
            logger.info(f"Rendering variant {variant_id} from {variant_render_key}")

            variant_trigger = Utils.TriggerFile(variant_render_key)
            variant_combiner = CombinerService.Combiner(
                gcs_bucket_name=bucket, render_file=variant_trigger
            )
            variant_combiner.render(cached_video_path=cached_video_path)
            logger.info(f"Variant {variant_id} render completed")
            return idx

        if num_variants <= 1:
            # Single variant: render sequentially
            update_job_status_sync(
                folder, stage=JobStage.RENDER_ENCODING, progress=20
            )
            _render_single_variant(0, combiner_variants[0])
            update_job_status_sync(folder, progress=95)
        else:
            # Multiple variants: render in parallel (max 2 to manage disk/CPU)
            from concurrent.futures import ThreadPoolExecutor, as_completed
            update_job_status_sync(
                folder, stage=JobStage.RENDER_ENCODING, progress=20
            )
            logger.info(f"Rendering {num_variants} variants in parallel (max_workers=2)")
            completed_count = 0
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(_render_single_variant, idx, variant): idx
                    for idx, variant in enumerate(combiner_variants)
                }
                for future in as_completed(futures):
                    future.result()  # raise if failed
                    completed_count += 1
                    completed_progress = 20 + int(completed_count * progress_per_variant)
                    update_job_status_sync(folder, progress=completed_progress)

        # Update status: finalizing (95%)
        update_job_status_sync(
            folder,
            stage=JobStage.RENDER_FINALIZING,
            progress=95
        )

        # Collect render results from combos.json files (or XML manifest)
        renders = []
        for idx, variant in enumerate(combiner_variants):
            variant_id = variant.get("variant_id", idx)

            if variant.get("output_type") == "xml":
                zip_key = f"{folder}/{variant_id}-{num_variants}_premiere.zip"
                render_id = f"{variant_id}_{int(datetime.utcnow().timestamp() * 1000)}"
                render_entry = {
                    "id": render_id,
                    "variantId": variant_id,
                    "title": variant.get("title", f"Variant {variant_id}"),
                    "description": variant.get("description", ""),
                    "outputType": "xml",
                    "formats": {
                        "zip": {"key": zip_key},
                    },
                    "createdAt": datetime.utcnow().isoformat(),
                }
                renders.append(render_entry)
                logger.info(f"Added XML render entry {render_id} for variant {variant_id}")
                continue

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

                # Upsert by variantId — one entry per variant since GCS has one slot per variant
                renders_by_variant = {r["variantId"]: r for r in existing_renders}
                for r in renders:
                    renders_by_variant[r["variantId"]] = r
                all_renders = list(renders_by_variant.values())

                logger.info(f"Total renders after upsert: {len(all_renders)}")

                # Update with upserted list
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
                logger.info(f"Saved {len(renders)} render results to MongoDB (upserted by variantId)")
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

    finally:
        # Clean up the shared cached video temp dir
        if shared_tmp_dir and os.path.exists(shared_tmp_dir):
            logger.info(f"Cleaning up shared temp dir: {shared_tmp_dir}")
            shutil.rmtree(shared_tmp_dir, ignore_errors=True)


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
            "output_type": request.output_type or "video",
        }

        # Start background render task in a thread pool so it doesn't block
        # the main event loop (ffmpeg calls are long-running and sync).
        # This allows run_coroutine_threadsafe calls in job_service to work.
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _render_variants_background, folder, render_data)

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
        # Pull MongoDB-tracked render entries (covers both video and XML)
        db = await get_database()
        job_doc = await db.jobs.find_one({"folder": folder})
        renders_array = (job_doc or {}).get("renders") or None

        # Try to get combos.json (legacy/video-only consumers may rely on it)
        combos_key = f"{folder}/{ConfigService.OUTPUT_COMBINATIONS_FILE}"
        combos_content = StorageService.download_file(combos_key, fetch_contents=True)
        combos = None
        if combos_content:
            combos = json.loads(combos_content.decode("utf-8"))

        if not combos and not renders_array:
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

        return RendersResponse(folder=folder, combos=combos, renders=renders_array)

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
    """Soft-delete a video: marks as deleted immediately, removes GCS files in background.

    Args:
        folder: The video folder name.

    Returns:
        Success message.
    """
    try:
        # Soft delete in MongoDB first - respond fast
        db = await get_database()
        await db.jobs.update_one(
            {"folder": folder},
            {"$set": {"deleted": True, "updatedAt": datetime.utcnow()}}
        )

        # Delete GCS files in background
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _delete_gcs_files_bg, folder)

        return {"status": "success", "message": f"Deleted {folder}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting video: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete video: {str(e)}"
        )


def _delete_gcs_files_bg(folder: str):
    """Delete all GCS files for a folder (runs in thread pool)."""
    try:
        from storage.storage import delete_folder
        count = delete_folder(prefix=f"{folder}/")
        logger.info(f"Background GCS cleanup: deleted {count} files for {folder}")
    except Exception as e:
        logger.error(f"Background GCS cleanup failed for {folder}: {e}")
