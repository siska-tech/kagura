# SPDX-License-Identifier: Apache-2.0
"""Numerical 480p acceptance of glyph caches and reconnect recovery."""
import gc
import json
from array import array


def _read(d, address, length):
    data = bytearray(length)
    d.read_memory_into(address, data)
    return data


def _tile_id(words, upper, col, row):
    index = row * 64 + col
    word = words[index * 2] | words[index * 2 + 1] << 8
    return (word & 1023) | (((upper[index // 8] >> (index % 8)) & 1) << 10)


def _font_codes(path, count):
    codes = array('H')
    with open(path, 'rb') as f:
        if f.read(4) != b'KJ8F':
            raise ValueError('font magic')
        f.read(4)
        while len(codes) < count:
            record = f.read(10)
            if len(record) != 10:
                raise ValueError('not enough nonblank glyphs')
            code = record[0] | record[1] << 8
            if code >= 128 and any(record[2:]):
                codes.append(code)
    return codes


def run(sdk='kagura', japanese='kagura_ja', font_path='/fonts/misaki8.kfnt', mode='qspi'):
    package = __import__(sdk, None, None, ['connect'])
    R = __import__(sdk + '.regs', None, None, ['REG_STATUS'])
    TileScreen = __import__(sdk + '.terminal', None, None, ['TileScreen']).TileScreen
    Video = __import__(sdk + '.video', None, None, ['Video']).Video
    ja = __import__(japanese, None, None, ['Font'])
    d = package.connect(mode=mode, baudrate=5_000_000)
    font = None
    try:
        if d.height != 240:
            raise ValueError('cache capacity test requires the 480p/240-line build')
        font = ja.Font(font_path)
        codes = _font_codes(font_path, 1073)
        screen = TileScreen(d, font)
        screen.initialize()
        # Stream UTF-8 as the real console does; joining 1073 characters
        # first creates large transient arrays on MicroPython's small heap.
        for code in codes:
            screen.feed(chr(code).encode())
        gc.collect()
        screen.flush()
        d.fence()
        words, upper = _read(d, 0x8000, 4096), _read(d, 0x9000, 256)
        for n in range(1073):
            expected = 128 + n if n < 1072 else 63
            if _tile_id(words, upper, n % 40, n // 40) != expected:
                raise AssertionError('terminal tile at glyph %d' % n)
            index = (n // 40) * 64 + n % 40
            if words[index * 2 + 1] & 0x3C:
                raise AssertionError('terminal palette corrupted by tile bit10')
        if sum(screen._refs) != 1072 or screen.glyph_overflow != 1:
            raise AssertionError('terminal capacity/refcounts')
        for index, code in ((1024, codes[896]), (1199, codes[1071])):
            address = 0xB000 + (index - 1024) * 32
            if _read(d, address, 32) != ja._tile(font.glyph(code)):
                raise AssertionError('terminal glyph payload %d' % index)
        print('T1200_CACHE ' + json.dumps(dict(event='terminal', slots=1072,
                                              glyph_overflow=1, last_tile=1199)))
        # The two owners never use their overlapping tile ranges together.
        d.write_reg(R.REG_DISPLAY_CTRL, 0)
        d.commit()
        del screen, words, upper
        gc.collect()
        d.fill(0x8000, 4096)
        d.fill(0x9000, 256)
        d.fill(0xA000, 2048)
        d.write_memory(0x9000, bytes((0x40, 0x80)))
        d.fence()
        layer = ja.TextLayer(d, font, tile_base=1022, tile_count=5,
                             palette=15, map_x=7, width=4, height=1)
        layer.clear()
        layer.text(''.join(chr(code) for code in codes[:3]))
        layer.flush()
        row = _read(d, 0x8000, 128)
        upper = _read(d, 0x9000, 2)
        if [_tile_id(row, upper, c, 0) for c in range(7, 11)] != [1023, 1024, 1025, 1022]:
            raise AssertionError('TextLayer 1023/1024 split')
        if upper != bytes((0x40, 0x83)):
            raise AssertionError('TextLayer changed neighbors')
        if any(((row[c * 2 + 1] >> 2) & 15) != 15 for c in range(7, 11)):
            raise AssertionError('TextLayer palette changed')
        layer2 = ja.TextLayer(d, font, tile_base=1197, tile_count=3,
                              map_y=2, width=4, height=1)
        layer2.clear()
        layer2.text(''.join(chr(code) for code in codes[:2]))
        layer2.flush()
        if _read(d, 0xC5E0, 32) != ja._tile(font.glyph(codes[1])):
            raise AssertionError('last TextLayer glyph')
        class CountIO:
            def __init__(self, base):
                self.base, self.calls = base, 0
            def write(self, *args):
                self.calls += 1
                return self.base.write(*args)
            def readinto(self, *args):
                self.calls += 1
                return self.base.readinto(*args)
            def __getattr__(self, name):
                return getattr(self.base, name)
        raw = d.transport
        count = CountIO(raw)
        d.transport = count
        try:
            try:
                layer2.text(chr(codes[2]))
            except MemoryError:
                pass
            else:
                raise AssertionError('glyph overflow was accepted')
            if count.calls:
                raise AssertionError('overflow performed FPGA I/O')
        finally:
            d.transport = raw
        d.check_errors()
        print('T1200_CACHE ' + json.dumps(dict(event='layer', last_tile=1199,
                                              split=True, palette_preserved=True,
                                              neighbors_preserved=True, overflow_io=0)))
        # Deliberately leave READ_READY and a sticky BAD_ACCESS at disconnect.
        Video(d).tile(1199, b'\x55' * 32)
        d.fence()
        d._address(0xC5E0)
        d.write_reg(R.REG_VRAM_READ_REQUEST, 0)
        d.wait_status(R.STATUS_READ_READY, R.STATUS_READ_READY)
        d.write_reg(R.REG_ID0, 0)
        if d.read_reg(R.REG_ERROR_CODE) != R.ERROR_CODE_BAD_ACCESS:
            raise AssertionError('fault injection failed')
        d.deinit()
        d = None
        d = package.connect(mode=mode, baudrate=5_000_000)
        if d.read_reg(R.REG_STATUS) & R.STATUS_READ_READY:
            raise AssertionError('probe left the old result unread')
        if d.read_reg(R.REG_IRQ_STATUS) & R.IRQ_STATUS_READ_DONE:
            raise AssertionError('probe left READ_DONE unacknowledged')
        if d.read_reg(R.REG_ERROR_CODE) != R.ERROR_CODE_BAD_ACCESS:
            raise AssertionError('probe erased the previous fault')
        d.clear_errors()
        if _read(d, 0xC5E0, 32) != b'\x55' * 32:
            raise AssertionError('fresh read after reconnect')
        result = dict(event='pass', passed=True, slots=1072, last_tile=1199,
                      palette_preserved=True, neighbors_preserved=True,
                      overflow_io=0, reconnect=True, sticky_fault_preserved=True,
                      visual_verified=False, height=d.height)
        print('T1200_CACHE ' + json.dumps(result))
        return result
    finally:
        if font is not None:
            font.close()
        if d is not None:
            d.deinit()
