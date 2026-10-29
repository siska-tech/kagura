# SPDX-License-Identifier: Apache-2.0
"""Generate original signed-8/48kHz mono PCM and both wavetable voices.

No third-party samples. Run from any directory; output is deterministic.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import wave

RATE = 48000
BPM = 160
STEP_SAMPLES = RATE * 60 // BPM // 4  # 4500 samples: exact sixteenth at 160 BPM
BGM_SECONDS = STEP_SAMPLES * 64 / RATE
# Original melody over V7 -> bVI -> bVII -> I in E: B7, C, D, E.
# Major G# in the last bar supplies the bright borrowed-mode resolution.
LEAD = (
    78, 0, 75, 78, 83, 81, 78, 75, 78, 81, 83, 86, 83, 81, 78, 75,
    79, 76, 72, 76, 79, 81, 83, 79, 84, 83, 79, 76, 79, 76, 74, 72,
    81, 78, 74, 78, 81, 83, 86, 81, 86, 84, 83, 81, 78, 81, 83, 86,
    83, 80, 76, 80, 83, 85, 88, 87, 88, 83, 80, 78, 76, 0, 71, 75,
)
BASS_ROOTS = (35, 36, 38, 40)
CHORDS = ((59, 63, 66, 69), (60, 64, 67, 72),
          (62, 66, 69, 74), (64, 68, 71, 76))


def frequency(note):
    return 440 * 2 ** ((note - 69) / 12)


def pcm(name, seconds):
    result = bytearray(round(seconds * RATE))
    random_state = 1
    for i in range(len(result)):
        t = i / RATE
        random_state = (1664525 * random_state + 1013904223) & 0xFFFFFFFF
        noise = ((random_state >> 16) & 65535) / 32768 - 1
        if name == 'bgm':
            step = (i // STEP_SAMPLES) % 64
            bar, sixteenth = step // 16, step % 16
            local = (i % STEP_SAMPLES) / RATE
            gate = STEP_SAMPLES / RATE * .91
            envelope = min(1, local / .002) * min(1, max(0, (gate - local) / .010))
            note = LEAD[step]
            phase = frequency(note) * local if note else 0
            duty = .25 + .06 * math.sin(2 * math.pi * 6 * t)
            pulse = ((1 if phase % 1 < duty else 0) - duty) * 2
            lead = (pulse * .72 + math.sin(2 * math.pi * phase) * .25
                    + math.sin(4 * math.pi * phase) * .12) * 48 if note else 0
            bass_note = BASS_ROOTS[bar] + (0, 12, 7, 12)[sixteenth % 4]
            bass_phase = (frequency(bass_note) * local) % 1
            bass = (1 - 4 * abs(bass_phase - .5)) * 28
            chord_time = (i % (STEP_SAMPLES * 2)) / RATE
            chord_env = min(1, chord_time / .002) * math.exp(-chord_time * 14)
            chord = sum(math.sin(2 * math.pi * frequency(n) * t)
                        + .2 * math.sin(4 * math.pi * frequency(n) * t)
                        for n in CHORDS[bar][:3]) * 5 * chord_env
            arp_note = CHORDS[bar][(i // (STEP_SAMPLES // 2)) % 4] + 12
            arp = math.sin(2 * math.pi * frequency(arp_note) * local) * 9 * envelope
            beat = (i % (STEP_SAMPLES * 4)) / RATE
            kick = math.sin(2 * math.pi * (45 * beat + 75 * .025 * (1 - math.exp(-beat / .025))))
            kick *= 30 * math.exp(-beat * 28)
            snare = ((noise * 26 + math.sin(2 * math.pi * 180 * beat) * 9)
                     * math.exp(-beat * 34)) if (sixteenth // 4) & 1 else 0
            hat = noise * 11 * math.exp(-chord_time * 130)
            if bar == 3 and sixteenth >= 12:
                hat += noise * 9 * math.exp(-local * 50)  # fill into the loop
            sample = math.tanh(((lead + bass) * envelope + chord + arp + kick + snare + hat) / 75) * 124
        else:
            u = i / max(1, len(result) - 1)
            envelope = min(1, t / .003) * (1 - u) ** 2
            if name == 'explosion':
                sample = (noise * 60 + math.sin(2 * math.pi * (100 * t - 70 * t * u)) * 22) * envelope
            elif name == 'powerup':
                sample = math.sin(2 * math.pi * (400 * t + 1400 * t * u)) * 65 * envelope
            elif name == 'stage':
                note = (64, 67, 71, 76)[min(3, int(u * 4))]
                sample = math.sin(2 * math.pi * frequency(note) * t) * 65 * envelope
            else:
                sample = (math.sin(2 * math.pi * (1800 * t - 1500 * t * u)) * 45 + noise * 18) * envelope
        # Exact zero at both loop/sample boundaries; never reinterpret unsigned.
        fade = min(1, i / 96, (len(result) - 1 - i) / 96)
        ceiling = 120 if name == 'bgm' else 100
        result[i] = max(-ceiling, min(ceiling, round(sample * fade))) & 255
    return bytes(result)


def generate(output, previews=False):
    output.mkdir(parents=True, exist_ok=True)
    manifest = dict(format='signed8-mono', rate=RATE, version=3,
                    music=dict(title='Star Runner - Afterburner', bpm=BPM, bars=4,
                               progression=['B7', 'C', 'D', 'E'], seconds=BGM_SECONDS), samples=[])
    address = 0x400000
    for name, seconds in (('bgm', BGM_SECONDS), ('explosion', .32), ('powerup', .24),
                          ('stage', .40), ('special', .36)):
        data = pcm(name, seconds)
        (output / (name + '.pcm')).write_bytes(data)
        manifest['samples'].append(dict(name=name, file=name + '.pcm', start=address,
                                        end=address + len(data), loop=name == 'bgm',
                                        sha256=hashlib.sha256(data).hexdigest()))
        address = (address + len(data) + 255) & ~255
        if previews:
            with wave.open(str(output / (name + '.wav')), 'wb') as stream:
                stream.setparams((1, 1, RATE, 0, 'NONE', 'not compressed'))
                stream.writeframes(bytes((n + 128) & 255 for n in data))
    # Separate harmonically rich original waveforms, both with zero DC.
    for voice in range(2):
        values = []
        for i in range(32):
            phase = 2 * math.pi * i / 32
            value = (math.sin(phase) * 72 + math.sin(phase * (3 if voice == 0 else 2)) * 24)
            values.append(round(value) & 255)
        (output / ('wave%d.bin' % voice)).write_bytes(bytes(values))
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] /
                        'software/micropython/examples/star_runner_assets')
    parser.add_argument('--wav', action='store_true', help='also write unsigned-8 WAV listening previews')
    args = parser.parse_args()
    result = generate(args.output, args.wav)
    print('Generated %d PCM samples at %dHz in %s' % (len(result['samples']), RATE, args.output))
