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

import concurrent.futures
import logging
import os
import pathlib
import time
from typing import Sequence

import config as ConfigService
import storage as StorageService
import utils as Utils
import video as VideoService


def process_video(
    output_dir: str,
    input_video_file_path: str,
    media_file: Utils.TriggerFile,
    gcs_bucket_name: str,
):
  """Creates video chunks to be analysed."""
  video_chunks = _get_video_chunks(
      output_dir=output_dir,
      video_file_path=input_video_file_path,
  )
  size = len(video_chunks)
  logging.info('EXTRACTOR - processing video with %d chunks...', size)

  # Only upload video chunk files, not the entire directory
  # to avoid race conditions with audio processing
  for chunk_path in video_chunks:
    chunk_basename = os.path.basename(chunk_path)
    StorageService.upload_gcs_file(
        file_path=chunk_path,
        bucket_name=gcs_bucket_name,
        destination_file_name=f"{media_file.gcs_folder}/{ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR}/{chunk_basename}",
    )

  # Process all video chunks immediately (not just single-chunk videos)
  if size == 1:
    logging.info('EXTRACTOR - analyzing single video chunk...')
    extract_video(media_file, gcs_bucket_name)
  else:
    # Process chunks in parallel (I/O-heavy: S3 download, API call, S3 upload)
    logging.info('EXTRACTOR - analyzing %d video chunks...', size)
    with concurrent.futures.ThreadPoolExecutor(max_workers=ConfigService.CONFIG_MAX_CONCURRENCY) as executor:
      futures = {}
      for i, chunk_path in enumerate(video_chunks, start=1):
        chunk_basename = os.path.basename(chunk_path)
        chunk_file = Utils.TriggerFile(
            f"{media_file.gcs_folder}/{ConfigService.OUTPUT_ANALYSIS_CHUNKS_DIR}/{chunk_basename}"
        )
        logging.info('EXTRACTOR - submitting video chunk %d/%d: %s', i, size, chunk_basename)
        futures[executor.submit(extract_video, chunk_file, gcs_bucket_name)] = i
      for future in concurrent.futures.as_completed(futures):
        idx = futures[future]
        future.result()  # propagate exceptions
        logging.info('EXTRACTOR - finished video chunk %d/%d', idx, size)


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
  max_retries = 3
  for attempt in range(1, max_retries + 1):
    try:
      VideoService.analyse_video(
          video_file_path=media_file.full_gcs_path,
          bucket_name=gcs_bucket_name,
          gcs_folder=media_file.gcs_folder,
          output_file_name=(
              f'{media_file.file_name}_analysis.json'
              if is_chunk else ConfigService.OUTPUT_ANALYSIS_FILE
          ),
      )
      break
    except Exception as e:
      if attempt < max_retries:
        wait = 30 * attempt
        logging.warning(
            'VIDEO_ANALYSIS - chunk#%s attempt %d/%d failed: %s. '
            'Retrying in %ds...',
            video_id, attempt, max_retries, e, wait,
        )
        time.sleep(wait)
      else:
        logging.error(
            'VIDEO_ANALYSIS - chunk#%s failed after %d attempts: %s',
            video_id, max_retries, e,
        )
        raise
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


def _get_video_chunks(
    output_dir: str,
    video_file_path: str,
    size_limit: int = ConfigService.CONFIG_MAX_VIDEO_CHUNK_SIZE,
) -> Sequence[str]:
  """Cuts the input video into smaller chunks by size."""
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

  if file_size > size_limit:
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
      Utils.execute_subprocess_commands(
          cmds=[
              'ffmpeg',
              '-ss',
              str(current_duration),
              '-i',
              video_file_path,
              '-fs',
              str(size_limit),
              '-c',
              'copy',
              output_file_path,
          ],
          description=(
              f'Cut input video into {size_limit/1e9}GB chunks. '
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
    result = Utils.rename_chunks(
        result, ConfigService.INPUT_EXTRACTION_VIDEO_FILENAME_SUFFIX
    )

  return result
