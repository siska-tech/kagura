"""Byte-exact existing host scenarios with title support disabled/enabled."""
from pathlib import Path
import hashlib
import json
import sys
base,new=map(Path,sys.argv[1:])
rows=[]
for folder in ('scenario','hdmi-ref'):
    before={p.name:p for p in (base/folder).glob('*') if p.is_file()}
    after={p.name:p for p in (new/folder).glob('*') if p.is_file()}
    assert before and before.keys()==after.keys(),folder
    for name in sorted(before):
        data=before[name].read_bytes(); assert data==after[name].read_bytes(),(folder,name)
        rows.append(dict(file=folder+'/'+name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
print(json.dumps(dict(result='ASCII_GUI_BYTE_EXACT',files=rows),indent=2))
