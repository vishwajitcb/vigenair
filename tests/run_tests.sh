#!/bin/bash
# Run all transcription tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "Installing test dependencies..."
echo "========================================"
pip install -q -r requirements.txt

echo ""
echo "========================================"
echo "Running Test 01: Audio Extraction"
echo "========================================"
python3 test_01_audio_extraction.py

echo ""
echo "========================================"
echo "Running Test 02: Gemini Transcription"
echo "========================================"
python3 test_02_gemini_transcription.py

echo ""
echo "========================================"
echo "Running Test 03: Regex Patterns"
echo "========================================"
python3 test_03_regex_patterns.py

echo ""
echo "========================================"
echo "Running Test 04: Full Pipeline"
echo "========================================"
python3 test_04_full_pipeline.py

echo ""
echo "========================================"
echo "All tests completed!"
echo "========================================"
