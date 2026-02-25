#!/usr/bin/env python3
"""
Test: Direct GCS → Gemini via Vertex AI + gs:// URI + Part.from_uri().

Upload local file to GCS, then pass gs:// URI directly to Gemini.
No download, no Files API, no polling, no cleanup.

Usage:
    export GCS_BUCKET="vigenairbucket"
    export GCS_PROJECT_ID="chai-shots-465914"
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa-key.json"

    python test_gcs_to_gemini.py /path/to/video.mp4
"""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def check_dependencies():
    missing = []
    try:
        import google.genai  # noqa: F401
    except ImportError:
        missing.append("google-genai")
    try:
        from google.cloud import storage  # noqa: F401
    except ImportError:
        missing.append("google-cloud-storage")
    if missing:
        log.error("Missing: %s — pip install %s", ", ".join(missing), " ".join(missing))
        sys.exit(1)


def check_env():
    bucket = os.environ.get("GCS_BUCKET")
    project_id = os.environ.get("GCS_PROJECT_ID")
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    location = os.environ.get("GCS_LOCATION", "us-central1")
    if not bucket:
        log.error("GCS_BUCKET not set"); sys.exit(1)
    if not project_id:
        log.error("GCS_PROJECT_ID not set"); sys.exit(1)
    log.info("GCS_PROJECT_ID : %s", project_id)
    log.info("GCS_BUCKET     : %s", bucket)
    log.info("SA_KEY         : %s", creds or "(using ADC)")
    log.info("LOCATION       : %s", location)
    return bucket, project_id, location


def upload_to_gcs(local_path, bucket_name):
    from google.cloud import storage
    import mimetypes

    if not os.path.exists(local_path):
        log.error("File not found: %s", local_path); sys.exit(1)

    file_size = os.path.getsize(local_path)
    filename = os.path.basename(local_path)
    mime_type, _ = mimetypes.guess_type(local_path)
    mime_type = mime_type or "video/mp4"

    log.info("Local file : %s (%.2f MB, %s)", local_path, file_size / 1e6, mime_type)

    client = storage.Client()
    gcs_key = "test-gcs-gemini/%s" % filename
    blob = client.bucket(bucket_name).blob(gcs_key)

    log.info("Uploading to gs://%s/%s ...", bucket_name, gcs_key)
    start = time.time()
    blob.upload_from_filename(local_path, content_type=mime_type)
    elapsed = time.time() - start
    log.info("Upload done: %.1fs (%.1f MB/s)", elapsed, (file_size / 1e6) / elapsed)
    return gcs_key, mime_type


def test_direct_stream(project_id, location, bucket_name, gcs_key, mime_type, model):
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project_id, location=location)
    gs_uri = "gs://%s/%s" % (bucket_name, gcs_key)

    log.info("")
    log.info("─" * 60)
    log.info("DIRECT STREAM: gs:// URI → Gemini (Vertex AI)")
    log.info("─" * 60)
    log.info("URI   : %s", gs_uri)
    log.info("Model : %s", model)

    video_part = types.Part.from_uri(file_uri=gs_uri, mime_type=mime_type)

    prompt = (
        "Describe what happens in this video in 2-3 sentences. "
        "Include any text, objects, or people you see."
    )

    log.info("Calling generate_content()...")
    start = time.time()

    try:
        response = client.models.generate_content(
            model=model,
            contents=[video_part, prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
            ),
        )
    except Exception as e:
        log.error("FAILED: %s", e)
        raise

    elapsed = time.time() - start

    if not response.candidates:
        log.error("No candidates: %s", response); sys.exit(1)

    text = response.text
    if not text or not text.strip():
        log.error("Empty response"); sys.exit(1)

    log.info("")
    log.info("=" * 60)
    log.info("  SUCCESS — Direct gs:// stream works with API key!")
    log.info("=" * 60)
    log.info("")
    log.info("Response: %s", text.strip())
    log.info("")
    log.info("Finish reason : %s", response.candidates[0].finish_reason)
    log.info("Latency       : %.1fs", elapsed)
    return elapsed


def cleanup(bucket_name, gcs_key):
    from google.cloud import storage
    try:
        storage.Client().bucket(bucket_name).blob(gcs_key).delete()
        log.info("Cleaned up : gs://%s/%s", bucket_name, gcs_key)
    except Exception as e:
        log.warning("Cleanup failed: %s", e)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python test_gcs_to_gemini.py <video_file> [--keep] [--model MODEL]")
        sys.exit(0)

    video_file = None
    keep = False
    model = "gemini-2.0-flash"
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--keep":
            keep = True
        elif sys.argv[i] == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]; i += 1
        elif not sys.argv[i].startswith("--"):
            video_file = sys.argv[i]
        i += 1

    if not video_file:
        log.error("No video file provided"); sys.exit(1)

    log.info("=" * 60)
    log.info("  GCS → Gemini Direct Stream (Vertex AI + gs:// URI)")
    log.info("=" * 60)

    check_dependencies()
    bucket_name, project_id, location = check_env()

    log.info("")
    log.info("STEP 1/3: Upload to GCS")
    gcs_key, mime_type = upload_to_gcs(video_file, bucket_name)

    try:
        log.info("")
        log.info("STEP 2/3: Direct stream test")
        latency = test_direct_stream(project_id, location, bucket_name, gcs_key, mime_type, model)

        log.info("")
        log.info("STEP 3/3: Cleanup")
        if keep:
            log.info("--keep, file at: gs://%s/%s", bucket_name, gcs_key)
        else:
            cleanup(bucket_name, gcs_key)
    except Exception:
        if not keep:
            cleanup(bucket_name, gcs_key)
        sys.exit(1)

    log.info("")
    log.info("ALL PASSED — direct stream latency: %.1fs", latency)


if __name__ == "__main__":
    main()
