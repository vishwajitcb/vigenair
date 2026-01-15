# Transcription Tests

This folder contains tests to debug and fix the audio transcription pipeline.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests
chmod +x run_tests.sh
./run_tests.sh

# Or run individual tests
python3 test_01_audio_extraction.py
python3 test_02_gemini_transcription.py
python3 test_03_regex_patterns.py
python3 test_04_full_pipeline.py
```

## Test Descriptions

### Test 01: Audio Extraction
- Checks that test video exists
- Verifies ffmpeg is installed
- Extracts audio from video
- Validates audio duration

### Test 02: Gemini Transcription
- Tests API key configuration
- Lists available Gemini models
- Tests transcription with multiple models (gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-flash)
- Checks if response matches expected regex pattern
- Saves responses to /tmp for analysis

### Test 03: Regex Patterns
- Tests current regex pattern against sample responses
- Tests alternative patterns that are more flexible
- Tests against real responses from Test 02
- Recommends the best pattern

### Test 04: Full Pipeline
- Runs complete transcription pipeline
- Tests with original prompt/pattern
- Tests with improved prompt/pattern
- Compares results and recommends changes

## Output Files

After running tests, check these files:

- `/tmp/test_extracted_audio.wav` - Extracted audio
- `/tmp/transcription_response_*.txt` - Raw API responses
- `/tmp/original_response.txt` - Response from original prompt
- `/tmp/improved_response.txt` - Response from improved prompt

## Common Issues

1. **Regex doesn't match**: The Gemini response format varies. Use the improved pattern.
2. **Empty transcription**: Audio may have no detectable speech, or response format changed.
3. **Non-English audio**: Current pattern works with any language if format is correct.

## Applying Fixes

After running tests, apply recommended changes to:
- `/service/config/config.py` - Update TRANSCRIBE_AUDIO_PROMPT and TRANSCRIBE_AUDIO_PATTERN
- `/service/audio/audio.py` - Update parsing logic if needed
