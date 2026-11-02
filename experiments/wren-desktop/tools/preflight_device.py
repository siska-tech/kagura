"""Read existing MicroPython/FPGA configuration; no flash writes or resets."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'c-gem-desktop/tools'))
import rp2040_sram_bench as base
p=argparse.ArgumentParser(); p.add_argument('--port'); p.add_argument('--expected-serial'); a=p.parse_args()
base.resolve_device(a)
source=base.CONSOLE_STATE+base.PAUSE+'''import sys,os,machine,json
from kagura import regs as R
print('CONSOLE',_cs)
print('MACHINE',sys.implementation._machine)
print('VERSION',sys.version)
print('CLOCK',machine.freq())
print('RESET_CAUSE',machine.reset_cause())
d=kagura_console.screen.device
print('LINK',type(d.transport).__name__)
print('BAUDRATE',d.transport.baudrate)
print('LANES',d.transport.lanes)
print('PINS',d.transport._io,d.transport._sck,d.transport._cs,d.transport._busy,d.transport._ready,d.transport._irq)
print('ABI_IDS',[d.read_reg(R.REG_ID0+i) for i in range(5)])
print('HEIGHT',d.ext_read(R.EXT_SCREEN_HEIGHT))
print('PATTERNS',d.ext_read(R.EXT_PATTERN_COUNT_L)|(d.ext_read(R.EXT_PATTERN_COUNT_H)<<8))
print('ERROR',d.read_reg(R.REG_ERROR_CODE))
'''
print(base.micropython_exec(a.port,source))
