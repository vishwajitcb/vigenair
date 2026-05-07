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

"""Video segments endpoints."""

import asyncio
import json
import logging
import os
import tempfile
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

import config as ConfigService
import storage as StorageService
import utils as Utils
from api.models.responses import (
    GenerateVariantsRequest,
    GenerateVariantsResponse,
    SegmentsResponse,
    SplitSegmentRequest,
    SplitSegmentResponse,
)
from config import variant_prompts
from utils.variant_segments import (
    DEFAULT_STRUCTURE,
    VALID_STRUCTURES,
    normalize_variant_segments,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _load_video_language(folder: str) -> str:
    """Load video language code from {folder}/language.txt, default 'en'."""
    try:
        key = f"{folder}/language.txt"
        content = StorageService.download_file(key, fetch_contents=True)
        if not content:
            return "en"
        lang = content.decode("utf-8").strip()
        return lang or "en"
    except Exception:
        return "en"


@router.get("/{folder}/segments", response_model=SegmentsResponse)
async def get_segments(folder: str):
    """Get extracted segments data for a video.

    Args:
        folder: The video folder name.

    Returns:
        SegmentsResponse with data.json and transcript.json contents.
    """
    try:
        bucket = os.environ.get("GCS_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="GCS_BUCKET not configured")

        # Try to get data.json
        data_key = f"{folder}/{ConfigService.OUTPUT_DATA_FILE}"
        data_content = StorageService.download_file(data_key, fetch_contents=True)

        if not data_content:
            raise HTTPException(
                status_code=404, detail=f"Segments not found. Video may still be processing."
            )

        data = json.loads(data_content.decode("utf-8"))

        # Try to get transcript.json (optional)
        transcript_key = f"{folder}/{ConfigService.OUTPUT_TRANSCRIPT_FILE}"
        transcript_content = StorageService.download_file(
            transcript_key, fetch_contents=True
        )
        transcript = None
        if transcript_content:
            transcript = json.loads(transcript_content.decode("utf-8"))

        return SegmentsResponse(folder=folder, data=data, transcript=transcript)

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.exception(f"Error parsing JSON: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse segments data")
    except Exception as e:
        logger.exception(f"Error getting segments: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get segments: {str(e)}"
        )


@router.post("/{folder}/variants/generate")
async def generate_variants(
    folder: str,
    request: GenerateVariantsRequest,
    background_tasks: BackgroundTasks,
):
    """Generate AI-powered variant suggestions.

    Two response modes depending on USE_LANGGRAPH:
      * Legacy (USE_LANGGRAPH=false): synchronous; returns
        `GenerateVariantsResponse` with the variants in the body.
      * LangGraph (USE_LANGGRAPH=true): kicks off the agent pipeline as a
        FastAPI background task and returns 202 Accepted immediately with
        `{"status": "generating", "folder": ...}`. The pipeline pushes
        variants to MongoDB as they finish; the frontend polls
        `/jobs/{folder}` and stops when `variantsGenerationStatus !=
        "generating"`.

    Args:
        folder: The video folder name.
        request: GenerateVariantsRequest with prompt and settings.
        background_tasks: FastAPI dependency for scheduling the bg pipeline.
    """
    try:
        import config as ConfigService
        from google.genai import types

        # Get segments data
        data_key = f"{folder}/{ConfigService.OUTPUT_DATA_FILE}"
        data_content = StorageService.download_file(data_key, fetch_contents=True)

        if not data_content:
            raise HTTPException(
                status_code=404, detail="Segments not found. Run extraction first."
            )

        data = json.loads(data_content.decode("utf-8"))
        # data.json is now a direct array of segments (not wrapped in object)
        segments = data if isinstance(data, list) else data.get("av_segments", [])

        if not segments:
            raise HTTPException(status_code=400, detail="No segments found in data")

        # Pre-filter segments that exceed the per-segment duration cap
        max_seg_dur = ConfigService.CONFIG_MAX_VARIANT_SEGMENT_DURATION
        eligible_segments = [
            s for s in segments if s.get("duration_s", 0) <= max_seg_dur
        ]
        filtered_count = len(segments) - len(eligible_segments)
        if filtered_count:
            logger.info(
                f"VARIANT_PREFILTER: Excluded {filtered_count} segments exceeding {max_seg_dur:.1f}s cap"
            )

        # Build segment descriptions for the prompt (eligible segments only, preserving original 1-based index)
        segment_descriptions = []
        eligible_indices = []
        for i, seg in enumerate(segments):
            if seg.get("duration_s", 0) <= max_seg_dur:
                desc = seg.get("description", "No description")
                duration = seg.get("duration_s", 0)
                segment_descriptions.append(
                    f"Segment {i + 1} ({duration:.1f}s): {desc}"
                )
                eligible_indices.append(i + 1)

        segments_text = "\n".join(segment_descriptions)
        total_duration = sum(s.get("duration_s", 0) for s in eligible_segments)

        # Build a lookup of {1-indexed-id-str: full segment dict} for the
        # variant_segments normalizer. Matches the convention used in
        # render.py:_transform_variants_for_combiner.
        segments_by_id: dict[str, dict] = {}
        for i, seg in enumerate(segments):
            segments_by_id[str(i + 1)] = seg

        # Create variant generation prompt
        target_duration = request.target_duration or total_duration * 0.3
        num_variants = request.num_variants

        prompt_option = request.prompt_option or "default"
        custom_prompt = request.custom_prompt or ""
        # Backward compat: if no prompt_option but legacy request.prompt is non-default text, treat as custom.
        if prompt_option == "default" and request.prompt and request.prompt not in variant_prompts.PROMPT_DIRECTIVES.values():
            prompt_option = "custom"
            custom_prompt = request.prompt

        video_language = request.video_language or _load_video_language(folder)
        expected_range = variant_prompts.calculate_expected_duration_range(target_duration)
        max_allowed_duration = target_duration * 1.5  # 50% overage allowed

        # ---- LangGraph path (USE_LANGGRAPH=true) ----
        # Schedule the agent pipeline as a background task and return 202.
        # The pipeline pushes variants to MongoDB as each one finishes; the
        # frontend polls /jobs/{folder} for live progress.
        if ConfigService.USE_LANGGRAPH:
            from agents.runner import run_variant_pipeline_background

            logger.info(
                f"VARIANT_GEN: scheduling LangGraph pipeline as background task "
                f"(model={ConfigService.CONFIG_TEXT_MODEL})"
            )
            request_params = {
                "prompt_option": prompt_option,
                "custom_prompt": custom_prompt,
                "business_objective": request.business_objective,
                "shorten_video": request.shorten_video,
            }
            generation_settings = {
                "promptOption": prompt_option,
                "customPrompt": custom_prompt,
                "targetDuration": float(target_duration),
                "shortenVideo": bool(request.shorten_video),
                "businessObjective": request.business_objective,
            }
            background_tasks.add_task(
                run_variant_pipeline_background,
                folder=folder,
                request_params=request_params,
                segments_text=segments_text,
                segments_by_id=segments_by_id,
                eligible_indices=eligible_indices,
                num_variants=num_variants,
                target_duration=target_duration,
                expected_duration_range=expected_range,
                max_allowed_duration=max_allowed_duration,
                video_language=video_language,
                generation_settings=generation_settings,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "status": "generating",
                    "folder": folder,
                    "message": "Variant generation started. Poll /jobs/{folder} for progress.",
                },
            )

        # ---- Pass 1: Hook & Angle Inventory ----
        # Only run for shortening mode. Aspect-ratio-only mode and crop-only
        # don't need hooks because they include all scenes.
        hook_inventory_block = ""
        run_hook_pass = request.shorten_video and prompt_option != "crop-only"
        if run_hook_pass:
            try:
                from google.genai import types as _genai_types

                hook_prompt = variant_prompts.assemble_hook_inventory_prompt(
                    segments_text=segments_text,
                    num_variants=num_variants,
                    video_language=video_language,
                )
                logger.info(
                    f"HOOK_PASS: starting Pass 1 hook inventory (model={ConfigService.CONFIG_TEXT_MODEL})"
                )
                _client = ConfigService.get_genai_client()
                _hook_resp = _client.models.generate_content(
                    model=ConfigService.CONFIG_TEXT_MODEL,
                    contents=hook_prompt,
                    config=_genai_types.GenerateContentConfig(
                        max_output_tokens=32768,
                        temperature=0.5,
                    ),
                )
                _hook_text = getattr(_hook_resp, "text", None)
                if not _hook_text:
                    _finish = None
                    try:
                        _finish = _hook_resp.candidates[0].finish_reason
                    except Exception:
                        pass
                    raise ValueError(f"Empty Pass 1 response (finish_reason={_finish})")

                _hook_text = _hook_text.strip()
                logger.info(f"HOOK_PASS raw: {_hook_text[:400]}")
                if _hook_text.startswith("```"):
                    _lines = _hook_text.split("\n")
                    _hook_text = "\n".join(_lines[1:-1])

                inventory = json.loads(_hook_text)
                hooks = inventory.get("hooks", [])
                if not hooks:
                    raise ValueError("Pass 1 returned no hooks")

                # Filter hooks to scenes that actually exist.
                valid_hooks = [
                    h for h in hooks
                    if isinstance(h.get("scene"), int) and 1 <= h["scene"] <= len(segments)
                ]
                # Drop hooks pointing at over-cap scenes the prefilter excluded.
                valid_hooks = [
                    h for h in valid_hooks
                    if h["scene"] in eligible_indices
                ]
                if len(valid_hooks) != len(hooks):
                    logger.warning(
                        f"HOOK_PASS: filtered {len(hooks) - len(valid_hooks)} hooks pointing at "
                        f"missing/ineligible scenes"
                    )
                if not valid_hooks:
                    raise ValueError("Pass 1 hooks all pointed at invalid scenes")

                inventory["hooks"] = valid_hooks
                assignment = variant_prompts.select_hooks_for_assignment(valid_hooks, num_variants)
                hook_inventory_block = variant_prompts.format_hook_inventory_block(inventory, assignment)
                logger.info(
                    f"HOOK_PASS: success — {len(valid_hooks)} hooks, "
                    f"assigned {len(assignment)} for {num_variants} variants. "
                    f"Assignment: {[(h.get('id'), h.get('scene'), h.get('hook_type'), h.get('dynamic')) for h in assignment]}"
                )
            except Exception as _e:
                logger.warning(f"HOOK_PASS: failed ({_e}); falling back to single-pass mode")
                hook_inventory_block = ""

        # ---- Pass 2: Variant Construction ----
        generation_prompt = variant_prompts.assemble_prompt(
            prompt_option=prompt_option,
            custom_prompt=custom_prompt,
            business_objective=request.business_objective,
            shorten_video=request.shorten_video,
            segments_text=segments_text,
            desired_duration=target_duration,
            expected_duration_range=expected_range,
            video_language=video_language,
            num_variants=num_variants,
            hook_inventory_block=hook_inventory_block,
        )

        logger.info(
            f"VARIANT_PROMPT: option={prompt_option} objective={request.business_objective} "
            f"shorten={request.shorten_video} lang={video_language} range={expected_range} "
            f"two_pass={'yes' if hook_inventory_block else 'no'}"
        )

        # Helper function to calculate actual duration of a variant
        def calculate_variant_duration(variant_segments: list) -> float:
            """Calculate actual total duration from segment indices."""
            total = 0.0
            for seg_num in variant_segments:
                # segment numbers are 1-indexed
                seg_idx = seg_num - 1
                if 0 <= seg_idx < len(segments):
                    total += segments[seg_idx].get("duration_s", 0)
            return total

        # Helper function to validate and filter variants
        def validate_variants(variants_list: list, max_duration: float) -> list:
            """Normalize segments (dedupe overlaps, reorder per structure),
            filter by duration cap, then dedupe by angle and hook_scene."""
            duration_ok = []
            for v in variants_list:
                raw_seg_ids = v.get("segments", [])

                # Backfill hook_scene from first emitted segment if Gemini omitted it.
                # Do this BEFORE normalization so we can pass the right hook to it.
                if not v.get("hook_scene") and raw_seg_ids:
                    try:
                        v["hook_scene"] = int(raw_seg_ids[0])
                    except (TypeError, ValueError):
                        v["hook_scene"] = None

                # Resolve structure (default + validate).
                structure = v.get("structure")
                if structure not in VALID_STRUCTURES:
                    if structure is not None:
                        logger.warning(
                            f"VARIANT_NORM_INVALID_STRUCTURE label={v.get('title')!r} "
                            f"got={structure!r}, defaulting to {DEFAULT_STRUCTURE}"
                        )
                    structure = DEFAULT_STRUCTURE

                # Normalize segments via shared utility.
                try:
                    ordered_ids, true_dur, _debug = normalize_variant_segments(
                        segment_ids=raw_seg_ids,
                        segments_by_id=segments_by_id,
                        hook_scene=v.get("hook_scene"),
                        structure=structure,
                        variant_label=str(v.get("title", "?")),
                    )
                except Exception as norm_err:
                    logger.exception(
                        f"VARIANT_NORM_FAIL label={v.get('title')!r} error={norm_err}"
                    )
                    # Fall back: keep raw IDs as strings, compute duration the old way.
                    ordered_ids = [str(s) for s in raw_seg_ids]
                    true_dur = calculate_variant_duration(raw_seg_ids)

                # Preserve original ID type (int) where Gemini emitted ints.
                if raw_seg_ids and isinstance(raw_seg_ids[0], int):
                    v["segments"] = [int(x) for x in ordered_ids]
                else:
                    v["segments"] = ordered_ids

                v["structure"] = structure
                v["actual_duration"] = true_dur
                v["estimated_duration"] = true_dur

                if true_dur <= max_duration:
                    duration_ok.append(v)
                    logger.info(
                        f"VARIANT_VALID: '{v.get('title')}' angle={v.get('angle')!r} "
                        f"hook={v.get('hook_scene')} structure={structure} "
                        f"segs={v['segments']} dur={true_dur:.1f}s"
                    )
                else:
                    logger.warning(
                        f"VARIANT_REJECTED: '{v.get('title')}' segs={v['segments']} "
                        f"dur={true_dur:.1f}s exceeds {max_duration:.1f}s"
                    )

            seen_angles: set[str] = set()
            seen_hooks: set[int] = set()
            unique = []
            for v in duration_ok:
                angle_key = " ".join((v.get("angle") or "").lower().split())
                hook = v.get("hook_scene")
                if angle_key and angle_key in seen_angles:
                    logger.warning(
                        f"VARIANT_DROPPED_DUP_ANGLE: '{v.get('title')}' angle={angle_key!r}"
                    )
                    continue
                if hook is not None and hook in seen_hooks:
                    logger.warning(
                        f"VARIANT_DROPPED_DUP_HOOK: '{v.get('title')}' hook={hook}"
                    )
                    continue
                if angle_key:
                    seen_angles.add(angle_key)
                if hook is not None:
                    seen_hooks.add(hook)
                unique.append(v)
            return unique

        # Call Gemini with retry logic
        client = ConfigService.get_genai_client()

        max_retries = 3
        retry_delay = 2  # seconds
        validated_variants = []
        last_error = None
        # max_allowed_duration is computed earlier (top of handler) so both
        # the LangGraph path and this legacy path use the same cap.

        for attempt in range(max_retries):
            try:
                logger.info(f"Gemini API call attempt {attempt + 1}/{max_retries} (target: {target_duration:.1f}s, max: {max_allowed_duration:.1f}s)")

                response = client.models.generate_content(
                    model=ConfigService.CONFIG_TEXT_MODEL,
                    contents=generation_prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=65536,
                        temperature=0.7,
                    ),
                )

                # Parse response — response.text can be None if the model
                # spent its budget on thought tokens and emitted no text parts.
                raw_text = getattr(response, "text", None)
                if not raw_text:
                    finish = None
                    try:
                        finish = response.candidates[0].finish_reason
                    except Exception:
                        pass
                    last_error = (
                        f"Empty response from Gemini (finish_reason={finish}). "
                        f"Likely token budget exhausted before text emission."
                    )
                    logger.warning(f"Attempt {attempt + 1} failed - {last_error}")
                    if attempt < max_retries - 1:
                        sleep_time = retry_delay * (2 ** attempt)
                        logger.info(f"Waiting {sleep_time}s before retry...")
                        time.sleep(sleep_time)
                    continue

                response_text = raw_text.strip()
                logger.info(f"Gemini raw response: {response_text[:500]}")

                # Handle markdown code blocks
                if response_text.startswith("```"):
                    lines = response_text.split("\n")
                    # Remove first line (```json) and last line (```)
                    response_text = "\n".join(lines[1:-1])
                    logger.info(f"After removing markdown: {response_text[:500]}")

                # Try to parse JSON
                result = json.loads(response_text)
                raw_variants = result.get("variants", [])
                logger.info(f"Parsed {len(raw_variants)} variants from Gemini")

                # Validate variants against duration constraint
                validated_variants = validate_variants(raw_variants, max_allowed_duration)
                logger.info(f"After validation: {len(validated_variants)} valid variants (of {len(raw_variants)})")

                # Check if we got enough valid variants (at least 1)
                if len(validated_variants) >= 1:
                    break
                else:
                    last_error = f"All {len(raw_variants)} variants exceeded max duration ({max_allowed_duration:.1f}s)"
                    logger.warning(f"{last_error}, retrying...")

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"Attempt {attempt + 1} failed - {last_error}")
                logger.warning(f"Response text was: {response_text[:1000] if 'response_text' in dir() else 'N/A'}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1} failed - Gemini API error: {last_error}")

            # Wait before retry (exponential backoff)
            if attempt < max_retries - 1:
                sleep_time = retry_delay * (2 ** attempt)
                logger.info(f"Waiting {sleep_time}s before retry...")
                time.sleep(sleep_time)

        if not validated_variants:
            logger.error(f"All {max_retries} attempts failed to produce valid variants. Last error: {last_error}")
            # Return empty list rather than failing - let frontend handle it

        # Stamp the rubric ceiling so the frontend can normalize correctly.
        score_max = variant_prompts.get_score_max(request.business_objective)
        for v in validated_variants:
            v["score_max"] = score_max

        return GenerateVariantsResponse(variants=validated_variants)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating variants: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate variants: {str(e)}"
        )


def _split_segment_background(folder: str, request: SplitSegmentRequest):
    """Background task to split a segment."""
    import extractor as ExtractorService

    try:
        logger.info(f"Starting segment split for folder: {folder}")

        bucket = os.environ.get("GCS_BUCKET")

        # Write split request file to trigger the extractor
        split_data = {
            "segment_id": request.segment_id,
            "split_times": request.split_times,
        }

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json"
        ) as f:
            json.dump(split_data, f)
            temp_path = f.name

        # Upload split request file
        split_key = f"{folder}/{request.segment_id}{ConfigService.INPUT_EXTRACTION_SPLIT_SEGMENT_SUFFIX}"
        StorageService.upload_file(temp_path, split_key)
        os.unlink(temp_path)

        # Create trigger file and run split
        trigger_file = Utils.TriggerFile(split_key)
        extractor_instance = ExtractorService.Extractor(
            gcs_bucket_name=bucket, media_file=trigger_file
        )
        extractor_instance.split_av_segment()

        logger.info(f"Segment split completed for: {folder}")

    except Exception as e:
        logger.exception(f"Error splitting segment: {e}")


@router.post("/{folder}/segments/split", response_model=SplitSegmentResponse)
async def split_segment(
    folder: str, request: SplitSegmentRequest, background_tasks: BackgroundTasks
):
    """Split a segment at specified times.

    Args:
        folder: The video folder name.
        request: SplitSegmentRequest with segment ID and split times.
        background_tasks: FastAPI background tasks handler.

    Returns:
        SplitSegmentResponse with status.
    """
    try:
        # Verify folder exists
        data_key = f"{folder}/{ConfigService.OUTPUT_DATA_FILE}"
        data_content = StorageService.download_file(data_key, fetch_contents=True)

        if not data_content:
            raise HTTPException(
                status_code=404, detail="Segments not found. Run extraction first."
            )

        # Run in thread pool so long-running sync work doesn't block the event loop
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _split_segment_background, folder, request)

        return SplitSegmentResponse(
            status="processing",
            message=f"Segment split started for {request.segment_id}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error starting segment split: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start segment split: {str(e)}"
        )
