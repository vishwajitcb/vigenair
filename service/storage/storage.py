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

This module provides methods for interacting with Amazon S3 storage.
Replaces the original Google Cloud Storage implementation.
"""

import logging
import os
import pathlib
from typing import Optional, Sequence, Union

import boto3
from botocore.exceptions import ClientError

import utils as Utils

# Initialize S3 client
_s3_client = None


def _get_s3_client():
    """Get or create the S3 client singleton."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            's3',
            region_name=os.environ.get('AWS_REGION', 'us-east-1'),
        )
    return _s3_client


def _get_bucket():
    """Get the S3 bucket name from environment."""
    bucket = os.environ.get('S3_BUCKET')
    if not bucket:
        raise ValueError("S3_BUCKET environment variable is not set")
    return bucket


def download_file(
    file_path: Union[str, Utils.TriggerFile],
    output_dir: Optional[str] = None,
    fetch_contents: bool = False,
    bucket_name: Optional[str] = None,  # Kept for backward compatibility, ignored
) -> Union[Optional[str], Optional[bytes]]:
    """Downloads a file from S3 and returns its path or contents.

    Args:
        file_path: The path of the file to download (string or TriggerFile).
        output_dir: Directory path to store the downloaded file in.
        fetch_contents: Whether to fetch the file contents instead of writing to a
            file.
        bucket_name: Deprecated - kept for backward compatibility, ignored.
            Bucket is read from S3_BUCKET environment variable.

    Returns:
        The retrieved file path or contents based on `fetch_contents`, or None if
        the file was not found.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    # Handle both string and TriggerFile inputs
    if isinstance(file_path, Utils.TriggerFile):
        key = file_path.full_gcs_path
        file_name = file_path.file_name_ext
    else:
        key = file_path
        file_name = os.path.basename(key)

    try:
        if fetch_contents:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            result = response['Body'].read()
        else:
            destination_file_name = str(pathlib.Path(output_dir, file_name))
            s3_client.download_file(bucket, key, destination_file_name)
            result = destination_file_name

        logging.info('DOWNLOAD - Fetched file "%s" from bucket "%s".', key, bucket)
        return result

    except ClientError as e:
        if e.response['Error']['Code'] == '404' or e.response['Error']['Code'] == 'NoSuchKey':
            logging.warning(
                'DOWNLOAD - Could not find file "%s" in bucket "%s".', key, bucket
            )
            return None
        raise


def upload_file(
    file_path: str,
    destination_file_name: str,
    bucket_name: Optional[str] = None,
    overwrite: bool = False,
) -> None:
    """Uploads a file to S3.

    Args:
        file_path: The path of the file to upload.
        destination_file_name: The name/key of the file in S3.
        bucket_name: The name of the bucket (optional, uses S3_BUCKET env var).
        overwrite: Whether to overwrite existing files.
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()

    try:
        if not overwrite:
            # Check if file exists
            try:
                s3_client.head_object(Bucket=bucket, Key=destination_file_name)
                logging.info(
                    'UPLOAD - File "%s" already exists, skipping.', destination_file_name
                )
                return
            except ClientError as e:
                if e.response['Error']['Code'] != '404':
                    raise

        s3_client.upload_file(file_path, bucket, destination_file_name)
        logging.info('UPLOAD - Uploaded path "%s".', destination_file_name)

    except ClientError as e:
        logging.error('UPLOAD - Failed to upload "%s": %s', destination_file_name, e)
        raise


def upload_dir(
    source_directory: str,
    bucket_name: str,
    target_dir: str,
) -> None:
    """Uploads all files in a directory to S3.

    Args:
        source_directory: The directory to upload.
        bucket_name: The name of the bucket to upload to.
        target_dir: The directory/prefix within the bucket to upload to.
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()

    directory_path = pathlib.Path(source_directory)
    paths = directory_path.rglob('*')

    for path in paths:
        if path.is_file():
            relative_path = path.relative_to(source_directory)
            s3_key = f'{target_dir}/{relative_path}'

            try:
                # Check if file exists
                s3_client.head_object(Bucket=bucket, Key=s3_key)
                logging.info('UPLOAD - File "%s" exists, skipping.', s3_key)
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    s3_client.upload_file(str(path), bucket, s3_key)
                    logging.info('UPLOAD - Uploaded path "%s".', s3_key)
                else:
                    logging.warning(
                        'UPLOAD - Failed to upload path "%s" due to exception: %r.',
                        s3_key,
                        e,
                    )


def filter_video_files(
    prefix: str,
    bucket_name: Optional[str] = None,
    first_only: bool = False,
) -> Sequence[str]:
    """Filters video files in S3 based on a prefix.

    Args:
        prefix: The prefix to filter files by.
        bucket_name: The name of the bucket (optional, uses S3_BUCKET env var).
        first_only: Whether to only return the first matching file.

    Returns:
        A list of video files matching the given prefix, or an empty list if no
        files match.
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()
    result = []

    paginator = s3_client.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
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
    """Lists/filters files in S3 based on prefix and optional suffix.

    Args:
        prefix: The prefix to filter files by.
        suffix: The suffix to filter files by (optional).
        fetch_content: Whether to return file names or their content.
        download: Whether to download files locally.
        download_dir: Directory to download files to.
        bucket_name: The name of the bucket (optional, uses S3_BUCKET env var).

    Returns:
        A list of file keys, contents, or local paths depending on parameters.
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()
    result = []

    paginator = s3_client.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']

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
                s3_client.download_file(bucket, key, destination_file_name)
                result.append(destination_file_name)
            elif fetch_content:
                response = s3_client.get_object(Bucket=bucket, Key=key)
                result.append(response['Body'].read())
            else:
                result.append(key)

    return result


def delete_file(
    file_path: Union[str, Utils.TriggerFile],
    bucket_name: Optional[str] = None,
) -> None:
    """Deletes a file from S3.

    Args:
        file_path: The path of the file to delete.
        bucket_name: The name of the bucket (optional, uses S3_BUCKET env var).
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()

    # Handle both string and TriggerFile inputs
    if isinstance(file_path, Utils.TriggerFile):
        key = file_path.full_gcs_path
    else:
        key = file_path

    try:
        # Check if file exists first
        s3_client.head_object(Bucket=bucket, Key=key)

        # Delete the file
        s3_client.delete_object(Bucket=bucket, Key=key)
        logging.info('DELETE - Deleted file "%s" from bucket "%s".', key, bucket)

    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            logging.warning(
                'DELETE - Could not find file "%s" in bucket "%s".', key, bucket
            )
        else:
            raise


def download_dir(
    bucket_name: str,
    dir_path: str,
    output_dir: str,
) -> int:
    """Downloads all files in a directory from S3.

    Args:
        bucket_name: The name of the bucket to download from.
        dir_path: The directory/prefix to download.
        output_dir: The local directory to download to.

    Returns:
        The number of files downloaded.
    """
    s3_client = _get_s3_client()
    bucket = bucket_name or _get_bucket()
    prefix = f'{dir_path}/'
    count_files = 0

    paginator = s3_client.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get('Contents', []):
            key = obj['Key']
            if key == prefix:
                continue

            filename = key.replace(prefix, '')
            local_path = str(pathlib.Path(output_dir, filename))

            # Create subdirectories if needed
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            s3_client.download_file(bucket, key, local_path)
            count_files += 1

    logging.info(
        'DOWNLOAD - Fetched "%d" files from bucket "%s" and folder "%s" '
        'into path "%s".',
        count_files,
        bucket,
        dir_path,
        output_dir,
    )
    return count_files


def get_presigned_url(key: str, expiration: int = 3600) -> str:
    """Generates a presigned URL for accessing an S3 object.

    Args:
        key: The S3 object key.
        expiration: URL expiration time in seconds (default 1 hour).

    Returns:
        The presigned URL string.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    url = s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expiration,
    )
    return url


def create_multipart_upload(key: str, content_type: str = 'video/mp4') -> str:
    """Initiates a multipart upload to S3.

    Args:
        key: The S3 object key.
        content_type: The MIME type of the file.

    Returns:
        The upload ID string.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    response = s3_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ContentType=content_type,
    )
    upload_id = response['UploadId']
    logging.info('MULTIPART - Initiated upload for "%s", upload_id="%s".', key, upload_id)
    return upload_id


def generate_presigned_upload_url(
    key: str, upload_id: str, part_number: int, expiration: int = 3600
) -> str:
    """Generates a presigned URL for uploading a single part.

    Args:
        key: The S3 object key.
        upload_id: The multipart upload ID.
        part_number: The part number (1-indexed).
        expiration: URL expiration time in seconds (default 1 hour).

    Returns:
        The presigned PUT URL string.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    url = s3_client.generate_presigned_url(
        'upload_part',
        Params={
            'Bucket': bucket,
            'Key': key,
            'UploadId': upload_id,
            'PartNumber': part_number,
        },
        ExpiresIn=expiration,
    )
    return url


def complete_multipart_upload(
    key: str, upload_id: str, parts: list
) -> dict:
    """Completes a multipart upload by assembling all parts.

    Args:
        key: The S3 object key.
        upload_id: The multipart upload ID.
        parts: List of dicts with 'ETag' and 'PartNumber' keys.

    Returns:
        The S3 CompleteMultipartUpload response.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    response = s3_client.complete_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={'Parts': parts},
    )
    logging.info('MULTIPART - Completed upload for "%s", upload_id="%s".', key, upload_id)
    return response


def abort_multipart_upload(key: str, upload_id: str) -> None:
    """Aborts a multipart upload and cleans up uploaded parts.

    Args:
        key: The S3 object key.
        upload_id: The multipart upload ID.
    """
    s3_client = _get_s3_client()
    bucket = _get_bucket()

    s3_client.abort_multipart_upload(
        Bucket=bucket,
        Key=key,
        UploadId=upload_id,
    )
    logging.info('MULTIPART - Aborted upload for "%s", upload_id="%s".', key, upload_id)


# Backward compatibility aliases for existing code
download_gcs_file = download_file
upload_gcs_file = upload_file
upload_gcs_dir = upload_dir
filter_files = list_files
delete_gcs_file = delete_file
download_gcs_dir = download_dir
