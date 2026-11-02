"""Static ARM ELF/link accounting, not hardware runtime measurements."""
import json
from pathlib import Path
import struct
root=Path(__file__).resolve().parents[1]
result={'kind':'Cortex-M0+ compile/link analysis ONLY; no hardware execution; no SDK/USB in probes'}
for mode in ('core','baseline','japanese'):
    data=(root/f'build-arm/{mode}/analysis.elf').read_bytes()
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',data)
    sh=[struct.unpack_from('<10I',data,h[6]+i*h[11]) for i in range(h[12])]
    names=data[sh[h[13]][4]:sh[h[13]][4]+sh[h[13]][5]]
    name=lambda table,index:table[index:].split(b'\0',1)[0].decode()
    rom=ram=0; sizes=None; symbols={}
    for s in sh:
        if s[2]&2:
            if 0x10000000<=s[3]<0x10200000:rom+=s[5]
            if 0x20000000<=s[3]<0x20042000:
                ram+=s[5]
                if s[1]!=8:rom+=s[5]
        if s[1]==2:
            strings=data[sh[s[6]][4]:sh[s[6]][4]+sh[s[6]][5]]
            for p in range(s[4],s[4]+s[5],s[9]):
                n,v,sz,info,other,index=struct.unpack_from('<IIIBBH',data,p)
                if not n or not index:continue
                label=name(strings,n); symbols[label]=sz
                if label=='kj_type_sizes':
                    sec=sh[index];sizes=struct.unpack_from('<7I',data,sec[4]+v-sec[3])
    assert not any(n in symbols for n in ('malloc','calloc','realloc','_malloc_r','wrenNewVM','mp_init'))
    assert sizes
    result[mode]={'ROM_bytes':rom,'static_RAM_bytes':ram,'sizes':dict(zip(('font','glyph','metrics','target','surface4','decoded','desktop'),sizes)),
                  'font_blob_bytes':symbols.get('font_bytes',0)}
result['native_increment_ROM']=result['japanese']['ROM_bytes']-result['baseline']['ROM_bytes']
result['native_increment_static_RAM']=result['japanese']['static_RAM_bytes']-result['baseline']['static_RAM_bytes']
result['objects']={}
for obj in ('kj_text','font_data','kj_desktop'):
    data=(root/f'build-arm/{obj}.o').read_bytes(); h=struct.unpack_from('<16sHHIIIIIHHHHHH',data)
    sections=[struct.unpack_from('<10I',data,h[6]+i*h[11]) for i in range(h[12])]
    result['objects'][obj]=dict(readonly_bytes=sum(s[5] for s in sections if s[2]&2 and not s[2]&1),
        initialized_RAM_bytes=sum(s[5] for s in sections if s[2]&3==3 and s[1]!=8),
        zeroed_RAM_bytes=sum(s[5] for s in sections if s[2]&3==3 and s[1]==8))
    assert result['objects'][obj]['initialized_RAM_bytes']==result['objects'][obj]['zeroed_RAM_bytes']==0
assert result['japanese']['font_blob_bytes']==71718 and result['native_increment_static_RAM']==0
lines=[]
for p in (root/'build-arm').rglob('*.su'):
    if p.name in ('kj_text.su','kj_desktop.su'):
        lines.extend(p.read_text().splitlines())
(root/'results/arm-stack-frames.txt').write_text('\n'.join(lines)+'\n')
for p in (root/'results').glob('*.map'):
    p.write_text('\n'.join(s.rstrip() for s in p.read_text().splitlines()).rstrip()+'\n')
for p in (root/'results').glob('arm-*.txt'):
    p.write_text('\n'.join(s.rstrip() for s in p.read_text().splitlines()).rstrip()+'\n')
(root/'results/arm-budget.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
