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

"""Video Extraction Component.

This module provides functionality to extract all available video information
from an input video file.
"""

import logging
import os
import pathlib
import time
from typing import Sequence

import config as ConfigService
import storage as StorageService
import utils as Utils
import video as VideoService
from google.api_core import exceptions as api_exceptions


def process_video(
    output_dir: str,
    input_video_file_path: str,
    media_file: Utils.TriggerFile,
    gcs_bucket_name: str,
    chunk_upload_delay: int = 60,  # Delay between chunk uploads in seconds
):
  """Creates video chunks to be analysed."""
  video_chunks = _get_video_chunks(
      output_dir=output_dir,
      video_file_path=input_video_file_path,
  )
  size = len(video_chunks)
  logging.info('EXTRACTOR - processing video with %d chunks...', size)

  if size > 1:
    # Upload video chunks with staggered delays to avoid API rate limiting
    # Each chunk upload triggers a Cloud Function that calls Video Intelligence API
    for i, chunk_path in enumerate(video_chunks):
      chunk_filename = os.path.basename(chunk_path)
      gcs_destination = str(pathlib.Path(
          media_file.gcs_folder,
          ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR,
          chunk_filename,
      ))
      logging.info(
          'VIDEO_UPLOAD - Uploading chunk %d/%d: %s',
          i + 1, size, chunk_filename,
      )
      StorageService.upload_gcs_file(
          file_path=chunk_path,
          bucket_name=gcs_bucket_name,
          destination_file_name=gcs_destination,
      )
      # Add delay between uploads (except after the last one)
      if i < size - 1:
        logging.info(
            'VIDEO_UPLOAD - Waiting %ds before next chunk to avoid rate limiting...',
            chunk_upload_delay,
        )
        time.sleep(chunk_upload_delay)
  else:
    # Single chunk - upload normally
    StorageService.upload_gcs_dir(
        source_directory=output_dir,
        bucket_name=gcs_bucket_name,
        target_dir=media_file.gcs_folder,
    )
    extract_video(media_file, gcs_bucket_name)


def extract_video(
    media_file: Utils.TriggerFile,
    gcs_bucket_name: str,
):
  """Extracts visual information from the input video."""
  video_id = media_file.file_name.replace(
      ConfigService.INPUT_EXTRACTION_VIDEO_FILENAME_SUFFIX, ''
  )
  is_chunk = (
      ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR in media_file.full_gcs_path
  )
  VideoService.analyse_video(
      video_file_path=media_file.full_gcs_path,
      bucket_name=gcs_bucket_name,
      gcs_folder=media_file.gcs_folder,
      output_file_name=(
          f'{media_file.file_name}_analysis.json'
          if is_chunk else ConfigService.OUTPUT_ANALYSIS_FILE
      ),
  )
  logging.info(
      'THREADING - analyse_video finished for chunk#%s!',
      video_id,
  )
  _check_finalise_extract_video(
      total_count=(
          1 if video_id == ConfigService.INPUT_FILENAME else
          int(video_id.split('-')[1])
      ),
      gcs_bucket_name=gcs_bucket_name,
      gcs_folder=media_file.gcs_folder,
  )


def _check_finalise_extract_video(
    total_count: int,
    gcs_bucket_name: str,
    gcs_folder: str,
):
  """Checks whether all video chunk analyses are complete."""
  analysed_count = len(
      StorageService.filter_files(
          bucket_name=gcs_bucket_name,
          prefix=f'{gcs_folder}/',
          suffix=ConfigService.OUTPUT_ANALYSIS_FILE,
      )
  )
  if analysed_count == total_count:
    finalise_file_path = (
        f'{total_count}-{total_count}_'
        f'{ConfigService.INPUT_EXTRACTION_FINALISE_VIDEO_FILE}'
    )
    with open(finalise_file_path, 'w', encoding='utf8'):
      pass

    try:
      StorageService.upload_gcs_file(
          file_path=finalise_file_path,
          bucket_name=gcs_bucket_name,
          destination_file_name=(
              str(pathlib.Path(gcs_folder, finalise_file_path))
              if total_count > 1 else str(
                  pathlib.Path(
                      gcs_folder,
                      ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR,
                      finalise_file_path,
                  )
              )
          ),
      )
    except api_exceptions.PreconditionFailed:
      logging.info(
          'VIDEO_FINALISE - File already exists (uploaded by another instance), '
          'skipping: %s', finalise_file_path
      )


def _get_video_chunks(
    output_dir: str,
    video_file_path: str,
    size_limit: int = ConfigService.CONFIG_MAX_VIDEO_CHUNK_SIZE,
    duration_limit: float = ConfigService.CONFIG_MAX_VIDEO_CHUNK_DURATION,
) -> Sequence[str]:
  """Cuts the input video into smaller chunks by size or duration."""
  _, file_ext = os.path.splitext(video_file_path)
  output_folder = str(
      pathlib.Path(output_dir, ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR)
  )
  os.makedirs(output_folder, exist_ok=True)

  file_size = os.stat(video_file_path).st_size
  duration = Utils.get_media_duration(video_file_path)
  current_duration = 0
  file_count = 0
  result = []

  # Chunk if file is too large OR duration is too long (to prevent API timeout)
  needs_chunking = file_size > size_limit or duration > duration_limit
  chunk_duration = min(duration_limit, duration) if needs_chunking else duration
  logging.info(
      'VIDEO_CHUNKING - file_size=%d, duration=%.1fs, needs_chunking=%s, chunk_duration=%.1fs',
      file_size, duration, needs_chunking, chunk_duration
  )

  if needs_chunking:
    while current_duration < duration:
      file_count += 1
      output_file_path = str(
          pathlib.Path(
              output_folder,
              f'{file_count}'
              f'{ConfigService.INPUT_EXTRACTION_VIDEO_FILENAME_SUFFIX}'
              f'{file_ext}',
          )
      )
      # Use duration-based chunking with -t flag
      Utils.execute_subprocess_commands(
          cmds=[
              'ffmpeg',
              '-ss',
              str(current_duration),
              '-i',
              video_file_path,
              '-t',
              str(chunk_duration),
              '-c',
              'copy',
              output_file_path,
          ],
          description=(
              f'Cut input video into {chunk_duration/60:.1f}min chunks. '
              f'Chunk #{file_count}.'
          ),
      )
      os.chmod(output_file_path, 777)
      new_duration = Utils.get_media_duration(output_file_path)
      if new_duration == 0.0:
        logging.warning('Skipping processing 0 length chunk#%d...', file_count)
        file_count -= 1
        os.remove(output_file_path)
        break
      current_duration += new_duration
      result.append(output_file_path)
  else:
    result.append(video_file_path)

  if file_count:
    Utils.rename_chunks(
        result, ConfigService.INPUT_EXTRACTION_VIDEO_FILENAME_SUFFIX
    )

  return result
