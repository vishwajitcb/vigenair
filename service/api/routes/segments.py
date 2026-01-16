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

import json
import logging
import os
import tempfile
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException

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

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{folder}/segments", response_model=SegmentsResponse)
async def get_segments(folder: str):
    """Get extracted segments data for a video.

    Args:
        folder: The video folder name.

    Returns:
        SegmentsResponse with data.json and transcript.json contents.
    """
    try:
        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            raise HTTPException(status_code=500, detail="S3_BUCKET not configured")

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


@router.post("/{folder}/variants/generate", response_model=GenerateVariantsResponse)
async def generate_variants(folder: str, request: GenerateVariantsRequest):
    """Generate AI-powered variant suggestions.

    Args:
        folder: The video folder name.
        request: GenerateVariantsRequest with prompt and settings.

    Returns:
        GenerateVariantsResponse with generated variants.
    """
    try:
        import google.generativeai as genai

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

        # Build segment descriptions for the prompt
        segment_descriptions = []
        for i, seg in enumerate(segments):
            desc = seg.get("description", "No description")
            duration = seg.get("duration_s", 0)
            segment_descriptions.append(
                f"Segment {i + 1} ({duration:.1f}s): {desc}"
            )

        segments_text = "\n".join(segment_descriptions)
        total_duration = sum(s.get("duration_s", 0) for s in segments)

        # Create variant generation prompt
        target_duration = request.target_duration or total_duration * 0.3
        num_variants = request.num_variants

        generation_prompt = f"""You are an expert video ad editor. Given the following video segments from a longer ad,
create {num_variants} different shorter variant scripts that tell a compelling story.

Original Video Segments:
{segments_text}

Total Original Duration: {total_duration:.1f} seconds
Target Duration for Each Variant: ~{target_duration:.1f} seconds

User's Request: {request.prompt}

For each variant, output in this JSON format (no comments allowed):
{{
  "variants": [
    {{
      "title": "Short Title (2-4 words)",
      "segments": [1, 3, 5],
      "description": "One sentence description",
      "estimated_duration": 15.0,
      "score": 85
    }}
  ]
}}

CRITICAL RULES:
- "segments" should contain 1-indexed segment numbers
- "estimated_duration" MUST be the actual SUM of the selected segment durations - ADD THEM UP!
- The total duration of selected segments MUST be close to the target duration (~{target_duration:.1f}s)
- Do NOT select segments that would make the total exceed {target_duration * 1.5:.1f} seconds
- "score" should be a quality score from 1-100 based on narrative coherence
- Keep title and description very short to avoid truncation

Create {num_variants} distinct variants. Output ONLY valid JSON.
"""

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
            """Filter variants that exceed the maximum allowed duration."""
            valid = []
            for v in variants_list:
                seg_ids = v.get("segments", [])
                actual_duration = calculate_variant_duration(seg_ids)
                # Update the estimated_duration with actual calculated value
                v["actual_duration"] = actual_duration
                v["estimated_duration"] = actual_duration  # Correct the estimate

                if actual_duration <= max_duration:
                    valid.append(v)
                    logger.info(
                        f"VARIANT_VALID: '{v.get('title')}' - segments {seg_ids} = {actual_duration:.1f}s (<= {max_duration:.1f}s)"
                    )
                else:
                    logger.warning(
                        f"VARIANT_REJECTED: '{v.get('title')}' - segments {seg_ids} = {actual_duration:.1f}s (exceeds {max_duration:.1f}s)"
                    )
            return valid

        # Call Gemini with retry logic
        model = genai.GenerativeModel(ConfigService.CONFIG_TEXT_MODEL)

        max_retries = 3
        retry_delay = 2  # seconds
        validated_variants = []
        last_error = None
        # Allow 50% overage for flexibility, but not more
        max_allowed_duration = target_duration * 1.5

        for attempt in range(max_retries):
            try:
                logger.info(f"Gemini API call attempt {attempt + 1}/{max_retries} (target: {target_duration:.1f}s, max: {max_allowed_duration:.1f}s)")

                response = model.generate_content(
                    generation_prompt,
                    generation_config={
                        "max_output_tokens": 8192,
                        "temperature": 0.7,
                    },
                )

                # Parse response
                response_text = response.text.strip()
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

        bucket = os.environ.get("S3_BUCKET")

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

        # Start background split task
        background_tasks.add_task(_split_segment_background, folder, request)

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
