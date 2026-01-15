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

Notes:
- "segments" should contain 1-indexed segment numbers
- "score" should be a quality score from 1-100 based on narrative coherence
- Keep title and description very short to avoid truncation

Create {num_variants} distinct variants. Output ONLY valid JSON.
"""

        # Call Gemini with retry logic
        model = genai.GenerativeModel(ConfigService.CONFIG_TEXT_MODEL)

        max_retries = 3
        retry_delay = 2  # seconds
        variants = []
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.info(f"Gemini API call attempt {attempt + 1}/{max_retries}")

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
                variants = result.get("variants", [])
                logger.info(f"Parsed {len(variants)} variants")

                # Check if we got enough variants (at least 1)
                if len(variants) >= 1:
                    break
                else:
                    logger.warning(f"Got 0 variants, retrying...")
                    last_error = "No variants returned"

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

        if not variants:
            logger.error(f"All {max_retries} attempts failed. Last error: {last_error}")
            # Return empty list rather than failing - let frontend handle it

        return GenerateVariantsResponse(variants=variants)

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
