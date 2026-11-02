"""Reuse every PR70 image safety assertion, then audit Stage 4 font/baseline."""
import contextlib
import io
import json
from pathlib import Path
import sys
r=Path(__file__).resolve().parents[1]
checker=(r/'../wren-desktop/tools/analyze_elf.py').resolve()
sys.argv=[str(checker),str(r/'build-pico/wren_desktop_flash.elf')]
scope={}
with contextlib.redirect_stdout(io.StringIO()):exec(compile(checker.read_text(),str(checker),'exec'),scope)
layout=scope['result']; symbols=scope['symbols']; sections=scope['sections']
baseline=json.loads((r/'../wren-desktop/results/flash-layout.json').read_text())
font=symbols['font_bytes']; descriptor=symbols['kj_misaki8']
assert font['size']==71718 and 0x10000000<=font['address']<font['address']+font['size']<=0x10200000
assert descriptor['size']==24 and 0x10000000<=descriptor['address']<0x10200000
assert layout['desktop_state']['size']==baseline['desktop_state']['size']==34284
layout['font_flash']=font; layout['font_descriptor_flash']=descriptor
rom=sum(h['filesz'] for h in layout['headers'] if 0x10000000<=int(h['paddr'],16)<0x10200000)
base_rom=sum(h['filesz'] for h in baseline['headers'] if 0x10000000<=int(h['paddr'],16)<0x10200000)
layout['ROM_bytes']=rom
layout['baseline_PR70']=dict(elf_sha256=baseline['elf_sha256'],ROM_bytes=base_rom,static_sram=45556,allocator_capacity=135168,stack_reserved=49152,recovery_reserved=8192,total_unassigned=32268)
layout['delta_PR70']=dict(ROM_bytes=rom-base_rom,static_sram=layout['static_sram']-45556,total_unassigned=layout['total_unassigned']-32268)
layout['physical_banks']=[dict(bank='SRAM0-3 main',start='0x20000000',end='0x20040000',bytes=262144,
    unassigned=layout['unassigned_main_ram']),dict(bank='scratch X',start='0x20040000',end='0x20041000',bytes=4096,unassigned=4096),
    dict(bank='scratch Y',start='0x20041000',end='0x20042000',bytes=4096,unassigned=4096)]
free=[0]*4
for address in range(int(layout['heap_limit'],16),int(layout['recovery_start'],16),4):
    free[((address-0x20000000)//4)%4]+=4
layout['main_word_interleaved_banks']=[dict(bank=i,bytes=65536,unassigned=n) for i,n in enumerate(free)]
(r/'results/flash-layout.json').write_text(json.dumps(layout,indent=2)+'\n')
print(json.dumps(layout,indent=2))
