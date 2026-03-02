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

"""Vigenair storage service.

This module provides methods for interacting with Google Cloud Storage.
"""

import datetime
import logging
import os
import pathlib
from typing import Optional, Sequence, Union

from google.cloud import storage as gcs_storage

import utils as Utils

# Initialize GCS client singleton
_gcs_client = None


def _get_gcs_client():
    """Get or create the GCS client singleton."""
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = gcs_storage.Client()
    return _gcs_client


def _get_bucket_name():
    """Get the GCS bucket name from environment."""
    bucket = os.environ.get('GCS_BUCKET')
    if not bucket:
        raise ValueError("GCS_BUCKET environment variable is not set")
    return bucket


def _get_bucket(bucket_name: Optional[str] = None):
    """Get a GCS bucket object."""
    client = _get_gcs_client()
    name = bucket_name or _get_bucket_name()
    return client.bucket(name)


def download_file(
    file_path: Union[str, Utils.TriggerFile],
    output_dir: Optional[str] = None,
    fetch_contents: bool = False,
    bucket_name: Optional[str] = None,
) -> Union[Optional[str], Optional[bytes]]:
    """Downloads a file from GCS and returns its path or contents.

    Args:
        file_path: The path of the file to download (string or TriggerFile).
        output_dir: Directory path to store the downloaded file in.
        fetch_contents: Whether to fetch the file contents instead of writing to a
            file.
        bucket_name: The name of the bucket (optional, uses GCS_BUCKET env var).

    Returns:
        The retrieved file path or contents based on `fetch_contents`, or None if
        the file was not found.
    """
    bucket = _get_bucket(bucket_name)

    # Handle both string and TriggerFile inputs
    if isinstance(file_path, Utils.TriggerFile):
        key = file_path.full_gcs_path
        file_name = file_path.file_name_ext
    else:
        key = file_path
        file_name = os.path.basename(key)

    blob = bucket.blob(key)

    try:
        if not blob.exists():
            logging.warning(
                'DOWNLOAD - Could not find file "%s" in bucket "%s".', key, bucket.name
            )
            return None

        if fetch_contents:
            result = blob.download_as_bytes()
        else:
            destination_file_name = str(pathlib.Path(output_dir, file_name))
            blob.download_to_filename(destination_file_name)
            result = destination_file_name

        logging.info('DOWNLOAD - Fetched file "%s" from bucket "%s".', key, bucket.name)
        return result

    except Exception as e:
        logging.warning(
            'DOWNLOAD - Error fetching file "%s" from bucket "%s": %s', key, bucket.name, e
        )
        return None


def upload_file(
    file_path: str,
    destination_file_name: str,
    bucket_name: Optional[str] = None,
    overwrite: bool = False,
) -> None:
    """Uploads a file to GCS.

    Args:
        file_path: The path of the file to upload.
        destination_file_name: The name/key of the file in GCS.
        bucket_name: The name of the bucket (optional, uses GCS_BUCKET env var).
        overwrite: Whether to overwrite existing files.
    """
    bucket = _get_bucket(bucket_name)
    blob = bucket.blob(destination_file_name)

    try:
        if not overwrite and blob.exists():
            logging.info(
                'UPLOAD - File "%s" already exists, skipping.', destination_file_name
            )
            return

        blob.upload_from_filename(file_path)
        logging.info('UPLOAD - Uploaded path "%s".', destination_file_name)

    except Exception as e:
        logging.error('UPLOAD - Failed to upload "%s": %s', destination_file_name, e)
        raise


def upload_dir(
    source_directory: str,
    bucket_name: str,
    target_dir: str,
    overwrite: bool = False,
) -> None:
    """Uploads all files in a directory to GCS.

    Args:
        source_directory: The directory to upload.
        bucket_name: The name of the bucket to upload to.
        target_dir: The directory/prefix within the bucket to upload to.
        overwrite: Whether to overwrite existing files.
    """
    bucket = _get_bucket(bucket_name)

    directory_path = pathlib.Path(source_directory)
    paths = directory_path.rglob('*')

    for path in paths:
        if path.is_file():
            relative_path = path.relative_to(source_directory)
            gcs_key = f'{target_dir}/{relative_path}'
            blob = bucket.blob(gcs_key)

            if not overwrite and blob.exists():
                logging.info('UPLOAD - File "%s" exists, skipping.', gcs_key)
            else:
                try:
                    blob.upload_from_filename(str(path))
                    logging.info('UPLOAD - Uploaded path "%s".', gcs_key)
                except Exception as e:
                    logging.warning(
                        'UPLOAD - Failed to upload path "%s" due to exception: %r.',
                        gcs_key,
                        e,
                    )


def filter_video_files(
    prefix: str,
    bucket_name: Optional[str] = None,
    first_only: bool = False,
) -> Sequence[str]:
    """Filters video files in GCS based on a prefix.

    Args:
        prefix: The prefix to filter files by.
        bucket_name: The name of the bucket (optional, uses GCS_BUCKET env var).
        first_only: Whether to only return the first matching file.

    Returns:
        A list of video files matching the given prefix, or an empty list if no
        files match.
    """
    client = _get_gcs_client()
    bucket_n = bucket_name or _get_bucket_name()
    result = []

    for blob in client.list_blobs(bucket_n, prefix=prefix):
        key = blob.name
        logging.info('FILTER - Found object with key "%s".', key)

        _, file_ext = os.path.splitext(key)
        file_ext = file_ext[1:]

        if file_ext and Utils.VideoExtension.has_value(file_ext):
            logging.info('FILTER - Found video file "%s".', key)
            result.append(key)
            if first_only:
                return result

    return result


def list_files(
    prefix: str = '',
    suffix: Optional[str] = None,
    fetch_content: bool = False,
    download: bool = False,
    download_dir: Optional[str] = None,
    bucket_name: Optional[str] = None,
) -> Sequence[Union[bytes, str]]:
    """Lists/filters files in GCS based on prefix and optional suffix.

    Args:
        prefix: The prefix to filter files by.
        suffix: The suffix to filter files by (optional).
        fetch_content: Whether to return file names or their content.
        download: Whether to download files locally.
        download_dir: Directory to download files to.
        bucket_name: The name of the bucket (optional, uses GCS_BUCKET env var).

    Returns:
        A list of file keys, contents, or local paths depending on parameters.
    """
    client = _get_gcs_client()
    bucket_n = bucket_name or _get_bucket_name()
    result = []

    for blob in client.list_blobs(bucket_n, prefix=prefix):
        key = blob.name

        if suffix and not key.endswith(suffix):
            continue

        logging.info('FILTER - Found matching file "%s".', key)

        if download and download_dir:
            file_path, file_ext = os.path.splitext(key)
            file_path = pathlib.Path(file_path)
            file_name = file_path.name
            destination_file_name = str(
                pathlib.Path(download_dir, f'{file_name}{file_ext}')
            )
            blob.download_to_filename(destination_file_name)
            result.append(destination_file_name)
        elif fetch_content:
            result.append(blob.download_as_bytes())
        else:
            result.append(key)

    return result


def delete_file(
    file_path: Union[str, Utils.TriggerFile],
    bucket_name: Optional[str] = None,
) -> None:
    """Deletes a file from GCS.

    Args:
        file_path: The path of the file to delete.
        bucket_name: The name of the bucket (optional, uses GCS_BUCKET env var).
    """
    bucket = _get_bucket(bucket_name)

    # Handle both string and TriggerFile inputs
    if isinstance(file_path, Utils.TriggerFile):
        key = file_path.full_gcs_path
    else:
        key = file_path

    blob = bucket.blob(key)

    try:
        if not blob.exists():
            logging.warning(
                'DELETE - Could not find file "%s" in bucket "%s".', key, bucket.name
            )
            return

        blob.delete()
        logging.info('DELETE - Deleted file "%s" from bucket "%s".', key, bucket.name)

    except Exception as e:
        logging.warning(
            'DELETE - Error deleting file "%s" from bucket "%s": %s', key, bucket.name, e
        )


def download_dir(
    bucket_name: str,
    dir_path: str,
    output_dir: str,
) -> int:
    """Downloads all files in a directory from GCS.

    Args:
        bucket_name: The name of the bucket to download from.
        dir_path: The directory/prefix to download.
        output_dir: The local directory to download to.

    Returns:
        The number of files downloaded.
    """
    client = _get_gcs_client()
    bucket_n = bucket_name or _get_bucket_name()
    prefix = f'{dir_path}/'
    count_files = 0

    for blob in client.list_blobs(bucket_n, prefix=prefix):
        key = blob.name
        if key == prefix:
            continue

        filename = key.replace(prefix, '')
        local_path = str(pathlib.Path(output_dir, filename))

        # Create subdirectories if needed
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        blob.download_to_filename(local_path)
        count_files += 1

    logging.info(
        'DOWNLOAD - Fetched "%d" files from bucket "%s" and folder "%s" '
        'into path "%s".',
        count_files,
        bucket_n,
        dir_path,
        output_dir,
    )
    return count_files


def get_presigned_url(key: str, expiration: int = 3600) -> str:
    """Generates a signed URL for accessing a GCS object.

    Args:
        key: The GCS object key.
        expiration: URL expiration time in seconds (default 1 hour).

    Returns:
        The signed URL string.
    """
    bucket = _get_bucket()
    blob = bucket.blob(key)

    url = blob.generate_signed_url(
        version='v4',
        expiration=datetime.timedelta(seconds=expiration),
        method='GET',
    )
    return url


def get_signed_upload_url(key: str, content_type: str = 'application/octet-stream', expiration: int = 7200) -> str:
    """Generates a signed URL for uploading (PUT) a GCS object.

    Args:
        key: The GCS object key.
        content_type: The MIME type of the file being uploaded.
        expiration: URL expiration time in seconds (default 2 hours).

    Returns:
        The signed upload URL string.
    """
    bucket = _get_bucket()
    blob = bucket.blob(key)

    url = blob.generate_signed_url(
        version='v4',
        expiration=datetime.timedelta(seconds=expiration),
        method='PUT',
        content_type=content_type,
    )
    return url


def get_gs_uri(key: str) -> str:
    """Returns the gs:// URI for a GCS object.

    Args:
        key: The GCS object key.

    Returns:
        The gs:// URI string (e.g., gs://bucket/key).
    """
    bucket_name = _get_bucket_name()
    return f'gs://{bucket_name}/{key}'


def create_resumable_upload_session(key: str, content_type: str = 'video/mp4') -> str:
    """Creates a resumable upload session for a GCS object.

    Args:
        key: The GCS object key.
        content_type: The MIME type of the file.

    Returns:
        The resumable upload session URI.
    """
    bucket = _get_bucket()
    blob = bucket.blob(key)

    session_uri = blob.create_resumable_upload_session(content_type=content_type)
    logging.info('RESUMABLE_UPLOAD - Created session for "%s".', key)
    return session_uri


def compose_objects(
    source_keys: Sequence[str],
    destination_key: str,
    content_type: str = 'video/mp4',
) -> None:
    """Composes multiple GCS objects into a single destination object.

    Args:
        source_keys: List of source object keys (max 32).
        destination_key: The destination object key.
        content_type: The MIME type of the composed object.

    Raises:
        ValueError: If more than 32 source keys are provided.
    """
    if len(source_keys) > 32:
        raise ValueError('GCS compose supports a maximum of 32 source objects')

    bucket = _get_bucket()
    source_blobs = [bucket.blob(k) for k in source_keys]
    destination_blob = bucket.blob(destination_key)
    destination_blob.content_type = content_type

    destination_blob.compose(source_blobs)
    logging.info(
        'COMPOSE - Composed %d objects into "%s".', len(source_keys), destination_key
    )


def delete_files(keys: Sequence[str]) -> None:
    """Batch-deletes multiple files from GCS.

    Args:
        keys: List of object keys to delete.
    """
    bucket = _get_bucket()
    for key in keys:
        try:
            blob = bucket.blob(key)
            blob.delete()
            logging.info('DELETE - Deleted file "%s".', key)
        except Exception as e:
            logging.warning('DELETE - Failed to delete "%s": %s', key, e)


def delete_folder(prefix: str) -> int:
    """Batch-deletes all files under a prefix using GCS batch API.

    Chunks into batches of 100 (GCS batch API limit).

    Args:
        prefix: The folder prefix (e.g. "job-folder/").

    Returns:
        The number of files deleted.
    """
    bucket = _get_bucket()
    blobs = list(bucket.list_blobs(prefix=prefix))
    if not blobs:
        return 0
    BATCH_SIZE = 100
    for i in range(0, len(blobs), BATCH_SIZE):
        chunk = blobs[i:i + BATCH_SIZE]
        bucket.delete_blobs(chunk, on_error=lambda blob: logging.warning(
            'DELETE - Failed to delete "%s".', blob.name
        ))
    logging.info('DELETE - Batch-deleted %d files under "%s".', len(blobs), prefix)
    return len(blobs)


def get_bucket_usage() -> dict:
    """Get total size of all objects in the bucket.

    Returns:
        Dict with totalBytes, totalFiles, and humanReadable size.
    """
    client = _get_gcs_client()
    bucket_name = _get_bucket_name()
    total_bytes = 0
    total_files = 0
    for blob in client.list_blobs(bucket_name):
        total_bytes += blob.size or 0
        total_files += 1

    # Human-readable
    if total_bytes < 1024:
        human = f"{total_bytes} B"
    elif total_bytes < 1024 ** 2:
        human = f"{total_bytes / 1024:.1f} KB"
    elif total_bytes < 1024 ** 3:
        human = f"{total_bytes / 1024 ** 2:.1f} MB"
    else:
        human = f"{total_bytes / 1024 ** 3:.2f} GB"

    return {
        "totalBytes": total_bytes,
        "totalFiles": total_files,
        "humanReadable": human,
    }


# Backward compatibility aliases
download_gcs_file = download_file
upload_gcs_file = upload_file
upload_gcs_dir = upload_dir
filter_files = list_files
delete_gcs_file = delete_file
download_gcs_dir = download_dir
