#!/usr/bin/env python3
"""Wrap stereo signed16 little-endian samples emitted by RTL in a WAV file."""
import argparse
from pathlib import Path
import wave

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("raw", type=Path)
parser.add_argument("wav", type=Path)
args = parser.parse_args()
payload = args.raw.read_bytes()
if not payload or len(payload) % 4:
    parser.error("RTL PCM must contain complete stereo signed16 samples")
args.wav.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(args.wav), "wb") as output:
    output.setnchannels(2)
    output.setsampwidth(2)
    output.setframerate(48000)
    output.writeframes(payload)
print(f"WAV: {len(payload) // 4} RTL stereo samples -> {args.wav}")
