# SPDX-License-Identifier: Apache-2.0
"""On-device repeatable matrix and five-minute soak; no output in game loop."""
import gc
import shooter


def matrix(console, frames=300, assets='star_runner_assets', target_fps=0,
           gc_interval=4):
    """Six required modes plus both EXTREME OAM sizes. Results also returned."""
    results = []
    for mode in ('BASE', 'PSG', 'PCM', 'FULL', 'HEAVY', 'EXTREME'):
        for records in ((128, 256) if mode == 'EXTREME' else (128,)):
            gc.collect()
            print('BENCH_BEGIN', mode, records)
            result = shooter.run(console=console, mode=mode, frames=frames,
                                 target_fps=target_fps, sprites=records,
                                 assets=assets, input_fn=lambda: 0,
                                 gc_interval=gc_interval)
            results.append(result)
    return results


def phase1(console, frames=300):
    """Compare with untouched v1: 32 OAM records, no new art/audio, GC/frame."""
    return shooter.run(console=console, mode='BASE', enhanced=False,
                       frames=frames, target_fps=0, gc_interval=1,
                       input_fn=lambda: 0)


def soak(console, duration=300, assets='star_runner_assets'):
    """HEAVY = continuously updated 64 OAM records, all supported sound types."""
    return shooter.run(console=console, mode='HEAVY', duration=duration,
                       target_fps=30, assets=assets, input_fn=lambda: 0)
