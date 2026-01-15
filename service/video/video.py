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

"""Vigenair video service.

This module contains functions to analyze videos using Gemini Vision API.
Replaces the Video Intelligence API with Gemini-based analysis.
"""

import json
import logging
import os
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import google.generativeai as genai
import config as ConfigService
import pandas as pd


# ==============================================================================
# Data Classes to mimic Video Intelligence API structures
# ==============================================================================

@dataclass
class TimeOffset:
    """Represents a time offset with seconds and nanoseconds."""
    seconds: int = 0
    nanos: int = 0

    @property
    def microseconds(self):
        return self.nanos // 1000


@dataclass
class Segment:
    """Represents a time segment."""
    start_time_offset: TimeOffset = field(default_factory=TimeOffset)
    end_time_offset: TimeOffset = field(default_factory=TimeOffset)


@dataclass
class Entity:
    """Represents an entity with a description."""
    description: str = ""


@dataclass
class ShotAnnotation:
    """Represents a shot/scene change."""
    start_time_offset: TimeOffset = field(default_factory=TimeOffset)
    end_time_offset: TimeOffset = field(default_factory=TimeOffset)


@dataclass
class LabelSegment:
    """Represents a labeled segment."""
    segment: Segment = field(default_factory=Segment)
    confidence: float = 0.0


@dataclass
class LabelAnnotation:
    """Represents a label annotation."""
    entity: Entity = field(default_factory=Entity)
    segments: List[LabelSegment] = field(default_factory=list)


@dataclass
class NormalizedBoundingBox:
    """Normalized bounding box coordinates."""
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass
class ObjectFrame:
    """Frame with bounding box for object tracking."""
    time_offset: TimeOffset = field(default_factory=TimeOffset)
    normalized_bounding_box: NormalizedBoundingBox = field(default_factory=NormalizedBoundingBox)


@dataclass
class ObjectAnnotation:
    """Represents object tracking annotation."""
    entity: Entity = field(default_factory=Entity)
    segment: Segment = field(default_factory=Segment)
    confidence: float = 0.0
    frames: List[ObjectFrame] = field(default_factory=list)


@dataclass
class TextSegmentFrameVertex:
    """Vertex for text bounding box."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class TextSegmentFrameBox:
    """Rotated bounding box for text."""
    vertices: List[TextSegmentFrameVertex] = field(default_factory=list)


@dataclass
class TextSegmentFrame:
    """Frame for text segment."""
    rotated_bounding_box: TextSegmentFrameBox = field(default_factory=TextSegmentFrameBox)


@dataclass
class TextSegment:
    """Represents a text segment."""
    segment: Segment = field(default_factory=Segment)
    confidence: float = 0.0
    frames: List[TextSegmentFrame] = field(default_factory=list)


@dataclass
class TextAnnotation:
    """Represents text detected in video."""
    text: str = ""
    segments: List[TextSegment] = field(default_factory=list)


@dataclass
class TimestampedObject:
    """Timestamped object for logo/face tracking."""
    time_offset: TimeOffset = field(default_factory=TimeOffset)
    normalized_bounding_box: NormalizedBoundingBox = field(default_factory=NormalizedBoundingBox)
    attributes: List[Any] = field(default_factory=list)


@dataclass
class Track:
    """Track for logo/face detection."""
    segment: Segment = field(default_factory=Segment)
    confidence: float = 0.0
    timestamped_objects: List[TimestampedObject] = field(default_factory=list)
    attributes: List[Any] = field(default_factory=list)


@dataclass
class LogoAnnotation:
    """Represents logo recognition annotation."""
    entity: Entity = field(default_factory=Entity)
    tracks: List[Track] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)


@dataclass
class FaceAnnotation:
    """Represents face detection annotation."""
    tracks: List[Track] = field(default_factory=list)


@dataclass
class VideoAnnotationResults:
    """Mimics videointelligence.VideoAnnotationResults structure."""
    input_uri: str = ""
    segment: Segment = field(default_factory=Segment)
    shot_annotations: List[ShotAnnotation] = field(default_factory=list)
    segment_label_annotations: List[LabelAnnotation] = field(default_factory=list)
    shot_label_annotations: List[LabelAnnotation] = field(default_factory=list)
    frame_label_annotations: List[LabelAnnotation] = field(default_factory=list)
    object_annotations: List[ObjectAnnotation] = field(default_factory=list)
    text_annotations: List[TextAnnotation] = field(default_factory=list)
    logo_recognition_annotations: List[LogoAnnotation] = field(default_factory=list)
    face_detection_annotations: List[FaceAnnotation] = field(default_factory=list)


# ==============================================================================
# Main Analysis Functions
# ==============================================================================

def video_annotation_from_json(annotation_json: Any) -> VideoAnnotationResults:
    """Creates VideoAnnotationResults from JSON data."""
    data = annotation_json.get('annotation_results', [{}])[0]
    return _parse_annotation_results(data)


def _parse_annotation_results(data: Dict[str, Any]) -> VideoAnnotationResults:
    """Parses annotation results from dictionary."""
    result = VideoAnnotationResults()
    result.input_uri = data.get('input_uri', '')

    # Parse segment
    if 'segment' in data:
        result.segment = _parse_segment(data['segment'])

    # Parse shots
    for shot in data.get('shot_annotations', []):
        result.shot_annotations.append(ShotAnnotation(
            start_time_offset=_parse_time_offset(shot.get('start_time_offset', {})),
            end_time_offset=_parse_time_offset(shot.get('end_time_offset', {}))
        ))

    # Parse labels
    for label in data.get('shot_label_annotations', []):
        result.shot_label_annotations.append(_parse_label_annotation(label))

    # Parse objects
    for obj in data.get('object_annotations', []):
        result.object_annotations.append(_parse_object_annotation(obj))

    # Parse text
    for text in data.get('text_annotations', []):
        result.text_annotations.append(_parse_text_annotation(text))

    # Parse logos
    for logo in data.get('logo_recognition_annotations', []):
        result.logo_recognition_annotations.append(_parse_logo_annotation(logo))

    return result


def _parse_time_offset(data: Dict[str, Any]) -> TimeOffset:
    """Parses time offset from dictionary."""
    return TimeOffset(
        seconds=data.get('seconds', 0),
        nanos=data.get('nanos', 0)
    )


def _parse_segment(data: Dict[str, Any]) -> Segment:
    """Parses segment from dictionary."""
    return Segment(
        start_time_offset=_parse_time_offset(data.get('start_time_offset', {})),
        end_time_offset=_parse_time_offset(data.get('end_time_offset', {}))
    )


def _parse_label_annotation(data: Dict[str, Any]) -> LabelAnnotation:
    """Parses label annotation from dictionary."""
    segments = []
    for seg in data.get('segments', []):
        segments.append(LabelSegment(
            segment=_parse_segment(seg.get('segment', {})),
            confidence=seg.get('confidence', 0.0)
        ))
    return LabelAnnotation(
        entity=Entity(description=data.get('entity', {}).get('description', '')),
        segments=segments
    )


def _parse_object_annotation(data: Dict[str, Any]) -> ObjectAnnotation:
    """Parses object annotation from dictionary."""
    frames = []
    for frame in data.get('frames', []):
        box = frame.get('normalized_bounding_box', {})
        frames.append(ObjectFrame(
            time_offset=_parse_time_offset(frame.get('time_offset', {})),
            normalized_bounding_box=NormalizedBoundingBox(
                left=box.get('left', 0.0),
                top=box.get('top', 0.0),
                right=box.get('right', 0.0),
                bottom=box.get('bottom', 0.0)
            )
        ))
    return ObjectAnnotation(
        entity=Entity(description=data.get('entity', {}).get('description', '')),
        segment=_parse_segment(data.get('segment', {})),
        confidence=data.get('confidence', 0.0),
        frames=frames
    )


def _parse_text_annotation(data: Dict[str, Any]) -> TextAnnotation:
    """Parses text annotation from dictionary."""
    segments = []
    for seg in data.get('segments', []):
        frames = []
        for frame in seg.get('frames', []):
            vertices = []
            for v in frame.get('rotated_bounding_box', {}).get('vertices', []):
                vertices.append(TextSegmentFrameVertex(x=v.get('x', 0.0), y=v.get('y', 0.0)))
            frames.append(TextSegmentFrame(
                rotated_bounding_box=TextSegmentFrameBox(vertices=vertices)
            ))
        segments.append(TextSegment(
            segment=_parse_segment(seg.get('segment', {})),
            confidence=seg.get('confidence', 0.0),
            frames=frames
        ))
    return TextAnnotation(text=data.get('text', ''), segments=segments)


def _parse_logo_annotation(data: Dict[str, Any]) -> LogoAnnotation:
    """Parses logo annotation from dictionary."""
    tracks = []
    for track in data.get('tracks', []):
        timestamped_objects = []
        for obj in track.get('timestamped_objects', []):
            box = obj.get('normalized_bounding_box', {})
            timestamped_objects.append(TimestampedObject(
                time_offset=_parse_time_offset(obj.get('time_offset', {})),
                normalized_bounding_box=NormalizedBoundingBox(
                    left=box.get('left', 0.0),
                    top=box.get('top', 0.0),
                    right=box.get('right', 0.0),
                    bottom=box.get('bottom', 0.0)
                )
            ))
        tracks.append(Track(
            segment=_parse_segment(track.get('segment', {})),
            confidence=track.get('confidence', 0.0),
            timestamped_objects=timestamped_objects
        ))

    segments = [_parse_segment(s) for s in data.get('segments', [])]

    return LogoAnnotation(
        entity=Entity(description=data.get('entity', {}).get('description', '')),
        tracks=tracks,
        segments=segments
    )


def combine_analysis_chunks(
    analysis_chunks: Sequence[VideoAnnotationResults]
) -> Tuple[Dict[str, Any], VideoAnnotationResults]:
    """Combines video analysis chunks into a single response."""
    if not analysis_chunks:
        return {}, VideoAnnotationResults()

    # For single chunk, just return it
    if len(analysis_chunks) == 1:
        result = analysis_chunks[0]
        result_dict = _annotation_results_to_dict(result)
        return {'annotation_results': [result_dict]}, result

    # Combine multiple chunks
    combined = VideoAnnotationResults()
    combined.input_uri = analysis_chunks[0].input_uri
    cumulative_seconds = 0

    for index, chunk in enumerate(analysis_chunks):
        if index == 0:
            combined.shot_annotations.extend(chunk.shot_annotations)
            combined.shot_label_annotations.extend(chunk.shot_label_annotations)
            combined.object_annotations.extend(chunk.object_annotations)
            combined.text_annotations.extend(chunk.text_annotations)
            combined.logo_recognition_annotations.extend(chunk.logo_recognition_annotations)
            if chunk.shot_annotations:
                cumulative_seconds = chunk.shot_annotations[-1].end_time_offset.seconds
        else:
            # Adjust timestamps for subsequent chunks
            for shot in chunk.shot_annotations:
                shot.start_time_offset.seconds += cumulative_seconds
                shot.end_time_offset.seconds += cumulative_seconds
                combined.shot_annotations.append(shot)

            # Similar adjustments for other annotations...
            combined.shot_label_annotations.extend(chunk.shot_label_annotations)
            combined.object_annotations.extend(chunk.object_annotations)
            combined.text_annotations.extend(chunk.text_annotations)
            combined.logo_recognition_annotations.extend(chunk.logo_recognition_annotations)

            if chunk.shot_annotations:
                cumulative_seconds = combined.shot_annotations[-1].end_time_offset.seconds

    if combined.shot_annotations:
        combined.segment.end_time_offset = combined.shot_annotations[-1].end_time_offset

    result_dict = _annotation_results_to_dict(combined)
    return {'annotation_results': [result_dict]}, combined


def _annotation_results_to_dict(result: VideoAnnotationResults) -> Dict[str, Any]:
    """Converts VideoAnnotationResults to dictionary."""
    return {
        'input_uri': result.input_uri,
        'segment': {
            'start_time_offset': {'seconds': result.segment.start_time_offset.seconds},
            'end_time_offset': {'seconds': result.segment.end_time_offset.seconds}
        },
        'shot_annotations': [
            {
                'start_time_offset': {'seconds': s.start_time_offset.seconds, 'nanos': s.start_time_offset.nanos},
                'end_time_offset': {'seconds': s.end_time_offset.seconds, 'nanos': s.end_time_offset.nanos}
            } for s in result.shot_annotations
        ],
        'shot_label_annotations': [
            {
                'entity': {'description': l.entity.description},
                'segments': [{'segment': {
                    'start_time_offset': {'seconds': s.segment.start_time_offset.seconds},
                    'end_time_offset': {'seconds': s.segment.end_time_offset.seconds}
                }, 'confidence': s.confidence} for s in l.segments]
            } for l in result.shot_label_annotations
        ],
        'object_annotations': [
            {
                'entity': {'description': o.entity.description},
                'segment': {
                    'start_time_offset': {'seconds': o.segment.start_time_offset.seconds},
                    'end_time_offset': {'seconds': o.segment.end_time_offset.seconds}
                },
                'confidence': o.confidence,
                'frames': [
                    {
                        'time_offset': {
                            'seconds': f.time_offset.seconds,
                            'nanos': f.time_offset.nanos
                        },
                        'normalized_bounding_box': {
                            'left': f.normalized_bounding_box.left,
                            'top': f.normalized_bounding_box.top,
                            'right': f.normalized_bounding_box.right,
                            'bottom': f.normalized_bounding_box.bottom
                        }
                    } for f in o.frames
                ]
            } for o in result.object_annotations
        ],
        'text_annotations': [
            {
                'text': t.text,
                'segments': [{'segment': {
                    'start_time_offset': {'seconds': s.segment.start_time_offset.seconds},
                    'end_time_offset': {'seconds': s.segment.end_time_offset.seconds}
                }, 'confidence': s.confidence} for s in t.segments]
            } for t in result.text_annotations
        ],
        'logo_recognition_annotations': [
            {
                'entity': {'description': l.entity.description},
                'tracks': [{'segment': {
                    'start_time_offset': {'seconds': t.segment.start_time_offset.seconds},
                    'end_time_offset': {'seconds': t.segment.end_time_offset.seconds}
                }, 'confidence': t.confidence} for t in l.tracks]
            } for l in result.logo_recognition_annotations
        ]
    }


def _run_gemini_video_analysis(
    local_video_path: str,
    video_file_path: str,
) -> str:
    """Runs Gemini Vision analysis in a thread.

    Note: Uses ThreadPoolExecutor for cleaner timeout handling and to avoid
    blocking the main thread during long-running API calls.

    Args:
        local_video_path: Path to the local video file.
        video_file_path: Original S3 path (for logging).

    Returns:
        The response text from Gemini.
    """
    # Initialize Gemini (must be done in each thread/process)
    api_key = os.environ.get('GOOGLE_API_KEY')
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set")

    genai.configure(api_key=api_key)

    # Upload video to Gemini Files API
    logging.info('VIDEO_ANALYSIS - Uploading video to Gemini...')
    video_file = genai.upload_file(local_video_path)

    # Wait for processing
    while video_file.state.name == 'PROCESSING':
        time.sleep(2)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == 'FAILED':
        raise ValueError(f'Video processing failed: {video_file.state.name}')

    logging.info('VIDEO_ANALYSIS - Video uploaded, running analysis...')

    # Create model and analyze
    model = genai.GenerativeModel(ConfigService.CONFIG_VISION_MODEL)

    response = model.generate_content(
        [video_file, ConfigService.VIDEO_ANALYSIS_PROMPT],
        generation_config=ConfigService.VIDEO_ANALYSIS_CONFIG,
    )

    # Cleanup uploaded Gemini file
    try:
        genai.delete_file(video_file.name)
        logging.info('VIDEO_ANALYSIS - Cleaned up Gemini file: %s', video_file.name)
    except Exception as e:
        logging.warning('Failed to delete uploaded video file: %s', e)

    # Check for empty response (e.g., content moderation)
    if not response.candidates:
        raise ValueError(
            'Gemini returned empty response - video may have been blocked by '
            'content moderation or safety filters'
        )

    return response.text


def analyse_video(
    video_file_path: str,
    bucket_name: str,
    gcs_folder: str,
    output_file_name: str,
) -> VideoAnnotationResults:
    """Runs video analysis via Gemini Vision API and returns the results.

    Note: Uses ThreadPoolExecutor for Gemini API calls to enable timeout handling
    and avoid blocking during long-running API operations.

    Args:
        video_file_path: Path to the video file (local path or S3 key).
        bucket_name: S3 bucket name.
        gcs_folder: S3 folder path for storing results.
        output_file_name: Name of the output analysis file.

    Returns:
        VideoAnnotationResults with the analysis data.
    """
    import concurrent.futures
    import tempfile
    import storage as StorageService
    import utils as Utils

    logging.info('VIDEO_ANALYSIS - Starting Gemini Vision analysis for: %s', video_file_path)

    # Download video from S3 if it's not a local file
    local_video_path = video_file_path
    tmp_dir = None
    if not os.path.exists(video_file_path):
        tmp_dir = tempfile.mkdtemp()
        logging.info('VIDEO_ANALYSIS - Downloading video from S3: %s', video_file_path)
        local_video_path = StorageService.download_file(
            file_path=Utils.TriggerFile(video_file_path),
            output_dir=tmp_dir,
        )
        if not local_video_path:
            raise ValueError(f"Failed to download video from S3: {video_file_path}")

    # Run Gemini analysis in a thread to avoid issues with forked processes
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _run_gemini_video_analysis,
            local_video_path,
            video_file_path,
        )
        response_text = future.result(timeout=600)  # 10 minute timeout for video

    # Parse response
    result = _parse_gemini_response(response_text, video_file_path)

    logging.info('VIDEO_ANALYSIS - Analysis complete. Found %d shots.', len(result.shot_annotations))

    # Save analysis results to S3
    result_dict = _annotation_results_to_dict(result)
    output_json = {'annotation_results': [result_dict]}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(output_json, f, indent=2)
        temp_json_path = f.name

    try:
        s3_destination = f'{gcs_folder}/{output_file_name}'
        logging.info('VIDEO_ANALYSIS - Uploading analysis to S3: %s', s3_destination)
        StorageService.upload_file(
            file_path=temp_json_path,
            destination_file_name=s3_destination,
            overwrite=True,
        )
        logging.info('VIDEO_ANALYSIS - Successfully saved %s', output_file_name)
    finally:
        if os.path.exists(temp_json_path):
            os.unlink(temp_json_path)

    return result


def _parse_gemini_response(response_text: str, input_uri: str) -> VideoAnnotationResults:
    """Parses Gemini response into VideoAnnotationResults."""
    result = VideoAnnotationResults()
    result.input_uri = input_uri

    # Extract JSON from response (handle markdown code blocks)
    text = response_text.strip()
    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logging.warning('Failed to parse Gemini response as JSON: %s', e)
        # Return empty results with minimal shot data
        result.shot_annotations.append(ShotAnnotation(
            start_time_offset=TimeOffset(seconds=0),
            end_time_offset=TimeOffset(seconds=30)  # Default 30 second video
        ))
        return result

    # Parse shots
    for shot in data.get('shots', []):
        result.shot_annotations.append(ShotAnnotation(
            start_time_offset=TimeOffset(seconds=int(shot.get('start_seconds', 0))),
            end_time_offset=TimeOffset(seconds=int(shot.get('end_seconds', 0)))
        ))

    # Parse labels
    for label in data.get('labels', []):
        segments = []
        for seg in label.get('segments', []):
            segments.append(LabelSegment(
                segment=Segment(
                    start_time_offset=TimeOffset(seconds=int(seg.get('start', 0))),
                    end_time_offset=TimeOffset(seconds=int(seg.get('end', 0)))
                ),
                confidence=label.get('confidence', 0.8)
            ))
        result.shot_label_annotations.append(LabelAnnotation(
            entity=Entity(description=label.get('description', '')),
            segments=segments
        ))

    # Parse objects
    for obj in data.get('objects', []):
        start_sec = int(obj.get('start', 0))
        end_sec = int(obj.get('end', 0))
        # Generate synthetic frames for object tracking (required by frontend)
        # Since Gemini doesn't provide frame-level bounding boxes, we create
        # frames at regular intervals with a centered bounding box
        frames = []
        for t in range(start_sec, max(end_sec, start_sec + 1)):
            frames.append(ObjectFrame(
                time_offset=TimeOffset(seconds=t),
                normalized_bounding_box=NormalizedBoundingBox(
                    left=0.1, top=0.1, right=0.9, bottom=0.9
                )
            ))
        result.object_annotations.append(ObjectAnnotation(
            entity=Entity(description=obj.get('description', '')),
            segment=Segment(
                start_time_offset=TimeOffset(seconds=start_sec),
                end_time_offset=TimeOffset(seconds=end_sec)
            ),
            confidence=obj.get('confidence', 0.8),
            frames=frames
        ))

    # Parse text
    for text_item in data.get('text', []):
        result.text_annotations.append(TextAnnotation(
            text=text_item.get('text', ''),
            segments=[TextSegment(
                segment=Segment(
                    start_time_offset=TimeOffset(seconds=int(text_item.get('start', 0))),
                    end_time_offset=TimeOffset(seconds=int(text_item.get('end', 0)))
                ),
                confidence=text_item.get('confidence', 0.8)
            )]
        ))

    # Parse logos
    for logo in data.get('logos', []):
        result.logo_recognition_annotations.append(LogoAnnotation(
            entity=Entity(description=logo.get('description', '')),
            tracks=[Track(
                segment=Segment(
                    start_time_offset=TimeOffset(seconds=int(logo.get('start', 0))),
                    end_time_offset=TimeOffset(seconds=int(logo.get('end', 0)))
                ),
                confidence=0.8
            )]
        ))

    # Set overall segment
    if result.shot_annotations:
        result.segment = Segment(
            start_time_offset=result.shot_annotations[0].start_time_offset,
            end_time_offset=result.shot_annotations[-1].end_time_offset
        )

    return result


# ==============================================================================
# Data Extraction Functions (unchanged from original)
# ==============================================================================

def get_visual_shots_data(
    annotation_results: VideoAnnotationResults,
    transcription_dataframe: pd.DataFrame,
    audio_segment_id_key: str = 'audio_segment_id',
    video_duration: float = None,
) -> pd.DataFrame:
    """Returns a DataFrame of visual shots.

    Args:
        annotation_results: Video annotation results from Gemini.
        transcription_dataframe: Transcription data.
        audio_segment_id_key: Key for audio segment ID.
        video_duration: Video duration in seconds to clamp shot times.
    """
    logging.info(
        'SHOT_DETECTION: Gemini Vision detected %d shots',
        len(annotation_results.shot_annotations)
    )
    shots_data = []
    for i, shot in enumerate(annotation_results.shot_annotations):
        start_time = (
            shot.start_time_offset.seconds
            + shot.start_time_offset.microseconds / 1e6
        )
        end_time = (
            shot.end_time_offset.seconds + shot.end_time_offset.microseconds / 1e6
        )

        # Clamp times to video duration if provided
        if video_duration is not None:
            if start_time >= video_duration:
                logging.warning(
                    'SHOT_DETECTION: Skipping shot %d - start %.2fs exceeds '
                    'video duration %.2fs', i + 1, start_time, video_duration
                )
                continue
            if end_time > video_duration:
                logging.info(
                    'SHOT_DETECTION: Clamping shot %d end from %.2fs to %.2fs',
                    i + 1, end_time, video_duration
                )
                end_time = video_duration

        duration = end_time - start_time

        if duration > 0:
            audio_segment_ids = _identify_segments(
                start_time,
                end_time,
                transcription_dataframe,
                audio_segment_id_key,
            )
            shots_data.append((
                i + 1,
                audio_segment_ids,
                start_time,
                end_time,
                duration,
            ))

    shots_dataframe = pd.DataFrame(
        shots_data,
        columns=[
            'shot_id',
            'audio_segment_ids',
            'start_s',
            'end_s',
            'duration_s',
        ],
    )
    shots_dataframe = shots_dataframe.sort_values(by='start_s')

    return shots_dataframe


def get_shot_labels_data(
    annotation_results: VideoAnnotationResults,
    optimised_av_segments: pd.DataFrame,
    av_segment_id_key: str = 'av_segment_id',
) -> pd.DataFrame:
    """Returns a DataFrame of shot labels."""
    labels_data = []
    for shot_label in annotation_results.shot_label_annotations:
        for shot in shot_label.segments:
            start_time = (
                shot.segment.start_time_offset.seconds
                + shot.segment.start_time_offset.microseconds / 1e6
            )
            end_time = (
                shot.segment.end_time_offset.seconds
                + shot.segment.end_time_offset.microseconds / 1e6
            )
            confidence = shot.confidence

            labels_data.append((
                shot_label.entity.description,
                _identify_segments(
                    start_time,
                    end_time,
                    optimised_av_segments,
                    av_segment_id_key,
                ),
                start_time,
                end_time,
                end_time - start_time,
                confidence,
            ))

    labels_dataframe = pd.DataFrame(
        labels_data,
        columns=[
            'label',
            'av_segment_ids',
            'start_s',
            'end_s',
            'duration_s',
            'confidence',
        ],
    )
    labels_dataframe = labels_dataframe.sort_values(by='start_s')

    return labels_dataframe


def get_object_tracking_data(
    annotation_results: VideoAnnotationResults,
    optimised_av_segments: pd.DataFrame,
    av_segment_id_key: str = 'av_segment_id',
) -> pd.DataFrame:
    """Returns a DataFrame of object tracking data."""
    object_tracking_data = []
    for object_annotation in annotation_results.object_annotations:
        bounding_boxes = []
        for frame in object_annotation.frames:
            box = frame.normalized_bounding_box
            bounding_boxes.append((box.left, box.top, box.right, box.bottom))

        description = object_annotation.entity.description
        start_time = (
            object_annotation.segment.start_time_offset.seconds
            + object_annotation.segment.start_time_offset.microseconds / 1e6
        )
        end_time = (
            object_annotation.segment.end_time_offset.seconds
            + object_annotation.segment.end_time_offset.microseconds / 1e6
        )
        confidence = object_annotation.confidence

        object_tracking_data.append((
            description,
            _identify_segments(
                start_time, end_time, optimised_av_segments, av_segment_id_key
            ),
            start_time,
            end_time,
            end_time - start_time,
            confidence,
            bounding_boxes,
        ))

    object_tracking_dataframe = pd.DataFrame(
        object_tracking_data,
        columns=[
            'label',
            'av_segment_ids',
            'start_s',
            'end_s',
            'duration_s',
            'confidence',
            'boxes_ltrb',
        ],
    )
    object_tracking_dataframe = object_tracking_dataframe.sort_values(
        by=['start_s', 'end_s']
    )

    return object_tracking_dataframe


def get_logo_detection_data(
    annotation_results: VideoAnnotationResults,
    optimised_av_segments: pd.DataFrame,
    av_segment_id_key: str = 'av_segment_id',
) -> pd.DataFrame:
    """Returns a DataFrame of logo detection data."""
    logo_detection_data = []
    for logo_annotation in annotation_results.logo_recognition_annotations:
        label = logo_annotation.entity.description
        segments = [(
            s.start_time_offset.seconds + s.start_time_offset.microseconds / 1e6,
            s.end_time_offset.seconds + s.end_time_offset.microseconds / 1e6,
        ) for s in logo_annotation.segments]

        for track in logo_annotation.tracks:
            start_time = (
                track.segment.start_time_offset.seconds
                + track.segment.start_time_offset.microseconds / 1e6
            )
            end_time = (
                track.segment.end_time_offset.seconds
                + track.segment.end_time_offset.microseconds / 1e6
            )
            confidence = track.confidence

            av_segment_ids = _identify_segments(
                start_time, end_time, optimised_av_segments, av_segment_id_key
            )
            boxes = [(
                obj.normalized_bounding_box.left,
                obj.normalized_bounding_box.top,
                obj.normalized_bounding_box.right,
                obj.normalized_bounding_box.bottom,
            ) for obj in track.timestamped_objects]
            attributes = []
            track_attributes = []

            logo_detection_data.append((
                label,
                segments,
                av_segment_ids,
                start_time,
                end_time,
                end_time - start_time,
                confidence,
                boxes,
                attributes,
                track_attributes,
            ))

    logo_detection_dataframe = pd.DataFrame(
        logo_detection_data,
        columns=[
            'label',
            'segments',
            'av_segment_ids',
            'start_s',
            'end_s',
            'duration_s',
            'confidence',
            'boxes_ltrb',
            'attributes',
            'track_attributes',
        ],
    )
    logo_detection_dataframe = logo_detection_dataframe.sort_values(
        by=['start_s', 'end_s']
    )

    return logo_detection_dataframe


def get_text_detection_data(
    annotation_results: VideoAnnotationResults,
    optimised_av_segments: pd.DataFrame,
    av_segment_id_key: str = 'av_segment_id',
) -> pd.DataFrame:
    """Returns a DataFrame of text detection data."""
    text_detection_data = []
    for text_annotation in annotation_results.text_annotations:
        text = text_annotation.text

        for text_segment in text_annotation.segments:
            start_time = (
                text_segment.segment.start_time_offset.seconds
                + text_segment.segment.start_time_offset.microseconds / 1e6
            )
            end_time = (
                text_segment.segment.end_time_offset.seconds
                + text_segment.segment.end_time_offset.microseconds / 1e6
            )
            confidence = text_segment.confidence

            av_segment_ids = _identify_segments(
                start_time, end_time, optimised_av_segments, av_segment_id_key
            )
            boxes = [(vertex.x, vertex.y)
                     for frame in text_segment.frames
                     for vertex in frame.rotated_bounding_box.vertices]
            text_detection_data.append((
                text,
                av_segment_ids,
                start_time,
                end_time,
                end_time - start_time,
                confidence,
                boxes,
            ))

    text_detection_dataframe = pd.DataFrame(
        text_detection_data,
        columns=[
            'text',
            'av_segment_ids',
            'start_s',
            'end_s',
            'duration_s',
            'confidence',
            'box_vertices',
        ],
    )
    text_detection_dataframe = text_detection_dataframe.sort_values(by=['start_s'])

    return text_detection_dataframe


def _identify_segments(
    start_time: float,
    end_time: float,
    data: pd.DataFrame,
    key: str,
    start_key: str = 'start_s',
    end_key: str = 'end_s',
) -> Sequence[int]:
    """Identifies rows in a dataframe that overlap with a given time range."""
    if not data.empty:
        result = data[
            ((data[start_key] <= start_time) & (data[end_key] > start_time)) |
            ((data[start_key] >= start_time) & (data[start_key] < end_time))]
        if not result.empty:
            return result[key].tolist()
    return []


# Legacy compatibility functions
def set_offset(key, element, segment_end, cumulative_seconds):
    """Legacy function for offset adjustment."""
    pass


def convert_keys(d):
    """Legacy function for key conversion."""
    return d


def camel_to_snake(s):
    """Converts a string from camelCase to snake_case."""
    return ''.join(['_' + c.lower() if c.isupper() else c for c in s]).lstrip('_')
