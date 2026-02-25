#!/usr/bin/env python3
"""Test 04: Full Transcription Pipeline

Tests the complete transcription pipeline and proposes robust fixes.
"""

import io
import os
import re
import sys
import time
import subprocess

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

from google import genai
from google.genai import types
from google.cloud import storage as gcs_storage
import pandas as pd

# Test files
TEST_VIDEO = os.path.join(PROJECT_ROOT, "Ep 01_1.mp4")
TEST_AUDIO = "/tmp/test_pipeline_audio.wav"

# Improved prompt - more explicit about format
IMPROVED_PROMPT = """Transcribe the provided audio file accurately.

IMPORTANT: Follow this EXACT output format:

Language: [detected language name]
Confidence: [confidence score between 0.0 and 1.0]

```csv
Start,End,Transcription
[mm:ss.SSS],[mm:ss.SSS],[transcribed text]
```

```vtt
WEBVTT

[mm:ss.SSS] --> [mm:ss.SSS]
[transcribed text]
```

RULES:
1. Detect the language being spoken (Telugu, Hindi, English, etc.)
2. Output confidence as a decimal (e.g., 0.95)
3. Use mm:ss.SSS format for timestamps (e.g., 01:23.456)
4. Each row = one complete sentence or phrase
5. If no speech is detected, output empty CSV and VTT blocks with just headers
6. Do NOT add any extra text, headers, or explanations
7. Do NOT use markdown formatting like **bold**
"""

# Improved regex pattern - more flexible
IMPROVED_PATTERN = r'Language[:\s]+([^\n]+)\n[\s\S]*?Confidence[:\s]+([^\n]+)\n[\s\S]*?```csv\n([\s\S]*?)```[\s\S]*?```vtt\n([\s\S]*?)```'


def get_client():
    """Get Vertex AI genai client."""
    return genai.Client(
        vertexai=True,
        project=os.environ.get('GCS_PROJECT_ID'),
        location=os.environ.get('GCS_LOCATION', 'us-central1'),
    )


def upload_audio_to_gcs(audio_path: str) -> tuple:
    """Upload audio to GCS and return (gs_uri, blob)."""
    gcs_client = gcs_storage.Client()
    bucket_name = os.environ.get('GCS_BUCKET')
    bucket = gcs_client.bucket(bucket_name)
    temp_key = f"_test_temp/pipeline_audio_{int(time.time())}.wav"
    blob = bucket.blob(temp_key)
    blob.upload_from_filename(audio_path, content_type='audio/wav')
    gs_uri = f"gs://{bucket_name}/{temp_key}"
    return gs_uri, blob


def extract_audio():
    """Extract audio from video."""
    print("Extracting audio from video...")

    if os.path.exists(TEST_AUDIO):
        os.remove(TEST_AUDIO)

    result = subprocess.run(
        ['ffmpeg', '-i', TEST_VIDEO, '-q:a', '0', '-map', 'a', TEST_AUDIO, '-y'],
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and os.path.exists(TEST_AUDIO):
        print(f"  PASS: Audio extracted to {TEST_AUDIO}")
        return True
    else:
        print(f"  FAIL: {result.stderr[-200:]}")
        return False


def transcribe_audio(prompt: str, model_name: str = 'gemini-2.5-flash'):
    """Run transcription with Gemini via Vertex AI."""
    print(f"\nTranscribing with {model_name}...")

    client = get_client()

    # Upload audio to GCS
    print("  Uploading audio to GCS...")
    gs_uri, blob = upload_audio_to_gcs(TEST_AUDIO)
    print(f"  Uploaded: {gs_uri}")

    try:
        # Generate transcription using gs:// URI
        audio_part = types.Part.from_uri(file_uri=gs_uri, mime_type='audio/wav')
        response = client.models.generate_content(
            model=model_name,
            contents=[audio_part, prompt],
            config=types.GenerateContentConfig(
                max_output_tokens=8192,
                temperature=0.1,
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

    if response.candidates and response.candidates[0].content.parts:
        text = response.candidates[0].content.parts[0].text
        print(f"  Got response: {len(text)} chars")
        return text
    else:
        print("  FAIL: No response")
        return None


def parse_transcription(response: str, pattern: str):
    """Parse transcription response with given pattern."""
    print("\nParsing response...")

    result = re.search(pattern, response, re.DOTALL | re.IGNORECASE)

    if not result:
        print("  FAIL: Pattern did not match")
        print("\n  Response preview:")
        for line in response[:500].split('\n'):
            print(f"    {line}")
        return None

    language = result.group(1).strip()
    confidence = result.group(2).strip()
    csv_content = result.group(3).strip()
    vtt_content = result.group(4).strip()

    print(f"  Language: {language}")
    print(f"  Confidence: {confidence}")
    print(f"  CSV rows: {len(csv_content.split(chr(10)))}")
    print(f"  VTT lines: {len(vtt_content.split(chr(10)))}")

    return {
        'language': language,
        'confidence': confidence,
        'csv': csv_content,
        'vtt': vtt_content
    }


def parse_csv_to_dataframe(csv_content: str):
    """Parse CSV content to pandas DataFrame."""
    print("\nParsing CSV to DataFrame...")

    if not csv_content.strip():
        print("  Empty CSV - no speech detected")
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            io.StringIO(csv_content),
            usecols=[0, 1, 2]
        ).dropna(axis=1, how='all')

        # Rename columns
        df = df.rename(columns={
            'Start': 'start_s',
            'End': 'end_s',
            'Transcription': 'transcript',
        })

        print(f"  Parsed {len(df)} rows")
        if len(df) > 0:
            print(f"  First row: {df.iloc[0].to_dict()}")

        return df
    except Exception as e:
        print(f"  FAIL: {e}")
        return pd.DataFrame()


def test_with_original():
    """Test with original prompt and pattern."""
    print("\n" + "=" * 60)
    print("Testing with ORIGINAL prompt and pattern")
    print("=" * 60)

    # Original prompt from config
    original_prompt = """Transcribe the provided audio file, paying close attention to speaker changes and pauses in speech.
Output exactly as shown below and in the following order:
1. **Language:** Specify the language of the audio (e.g., "Language: English")
2. **Confidence:**  Specify the confidence score of the transcription (e.g., "Confidence: 0.95")
3. **Transcription CSV:** Output the transcription in CSV (Comma-Separated Values) format (e.g. ```csv<output>```) with these columns:
    * **Start:** (Start timestamp for each utterance in the format "mm:ss.SSS")
    * **End:** (End timestamp for each utterance in the format "mm:ss.SSS")
    * **Transcription:** (The transcribed text of the utterance)
4. **WebVTT Format:** Output the transcription information in WebVTT format, surrounded by backticks (e.g. ```vtt<output>```)

**Constraints:**
    * **No Extra Text:** Only output the language, confidence, table, and WebVTT data.
"""
    original_pattern = r'.*Language: ?(.*)\n*.*Confidence: ?(.*)\n*```csv\n(.*)```\n*```vtt\n(.*)```'

    response = transcribe_audio(original_prompt)
    if response:
        # Save for analysis
        with open('/tmp/original_response.txt', 'w') as f:
            f.write(response)
        print("  Saved to /tmp/original_response.txt")

        parsed = parse_transcription(response, original_pattern)
        if parsed:
            df = parse_csv_to_dataframe(parsed['csv'])
            return True, parsed, df

    return False, None, None


def test_with_improved():
    """Test with improved prompt and pattern."""
    print("\n" + "=" * 60)
    print("Testing with IMPROVED prompt and pattern")
    print("=" * 60)

    response = transcribe_audio(IMPROVED_PROMPT)
    if response:
        # Save for analysis
        with open('/tmp/improved_response.txt', 'w') as f:
            f.write(response)
        print("  Saved to /tmp/improved_response.txt")

        parsed = parse_transcription(response, IMPROVED_PATTERN)
        if parsed:
            df = parse_csv_to_dataframe(parsed['csv'])
            return True, parsed, df

    return False, None, None


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 04: Full Transcription Pipeline")
    print("=" * 60)

    # Check prerequisites
    if not os.path.exists(TEST_VIDEO):
        print(f"FAIL: Test video not found: {TEST_VIDEO}")
        sys.exit(1)

    if not os.environ.get('GCS_PROJECT_ID'):
        print("FAIL: GCS_PROJECT_ID not set")
        sys.exit(1)

    # Extract audio
    if not extract_audio():
        sys.exit(1)

    # Test original
    orig_success, orig_parsed, orig_df = test_with_original()

    # Test improved
    impr_success, impr_parsed, impr_df = test_with_improved()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"\nOriginal prompt/pattern: {'PASS' if orig_success else 'FAIL'}")
    if orig_parsed:
        print(f"  - Language: {orig_parsed['language']}")
        print(f"  - Rows: {len(orig_df) if orig_df is not None else 0}")

    print(f"\nImproved prompt/pattern: {'PASS' if impr_success else 'FAIL'}")
    if impr_parsed:
        print(f"  - Language: {impr_parsed['language']}")
        print(f"  - Rows: {len(impr_df) if impr_df is not None else 0}")

    if impr_success and not orig_success:
        print("\n*** RECOMMENDATION: Use improved prompt and pattern! ***")
        print("\nImproved pattern:")
        print(f"  {IMPROVED_PATTERN}")

    sys.exit(0 if (orig_success or impr_success) else 1)
