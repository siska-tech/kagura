#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Render the live KAGURA-9 presentation as 320x240 pseudo-256-colour .kimg.

uv run --with pillow --with numpy tools/gen-showcase-assets.py
Use --font/--bold with a locally licensed Japanese font on non-Windows hosts.
No font files are distributed. Captions use the repo's licensed Misaki glyphs.
The ordinary send_image converter enforces 16 colours per 8x8 cell.
"""
import argparse
import colorsys
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import struct
import zlib

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
NAMES = ('opening', 'architecture', 'colour', 'game', 'orchestra', 'create', 'closing')
NAVY, INK, PAPER, CYAN, CORAL = '#07131f', '#102536', '#f3eedc', '#56dccf', '#ff9874'


def fonts(args):
    from PIL import ImageFont
    candidates = [args.font, 'C:/Windows/Fonts/BIZ-UDGothicR.ttc',
                  '/mnt/c/Windows/Fonts/BIZ-UDGothicR.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    regular = next((p for p in candidates if p and Path(p).is_file()), None)
    if regular is None:
        raise SystemExit('Supply --font with a licensed Japanese TrueType/OpenType font')
    bold = args.bold or regular.replace('GothicR', 'GothicB').replace('Regular', 'Bold')
    if not Path(bold).is_file():
        bold = regular
    latin = next((p for p in ('C:/Windows/Fonts/seguisb.ttf', '/mnt/c/Windows/Fonts/seguisb.ttf',
                              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf') if Path(p).is_file()), bold)
    return lambda size, kind='regular': ImageFont.truetype(
        latin if kind == 'latin' else bold if kind == 'bold' else regular, size)


def canvas(number, label, font):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (320, 240))
    pix = image.load()
    for y in range(240):
        for x in range(320):
            glow = max(0, 1 - math.hypot((x - 285) / 260, (y - 145) / 190))
            pix[x, y] = (7 + int(5 * glow), 19 + int(18 * glow), 31 + int(20 * glow))
    d = ImageDraw.Draw(image)
    for x in range(16, 320, 16):
        for y in range(16, 240, 16):
            d.point((x, y), fill='#183344')
    d.rectangle((20, 17, 23, 25), fill=CORAL)
    d.text((30, 14), label, font=font(10, 'latin'), fill=CYAN)
    d.line((20, 224, 300, 224), fill='#284653')
    d.text((20, 228), 'KAGURA-9 / LIVE SHOWCASE', font=font(8, 'latin'), fill='#86a5ad')
    d.text((275, 227), '%02d / 07' % (number + 1), font=font(8, 'latin'), fill=PAPER)
    for i in range(7):
        d.rectangle((198 + i * 10, 231, 203 + i * 10, 233), fill=CORAL if i == number else '#34525c')
    return image, d


def jp(d, xy, text, font, size=14, fill=PAPER, bold=False):
    f = font(size, 'bold' if bold else 'regular')
    box = d.textbbox(xy, text, font=f)
    if box[2] > 306:
        raise ValueError('text leaves slide: ' + text)
    d.text(xy, text, font=f, fill=fill)


def chip(d, x, y, size=70):
    for i in range(8):
        k = 7 + i * (size - 14) // 7
        for box in ((x - 5, y + k, x, y + k + 2), (x + size, y + k, x + size + 5, y + k + 2),
                    (x + k, y - 5, x + k + 2, y), (x + k, y + size, x + k + 2, y + size + 5)):
            d.rectangle(box, fill='#587e86')
    d.rounded_rectangle((x, y, x + size, y + size), 7, fill=INK, outline=CYAN, width=2)
    d.rectangle((x + 12, y + 12, x + size - 12, y + size - 12), outline='#426775')
    d.ellipse((x + 8, y + 8, x + 11, y + 11), fill=CORAL)


def render(name, number, font):
    image, d = canvas(number, ('A CHIP. A WORLD.', 'HOST x FPGA', 'COLOUR, BY DESIGN',
                              'MAKE IT PLAY', 'ALL TOGETHER', 'YOUR TURN', 'THANK YOU')[number], font)
    if name == 'opening':
        d.text((17, 34), 'KAGURA-9', font=font(42, 'latin'), fill=PAPER)
        jp(d, (20, 92), '小さなFPGAに、画と音を。', font, 18, bold=True)
        jp(d, (20, 123), 'HDMIビデオ・サウンドチップ', font, 12, fill=CYAN)
        jp(d, (20, 144), 'MicroPythonで、その力を引き出す。', font, 12)
        chip(d, 246, 160, 42)
        d.text((20, 187), 'Tang Nano 9K + Raspberry Pi Pico', font=font(11, 'latin'), fill='#9cb5bb')
    elif name == 'architecture':
        jp(d, (20, 43), '描画と音を、任せる。', font, 23, bold=True)
        jp(d, (20, 80), 'ホストが指示。FPGAが合成して、HDMIへ。', font, 12)
        for x, w, title, subtitle in ((20, 70, 'PICO', 'MicroPython'), (120, 90, 'FPGA', 'KAGURA-9'), (240, 60, 'HDMI', 'VIDEO + AUDIO')):
            d.rounded_rectangle((x, 115, x + w, 174), 6, fill=INK, outline='#426775')
            d.text((x + 8, 124), title, font=font(17, 'latin'), fill=CYAN if title == 'FPGA' else PAPER)
            d.text((x + 6, 154), subtitle, font=font(8, 'latin'), fill='#9cb5bb')
        for x in (95, 215):
            d.line((x, 141, x + 19, 141), fill=CORAL, width=2)
            d.polygon(((x + 20, 141), (x + 14, 137), (x + 14, 145)), fill=CORAL)
        d.text((91, 105), 'SPI/QSPI', font=font(8, 'latin'), fill=CORAL)
        jp(d, (20, 193), '映像 480p / 720p  +  ステレオ音声 48kHz', font, 11)
    elif name == 'colour':
        jp(d, (20, 43), 'タイルから、色が広がる。', font, 20, bold=True)
        jp(d, (20, 77), '疑似256色で、写真も解説スライドも。', font, 12)
        for row in range(8):
            for col in range(16):
                r, g, b = colorsys.hsv_to_rgb(col / 16, 0.35 + row / 13, 0.95 - row / 24)
                x, y = 20 + col * 17, 107 + row * 8
                d.rectangle((x, y, x + 15, y + 6), fill=(int(r * 255), int(g * 255), int(b * 255)))
        d.text((20, 180), '16 PALETTES x 16 ENTRIES', font=font(11, 'latin'), fill=CYAN)
        jp(d, (20, 200), '8x8セルごとに16色。色0は共通の背景。', font, 10)
    elif name == 'game':
        jp(d, (20, 43), '絵が、ゲームになる。', font, 23, bold=True)
        jp(d, (20, 81), '自機・敵・弾・HUDを重ねる。', font, 13)
        for i in range(38):
            x, y = 20 + (i * 71 % 280), 110 + (i * 29 % 70)
            d.rectangle((x, y, x + 1, y + 1), fill='#7298aa')
        d.polygon(((43, 130), (80, 147), (43, 165), (51, 147)), fill=CYAN)
        d.polygon(((40, 141), (24, 147), (40, 154)), fill=CORAL)
        for x, y in ((213, 127), (246, 151), (278, 126)):
            d.polygon(((x - 10, y - 7), (x + 10, y), (x - 10, y + 7), (x - 4, y)), fill=CORAL)
        for x in (102, 139, 176):
            d.rectangle((x, 146, x + 9, 147), fill=PAPER)
        d.text((20, 184), 'NEXT / PROJECT STARFALL', font=font(11, 'latin'), fill=CYAN)
        jp(d, (20, 202), '6音源のBGMと効果音、装備とボス戦。', font, 11)
    elif name == 'orchestra':
        jp(d, (20, 43), '画も、音も、同時に。', font, 23, bold=True)
        jp(d, (20, 81), '個々の機能が、ひとつの風景になる。', font, 12)
        for x, y, big, small in ((20, 111, '256', 'SPRITE REGISTERS'), (166, 111, '8', 'RASTER ENTRIES'),
                                 (20, 156, '2 ch', 'PCM + SIX VOICES'), (166, 156, '4 MiB', 'PSRAM / COPY')):
            d.rounded_rectangle((x, y, x + 134, y + 39), 5, fill=INK)
            d.text((x + 9, y + 1), big, font=font(20, 'latin'), fill=CYAN)
            d.text((x + 9, y + 26), small, font=font(8, 'latin'), fill='#a6bec0')
        jp(d, (20, 204), 'spriteは16個/走査線。PSRAMは対応構成で。', font, 10)
    elif name == 'create':
        jp(d, (20, 43), '次は、あなたの作品を。', font, 22, bold=True)
        d.rounded_rectangle((20, 91, 300, 165), 5, fill='#051019', outline='#34525c')
        for i, line in enumerate(('import kagura', 'd = kagura.connect()', 'd.write_memory(...)', 'd.commit()')):
            d.text((32, 100 + i * 14), line, font=font(11, 'latin'), fill=CYAN if i < 2 else PAPER)
        jp(d, (20, 179), 'ゲーム、音源、スプライトエディタへ。', font, 12)
        d.text((20, 202), 'github.com/siska-tech/kagura', font=font(11, 'latin'), fill=CORAL)
    else:
        d.text((17, 44), 'KAGURA-9', font=font(42, 'latin'), fill=PAPER)
        jp(d, (20, 108), 'つくる楽しさを、画面の向こうへ。', font, 16, bold=True)
        d.text((20, 153), 'FPGA VIDEO + SOUND / MicroPython SDK', font=font(11, 'latin'), fill=CYAN)
        jp(d, (20, 184), 'Space / N : 次の章     Q : 終了', font, 12)
    return image


def captions(output):
    rows = (('plasma', '色だけで、動かす。', '絵はそのまま。パレットを変えて、光を走らせる。'),
            ('tunnel', '奥行きを、色で描く。', '静止したタイルに、前進するトンネルの錯覚。'),
            ('tesseract', '線が、立体になる。', '4次元の回転と星空。変わったタイルだけを転送。'),
            ('ribbon', '動きの跡を、光にする。', '線の軌跡とパレットがつくる、ネオンのリボン。'))
    data = (ROOT / 'software/micropython/fonts/misaki8.kfnt').read_bytes()
    glyphs = {int.from_bytes(data[i:i + 2], 'little'): data[i + 2:i + 10] for i in range(8, len(data), 10)}
    from PIL import Image
    for name, title, subtitle in rows:
        p = Image.new('L', (320, 24), 2)
        for text, y, colour in ((title, 3, 1), (subtitle, 14, 3)):
            x = 12
            for ch in text:
                code = ord(ch)
                if code not in glyphs:
                    raise ValueError('Misaki caption lacks ' + ch)
                for yy, row in enumerate(glyphs[code]):
                    for xx in range(8):
                        if row & (128 >> xx):
                            p.putpixel((x + xx, y + yy), colour)
                x += 4 if code < 128 else 8
            if x > 308:
                raise ValueError('caption too wide: ' + text)
        raw = bytearray()
        for ty in range(3):
            for tx in range(40):
                for yy in range(8):
                    for xx in range(0, 8, 2):
                        raw.append(p.getpixel((tx * 8 + xx, ty * 8 + yy)) << 4 |
                                   p.getpixel((tx * 8 + xx + 1, ty * 8 + yy)))
        (output / (name + '.caption')).write_bytes(raw)


def scenery(output):
    # Reuse the headless native-kernel/register model used for C parity tests.
    # Only the static load-time background is baked; live petals/audio/COPY
    # remain the ordinary Sakura program on the Pico.
    sys.path.insert(0, str(ROOT / 'software/micropython/tests'))
    import test_sakura as fixture
    d = fixture.Device()
    count = fixture.S.build_scenery(d, bytearray(4096), bytearray(2048), bytearray(4096))
    tiles = bytes(d.memory[256 * 32:(256 + count) * 32])
    tilemap = bytes(d.memory[0x8000:0x9000])
    for name, data in (('scenery', tiles), ('map', tilemap)):
        if hashlib.sha256(data).hexdigest() != fixture.C_SHA256[name]:
            raise ValueError('scenery differs from C golden: ' + name)
    payload = tiles + tilemap
    data = b'SCN1' + struct.pack('<H', count) + payload + struct.pack('<I', zlib.crc32(payload))
    (output / 'sakura.scenery').write_bytes(data)
    return dict(tiles=count, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                tile_sha256=hashlib.sha256(tiles).hexdigest(), map_sha256=hashlib.sha256(tilemap).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font')
    parser.add_argument('--bold')
    parser.add_argument('--output', type=Path, default=ROOT / 'software/micropython/examples/showcase_assets')
    parser.add_argument('--preview', type=Path, default=ROOT / 'build/showcase-preview')
    parser.add_argument('--scenery-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.preview.mkdir(parents=True, exist_ok=True)
    if args.scenery_only:
        path = args.output / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['scenery'] = scenery(args.output)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('SCENERY', manifest['scenery'], flush=True)
        return
    spec = importlib.util.spec_from_file_location('kimg_converter', ROOT / 'software/pico/send_image.py')
    converter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(converter)
    from PIL import Image
    import numpy as np
    font = fonts(args)
    manifest = dict(format='KIMG', size=[320, 240], palette_rule='16 per 8x8 cell; shared colour 0', slides=[])
    for i, name in enumerate(NAMES):
        original = render(name, i, font)
        original.save(args.preview / (name + '-source.png'))
        palette, cells, index = converter.quantize(np.asarray(original, dtype=np.int32))
        data = converter.frame(palette, cells, converter.pack(index))
        (args.output / (name + '.kimg')).write_bytes(data)
        converter.preview(args.preview / (name + '.png'), palette, cells, index)
        manifest['slides'].append(dict(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        print('SLIDE', name, len(data), flush=True)
    captions(args.output)
    manifest['scenery'] = scenery(args.output)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    sheet = Image.new('RGB', (640 * 2, 480 * 4), NAVY)
    for i, name in enumerate(NAMES):
        sheet.paste(Image.open(args.preview / (name + '.png')), (i % 2 * 640, i // 2 * 480))
    sheet.save(args.preview / 'overview.png')
    print('PREVIEW', args.preview / 'overview.png', flush=True)


if __name__ == '__main__':
    main()
