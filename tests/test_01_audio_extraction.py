#!/usr/bin/env python3
"""Test 01: Audio Extraction from Video

Tests that we can extract audio from a video file using ffmpeg.
"""

import os
import subprocess
import sys

# Test video path (relative to project root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_VIDEO = os.path.join(PROJECT_ROOT, "Ep 01_1.mp4")
OUTPUT_AUDIO = "/tmp/test_extracted_audio.wav"


def test_video_exists():
    """Check if test video exists."""
    print(f"Checking for test video: {TEST_VIDEO}")
    if os.path.exists(TEST_VIDEO):
        size_mb = os.path.getsize(TEST_VIDEO) / (1024 * 1024)
        print(f"  PASS: Video exists ({size_mb:.2f} MB)")
        return True
    else:
        print(f"  FAIL: Video not found!")
        # List available files
        print(f"  Available .mp4 files in {PROJECT_ROOT}:")
        for f in os.listdir(PROJECT_ROOT):
            if f.endswith('.mp4'):
                print(f"    - {f}")
        return False


def test_ffmpeg_available():
    """Check if ffmpeg is installed."""
    print("Checking ffmpeg installation...")
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"  PASS: {version}")
            return True
        else:
            print(f"  FAIL: ffmpeg returned error")
            return False
    except FileNotFoundError:
        print("  FAIL: ffmpeg not found in PATH")
        return False


def test_audio_extraction():
    """Extract audio from video."""
    print(f"Extracting audio to: {OUTPUT_AUDIO}")

    # Remove existing file
    if os.path.exists(OUTPUT_AUDIO):
        os.remove(OUTPUT_AUDIO)

    result = subprocess.run(
        [
            'ffmpeg', '-i', TEST_VIDEO,
            '-q:a', '0',
            '-map', 'a',
            OUTPUT_AUDIO,
            '-y'
        ],
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and os.path.exists(OUTPUT_AUDIO):
        size_mb = os.path.getsize(OUTPUT_AUDIO) / (1024 * 1024)
        print(f"  PASS: Audio extracted ({size_mb:.2f} MB)")
        return True
    else:
        print(f"  FAIL: Could not extract audio")
        print(f"  stderr: {result.stderr[-500:]}")
        return False


def test_audio_duration():
    """Check audio duration using ffprobe."""
    print("Checking audio duration...")

    result = subprocess.run(
        [
            'ffprobe', '-i', OUTPUT_AUDIO,
            '-show_entries', 'format=duration',
            '-v', 'quiet',
            '-of', 'default=noprint_wrappers=1:nokey=1'
        ],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        duration = float(result.stdout.strip())
        print(f"  PASS: Duration = {duration:.2f} seconds")
        return True, duration
    else:
        print("  FAIL: Could not get duration")
        return False, 0


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 01: Audio Extraction")
    print("=" * 60)

    results = []

    results.append(("Video exists", test_video_exists()))
    results.append(("FFmpeg available", test_ffmpeg_available()))

    if results[-1][1]:  # If ffmpeg is available
        results.append(("Audio extraction", test_audio_extraction()))
        if results[-1][1]:  # If extraction worked
            passed, duration = test_audio_duration()
            results.append(("Audio duration", passed))

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)
