#!/usr/bin/env python3
"""Verify FLASH-resident ELF and account for every SRAM byte; no device IO."""
import json
import hashlib
from pathlib import Path
import struct
import sys
elf=Path(sys.argv[1]); data=elf.read_bytes()
assert data[:7]==b'\x7fELF\x01\x01\x01'
h=struct.unpack_from('<16sHHIIIIIHHHHHH',data)
assert h[1:3]==(2,40)
entry,phoff,shoff=h[4:7]
assert 0x10000000 <= (entry&~1) <0x10200000 and entry&1
headers=[]
for i in range(h[10]):
    kind,offset,va,pa,fs,ms,flags,align=struct.unpack_from('<8I',data,phoff+i*h[9])
    if kind!=1:continue
    assert fs<=ms and offset+fs<=len(data)
    if fs: assert 0x10000000<=pa<pa+fs<=0x10200000, 'file data must originate in flash'
    assert (0x10000000<=va<=va+ms<=0x10200000) or (0x20000000<=va<=va+ms<=0x20042000)
    headers.append(dict(vaddr=hex(va),paddr=hex(pa),filesz=fs,memsz=ms,flags=flags))
sh=[struct.unpack_from('<10I',data,shoff+i*h[11]) for i in range(h[12])]
names=data[sh[h[13]][4]:sh[h[13]][4]+sh[h[13]][5]]
name=lambda table,index:table[index:].split(b'\0',1)[0].decode()
sections=[]; symbols={}
for s in sh:
    n,k,flags,address,offset,size,link,info,align,entsize=s
    if flags&2 and size:
        sections.append(dict(name=name(names,n),address=hex(address),size=size,noload=k==8))
    if k==2:
        strings=data[sh[link][4]:sh[link][4]+sh[link][5]]
        for p in range(offset,offset+size,entsize):
            sn,value,sz,si,other,index=struct.unpack_from('<IIIBBH',data,p)
            if sn and index:symbols[name(strings,sn)]=dict(address=value,size=sz,type=si&15)
for forbidden in ('flash_range_erase','flash_range_program','mock_device_vram','tfb','tile_staging'):
    assert forbidden not in symbols, forbidden
assert not any(n.startswith(('mock_','multicore_launch_core1')) for n in symbols)
# Hardware validation explicitly returns to ROM BOOTSEL for restoration.
# This recovery entry is not a flash erase/program implementation.
addr=lambda n:symbols[n]['address']
heap_start,heap_limit=addr('__end__'),addr('__HeapLimit')
bottom,top=addr('__StackBottom'),addr('__StackTop')
rs,re=addr('__recovery_start'),addr('__recovery_end')
assert heap_limit-heap_start==135168 and addr('__StackLimit')==heap_limit
assert heap_limit<=rs<re==bottom<top==0x20040000 and top-bottom==49152 and re-rs==8192
assert symbols['desktop_state']['size']<35000
assert sum(s['size'] for s in sections if s['name'] in ('.scratch_x','.scratch_y','.stack1_dummy'))==0
static=heap_start-0x20000000
unassigned=rs-heap_limit+8192
assert static+135168+49152+8192+unassigned==270336
result=dict(kind='static FLASH-resident RP2040 link, NOT hardware execution',elf_sha256=hashlib.sha256(data).hexdigest(),entry=hex(entry),headers=headers,sections=sections,
            static_sram=static,desktop_state=symbols['desktop_state'],runtime=symbols['runtime'],heap_start=hex(heap_start),heap_limit=hex(heap_limit),allocator_capacity=135168,
            stack_bottom=hex(bottom),stack_top=hex(top),stack_reserved=49152,recovery_start=hex(rs),recovery_end=hex(re),recovery_reserved=8192,
            unassigned_main_ram=rs-heap_limit,unused_scratch=8192,total_unassigned=unassigned,
            estimated_native_integration=241284,linked_reserved=270336-unassigned,
            difference_from_estimate=(270336-unassigned)-241284)
print(json.dumps(result,indent=2))
