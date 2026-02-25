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

"""Vigenair audio service.

This module contains functions to extract, split and transcribe audio files.
Uses Gemini for transcription via gs:// URIs.
"""

import datetime
import io
import logging
import os
import pathlib
import re
import shutil
import time
from typing import Optional, Sequence, Tuple

import config as ConfigService
import pandas as pd
import utils as Utils


def combine_audio_files(output_path: str, audio_files: Sequence[str]):
  """Combines audio analysis files into a single file."""
  # Write to temp file first since output might be same as one of the inputs
  # (ffmpeg cannot edit files in-place)
  temp_output = output_path + '.tmp.wav'

  ffmpeg_cmds = ['ffmpeg', '-y']
  for audio_file in audio_files:
    ffmpeg_cmds.extend(['-i', audio_file])

  ffmpeg_cmds += ['-filter_complex'] + [
      ''.join([f'[{index}:0]' for index, _ in enumerate(audio_files)])
      + f'concat=n={len(audio_files)}:v=0:a=1[outa]'
  ] + ['-map', '[outa]', temp_output]

  Utils.execute_subprocess_commands(
      cmds=ffmpeg_cmds,
      description=(
          f'Merge {len(audio_files)} audio files and output to {output_path}.'
      ),
  )

  # Move temp file to final output path
  shutil.move(temp_output, output_path)
  os.chmod(output_path, 777)


def combine_analysis_chunks(
    analysis_chunks: Sequence[pd.DataFrame]
) -> pd.DataFrame:
  """Combines audio analysis chunks into a single response."""
  combined_df = pd.DataFrame()
  max_audio_segment_id = 0
  max_end_s = 0

  for idx, df in enumerate(analysis_chunks):
    # Check if dataframe is empty or missing required columns
    if df.empty:
      logging.warning(
          'AUDIO - Skipping empty analysis chunk dataframe at index %d '
          '(transcription may have failed for this chunk)',
          idx
      )
      continue

    if 'audio_segment_id' not in df.columns:
      logging.error(
          'AUDIO - Analysis chunk dataframe at index %d is missing '
          'audio_segment_id column. Columns: %s',
          idx, list(df.columns)
      )
      continue

    df['audio_segment_id'] += max_audio_segment_id
    df['start_s'] += max_end_s
    df['end_s'] += max_end_s

    max_audio_segment_id = df['audio_segment_id'].max()
    max_end_s = df['end_s'].max()

    combined_df = pd.concat([combined_df, df], ignore_index=True)

  return combined_df


def combine_subtitle_files(
    audio_output_dir: str,
    subtitles_output_path: str,
):
  """Combines audio analysis subtitle files content into a single file."""
  subtitles_files = [
      str(file_path) for file_path in pathlib.Path(audio_output_dir).
      glob(f'*.{ConfigService.OUTPUT_SUBTITLES_TYPE}')
  ]
  logging.info(
      'THREADING - Combining %d subtitle files found in %s...',
      len(subtitles_files),
      audio_output_dir,
  )
  combined_content = ''
  last_timestamp = datetime.datetime.strptime('00:00:00.000', '%H:%M:%S.%f')

  for index, subtitles_file in enumerate(subtitles_files):
    with open(subtitles_file, 'r', encoding='utf-8') as f:
      lines = f.readlines()

      if index:
        lines = lines[2:]

      for line in lines:
        if '-->' in line:
          start, end = line.strip().split(' --> ')
          start_time = last_timestamp + datetime.timedelta(
              minutes=int(start[:2]),
              seconds=int(start[3:5]),
              milliseconds=int(start[6:]),
          )
          end_time = last_timestamp + datetime.timedelta(
              minutes=int(end[:2]),
              seconds=int(end[3:5]),
              milliseconds=int(end[6:]),
          )

          start = start_time.strftime('%H:%M:%S.%f')[:-3]
          end = end_time.strftime('%H:%M:%S.%f')[:-3]

          combined_content += f'{start} --> {end}\n'
        else:
          combined_content += line

      # Find the last timestamp line by searching backwards through the file
      last_end_time = None
      for line in reversed(lines):
        if '-->' in line:
          _, end = line.strip().split(' --> ')
          last_end_time = end
          break

      if last_end_time:
        last_timestamp += datetime.timedelta(
            minutes=int(last_end_time[:2]),
            seconds=int(last_end_time[3:5]),
            milliseconds=int(last_end_time[6:]),
        )

  with open(subtitles_output_path, 'w', encoding='utf-8') as f:
    f.write(combined_content)


def extract_audio(video_file_path: str) -> Optional[str]:
  """Extracts the audio track from a video file, if it exists.

  Args:
    video_file_path: path to the video file from which the audio will be
      extracted.

  Returns:
    The path to the extracted audio file if it exists, or None if the video does
    not contain an audio track.
  """
  output = Utils.execute_subprocess_commands(
      cmds=[
          'ffprobe',
          '-i',
          video_file_path,
          '-show_streams',
          '-select_streams',
          'a',
          '-loglevel',
          'error',
      ],
      description='check if video has audio with ffprobe',
  )
  if not output:
    logging.warning(
        'AUDIO_EXTRACTION - Video does not contain an audio track! '
        'Skipping audio extraction...'
    )
    return None

  audio_file_path = f"{video_file_path.split('.')[0]}.wav"
  Utils.execute_subprocess_commands(
      cmds=[
          'ffmpeg',
          '-i',
          video_file_path,
          '-q:a',
          '0',
          '-map',
          'a',
          audio_file_path,
      ],
      description='extract audio track with ffmpeg',
  )
  return audio_file_path


def split_audio(
    output_dir: str,
    audio_file_path: str,
    prefix='',
) -> Tuple[str, str]:
  """Splits the audio into vocals and music tracks and returns their paths.

  Uses demucs for audio separation (replaces spleeter).
  Demucs outputs to: output_dir/htdemucs/track_name/vocals.wav and no_vocals.wav

  Args:
    output_dir: directory where the split audio tracks will be saved.
    audio_file_path: path to the audio file that will be split.
    prefix: optional prefix for output filenames.

  Returns:
    A tuple with the path to the vocals and music tracks.
  """
  # Run demucs with two-stems mode (vocals + no_vocals)
  Utils.execute_subprocess_commands(
      cmds=[
          'python', '-m', 'demucs',
          '--two-stems=vocals',
          '-d', 'cpu',
          '-o', output_dir,
          audio_file_path,
      ],
      description='split voice-over and background music with demucs',
  )

  # Demucs creates: output_dir/htdemucs/track_name/vocals.wav and no_vocals.wav
  audio_filename = os.path.splitext(os.path.basename(audio_file_path))[0]
  demucs_output_dir = pathlib.Path(output_dir, 'htdemucs', audio_filename)

  vocals_file_path = str(
      pathlib.Path(output_dir, f'{prefix}{ConfigService.OUTPUT_SPEECH_FILE}')
  )
  music_file_path = str(
      pathlib.Path(output_dir, f'{prefix}{ConfigService.OUTPUT_MUSIC_FILE}')
  )

  # Move files from demucs output structure to expected locations
  shutil.move(
      str(demucs_output_dir / 'vocals.wav'),
      vocals_file_path if prefix else output_dir
  )
  shutil.move(
      str(demucs_output_dir / 'no_vocals.wav'),
      music_file_path if prefix else output_dir
  )

  # Clean up demucs directory structure
  shutil.rmtree(pathlib.Path(output_dir, 'htdemucs'), ignore_errors=True)

  return vocals_file_path, music_file_path


def transcribe_audio(
    output_dir: str,
    audio_file_path: str,
    gcs_folder: str,
    gcs_bucket_name: str,
) -> Tuple[pd.DataFrame, str, float]:
  """Transcribes an audio file using Gemini and returns the transcription.

  Uploads the local audio file to GCS, uses gs:// URI with Vertex AI Gemini,
  then cleans up the temp GCS file.

  Args:
    output_dir: Directory where the transcription will be saved.
    audio_file_path: Path to the audio file that will be transcribed.
    gcs_folder: The GCS folder for temporary uploads.
    gcs_bucket_name: The GCS bucket name.

  Returns:
    A tuple of (transcription dataframe, detected language, confidence).
  """
  import json
  import storage as StorageService
  from google.genai import types

  transcription_dataframe = pd.DataFrame()
  video_language = ConfigService.DEFAULT_VIDEO_LANGUAGE
  language_probability = 0.0
  subtitles_content = ''
  temp_gcs_key = None

  # Define structured output schema
  import typing_extensions as typing

  class TranscriptionSegment(typing.TypedDict):
    start: str
    end: str
    text: str

  class TranscriptionResponse(typing.TypedDict):
    language: str
    confidence: float
    segments: list[TranscriptionSegment]

  client = ConfigService.get_genai_client()

  try:
    # Get audio duration to determine expected minimum segments
    audio_duration = Utils.get_media_duration(audio_file_path)
    # Expect at least 1 segment per 15 seconds for audio > 30s
    min_expected_segments = max(1, int(audio_duration / 15)) if audio_duration > 30 else 1
    logging.info(
        'TRANSCRIPTION - Audio duration: %.1fs, expecting at least %d segments',
        audio_duration, min_expected_segments
    )

    # Upload audio to GCS as temp file, then use gs:// URI
    audio_filename = os.path.basename(audio_file_path)
    temp_gcs_key = f'{gcs_folder}/_temp_audio_{audio_filename}'
    StorageService.upload_file(
        file_path=audio_file_path,
        destination_file_name=temp_gcs_key,
        bucket_name=gcs_bucket_name,
        overwrite=True,
    )
    gs_uri = StorageService.get_gs_uri(temp_gcs_key)
    logging.info('TRANSCRIPTION - Uploaded audio to GCS: %s', gs_uri)

    audio_part = types.Part.from_uri(file_uri=gs_uri, mime_type='audio/wav')

    # Retry logic for insufficient segmentation
    max_retries = 3
    segments = []
    video_language = ConfigService.DEFAULT_VIDEO_LANGUAGE
    language_probability = 0.0

    for attempt in range(max_retries):
      logging.info('TRANSCRIPTION - Attempt %d/%d', attempt + 1, max_retries)

      response = client.models.generate_content(
          model=ConfigService.CONFIG_TRANSCRIPTION_MODEL_GEMINI,
          contents=[audio_part, ConfigService.TRANSCRIBE_AUDIO_PROMPT_JSON],
          config=types.GenerateContentConfig(
              response_mime_type='application/json',
              response_schema=TranscriptionResponse,
              temperature=0.1,
              max_output_tokens=65536,
              safety_settings=ConfigService.CONFIG_DEFAULT_SAFETY_SETTINGS,
          ),
      )

      if response.candidates and response.candidates[0].content.parts:
        text = response.candidates[0].content.parts[0].text
        logging.info('TRANSCRIPTION - Raw JSON (attempt %d): %s', attempt + 1, text[:1500])

        data = json.loads(text)
        video_language = data.get('language', ConfigService.DEFAULT_VIDEO_LANGUAGE)
        language_probability = float(data.get('confidence', 0.0))
        segments = data.get('segments', [])

        # Check if we got enough segments
        if len(segments) >= min_expected_segments:
          logging.info(
              'TRANSCRIPTION - Got %d segments (>= %d expected), accepting result',
              len(segments), min_expected_segments
          )
          break
        else:
          logging.warning(
              'TRANSCRIPTION - Only got %d segments (expected >= %d), retrying...',
              len(segments), min_expected_segments
          )
          if attempt < max_retries - 1:
            time.sleep(2)  # Brief delay before retry
      else:
        logging.warning('TRANSCRIPTION - No content in response, retrying...')
        if attempt < max_retries - 1:
          time.sleep(2)

    # Log final result
    if len(segments) < min_expected_segments:
      logging.warning(
          'TRANSCRIPTION - After %d attempts, only got %d segments (expected %d). Proceeding anyway.',
          max_retries, len(segments), min_expected_segments
      )

    if segments:
      # Build dataframe from segments
      # Handle missing 'end' timestamps by using next segment's start or estimating
      rows = []
      for i, seg in enumerate(segments):
        start_s = Utils.timestring_to_seconds(seg['start'])
        # Use 'end' if provided, otherwise use next segment's start or add 3 seconds
        if 'end' in seg:
          end_s = Utils.timestring_to_seconds(seg['end'])
        elif i + 1 < len(segments):
          end_s = Utils.timestring_to_seconds(segments[i + 1]['start'])
        else:
          # Last segment - estimate based on text length (avg 3 chars/sec)
          end_s = start_s + max(3.0, len(seg.get('text', '')) / 10.0)
        rows.append({
            'audio_segment_id': i + 1,
            'start_s': start_s,
            'end_s': end_s,
            'transcript': seg['text'],
        })
      transcription_dataframe = pd.DataFrame(rows)
      transcription_dataframe['duration_s'] = (
          transcription_dataframe['end_s'] - transcription_dataframe['start_s']
      )

      # Generate VTT content
      subtitles_content = 'WEBVTT\n\n'
      for i, seg in enumerate(segments):
        start_time = seg['start']
        if 'end' in seg:
          end_time = seg['end']
        elif i + 1 < len(segments):
          end_time = segments[i + 1]['start']
        else:
          # Estimate end for last segment
          start_s = Utils.timestring_to_seconds(seg['start'])
          end_s = start_s + max(3.0, len(seg.get('text', '')) / 10.0)
          mins, secs = divmod(end_s, 60)
          end_time = f"{int(mins):02d}:{secs:06.3f}"
        subtitles_content += f"{start_time} --> {end_time}\n{seg['text']}\n\n"

      logging.info('TRANSCRIPTION - Parsed %d segments', len(segments))
    else:
      logging.warning('TRANSCRIPTION - No segments in response')
  # Execution should continue regardless of the underlying exception
  # pylint: disable=broad-exception-caught
  except Exception:
    logging.exception(
        'Encountered error during transcription! '
        'Returning empty transcription...'
    )
  finally:
    # Clean up temporary GCS file
    if temp_gcs_key:
      try:
        StorageService.delete_file(temp_gcs_key, bucket_name=gcs_bucket_name)
        logging.info('TRANSCRIPTION - Cleaned up temp GCS file: %s', temp_gcs_key)
      except Exception as cleanup_error:
        logging.warning(
            'TRANSCRIPTION - Failed to clean up temp GCS file: %s',
            cleanup_error
        )

  subtitles_output_path = audio_file_path.replace(
      '.wav', f'.{ConfigService.OUTPUT_SUBTITLES_TYPE}'
  )
  with open(subtitles_output_path, 'w', encoding='utf8') as f:
    f.write(subtitles_content)

  logging.info(
      'TRANSCRIPTION - transcript for %s written successfully!',
      audio_file_path,
  )
  return transcription_dataframe, video_language, float(language_probability)
