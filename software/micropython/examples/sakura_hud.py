# SPDX-License-Identifier: Apache-2.0
"""HUD fields with reusable metadata, glyph layouts and transfer views."""
from array import array
import sakura as S
import sakura_hud_viper as K

# Use runtime values: mpy-cross can fold float constants on its host.
# Retain the original formatter on double-float or differently-rounded ports.
_probe = 16777217
FLOAT32 = _probe / 1048576 == 16.0
_probe = 1221591
FLOAT32 = FLOAT32 and '%.2f' % (_probe / 1048576) == '1.17'
del _probe


class Hud:
    def __init__(self, demo):
        self.demo = demo
        self.text = tx = demo.text
        self.integer_mb = FLOAT32 and 'hudround' in demo.opt
        self.fine = 'hudglyph' in demo.opt
        self.meta, self.glyphs, self.oldmeta, self.oldglyphs = [], [], [], []
        rows = ((('KAGURA-9', S.C_TEXT), (S.TITLE, S.C_NOTE), (16, S.C_GOOD)),
                ((S.LABELS[0], S.C_LABEL), ('256', S.C_TEXT), (S.LABELS[1], S.C_LABEL),
                 (16, S.C_GOOD), (S.LABELS[2], S.C_LABEL), (16, S.C_GOOD),
                 ('PSRAM', S.C_LABEL), (48, S.C_TEXT), (16, S.C_GOOD)))
        for fields in rows:
            meta, data = [], bytearray()
            for text, colour in fields:
                offset = len(data)
                if isinstance(text, int):
                    data.extend(bytes(4 * text))
                    count = width = 0
                else:
                    layout, width = tx.layout(text)
                    data.extend(layout)
                    count = len(layout) // 4
                meta.extend((0, count, colour, offset, width))
            self.meta.append(array('i', meta))
            self.glyphs.append(data)
            previous = array('i', meta)
            previous[1] = -1
            self.oldmeta.append(previous)
            self.oldglyphs.append(bytearray(len(data)))
        self.meta[0][0] = 3
        self.meta[0][5] = 3 + self.meta[0][4] + 6
        self.gaps = (0, 2, 6, 2, 6, 2, 6, 3)
        # A dirty span is packed at offset zero. Cache just 40 lengths rather
        # than allocating two memoryviews for every possible (first, end).
        view = memoryview(tx.packed)
        self.views = tuple(view[:32 * n] for n in range(1, 41))

    def number(self, row, field, value, mode=0, extra=0):
        meta = self.meta[row]
        k = field * 5
        n = K.number_field(self.glyphs[row], self.text.atlas, meta[k + 3], value, mode, extra)
        meta[k + 1], meta[k + 4] = n, n * 4

    def fallback(self, h, row):
        # Very large counters still retain Python's unbounded formatting.
        # Such frames are outside the small-int allocation-free workspace.
        demo = self.demo
        if not hasattr(demo, 'hud_placed'):
            demo.hud_placed = [None, None]
            demo.hud_strips = [self.text.strip, self.text.strip]
        demo.hud_placed[row] = None
        self.oldmeta[row][1] = -1
        return demo.hud_row(row, demo.hud_runs(h, row))

    def update(self, h, row):
        meta = self.meta[row]
        if row == 0:
            value = h['fps10']
            if value < 0 or value > 0x3fffffff:
                return self.fallback(h, row)
            self.number(0, 2, value, 1)
            meta[10] = 317 - meta[14]
            meta[12] = S.C_GOOD if value >= 595 else S.C_BAD
        else:
            overflow, underrun, errors = h['overflow'], h['underrun'], h['errors']
            if (overflow < 0 or overflow > 0x3fffffff or underrun < 0 or underrun > 0x3fffffff
                    or errors < 0 or errors > 0x3fffffff):
                return self.fallback(h, row)
            bytecount, kbs = h['psram_bytes'], h['psram_kbs']
            if (self.integer_mb and 0 <= bytecount <= 0x3fffffff and 0 <= kbs <= 0x3fffffff):
                self.number(1, 7, K.cents(bytecount), 3, kbs)
            else:
                psram = '%.2fMB %dKB/s' % (bytecount / 1048576, kbs)
                if len(psram) > 48:
                    return self.fallback(h, row)
                n = K.ascii_field(self.glyphs[1], self.text.atlas, meta[38], psram)
                meta[36], meta[39] = n, n * 4
            self.number(1, 3, overflow)
            self.number(1, 5, underrun)
            self.number(1, 8, errors, 2)
            meta[17] = S.C_BAD if overflow else S.C_GOOD
            meta[27] = S.C_BAD if underrun else S.C_GOOD
            meta[42] = S.C_BAD if errors or h['line_underrun'] else S.C_GOOD
            x = 3
            for field in range(8):
                k = field * 5
                x += self.gaps[field]
                meta[k] = x
                x += meta[k + 4]
            meta[40] = 317 - meta[44]
        span = K.render(self.text.strip, self.text.atlas, self.glyphs[row], meta,
                        self.oldglyphs[row], self.oldmeta[row], self.text.packed,
                        S.C_BAR if row == 0 else S.C_RULE, self.fine)
        if not span:
            return 0
        first, end = span >> 8, span & 255
        self.demo.d.write_memory((S.TILE_HUD + 40 * row + first) * 32, self.views[end - first - 1])
        return end - first
