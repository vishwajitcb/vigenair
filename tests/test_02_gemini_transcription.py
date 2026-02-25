#!/usr/bin/env python3
"""Test 02: Gemini API Transcription

Tests the Gemini API transcription with the audio file.
"""

import os
import re
import sys
import time

# Load environment variables
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

from google import genai
from google.genai import types

# Test audio file (created by test_01)
TEST_AUDIO = "/tmp/test_extracted_audio.wav"

# The prompt from config
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

# The regex pattern from config
TRANSCRIBE_AUDIO_PATTERN = r'.*Language: ?(.*)\n*.*Confidence: ?(.*)\n*```csv\n(.*)```\n*```vtt\n(.*)```'

# Models to test
MODELS_TO_TEST = [
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-1.5-flash',
]


def get_client():
    """Get Vertex AI genai client."""
    return genai.Client(
        vertexai=True,
        project=os.environ.get('GCS_PROJECT_ID'),
        location=os.environ.get('GCS_LOCATION', 'us-central1'),
    )


def test_credentials():
    """Check if GCP credentials are configured."""
    print("Checking GCP credentials...")
    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    project_id = os.environ.get('GCS_PROJECT_ID')
    if creds_path and project_id:
        print(f"  PASS: Credentials found ({creds_path}), project: {project_id}")
        return True
    else:
        if not creds_path:
            print("  FAIL: GOOGLE_APPLICATION_CREDENTIALS not set in environment")
        if not project_id:
            print("  FAIL: GCS_PROJECT_ID not set in environment")
        return False


def test_audio_file():
    """Check if test audio exists."""
    print(f"Checking audio file: {TEST_AUDIO}")
    if os.path.exists(TEST_AUDIO):
        size_mb = os.path.getsize(TEST_AUDIO) / (1024 * 1024)
        print(f"  PASS: Audio exists ({size_mb:.2f} MB)")
        return True
    else:
        print("  FAIL: Audio not found. Run test_01 first!")
        return False


def test_list_models():
    """List available Gemini models."""
    print("Listing available models...")
    client = get_client()

    available = []
    for m in client.models.list():
        available.append(m.name)
        if any(test_model in m.name for test_model in MODELS_TO_TEST):
            print(f"  - {m.name} (will test)")

    return available


def test_transcription(model_name: str):
    """Test transcription with a specific model."""
    print(f"\nTesting transcription with: {model_name}")
    print("-" * 50)

    client = get_client()

    # Upload audio to GCS for gs:// URI access
    from google.cloud import storage as gcs_storage
    gcs_client = gcs_storage.Client()
    bucket_name = os.environ.get('GCS_BUCKET')
    bucket = gcs_client.bucket(bucket_name)
    temp_key = f"_test_temp/test_audio_{int(time.time())}.wav"
    blob = bucket.blob(temp_key)

    print("  Uploading audio file to GCS...")
    try:
        blob.upload_from_filename(TEST_AUDIO, content_type='audio/wav')
        gs_uri = f"gs://{bucket_name}/{temp_key}"
        print(f"  Uploaded: {gs_uri}")
    except Exception as e:
        print(f"  FAIL: Could not upload audio: {e}")
        return None

    # Generate transcription using gs:// URI
    print("  Generating transcription...")
    try:
        audio_part = types.Part.from_uri(file_uri=gs_uri, mime_type='audio/wav')
        response = client.models.generate_content(
            model=model_name,
            contents=[audio_part, TRANSCRIBE_AUDIO_PROMPT],
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                temperature=0.2,
            ),
        )
    except Exception as e:
        print(f"  FAIL: API error: {e}")
        blob.delete()
        return None

    # Cleanup GCS temp file
    try:
        blob.delete()
    except:
        pass

    # Extract response
    if response.candidates and response.candidates[0].content.parts:
        text = response.candidates[0].content.parts[0].text
        print(f"  Response length: {len(text)} chars")
        return text
    else:
        print("  FAIL: No response text")
        return None


def test_regex_pattern(response_text: str):
    """Test if response matches the expected regex pattern."""
    print("\nTesting regex pattern match...")

    result = re.search(TRANSCRIBE_AUDIO_PATTERN, response_text, re.DOTALL)

    if result:
        print("  PASS: Pattern matched!")
        print(f"    Language: {result.group(1)}")
        print(f"    Confidence: {result.group(2)}")
        print(f"    CSV length: {len(result.group(3))} chars")
        print(f"    VTT length: {len(result.group(4))} chars")
        return True
    else:
        print("  FAIL: Pattern did not match!")
        print("\n  Response preview:")
        print("  " + "-" * 40)
        for line in response_text[:1000].split('\n'):
            print(f"  {line}")
        print("  " + "-" * 40)

        # Try to diagnose why
        print("\n  Diagnosis:")
        if "Language:" in response_text:
            print("    - 'Language:' found")
        else:
            print("    - 'Language:' NOT found")

        if "Confidence:" in response_text:
            print("    - 'Confidence:' found")
        else:
            print("    - 'Confidence:' NOT found")

        if "```csv" in response_text:
            print("    - '```csv' block found")
        else:
            print("    - '```csv' block NOT found")

        if "```vtt" in response_text:
            print("    - '```vtt' block found")
        else:
            print("    - '```vtt' block NOT found")

        return False


def save_response(model_name: str, response_text: str):
    """Save response to file for analysis."""
    filename = f"/tmp/transcription_response_{model_name.replace('/', '_')}.txt"
    with open(filename, 'w') as f:
        f.write(response_text)
    print(f"  Response saved to: {filename}")


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 02: Gemini API Transcription")
    print("=" * 60)

    # Pre-checks
    if not test_credentials():
        sys.exit(1)

    if not test_audio_file():
        sys.exit(1)

    available_models = test_list_models()

    # Test each model
    results = {}
    for model in MODELS_TO_TEST:
        # Find full model name
        full_name = None
        for m in available_models:
            if model in m:
                full_name = m.split('/')[-1]  # Remove 'models/' prefix
                break

        if not full_name:
            print(f"\n  SKIP: {model} not available")
            continue

        response = test_transcription(full_name)
        if response:
            save_response(full_name, response)
            matched = test_regex_pattern(response)
            results[model] = matched
        else:
            results[model] = False

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for model, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {model}")

    sys.exit(0 if all(results.values()) else 1)
