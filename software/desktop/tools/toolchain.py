"""Capture the tools used by the documented offline validation environment."""
from pathlib import Path
import subprocess
r = Path(__file__).resolve().parents[1]
arm = Path.home() / 'opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc'
cmake = Path.home() / 'opt/cmake-3.31.6-linux-x86_64/bin/cmake'
qemu = r.parents[2] / 'build/c-gem-deps/qemu/root/usr/bin/qemu-arm'
commands = [['gcc', '--version'], ['cmake', '--version'], ['python3', '--version'],
            [str(arm), '--version'], [str(cmake), '--version'], [str(qemu), '--version']]
(r / 'results/toolchain.txt').write_text('\n'.join(
    '$ ' + ' '.join(c) + '\n' + subprocess.check_output(c, text=True) for c in commands))
