"""Stage4 goldens + unchanged PR70 bounded programming/restoration procedure.
Execution requires NEW separate hardware approval and the original --approved
and exact artifact/backup hashes. --plan-only never accesses a device.
"""
import json
from pathlib import Path
r=Path(__file__).resolve().parents[1]
gold=json.loads((r/'results/goldens.json').read_text())['cases']['0']
original=(r/'../wren-desktop/tools/hardware_run.py').resolve()
text=original.read_text()
old='refs=[0xbe72ff88,0xc91b4078,0x7017406d,0xe89d5ada,0xf07a198f,0xabb5deb8,0xbe72ff88]'
assert text.count(old)==1
text=text.replace(old,'refs=['+','.join('0x'+s for s in gold)+']')
exec(compile(text,str(original),'exec'),{'__file__':str(r/'tools/hardware_run.py'),'__name__':'__main__'})
