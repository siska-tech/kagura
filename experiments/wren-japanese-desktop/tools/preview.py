"""Host-only colour preview of indexed C/Wren framebuffer exports."""
from pathlib import Path
import re
import sys
from PIL import Image
r=Path(__file__).resolve().parents[1]
gfx=(r/'../c-gem-desktop/src/kd_gfx.c').read_text()
part=gfx.split('kd_palette_rgb444[16]',1)[1].split('};',1)[0]
colors=[int(s,16) for s in re.findall(r'0x[0-9a-fA-F]+',part)]
assert len(colors)==16
palette=[component for c in colors for component in (((c>>8)&15)*17,((c>>4)&15)*17,(c&15)*17)]
image=Image.open(sys.argv[1]); image.putpalette(palette+[0]*(768-len(palette)))
image.convert('RGB').resize((960,720),Image.Resampling.NEAREST).save(sys.argv[2])
