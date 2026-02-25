#!/usr/bin/env python3
"""Test 05: End-to-End Flow (Exact App Replica)

This test replicates EXACTLY what the main app does:
1. Extract audio from video
2. Upload audio to GCS
3. Transcribe with exact prompt/config from app via gs:// URI
4. Parse response with exact regex from app
5. Write VTT file locally
6. Upload VTT to GCS
7. Read VTT back from GCS
8. Verify content

This mirrors the code in:
- /service/audio/audio.py (transcribe_audio function)
- /service/storage/storage.py (upload/download functions)
- /service/config/config.py (prompts and patterns)
"""

import io
import os
import re
import sys
import tempfile
import time

# Add service directory to path to import actual app modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_DIR = os.path.join(PROJECT_ROOT, 'service')
sys.path.insert(0, SERVICE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

from google import genai
from google.genai import types
from google.cloud import storage as gcs_storage
import pandas as pd

# ============================================================
# EXACT COPIES FROM APP CONFIG (service/config/config.py)
# ============================================================

DEFAULT_VIDEO_LANGUAGE = 'en'
OUTPUT_SUBTITLES_TYPE = 'vtt'

TRANSCRIBE_AUDIO_PROMPT = """Transcribe the provided audio file, paying close attention to speaker changes and pauses in speech.
Output exactly as shown below and in the following order:
1. **Language:** Specify the language of the audio (e.g., "Language: English")
2. **Confidence:**  Specify the confidence score of the transcription (e.g., "Confidence: 0.95")
3. **Transcription CSV:** Output the transcription in CSV (Comma-Separated Values) format (e.g. ```csv<output>```) with these columns:
    * **Start:** (Start timestamp for each utterance in the format "mm:ss.SSS")
    * **End:** (End timestamp for each utterance in the format "mm:ss.SSS")
    * **Transcription:** (The transcribed text of the utterance)
    Ensure each row in the CSV corresponds to a complete sentence or a meaningful phrase. Sentences by different speakers, even if related, should not be grouped together.
    **Critical Timestamping Requirements:**
        * **Pause Detection:** It is absolutely essential to accurately identify and incorporate pauses in speech. If there is a period of silence between utterances, even a brief one, this MUST be reflected in the timestamps. Do not assume continuous speech.
        * **No Overlapping:** Timestamps for consecutive sentences should NOT overlap. The end timestamp of one sentence should be the start timestamp of the next sentence ONLY if there is no pause between them.
4. **WebVTT Format:** Output the transcription information in WebVTT format, surrounded by backticks (e.g. ```vtt<output>```)

**Constraints:**
    * **No Extra Text:** Only output the language, confidence, table, and WebVTT data, without any additional text or explanations. This includes avoiding any labels or headings before or after the transcription table and WebVTT data. Do not output in JSON.
    * **Valid Timestamps:** All timestamps MUST be within the actual duration of the audio. No timestamps should exceed the total length of the audio. This is absolutely critical.
    * **Sequential Timestamps:** Timestamps should progress sequentially and logically from the beginning to the end of the audio.

"""

TRANSCRIBE_AUDIO_CONFIG = {
    'max_output_tokens': 8192,
    'temperature': 0.2,
    'top_p': 1,
}

TRANSCRIBE_AUDIO_PATTERN = r'.*Language: ?(.*)\n*.*Confidence: ?(.*)\n*```csv\n(.*)```\n*```vtt\n(.*)```'

CONFIG_DEFAULT_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

CONFIG_TRANSCRIPTION_MODEL_GEMINI = 'gemini-2.5-flash'

# ============================================================
# TEST CONFIGURATION
# ============================================================

TEST_VIDEO = os.path.join(PROJECT_ROOT, "Ep 01_1.mp4")
TEST_FOLDER = "test_e2e_transcription"
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'vigenair')


def get_client():
    """Get Vertex AI genai client."""
    return genai.Client(
        vertexai=True,
        project=os.environ.get('GCS_PROJECT_ID'),
        location=os.environ.get('GCS_LOCATION', 'us-central1'),
    )


def get_gcs_client():
    """Get GCS storage client."""
    return gcs_storage.Client()


def step_1_extract_audio(video_path: str, output_dir: str) -> str:
    """Step 1: Extract audio from video (mirrors audio.extract_audio)"""
    print("\n" + "=" * 60)
    print("STEP 1: Extract Audio from Video")
    print("=" * 60)

    import subprocess

    audio_file_path = os.path.join(output_dir, "input.wav")

    # Check if video has audio
    result = subprocess.run(
        ['ffprobe', '-i', video_path, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'],
        capture_output=True, text=True
    )

    if not result.stdout:
        print("  ERROR: Video has no audio track!")
        return None

    print(f"  Video has audio track")

    # Extract audio
    result = subprocess.run(
        ['ffmpeg', '-i', video_path, '-q:a', '0', '-map', 'a', audio_file_path, '-y'],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"  ERROR: FFmpeg failed: {result.stderr[-200:]}")
        return None

    size_mb = os.path.getsize(audio_file_path) / (1024 * 1024)
    print(f"  PASS: Audio extracted to {audio_file_path} ({size_mb:.2f} MB)")

    return audio_file_path


def step_2_transcribe_audio(audio_file_path: str, output_dir: str) -> tuple:
    """Step 2: Transcribe audio with Gemini via Vertex AI (mirrors audio.transcribe_audio)"""
    print("\n" + "=" * 60)
    print("STEP 2: Transcribe Audio with Gemini (Vertex AI)")
    print("=" * 60)

    # Initialize variables exactly as in the app
    transcription_dataframe = pd.DataFrame()
    video_language = DEFAULT_VIDEO_LANGUAGE
    language_probability = 0.0
    subtitles_content = None
    temp_gcs_blob = None

    # Initialize Vertex AI client
    client = get_client()
    gcs_client = get_gcs_client()

    print(f"  Using model: {CONFIG_TRANSCRIPTION_MODEL_GEMINI}")

    try:
        # Upload audio to GCS for gs:// URI access
        print(f"  Uploading audio to GCS...")
        bucket = gcs_client.bucket(GCS_BUCKET)
        temp_key = f"_test_temp/e2e_audio_{int(time.time())}.wav"
        temp_gcs_blob = bucket.blob(temp_key)
        temp_gcs_blob.upload_from_filename(audio_file_path, content_type='audio/wav')
        gs_uri = f"gs://{GCS_BUCKET}/{temp_key}"
        print(f"  Uploaded: {gs_uri}")

        # Generate transcription using gs:// URI
        print(f"  Generating transcription...")
        audio_part = types.Part.from_uri(file_uri=gs_uri, mime_type='audio/wav')
        response = client.models.generate_content(
            model=CONFIG_TRANSCRIPTION_MODEL_GEMINI,
            contents=[audio_part, TRANSCRIBE_AUDIO_PROMPT],
            config=types.GenerateContentConfig(
                **TRANSCRIBE_AUDIO_CONFIG,
                safety_settings=CONFIG_DEFAULT_SAFETY_SETTINGS,
            ),
        )

        if (response.candidates and response.candidates[0].content.parts
            and response.candidates[0].content.parts[0].text):

            text = response.candidates[0].content.parts[0].text
            print(f"  Got response: {len(text)} chars")

            # Save raw response for debugging
            with open(os.path.join(output_dir, 'raw_response.txt'), 'w') as f:
                f.write(text)
            print(f"  Saved raw response to raw_response.txt")

            # Parse with regex (EXACT code from app)
            result = re.search(TRANSCRIBE_AUDIO_PATTERN, text, re.DOTALL)

            print(f"\n  Regex match result: {result is not None}")

            if result is None:
                print(f"  ERROR: Response did not match expected format!")
                print(f"  Response preview:")
                for line in text[:500].split('\n'):
                    print(f"    {line}")
            else:
                video_language = result.group(1)
                language_probability = result.group(2)
                print(f"  Language: {video_language}")
                print(f"  Confidence: {language_probability}")

                # Parse CSV (EXACT code from app)
                try:
                    transcription_dataframe = (
                        pd.read_csv(io.StringIO(result.group(3)), usecols=[0, 1, 2])
                        .dropna(axis=1, how='all')
                        .rename(columns={
                            'Start': 'start_s',
                            'End': 'end_s',
                            'Transcription': 'transcript',
                        })
                    )
                    print(f"  Parsed CSV: {len(transcription_dataframe)} rows")
                except Exception as e:
                    print(f"  ERROR parsing CSV: {e}")

                subtitles_content = result.group(4)
                print(f"  VTT content length: {len(subtitles_content) if subtitles_content else 0} chars")
        else:
            print(f"  ERROR: No response from Gemini")

    except Exception as e:
        print(f"  EXCEPTION during transcription: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup GCS temp file
        if temp_gcs_blob:
            try:
                temp_gcs_blob.delete()
                print(f"  Cleaned up GCS temp file")
            except Exception as e:
                print(f"  Warning: Failed to cleanup GCS temp file: {e}")

    return transcription_dataframe, video_language, language_probability, subtitles_content


def step_3_write_vtt_file(audio_file_path: str, subtitles_content: str) -> str:
    """Step 3: Write VTT file locally (mirrors audio.transcribe_audio end)"""
    print("\n" + "=" * 60)
    print("STEP 3: Write VTT File Locally")
    print("=" * 60)

    subtitles_output_path = audio_file_path.replace('.wav', f'.{OUTPUT_SUBTITLES_TYPE}')

    print(f"  Output path: {subtitles_output_path}")

    with open(subtitles_output_path, 'w', encoding='utf8') as f:
        if subtitles_content:
            f.write(subtitles_content)
            print(f"  PASS: Wrote {len(subtitles_content)} chars to VTT file")
        else:
            pass
            print(f"  WARNING: No subtitles content - wrote EMPTY file!")

    file_size = os.path.getsize(subtitles_output_path)
    print(f"  File size: {file_size} bytes")

    return subtitles_output_path


def step_4_upload_to_gcs(local_path: str, gcs_key: str) -> bool:
    """Step 4: Upload VTT to GCS (mirrors storage.upload_file)"""
    print("\n" + "=" * 60)
    print("STEP 4: Upload VTT to GCS")
    print("=" * 60)

    gcs_client = get_gcs_client()
    bucket = gcs_client.bucket(GCS_BUCKET)

    print(f"  Bucket: {GCS_BUCKET}")
    print(f"  Key: {gcs_key}")
    print(f"  Local file: {local_path}")

    try:
        blob = bucket.blob(gcs_key)
        blob.upload_from_filename(local_path)
        print(f"  PASS: Uploaded to GCS")
        return True
    except Exception as e:
        print(f"  ERROR: Failed to upload: {e}")
        return False


def step_5_download_from_gcs(gcs_key: str) -> bytes:
    """Step 5: Download VTT from GCS (mirrors storage.download_file with fetch_contents=True)"""
    print("\n" + "=" * 60)
    print("STEP 5: Download VTT from GCS")
    print("=" * 60)

    gcs_client = get_gcs_client()
    bucket = gcs_client.bucket(GCS_BUCKET)

    print(f"  Bucket: {GCS_BUCKET}")
    print(f"  Key: {gcs_key}")

    try:
        blob = bucket.blob(gcs_key)
        content = blob.download_as_bytes()
        print(f"  PASS: Downloaded {len(content)} bytes")
        return content
    except Exception as e:
        print(f"  ERROR: Failed to download: {e}")
        return None


def step_6_api_check(content: bytes) -> bool:
    """Step 6: Check if API would return 404 (mirrors files.py download endpoint)"""
    print("\n" + "=" * 60)
    print("STEP 6: API Response Check")
    print("=" * 60)

    if not content:
        print(f"  RESULT: API would return 404 (content is None/empty)")
        return False

    if content == b'':
        print(f"  RESULT: API would return 404 (content is empty bytes)")
        print(f"  NOTE: 'if not content' evaluates to True for empty bytes!")
        return False

    print(f"  RESULT: API would return 200 with {len(content)} bytes")
    return True


def cleanup_gcs(gcs_key: str):
    """Cleanup test file from GCS"""
    print("\n" + "=" * 60)
    print("CLEANUP: Removing test file from GCS")
    print("=" * 60)

    gcs_client = get_gcs_client()
    bucket = gcs_client.bucket(GCS_BUCKET)

    try:
        blob = bucket.blob(gcs_key)
        blob.delete()
        print(f"  Deleted: {gcs_key}")
    except Exception as e:
        print(f"  Warning: Failed to cleanup: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 05: End-to-End Flow (Exact App Replica)")
    print("=" * 60)

    # Check prerequisites
    if not os.path.exists(TEST_VIDEO):
        print(f"ERROR: Test video not found: {TEST_VIDEO}")
        sys.exit(1)

    if not os.environ.get('GCS_PROJECT_ID'):
        print("ERROR: GCS_PROJECT_ID not set")
        sys.exit(1)

    if not os.environ.get('GCS_BUCKET'):
        print("ERROR: GCS_BUCKET not set")
        sys.exit(1)

    # Create temp directory
    tmp_dir = tempfile.mkdtemp(prefix='vigenair_test_')
    print(f"\nTemp directory: {tmp_dir}")

    gcs_vtt_key = f"{TEST_FOLDER}/input.vtt"

    try:
        # Step 1: Extract audio
        audio_path = step_1_extract_audio(TEST_VIDEO, tmp_dir)
        if not audio_path:
            sys.exit(1)

        # Step 2: Transcribe
        df, language, confidence, vtt_content = step_2_transcribe_audio(audio_path, tmp_dir)

        # Step 3: Write VTT file
        vtt_path = step_3_write_vtt_file(audio_path, vtt_content)

        # Step 4: Upload to GCS
        if not step_4_upload_to_gcs(vtt_path, gcs_vtt_key):
            sys.exit(1)

        # Step 5: Download from GCS
        content = step_5_download_from_gcs(gcs_vtt_key)

        # Step 6: API check
        api_ok = step_6_api_check(content)

        # Final summary
        print("\n" + "=" * 60)
        print("FINAL SUMMARY")
        print("=" * 60)
        print(f"  Audio extracted: YES")
        print(f"  Transcription rows: {len(df) if df is not None else 0}")
        print(f"  Language detected: {language}")
        print(f"  VTT content generated: {'YES' if vtt_content else 'NO'}")
        print(f"  VTT file size: {os.path.getsize(vtt_path)} bytes")
        print(f"  GCS upload: SUCCESS")
        print(f"  GCS download: {len(content) if content else 0} bytes")
        print(f"  API would return: {'200 OK' if api_ok else '404 NOT FOUND'}")

        if not api_ok:
            print("\n  *** ISSUE IDENTIFIED ***")
            print("  The VTT file exists but is EMPTY!")
            print("  This causes 'if not content' to be True, returning 404")

    finally:
        # Cleanup
        cleanup_gcs(gcs_vtt_key)

        # Keep temp dir for inspection
        print(f"\n  Temp files kept at: {tmp_dir}")
        print(f"  - input.wav")
        print(f"  - input.vtt")
        print(f"  - raw_response.txt")

    sys.exit(0 if api_ok else 1)
