#!/usr/bin/env python3
"""Offline linker-boundary and forbidden-symbol checks, independent of CMake."""
import argparse
from pathlib import Path
import subprocess
from verify_image import verify, LOW, HIGH

ap = argparse.ArgumentParser()
ap.add_argument('elf',type=Path)
ap.add_argument('uf2',type=Path)
ap.add_argument('--nm',default='arm-none-eabi-nm')
ap.add_argument('--min-arena',type=int,default=0,help='Require physical allocator capacity for a proposed profile')
args = ap.parse_args()
headers, sections, count = verify(args.elf.read_bytes(),args.uf2.read_bytes())
raw = subprocess.check_output([args.nm,'-n',str(args.elf)],text=True)
symbols = {}
for line in raw.splitlines():
    tokens = line.split()
    if len(tokens)==3:
        symbols[tokens[2]] = int(tokens[0],16)
for name in symbols:
    assert not name.startswith(('flash_','rom_reset_usb_boot','multicore_launch_core1','multicore_fifo_')), name
start, limit, bottom, top = (symbols[key] for key in ('__end__','__HeapLimit','__StackBottom','__StackTop'))
assert LOW <= start < limit <= bottom < top <= HIGH
assert symbols['__StackLimit']==limit
assert symbols['__bss_end__']<=start
assert top-bottom>=48*1024, 'retired 32 KiB stack image is ineligible'
for name, address, size, mode in sections:
    if name.startswith(('.scratch_x','.scratch_y','.stack1')):
        assert size==0, 'scratch/core1 overlap'
    if name=='.stack_dummy':
        assert int(address,16)==bottom and size==top-bottom and mode=='NOLOAD'
print('LAYOUT_PASS malloc_start=%#x malloc_limit=%#x capacity=%d stack_bottom=%#x stack_top=%#x stack_bytes=%d blocks=%d' %
      (start,limit,limit-start,bottom,top,top-bottom,count))
print('No flash-programming, USB-boot reset or core1/FIFO launch symbols linked')
assert limit-start >= args.min_arena, 'insufficient physical arena for requested acceptance profile'
