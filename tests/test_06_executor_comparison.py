#!/usr/bin/env python3
"""Test 06: ProcessPoolExecutor vs ThreadPoolExecutor

Tests the nested executor issue that caused transcription to fail silently.

The app structure is:
  extractor.py (ProcessPoolExecutor)
    └── audio_extractor.py
          └── _analyse_audio (ProcessPoolExecutor) <-- NESTED! This fails silently

This test verifies:
1. Nested ProcessPoolExecutor fails silently
2. ThreadPoolExecutor inside ProcessPoolExecutor works
"""

import concurrent.futures
import os
import sys
import time

# Add service directory to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_DIR = os.path.join(PROJECT_ROOT, 'service')
sys.path.insert(0, SERVICE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

from google import genai
from google.genai import types
from google.cloud import storage as gcs_storage

# Test audio file
TEST_AUDIO = "/tmp/test_extracted_audio.wav"


def get_client():
    """Get Vertex AI genai client."""
    return genai.Client(
        vertexai=True,
        project=os.environ.get('GCS_PROJECT_ID'),
        location=os.environ.get('GCS_LOCATION', 'us-central1'),
    )


def simple_task(x):
    """A simple task that returns a value."""
    time.sleep(0.1)
    return x * 2


def task_with_nested_process_executor(x):
    """Task that tries to use ProcessPoolExecutor inside (WILL FAIL)."""
    print(f"    [Nested Process] Starting task with x={x}")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(simple_task, i) for i in range(2)]
            results = [f.result(timeout=10) for f in futures]
            print(f"    [Nested Process] Got results: {results}")
            return sum(results)
    except Exception as e:
        print(f"    [Nested Process] EXCEPTION: {e}")
        return None


def task_with_nested_thread_executor(x):
    """Task that uses ThreadPoolExecutor inside (WILL WORK)."""
    print(f"    [Nested Thread] Starting task with x={x}")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(simple_task, i) for i in range(2)]
            results = [f.result(timeout=10) for f in futures]
            print(f"    [Nested Thread] Got results: {results}")
            return sum(results)
    except Exception as e:
        print(f"    [Nested Thread] EXCEPTION: {e}")
        return None


def transcribe_task_process(audio_path):
    """Simulates transcribe_audio running in ProcessPoolExecutor with nested Process."""
    print(f"    [Transcribe-Process] Starting transcription...")

    # This simulates what the OLD code did - nested ProcessPoolExecutor
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(do_transcription, audio_path)
            result = future.result(timeout=120)
            print(f"    [Transcribe-Process] Got result: {result is not None}")
            return result
    except Exception as e:
        print(f"    [Transcribe-Process] EXCEPTION: {e}")
        return None


def transcribe_task_thread(audio_path):
    """Simulates transcribe_audio running in ProcessPoolExecutor with nested Thread."""
    print(f"    [Transcribe-Thread] Starting transcription...")

    # This simulates what the NEW code does - ThreadPoolExecutor inside
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(do_transcription, audio_path)
            result = future.result(timeout=120)
            print(f"    [Transcribe-Thread] Got result: {result is not None}")
            return result
    except Exception as e:
        print(f"    [Transcribe-Thread] EXCEPTION: {e}")
        return None


def do_transcription(audio_path):
    """Actually do the transcription (called from nested executor)."""
    print(f"      [DoTranscription] Running with audio: {audio_path}")

    if not os.path.exists(audio_path):
        print(f"      [DoTranscription] Audio file not found!")
        return None

    client = get_client()
    gcs_client = gcs_storage.Client()
    bucket_name = os.environ.get('GCS_BUCKET')
    bucket = gcs_client.bucket(bucket_name)

    # Upload audio to GCS
    temp_key = f"_test_temp/executor_test_{int(time.time())}.wav"
    blob = bucket.blob(temp_key)
    blob.upload_from_filename(audio_path, content_type='audio/wav')
    gs_uri = f"gs://{bucket_name}/{temp_key}"
    print(f"      [DoTranscription] Uploaded: {gs_uri}")

    try:
        audio_part = types.Part.from_uri(file_uri=gs_uri, mime_type='audio/wav')
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[audio_part, "What language is spoken in this audio? Reply with just the language name."],
            config=types.GenerateContentConfig(max_output_tokens=100),
        )
    finally:
        # Cleanup
        try:
            blob.delete()
        except:
            pass

    if response.candidates:
        result = response.candidates[0].content.parts[0].text
        print(f"      [DoTranscription] Result: {result}")
        return result
    return None


def test_nested_process_executor():
    """Test 1: Nested ProcessPoolExecutor (OLD behavior - expected to fail)"""
    print("\n" + "=" * 60)
    print("TEST 1: Nested ProcessPoolExecutor (OLD - should FAIL)")
    print("=" * 60)

    print("  Outer ProcessPoolExecutor starting...")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as outer:
            future = outer.submit(task_with_nested_process_executor, 5)
            try:
                result = future.result(timeout=15)
                if result is not None:
                    print(f"  UNEXPECTED: Nested ProcessPoolExecutor worked! Result: {result}")
                    return True
                else:
                    print(f"  EXPECTED: Nested ProcessPoolExecutor returned None (silent failure)")
                    return False
            except concurrent.futures.TimeoutError:
                print(f"  EXPECTED: Nested ProcessPoolExecutor timed out (deadlock)")
                return False
            except Exception as e:
                print(f"  EXPECTED: Nested ProcessPoolExecutor failed: {e}")
                return False
    except Exception as e:
        print(f"  Outer executor failed: {e}")
        return False


def test_nested_thread_executor():
    """Test 2: ThreadPoolExecutor inside ProcessPoolExecutor (NEW behavior - should work)"""
    print("\n" + "=" * 60)
    print("TEST 2: ThreadPoolExecutor inside ProcessPoolExecutor (NEW - should PASS)")
    print("=" * 60)

    print("  Outer ProcessPoolExecutor starting...")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as outer:
            future = outer.submit(task_with_nested_thread_executor, 5)
            result = future.result(timeout=15)
            if result is not None:
                print(f"  PASS: ThreadPoolExecutor inside ProcessPoolExecutor worked! Result: {result}")
                return True
            else:
                print(f"  FAIL: ThreadPoolExecutor returned None")
                return False
    except Exception as e:
        print(f"  FAIL: Exception: {e}")
        return False


def test_real_transcription_with_process():
    """Test 3: Real transcription with nested ProcessPoolExecutor"""
    print("\n" + "=" * 60)
    print("TEST 3: Real Transcription with Nested ProcessPoolExecutor")
    print("=" * 60)

    if not os.path.exists(TEST_AUDIO):
        print(f"  SKIP: Audio file not found. Run test_01 first.")
        return None

    print("  Outer ProcessPoolExecutor starting...")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as outer:
            future = outer.submit(transcribe_task_process, TEST_AUDIO)
            try:
                result = future.result(timeout=120)
                if result:
                    print(f"  Result: {result}")
                    return True
                else:
                    print(f"  EXPECTED FAIL: Nested Process executor failed silently")
                    return False
            except concurrent.futures.TimeoutError:
                print(f"  EXPECTED FAIL: Timeout (deadlock in nested executor)")
                return False
    except Exception as e:
        print(f"  Exception: {e}")
        return False


def test_real_transcription_with_thread():
    """Test 4: Real transcription with ThreadPoolExecutor (the fix)"""
    print("\n" + "=" * 60)
    print("TEST 4: Real Transcription with ThreadPoolExecutor (THE FIX)")
    print("=" * 60)

    if not os.path.exists(TEST_AUDIO):
        print(f"  SKIP: Audio file not found. Run test_01 first.")
        return None

    print("  Outer ProcessPoolExecutor starting...")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as outer:
            future = outer.submit(transcribe_task_thread, TEST_AUDIO)
            result = future.result(timeout=120)
            if result:
                print(f"  PASS: Transcription worked! Language: {result}")
                return True
            else:
                print(f"  FAIL: No result")
                return False
    except Exception as e:
        print(f"  FAIL: Exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 06: ProcessPoolExecutor vs ThreadPoolExecutor")
    print("=" * 60)
    print("\nThis test demonstrates why nested ProcessPoolExecutor fails")
    print("and why ThreadPoolExecutor is the correct fix.\n")

    results = {}

    # Test 1: Nested Process (should fail)
    results['nested_process'] = test_nested_process_executor()

    # Test 2: Thread inside Process (should work)
    results['thread_in_process'] = test_nested_thread_executor()

    # Test 3: Real transcription with Process (should fail)
    results['real_process'] = test_real_transcription_with_process()

    # Test 4: Real transcription with Thread (should work)
    results['real_thread'] = test_real_transcription_with_thread()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print("\n  Expected behavior:")
    print("  - nested_process: FAIL (nested ProcessPoolExecutor deadlocks)")
    print("  - thread_in_process: PASS (ThreadPoolExecutor works inside)")
    print("  - real_process: FAIL (real transcription with nested Process)")
    print("  - real_thread: PASS (real transcription with Thread fix)")

    print("\n  Actual results:")
    for name, result in results.items():
        if result is None:
            status = "SKIP"
        elif result:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"    [{status}] {name}")

    # The fix is correct if:
    # - nested_process FAILS
    # - thread_in_process PASSES
    # - real_thread PASSES
    fix_validated = (
        results.get('nested_process') == False and
        results.get('thread_in_process') == True and
        results.get('real_thread') == True
    )

    print("\n" + "=" * 60)
    if fix_validated:
        print("CONCLUSION: ThreadPoolExecutor fix is VALIDATED!")
        print("The nested ProcessPoolExecutor was the root cause.")
    else:
        print("CONCLUSION: Results unexpected - investigate further")
    print("=" * 60)

    sys.exit(0 if fix_validated else 1)
