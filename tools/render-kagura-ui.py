# SPDX-License-Identifier: Apache-2.0
"""Export the PC reference surface as PNG; not a hardware HDMI capture."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
import struct
import zlib
root = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'software/micropython/tests'))
import test_driver
sys.path.insert(0,str(root/'software/micropython/examples'))
from kagura.ui import App, Theme, BitmapFont8
from kagura.ui.mock import MockBackend
from kagura_ja import Font


def chunk(kind, data):
    return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data))


out = Path(sys.argv[1]) if len(sys.argv)>1 else root/'build/ui-previews'
out.mkdir(parents=True,exist_ok=True)
with Font(str(root/'software/micropython/fonts/misaki8.kfnt')) as font:
    for name in ('ui_gallery','ui_monitor','ui_studio_mock'):
        backend = MockBackend()
        app = App(backend=backend,theme=Theme(BitmapFont8(font)))
        demo = __import__(name)
        if name == 'ui_monitor': demo.now_us=lambda:0
        update = demo.build(app)
        app.step()
        if update:
            demo.now_us=lambda:1000000
            update(); app.step()
        palette = app.theme.palette
        data = bytearray()
        for y in range(240):
            data.append(0)
            for x in range(320):
                rgb = palette[backend.pixels[y*320+x]]
                data.extend(((rgb>>8)*17,((rgb>>4)&15)*17,(rgb&15)*17))
        png = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',320,240,8,2,0,0,0))
        png += chunk(b'IDAT',zlib.compress(data))+chunk(b'IEND',b'')
        (out/(name+'.png')).write_bytes(png)
        app.close()
        print(out/(name+'.png'))
