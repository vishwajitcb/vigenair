#!/usr/bin/env python3
"""Test 03: Regex Pattern Alternatives

Tests different regex patterns to find one that works with various response formats.
"""

import os
import re
import sys
import glob

# Sample responses to test against
SAMPLE_RESPONSES = [
    # Expected format
    """Language: English
Confidence: 0.95
```csv
Start,End,Transcription
00:00.000,00:05.500,Hello and welcome to this video.
00:06.000,00:10.200,Today we will learn something new.
```
```vtt
WEBVTT

00:00.000 --> 00:05.500
Hello and welcome to this video.

00:06.000 --> 00:10.200
Today we will learn something new.
```""",

    # Format with extra newlines
    """Language: Telugu

Confidence: 0.92

```csv
Start,End,Transcription
00:00.000,00:03.500,నమస్కారం
00:04.000,00:08.200,ఈ వీడియోకి స్వాగతం
```

```vtt
WEBVTT

00:00.000 --> 00:03.500
నమస్కారం

00:04.000 --> 00:08.200
ఈ వీడియోకి స్వాగతం
```""",

    # Format with markdown headers (common variation)
    """**Language:** Hindi
**Confidence:** 0.88

```csv
Start,End,Transcription
00:00.000,00:04.000,नमस्ते दोस्तों
00:04.500,00:09.000,आज हम कुछ नया सीखेंगे
```

```vtt
WEBVTT

00:00.000 --> 00:04.000
नमस्ते दोस्तों

00:04.500 --> 00:09.000
आज हम कुछ नया सीखेंगे
```""",

    # Format with "Language" as a heading
    """Language: Spanish
Confidence: 0.91
```csv
Start,End,Transcription
00:00.000,00:02.500,Hola a todos
```
```vtt
WEBVTT

00:00.000 --> 00:02.500
Hola a todos
```""",

    # No speech detected format
    """Language: Unknown
Confidence: 0.0

The audio does not contain any detectable speech.

```csv
Start,End,Transcription
```

```vtt
WEBVTT
```""",
]

# Current pattern (from config)
CURRENT_PATTERN = r'.*Language: ?(.*)\n*.*Confidence: ?(.*)\n*```csv\n(.*)```\n*```vtt\n(.*)```'

# Alternative patterns to test
ALTERNATIVE_PATTERNS = {
    "current": CURRENT_PATTERN,

    "flexible_whitespace": r'.*?Language:\s*(.+?)\s*\n.*?Confidence:\s*(.+?)\s*\n.*?```csv\s*\n(.*?)```.*?```vtt\s*\n(.*?)```',

    "with_optional_bold": r'.*?\*{0,2}Language:?\*{0,2}\s*(.+?)\s*\n.*?\*{0,2}Confidence:?\*{0,2}\s*(.+?)\s*\n.*?```csv\s*\n(.*?)```.*?```vtt\s*\n(.*?)```',

    "very_flexible": r'Language[:\s]+([^\n]+)\n[\s\S]*?Confidence[:\s]+([^\n]+)\n[\s\S]*?```csv\n([\s\S]*?)```[\s\S]*?```vtt\n([\s\S]*?)```',

    "named_groups": r'(?:Language[:\s*]+)(?P<language>[^\n]+)\n[\s\S]*?(?:Confidence[:\s*]+)(?P<confidence>[^\n]+)\n[\s\S]*?```csv\n(?P<csv>[\s\S]*?)```[\s\S]*?```vtt\n(?P<vtt>[\s\S]*?)```',
}


def test_pattern(pattern_name: str, pattern: str, response: str, index: int):
    """Test a pattern against a response."""
    try:
        result = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if result:
            # Get groups (handle named groups)
            try:
                lang = result.group('language') if 'language' in result.groupindex else result.group(1)
                conf = result.group('confidence') if 'confidence' in result.groupindex else result.group(2)
                csv_content = result.group('csv') if 'csv' in result.groupindex else result.group(3)
                vtt_content = result.group('vtt') if 'vtt' in result.groupindex else result.group(4)

                return True, {
                    'language': lang.strip(),
                    'confidence': conf.strip(),
                    'csv_length': len(csv_content),
                    'vtt_length': len(vtt_content)
                }
            except:
                return True, {'error': 'Could not extract groups'}
        else:
            return False, None
    except Exception as e:
        return False, {'error': str(e)}


def load_real_responses():
    """Load actual responses from test_02 if available."""
    responses = []
    for f in glob.glob('/tmp/transcription_response_*.txt'):
        with open(f, 'r') as file:
            responses.append((os.path.basename(f), file.read()))
    return responses


if __name__ == "__main__":
    print("=" * 60)
    print("TEST 03: Regex Pattern Alternatives")
    print("=" * 60)

    # Test with sample responses
    print("\n--- Testing with SAMPLE responses ---\n")

    pattern_scores = {name: 0 for name in ALTERNATIVE_PATTERNS}

    for i, response in enumerate(SAMPLE_RESPONSES):
        print(f"Sample Response #{i + 1}:")
        # Show first line
        first_line = response.split('\n')[0][:50]
        print(f"  First line: {first_line}...")

        for pattern_name, pattern in ALTERNATIVE_PATTERNS.items():
            passed, info = test_pattern(pattern_name, pattern, response, i)
            if passed:
                pattern_scores[pattern_name] += 1
                if pattern_name == "current":
                    print(f"    [PASS] {pattern_name}")
            else:
                if pattern_name == "current":
                    print(f"    [FAIL] {pattern_name}")

        print()

    print("\n--- Pattern Scores (sample responses) ---")
    for name, score in sorted(pattern_scores.items(), key=lambda x: -x[1]):
        total = len(SAMPLE_RESPONSES)
        pct = (score / total) * 100
        print(f"  {name}: {score}/{total} ({pct:.0f}%)")

    # Test with real responses if available
    real_responses = load_real_responses()
    if real_responses:
        print("\n" + "=" * 60)
        print("--- Testing with REAL responses from test_02 ---\n")

        for filename, response in real_responses:
            print(f"File: {filename}")

            for pattern_name, pattern in ALTERNATIVE_PATTERNS.items():
                passed, info = test_pattern(pattern_name, pattern, response, 0)
                status = "PASS" if passed else "FAIL"
                if passed:
                    print(f"  [{status}] {pattern_name}: lang={info.get('language', 'N/A')[:20]}")
                else:
                    print(f"  [{status}] {pattern_name}")

            print()
    else:
        print("\nNo real responses found. Run test_02 first to generate them.")

    # Recommend best pattern
    print("\n" + "=" * 60)
    print("RECOMMENDATION")
    print("=" * 60)

    best_pattern_name = max(pattern_scores.items(), key=lambda x: x[1])[0]
    print(f"\nBest performing pattern: {best_pattern_name}")
    print(f"\nPattern:")
    print(f"  {ALTERNATIVE_PATTERNS[best_pattern_name]}")

    if best_pattern_name != "current":
        print("\nSuggested change in config.py:")
        print(f"  TRANSCRIBE_AUDIO_PATTERN = r'{ALTERNATIVE_PATTERNS[best_pattern_name]}'")
