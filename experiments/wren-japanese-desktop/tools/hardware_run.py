"""Stage4 goldens + unchanged PR70 bounded programming/restoration procedure.
Execution requires NEW separate hardware approval and the original --approved
and exact artifact/backup hashes. --plan-only never accesses a device.
"""
import json
from pathlib import Path
r=Path(__file__).resolve().parents[1]
def verify_capture(path):
    # Signal-presence sanity only; the original full colour classifier and its
    # thresholds remain unchanged. All visible scenes have these fixed pixels.
    from PIL import Image
    with Image.open(path) as im:
        rgb=im.convert('RGB')
        desk=rgb.getpixel((300*4+2,170*4+2))
        menu=rgb.getpixel((20*4+2,5*4+2))
    assert desk[1]>60 and desk[0]<80 and min(menu)>160,('HDMI signal missing/invalid',desk,menu)
    return dict(desk=desk,menu=menu)
gold=json.loads((r/'results/goldens.json').read_text())['cases']['0']
original=(r/'../wren-desktop/tools/hardware_run.py').resolve()
text=original.read_text()
old='refs=[0xbe72ff88,0xc91b4078,0x7017406d,0xe89d5ada,0xf07a198f,0xabb5deb8,0xbe72ff88]'
assert text.count(old)==1
text=text.replace(old,'refs=['+','.join('0x'+s for s in gold)+']')
assert text.count("'-frames:v','20'")==1
text=text.replace("'-frames:v','20'","'-frames:v','180'") # receiver relock: 3s, not 0.33s
needle="                    s.write(b'n')"
assert text.count(needle)==1
text=text.replace(needle,"                    if index: log('HDMI_SIGNAL '+str(_wj_verify_capture(a.out/f'frame-{index}.png')))\n"+needle)
exec(compile(text,str(original),'exec'),{'__file__':str(r/'tools/hardware_run.py'),'__name__':'__main__','_wj_verify_capture':verify_capture})
