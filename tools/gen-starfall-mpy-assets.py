#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Export original STARFALL C artwork/scores; host compiler only, never flash.

python3 tools/gen-starfall-mpy-assets.py [--cc cc]
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cc', default='cc')
    args = p.parse_args()
    source = ROOT / 'software/starfall'
    output = ROOT / 'software/micropython/examples/starfall_assets'
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        exporter = tmp / 'export.c'
        exporter.write_text('''#include "starfall.h"
#include <stdio.h>
int main(void) {
 uint8_t p[SF_PATTERNS*32],m[4096],c[SF_PALETTE_BYTES];
 sf_make_patterns(p);fwrite(p,1,sizeof p,stdout);
 sf_make_palette(c);fwrite(c,1,sizeof c,stdout);
 sf_make_title_map(m,240);fwrite(m,1,sizeof m,stdout);
 sf_make_map(m,180);fwrite(m,1,sizeof m,stdout);
 sf_make_map(m,240);fwrite(m,1,sizeof m,stdout);return 0;
}''')
        exe = tmp / 'export'
        logic = ['game','player','bullet','powerup','enemy','stage','boss','collision','attract','renderer','assets']
        subprocess.run([args.cc,'-std=c11','-O2','-I',str(source),str(exporter),
                        *[str(source/(n+'.c')) for n in logic],'-o',str(exe)],check=True)
        payload = subprocess.check_output([str(exe)])
    (output/'video.bin').write_bytes(payload)
    scores = (source/'music.c').read_text()
    scores = scores.split('static const Score scores[SF_MUSIC_COUNT]=',1)[1].split(';',1)[0]
    scores = re.sub(r'/\*.*?\*/','',scores,flags=re.S)
    scores = ast.literal_eval(scores.replace('{','[').replace('}',']').replace('false','False').replace('true','True'))
    data = '# SPDX-License-Identifier: Apache-2.0\n# Generated from software/starfall/music.c; do not edit.\nVIDEO_SIZE = %d\nVIDEO_CRC = %d\nSCORES = ' % (len(payload),zlib.crc32(payload)) +repr(tuple(tuple(tuple(x) if isinstance(x,list) else x for x in s) for s in scores))+'\n'
    (ROOT/'software/micropython/examples/starfall_scores.py').write_text(data)
    manifest = {'format':'STARFALL C video: patterns22528/palette160/title4096/map1804096/map2404096',
                'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),
                'sources':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (source/'assets.c',source/'stage.c',source/'music.c')}}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Exported',len(payload),'video bytes and',len(scores),'original scores')


if __name__ == '__main__':
    main()
