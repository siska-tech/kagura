# SPDX-License-Identifier: Apache-2.0
"""Independent linear reference raster and queue-aware framebuffer tests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_driver as T
sys.path.insert(0, str(T.ROOT / "software/micropython/examples"))
from unittest import TestCase, main
from unittest.mock import patch
import random
from math import isqrt
from kagura.framebuffer import TileFramebuffer
from kagura import Kagura, regs as R


class Reference:
    def __init__(self):
        self.p = bytearray(320 * 240)
    def pixel(self, x, y, c):
        if 0 <= x < 320 and 0 <= y < 240:
            self.p[y * 320 + x] = c
    def fill_rect(self, x, y, w, h, c):
        for yy in range(max(0, y), min(240, y + max(0, h))):
            for xx in range(max(0, x), min(320, x + max(0, w))):
                self.pixel(xx, yy, c)
    def line(self, x0, y0, x1, y1, c):
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx, sy = 1 if x1 >= x0 else -1, 1 if y1 >= y0 else -1
        if dx >= dy:
            for n in range(dx + 1):
                self.pixel(x0 + sx * n, y0 + sy * ((n * dy + dx // 2) // dx if dx else 0), c)
        else:
            for n in range(dy + 1):
                self.pixel(x0 + sx * ((n * dx + dy // 2) // dy), y0 + sy * n, c)
    def circle(self, x, y, radius, c):
        # Geometric nearest integer to sqrt(r*r-b*b), no midpoint recurrence.
        for b in range(radius + 1):
            squared = radius * radius - b * b
            a = isqrt(squared)
            if squared - a * a > a:
                a += 1
            if b > a:
                break
            for xx, yy in {(a,b),(b,a),(-a,b),(-b,a),(a,-b),(b,-a),(-a,-b),(-b,-a)}:
                self.pixel(x + xx, y + yy, c)
    def get(self, x, y):
        return self.p[y * 320 + x]
    def blit(self, source, x, y, width, height, key, sx, sy):
        # source(u, v) -> colour; snapshot first, so overlaps are well defined.
        block = {(u, v): source(u, v) for v in range(sy, sy + height) for u in range(sx, sx + width)}
        for (u, v), c in block.items():
            if c != key:
                self.pixel(x + u - sx, y + v - sy, c)
    @staticmethod
    def inside(x, b, rx, ry):
        # Closed form, no extents: nearest pixel by row OR by column rounding.
        x, b = abs(x), abs(b)
        if x > rx or b > ry:
            return False
        if x == 0 or b == 0:
            return True
        return ((2*x-1)**2*ry*ry < 4*rx*rx*(ry*ry-b*b) or
                (2*b-1)**2*rx*rx < 4*ry*ry*(rx*rx-x*x))
    def ellipse(self, cx, cy, rx, ry, c, fill):
        for y in range(max(0, cy - ry), min(240, cy + ry + 1)):
            for x in range(max(0, cx - rx), min(320, cx + rx + 1)):
                dx, dy = x - cx, y - cy
                if not self.inside(dx, dy, rx, ry):
                    continue
                if fill or not all(self.inside(dx + a, dy + b, rx, ry)
                                   for a, b in ((1,0),(-1,0),(0,1),(0,-1))):
                    self.pixel(x, y, c)
    def region(self, x, y):
        old, seen, todo = self.get(x, y), {(x, y)}, [(x, y)]
        while todo:
            px, py = todo.pop()
            for qx, qy in ((px+1,py),(px-1,py),(px,py+1),(px,py-1)):
                if 0 <= qx < 320 and 0 <= qy < 240 and (qx, qy) not in seen and self.get(qx, qy) == old:
                    seen.add((qx, qy)); todo.append((qx, qy))
        return seen
    def paint(self, x, y, c):
        if 0 <= x < 320 and 0 <= y < 240:
            for px, py in self.region(x, y):
                self.pixel(px, py, c)


def decode(buffer):
    image = bytearray(320 * 240)
    for tile in range(1200):
        ox, oy = tile % 40 * 8, tile // 40 * 8
        for yy in range(8):
            for pair in range(4):
                value = buffer[tile * 32 + yy * 4 + pair]
                i = (oy + yy) * 320 + ox + pair * 2
                image[i], image[i + 1] = value >> 4, value & 15
    return image


def linear_source(data, stride):
    return lambda u, v: (data[v * stride // 2 + u // 2] >> (0 if u & 1 else 4)) & 15


def tile_source(data, width):
    def pixel(u, v):
        value = data[((v // 8) * (width // 8) + u // 8) * 32 + (v % 8) * 4 + (u % 8) // 2]
        return (value >> (0 if u & 1 else 4)) & 15
    return pixel


class FramebufferTests(TestCase):
    def setUp(self):
        self.model = T.RegisterModel()
        self.model.ext[R.EXT_SCREEN_HEIGHT] = 240
        self.model.ext[R.EXT_PATTERN_COUNT_L] = 1200 & 255
        self.model.ext[R.EXT_PATTERN_COUNT_H] = 1200 >> 8
        self.d = Kagura(self.model).probe()
        self.fb = TileFramebuffer(self.d)
        self.ref = Reference()
    def clean(self):
        self.fb.initialize()
        self.model.calls.clear()
    def compare(self):
        # Decode raw tile data into an independent linear image.
        self.assertEqual(decode(self.fb.buffer), self.ref.p)
    def sync(self):
        # Adopt the current plane as reference input and start a clean dirty set.
        self.ref.p = decode(self.fb.buffer)
        self.fb.dirty[:] = bytes(1200)
        return bytes(self.fb.buffer)
    def assert_dirty_exact(self, before):
        changed = bytes(int(before[t*32:t*32+32] != bytes(self.fb.buffer[t*32:t*32+32]))
                        for t in range(1200))
        self.assertEqual(bytes(self.fb.dirty), changed)
    def random_plane(self, rng):
        for n in range(38400):
            self.fb.buffer[n] = rng.randrange(256)
    def test_nibbles_corners_tile_boundaries(self):
        self.fb.dirty[:] = bytes(1200)
        for x,y,c in ((0,0,1),(1,0,2),(7,7,3),(8,7,4),(319,0,5),(0,239,6),(319,239,7),(191,199,8),(192,199,9)):
            self.fb.pixel(x,y,c);self.ref.pixel(x,y,c)
        self.assertEqual(self.fb.buffer[0],0x12)
        self.assertEqual(self.fb.pixel(1,0),2)
        self.assertEqual(self.fb.dirty[1199],1)
        self.compare()
    def test_nochange_drawing_and_offscreen(self):
        self.clean()
        for call in (lambda:self.fb.pixel(-1,0,4),lambda:self.fb.pixel(320,240,2),lambda:self.fb.fill(0),lambda:self.fb.fill_rect(-8,-8,8,8,4),lambda:self.fb.rect(0,0,0,1,3)):
            call()
        self.assertIsNone(self.fb.pixel(-1,0))
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.fb.flush()['bytes'],0)
        self.assertEqual(self.model.calls,[])
    def test_validation(self):
        for method,args in ((self.fb.pixel,(0,0,16)),(self.fb.fill,(-1,)),(self.fb.line,(0,0,2.5,3,1)),(self.fb.circle,(0,0,-1,2))):
            with self.assertRaises((ValueError,TypeError)):method(*args)
        with self.assertRaises(RuntimeError):self.fb.flush()
        self.d.height=180
        with self.assertRaises(ValueError):TileFramebuffer(self.d)
        self.d.height=240;self.d.abi=(0,5)
        with self.assertRaises(ValueError):TileFramebuffer(self.d)
    def test_primitives_reference_seeded(self):
        self.model.calls.clear()
        rng=random.Random(1200)
        for n in range(100):
            x,y=rng.randrange(-40,340),rng.randrange(-40,260)
            w,h=rng.randrange(-5,80),rng.randrange(-5,80);c=rng.randrange(16)
            kind=n%6
            if kind==0:
                x1,y1=rng.randrange(-40,340),rng.randrange(-40,260)
                self.fb.line(x,y,x1,y1,c);self.ref.line(x,y,x1,y1,c)
            elif kind==1:
                self.fb.fill_rect(x,y,w,h,c);self.ref.fill_rect(x,y,w,h,c)
            elif kind==2:
                self.fb.rect(x,y,w,h,c)
                if w>0 and h>0:
                    self.ref.fill_rect(x,y,w,1,c);self.ref.fill_rect(x,y+h-1,w,1,c)
                    self.ref.fill_rect(x,y,1,h,c);self.ref.fill_rect(x+w-1,y,1,h,c)
            elif kind==3:
                radius=rng.randrange(35)
                self.fb.circle(x,y,radius,c);self.ref.circle(x,y,radius,c)
            elif kind==4:
                self.fb.hline(x,y,w,c);self.ref.fill_rect(x,y,w,1,c)
            else:
                self.fb.vline(x,y,h,c);self.ref.fill_rect(x,y,1,h,c)
        self.compare()
        self.assertEqual(self.model.calls,[])
    def test_initialize_map_palette_upper_and_unused_cells(self):
        self.fb=TileFramebuffer(self.d,palette=13)
        self.model.memory[:]=b'\xff'*len(self.model.memory)
        self.fb.initialize()
        for row in range(32):
            for col in range(64):
                i=row*64+col
                word=int.from_bytes(self.model.memory[0x8000+i*2:0x8002+i*2],'little')
                high=(self.model.memory[0x9000+i//8]>>(i%8))&1
                if row<30 and col<40:
                    t=row*40+col
                    self.assertEqual((word&1023)|high<<10,t)
                    self.assertEqual(word>>10,13)
                else:self.assertEqual((word,high),(0,0))
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.model.reg[R.REG_DISPLAY_CTRL],3)
        self.assertEqual(self.d.busy,0)
    def test_set_cell_palettes_changes_only_the_palette_field(self):
        with self.assertRaises(RuntimeError):self.fb.set_cell_palettes(bytes(1200))
        self.fb.initialize()
        before=bytes(self.model.memory)
        cells=bytes((t*7+t//40)%16 for t in range(1200))
        self.fb.set_cell_palettes(cells)
        for row in range(32):
            for col in range(64):
                i=row*64+col
                word=int.from_bytes(self.model.memory[0x8000+i*2:0x8002+i*2],'little')
                old=int.from_bytes(before[0x8000+i*2:0x8002+i*2],'little')
                if row<30 and col<40:
                    self.assertEqual(word&1023,old&1023)
                    self.assertEqual(word>>10,cells[row*40+col])
                else:self.assertEqual(word,old)
        self.assertEqual(self.model.memory[0x9000:0x9100],before[0x9000:0x9100])
        self.assertEqual(self.model.memory[:0x8000],before[:0x8000])
        for bad in (bytes(1199),bytes(1199)+b'\x10'):
            with self.assertRaises(ValueError):self.fb.set_cell_palettes(bad)
        self.fb.initialize()
        self.assertTrue(all(int.from_bytes(self.model.memory[0x8000+(r*64+c)*2:0x8002+(r*64+c)*2],'little')>>10==0
                            for r in range(30) for c in range(40)))
        self.assertEqual(self.d.busy,0)
    def test_image256_shows_a_checked_kimg(self):
        import tempfile, image256
        sys.path.insert(0, str(T.ROOT / "software/pico"))
        import send_image
        rng=random.Random(256)
        palette=[0x123]*16+[rng.randrange(4096) for _ in range(240)]
        for p in range(16):palette[p*16]=0x123
        cells=[rng.randrange(16) for _ in range(1200)]
        pixels=bytes(rng.randrange(256) for _ in range(38400))
        data=send_image.frame(palette,cells,pixels)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'p.kimg'
            self.clean()
            for bad in (data[:-1],data+b'\0',data[:100]+bytes((data[100]^1,))+data[101:],b'KIMX'+data[4:]):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):image256.show(self.fb,str(path))
                self.assertEqual(self.model.calls,[])
            path.write_bytes(data)
            image256.show(self.fb,str(path),fade_frames=4)
        self.assertEqual(bytes(self.fb.buffer),pixels)
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.model.memory[:0x8000]+self.model.memory[0xB000:0xC600],pixels)
        self.assertEqual([int.from_bytes(self.model.memory[0x8000+(t//40*64+t%40)*2:][:2],'little')>>10 for t in range(1200)],cells)
        self.assertEqual(list(int.from_bytes(self.model.memory[0x9400+i*2:][:2],'little') for i in range(256)),palette)
        with self.assertRaises(ValueError):image256.show(TileFramebuffer(self.d,palette=1),str(path))
    def test_pattern_count_rejected_before_map_writes(self):
        self.model.ext[R.EXT_PATTERN_COUNT_H]=0
        with self.assertRaises(ValueError):self.fb.initialize()
        self.assertFalse(self.fb.initialized)
        self.assertEqual(sum(self.fb.dirty),1200)
        self.assertEqual(self.model.memory,bytearray(0xC600))
    def test_run_merging_and_split_1023_1024_1199(self):
        self.clean()
        for tile in (1022,1023,1024,1025,1199):
            self.fb.pixel(tile%40*8,tile//40*8,tile%15+1)
        with patch.object(self.d,'write_memory',wraps=self.d.write_memory) as write:
            stats=self.fb.flush()
            self.assertEqual([(a.args[0],len(a.args[1])) for a in write.call_args_list],[(1022*32,64),(0xB000,64),(0xC5E0,32)])
        self.assertEqual((stats['runs'],stats['writes'],stats['tiles'],stats['bytes']),(2,3,5,160))
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.model.memory[0xC5E0:0xC600],self.fb.buffer[-32:])
    def test_partial_write_timeout_no_implicit_replay(self):
        self.clean();self.fb.fill(4)
        original=self.d.write_memory
        def fail(address,data):
            original(address,data[:16])
            raise OSError('timeout after partial write')
        with patch.object(self.d,'write_memory',side_effect=fail) as write:
            with self.assertRaises(OSError):self.fb.flush()
            self.assertEqual(write.call_count,1)
        self.assertEqual(sum(self.fb.dirty),1200)
        self.assertEqual(self.d.busy,0)
        self.assertEqual(self.fb.flush()['tiles'],1200)
        self.assertEqual(self.model.memory[0:32768],self.fb.buffer[:32768])
    def test_gap_merge_opt_in_threshold_and_no_edge_padding(self):
        self.clean()
        for gap, expected in ((0,(4,4)),(1,(3,5)),(2,(2,7))):
            self.fb.dirty[:]=bytes(1200)
            for tile in (0,2,5,1199):self.fb.dirty[tile]=1
            stats=self.fb.flush(max_gap=gap)
            self.assertEqual((stats['runs'],stats['tiles']),expected)
            self.assertEqual(stats['bytes'],expected[1]*32)
            self.assertEqual(stats['fences'],expected[0])
            self.assertEqual(sum(self.fb.dirty),0)
        self.model.calls.clear()
        self.assertEqual(self.fb.flush(max_gap=1)['tiles'],0)
        self.assertEqual(self.model.calls,[])
        for invalid in (-1,1199,None,1.5):
            with self.assertRaises(ValueError):self.fb.flush(max_gap=invalid)
        self.assertEqual(self.model.calls,[])
    def test_gap_merge_bank_split_readback_and_buffer_unchanged(self):
        self.clean()
        self.fb.buffer[:]=bytes((i*73+(i>>7)*29)&255 for i in range(38400))
        before=bytes(self.fb.buffer)
        for tile in (1022,1024,1199):self.fb.dirty[tile]=1
        with patch.object(self.d,'write_memory',wraps=self.d.write_memory) as write:
            stats=self.fb.flush(max_gap=1)
        self.assertEqual([(a.args[0],len(a.args[1])) for a in write.call_args_list],
                         [(1022*32,64),(0xB000,32),(0xC5E0,32)])
        self.assertEqual((stats['runs'],stats['writes'],stats['tiles']),(2,3,4))
        self.assertEqual(self.fb.buffer,before)
        self.assertEqual(self.model.memory[1022*32:32768],before[1022*32:32768])
        self.assertEqual(self.model.memory[0xB000:0xB020],before[32768:32800])
    def test_gap_merge_failures_preserve_expanded_unconfirmed_run(self):
        self.clean()
        for stage in ('write','fence','error'):
            self.fb.dirty[:]=bytes(1200)
            self.fb.dirty[1022]=self.fb.dirty[1024]=1
            def fail(*args):
                self.assertGreater(self.d.busy,0)
                self.assertEqual(list(self.fb.dirty[1022:1025]),[1,1,1])
                if stage=='write':
                    self.model.memory[1022*32:1022*32+16]=b'\x55'*16
                raise OSError('injected partial transfer or completion failure')
            owner,name=(self.fb.video,'tiles') if stage=='write' else (self.d,'fence' if stage=='fence' else 'check_errors')
            with patch.object(owner,name,side_effect=fail) as call:
                with self.assertRaises(OSError):self.fb.flush(max_gap=1)
                self.assertEqual(call.call_count,1)
            self.assertEqual(list(self.fb.dirty[1022:1025]),[1,1,1])
            self.assertEqual(self.fb.last_flush['tiles'],0)
            self.assertEqual(self.d.busy,0)
            # Explicit retry after the fault is removed, never implicit replay.
            self.assertEqual(self.fb.flush()['tiles'],3)
    def test_gap_merge_post_fence_error_keeps_prior_run_confirmed(self):
        self.clean()
        for tile in (0,1022,1024):self.fb.dirty[tile]=1
        fence=self.d.fence;check=self.d.check_errors;completed=[]
        def complete():
            fence();completed.append(1)
        def check_after_fence():
            if len(completed)==2:raise OSError('post-FENCE error')
            check()
        with patch.object(self.d,'fence',side_effect=complete), patch.object(self.d,'check_errors',side_effect=check_after_fence):
            with self.assertRaises(OSError):self.fb.flush(max_gap=1)
        self.assertEqual(self.fb.dirty[0],0)
        self.assertEqual(list(self.fb.dirty[1022:1025]),[1,1,1])
        self.assertEqual(self.fb.last_flush['tiles'],1)
        self.assertEqual(self.d.busy,0)
    def test_fence_failure_keeps_run_dirty_and_prior_run_clean(self):
        self.clean()
        self.fb.pixel(0,0,1);self.fb.pixel(16,0,2)
        original=self.d.fence;calls=[]
        def fail_second():
            calls.append(1)
            if len(calls)==2:raise OSError('FENCE timeout')
            original()
        with patch.object(self.d,'fence',side_effect=fail_second):
            with self.assertRaises(OSError):self.fb.flush()
        self.assertEqual(list(self.fb.dirty[:3]),[0,0,1])
        self.assertEqual(self.fb.last_flush['tiles'],1)
        self.assertEqual(self.d.busy,0)
    def test_initialize_failure_and_explicit_recovery(self):
        with patch.object(self.d,'write_memory',side_effect=OSError('map write interrupted')):
            with self.assertRaises(OSError):self.fb.initialize()
        self.assertFalse(self.fb.initialized)
        self.assertEqual(self.model.reg[R.REG_DISPLAY_CTRL],0)
        self.assertEqual(self.d.busy,0)
        self.fb.initialize()
        self.assertTrue(self.fb.initialized)
    def test_memory_error_before_io_and_flush_preserves_dirty(self):
        self.model.calls.clear()
        with patch('kagura.framebuffer.bytearray',side_effect=MemoryError,create=True):
            with self.assertRaises(MemoryError):TileFramebuffer(self.d)
        self.assertEqual(self.model.calls,[])
        self.clean();self.fb.pixel(0,0,1)
        with patch.object(self.fb.video,'tiles',side_effect=MemoryError):
            with self.assertRaises(MemoryError):self.fb.flush()
        self.assertEqual(self.fb.dirty[0],1)
        self.assertEqual(self.d.busy,0)
    def test_diagnostic_scene_a_all_indices_unique_even_corners(self):
        sys.path.insert(0,str(T.ROOT/'software/micropython/examples'))
        import framebuffer_diagnostic as diagnostic
        self.clean()
        scene=diagnostic.Session.__new__(diagnostic.Session)
        scene.fb,scene.d=self.fb,self.d
        with patch.dict(sys.modules,{'framebuf':T.types.SimpleNamespace(FrameBuffer=__import__('viper_emulator').MonoFont,MONO_HLSB=3)}):
            scene.scene('A')
        tiles={bytes(self.fb.buffer[n*32:(n+1)*32]) for n in range(1200)}
        self.assertEqual(len(tiles),1200)
        # L's bottom stroke must stay intact above the tile index-code rows.
        for y in (0,232):
            self.assertEqual([self.fb.pixel(x,y+5) for x in (4,5,6)],[1,1,1])
        self.assertEqual([self.fb.pixel(x,5) for x in (0,1,2)],[0,1,0])
        for n in range(1200):
            code=sum((self.fb.pixel(n%40*8+bit%6,n//40*8+6+bit//6)==1)<<bit for bit in range(11))
            self.assertEqual(code,n)

    def test_diagnostic_scenes_fgh_match_python_and_reference_parts(self):
        import framebuffer_diagnostic as diagnostic
        import kagura.framebuffer as module
        python=TileFramebuffer(self.d);python.set_viper(False)
        for name in 'FGH':
            outputs=[]
            for fb in (python,self.fb):
                fb.fill(0);fb.dirty[:]=bytes(1200)
                outputs.append(diagnostic.draw_scene(fb,name,module))
            self.assertEqual(self.fb.buffer,python.buffer,name)
            self.assertEqual(self.fb.dirty,python.dirty,name)
            self.assertEqual(outputs[0],outputs[1])
        extra=outputs[1]
        self.assertTrue(all(extra['paint_results']) and extra['same_color_noop'],extra)
        self.assertLess(max(extra['paint_peaks']),64)
        # Scene F: keyed gem leaves the stripe colour; clipped corners stay in range.
        badge,gem=diagnostic.icons(module)
        self.ref.p=bytearray(76800)
        for x in range(0,320,16):self.ref.fill_rect(x,0,8,240,8)
        for n in range(14):self.ref.blit(linear_source(gem[0],16),3+22*n,49,16,16,0,0,0)
        python.fill(0);diagnostic.draw_scene(python,'F',module)
        image=decode(python.buffer)
        for yy in range(49,65):
            for xx in range(0,320):
                self.assertEqual(image[yy*320+xx],self.ref.p[yy*320+xx],(xx,yy))

    def test_benchmark_samples_bounded_and_percentile_explicit(self):
        sys.path.insert(0,str(T.ROOT/'software/micropython/examples'))
        from framebuffer_benchmark import Samples
        values=Samples()
        for n in range(10000):values.append(n)
        stats=values.stats()
        self.assertEqual(len(values.values),256)
        self.assertEqual(stats['count'],10000)
        self.assertEqual(stats['mean_us'],4999.5)
        self.assertEqual(stats['max_us'],9999)
        self.assertEqual(stats['p95_recent_us'],9987)

    def test_mark_dirty_clips_direct_edits(self):
        self.clean();self.fb.buffer[-1]=0xAF
        self.fb.mark_dirty(319,239,8,8)
        self.assertEqual(sum(self.fb.dirty),1)
        self.assertEqual(self.fb.flush()['bytes'],32)

    # --- blit -----------------------------------------------------------------
    def test_blit_linear_and_tile_sources_reference_seeded(self):
        from kagura.framebuffer import GS4_HMSB, TILE4
        rng=random.Random(4096)
        self.random_plane(rng)
        for n in range(60):
            before=self.sync()
            if n%2:
                w,h=rng.randrange(1,70),rng.randrange(1,50)
                stride=w+(w&1)+2*rng.randrange(3)
                data=bytes(rng.randrange(256) for _ in range((stride*h+1)//2))
                source=(data,w,h,GS4_HMSB,stride);pixel=linear_source(data,stride)
            else:
                w,h=8*rng.randrange(1,9),8*rng.randrange(1,7)
                data=bytes(rng.randrange(256) for _ in range(w*h//2))
                source=(data,w,h,TILE4);pixel=tile_source(data,w)
            sx,sy=rng.randrange(w),rng.randrange(h)
            width=None if n%3==0 else rng.randrange(-2,w+4)
            height=None if n%5==0 else rng.randrange(-2,h+4)
            # Bias half the positions onto the tile grid to exercise word paths.
            x=rng.randrange(-80,330) if n%4 else 8*rng.randrange(-8,41)
            y=rng.randrange(-60,250) if n%4 else 8*rng.randrange(-6,31)
            key=None if n%3 else rng.randrange(16)
            self.fb.blit(source,x,y,width,height,key,sx,sy)
            rw=w-sx if width is None else min(width,w-sx)
            rh=h-sy if height is None else min(height,h-sy)
            if rw>0 and rh>0:self.ref.blit(pixel,x,y,rw,rh,key,sx,sy)
            self.compare();self.assert_dirty_exact(before)

    def test_blit_self_overlap_memmove_all_directions(self):
        rng=random.Random(77)
        self.random_plane(rng)
        for dx in (-9,-8,-3,-1,0,1,2,8,16):
            for dy in (-8,-2,-1,0,1,5,8):
                for key in (None,6):
                    before=self.sync()
                    sx,sy,x,y=40,40,40+dx,40+dy
                    self.fb.blit(self.fb,x,y,96,64,key,sx,sy)
                    self.ref.blit(lambda u,v,i=bytes(self.ref.p):i[v*320+u],x,y,96,64,key,sx,sy)
                    self.compare();self.assert_dirty_exact(before)
        # Whole-screen scroll by one tile row and by an odd pixel.
        for args in ((0,0,None,None,None,0,8),(0,8,None,None,None,0,0),(1,0,None,None,None,0,0),(0,0,None,None,None,3,1)):
            before=self.sync()
            self.fb.blit(self.fb,*args)
            x,y,_,_,key,sx,sy=args
            self.ref.blit(lambda u,v,i=bytes(self.ref.p):i[v*320+u],x,y,320-sx,240-sy,key,sx,sy)
            self.compare();self.assert_dirty_exact(before)

    def test_blit_between_framebuffers_and_unchanged_copy_is_clean(self):
        other=TileFramebuffer(self.d);other.set_viper(False)
        rng=random.Random(9)
        for n in range(38400):other.buffer[n]=rng.randrange(256)
        self.fb.blit(other,0,0)
        self.assertEqual(self.fb.buffer,other.buffer)
        self.fb.dirty[:]=bytes(1200)
        for args in ((0,0),(8,8,64,64,None,8,8),(3,5,50,40,None,3,5),(0,0,None,None,4)):
            self.fb.blit(other,*args)
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.fb.buffer,other.buffer)

    def test_blit_nibbles_and_boundary_tiles_1023_1024_1199(self):
        from kagura.framebuffer import GS4_HMSB
        self.fb.fill(5);before=self.sync()
        data=bytes((0x12,0x34,0x56))  # 3x2 odd width, stride 4 pixels
        self.fb.blit((data[:2]+data[:2],3,2,GS4_HMSB,4),190,206)
        self.ref.blit(linear_source(data[:2]+data[:2],4),190,206,3,2,None,0,0)
        for x,y in ((183,200),(311,231),(-1,-1),(318,238)):
            self.fb.blit((bytes([0xAB]*8),4,4,GS4_HMSB),x,y,None,None,0xB)
            self.ref.blit(linear_source(bytes([0xAB]*8),4),x,y,4,4,0xB,0,0)
        self.compare();self.assert_dirty_exact(before)
        self.assertEqual(self.fb.pixel(193,206),5)  # odd-width image keeps neighbour
        for tile in (1023,1024,1199):self.assertEqual(self.fb.dirty[tile],1)

    def test_blit_validation_and_noops(self):
        from kagura.framebuffer import GS4_HMSB, TILE4
        image=(bytes(8),4,4,GS4_HMSB)
        bad=(((bytes(7),4,4,GS4_HMSB),0,0),((bytes(8),4,4,GS4_HMSB,5),0,0),
             ((bytes(8),4,4,GS4_HMSB,2),0,0),((bytes(32),8,9,TILE4),0,0),
             ((bytes(31),8,8,TILE4),0,0),((bytes(32),8,8,TILE4,8),0,0),
             ((bytes(8),4,4,3),0,0),(bytes(8),0,0),((list(bytes(8)),4,4,GS4_HMSB),0,0),
             (image,0,0,None,None,16),(image,0,0,None,None,-1),(image,0,0,None,None,None,-1),
             (image,0.5,0),(image,0,0,2.0),((bytes(8),-4,4,GS4_HMSB),0,0))
        self.clean()
        for args in bad:
            with self.assertRaises((ValueError,TypeError),msg=args):self.fb.blit(*args)
        for args in ((image,320,0),(image,-4,0),(image,0,240),(image,0,-4),(image,0,0,0),
                     (image,0,0,None,-3),(image,0,0,None,None,None,4),(image,-(1<<70),0,1<<71),
                     ((b'',0,0,GS4_HMSB),5,5)):
            self.fb.blit(*args)
        self.assertEqual(sum(self.fb.dirty),0)
        self.assertEqual(self.fb.buffer,bytearray(38400))
        self.assertEqual(self.model.calls,[])

    # --- ellipse --------------------------------------------------------------
    def test_ellipse_reference_seeded_outline_and_fill(self):
        rng=random.Random(321)
        for n in range(70):
            before=self.sync()
            args=(rng.randrange(-60,380),rng.randrange(-60,300),rng.randrange(70),
                  rng.randrange(70),rng.randrange(16),bool(n&1))
            self.fb.ellipse(*args);self.ref.ellipse(*args)
            self.compare();self.assert_dirty_exact(before)

    def test_ellipse_equals_circle_when_radii_match(self):
        other=TileFramebuffer(self.d);other.set_viper(False)
        for radius in list(range(0,40))+[63,64,100,159,160,200,250]:
            self.fb.fill(0);other.fill(0)
            self.fb.ellipse(150,110,radius,radius,9);other.circle(150,110,radius,9)
            self.assertEqual(self.fb.buffer,other.buffer,radius)

    def test_ellipse_degenerate_symmetry_corners_and_repeat(self):
        for args in ((10,10,0,0,3,False),(20,20,0,5,4,False),(40,20,6,0,5,True),
                     (0,0,40,30,6,False),(319,0,40,30,7,True),(0,239,25,60,8,False),
                     (319,239,60,25,9,True),(160,120,1,1,10,False),(160,120,1,8,11,True)):
            before=self.sync()
            self.fb.ellipse(*args);self.ref.ellipse(*args)
            self.compare();self.assert_dirty_exact(before)
            self.fb.dirty[:]=bytes(1200);self.fb.ellipse(*args)
            self.assertEqual(sum(self.fb.dirty),0)
        # Quadrant symmetry about a centre with all four quadrants on screen.
        for rx,ry in ((37,11),(11,37),(50,50),(3,90)):
            self.fb.fill(0);self.fb.ellipse(160,120,rx,ry,1)
            for y in range(120-min(ry,119),120+min(ry,119)+1):
                for x in range(160-rx,160+rx+1):
                    v=self.fb.pixel(x,y)
                    self.assertEqual(v,self.fb.pixel(320-x,y));self.assertEqual(v,self.fb.pixel(x,240-y))

    def test_ellipse_large_values_offscreen_and_validation(self):
        before=self.sync()
        for args in ((1<<70,0,5,5,1,False),(-(1<<70),100,(1<<31)-1,3,1,False),
                     (100,-1000,10,999,2,True),(500,120,179,10,3,False)):
            self.fb.ellipse(*args)
        self.assertEqual(sum(self.fb.dirty),0)
        # Huge radii whose arcs cross the screen: exact big-integer fallback.
        for args in ((160,(1<<30)+100,(1<<31)-1,1<<30,4,False),(-(1<<30)+200,120,1<<30,90,5,True),
                     (160,120,400,300,6,False),(160,120,700,20,7,False)):
            before=self.sync()
            self.fb.ellipse(*args);self.ref.ellipse(*args)
            self.compare();self.assert_dirty_exact(before)
        for args in ((0,0,-1,2,1),(0,0,2,-1,1),(0,0,2,2,16),(0,0,1<<31,2,1),(0,0,2,2,1,'yes'),(0.0,0,2,2,1)):
            with self.assertRaises((ValueError,TypeError),msg=args):self.fb.ellipse(*args)

    def test_ellipse_outline_painted_inside_equals_fill(self):
        other=TileFramebuffer(self.d);other.set_viper(False)
        for rx,ry in ((5,3),(30,12),(12,30),(70,50),(2,9)):
            self.fb.fill(0);self.fb.ellipse(150,110,rx,ry,3)
            self.assertTrue(self.fb.paint(150,110,3))
            other.fill(0);other.ellipse(150,110,rx,ry,3,True)
            self.assertEqual(self.fb.buffer,other.buffer,(rx,ry))

    # --- paint ----------------------------------------------------------------
    def test_paint_shapes_match_reference_and_stats(self):
        import framebuffer_shapes as shapes
        for name in shapes.NAMES:
            seed=shapes.prepare(self.fb,name)
            before=self.sync()
            self.assertTrue(self.fb.paint(*seed,7),name)
            self.ref.paint(*seed,7)
            self.compare();self.assert_dirty_exact(before)
            stats=self.fb.last_paint;old=decode(before)
            self.assertEqual(stats['pixels'],sum(1 for n in range(76800) if old[n]!=self.ref.p[n]))
            self.assertTrue(stats['complete']);self.assertEqual(stats['dropped'],0)
            self.assertLessEqual(stats['peak'],stats['capacity'])

    def test_paint_noops_and_random_regions(self):
        self.clean()
        for args in ((-1,0,3),(0,-1,3),(320,0,3),(0,240,3),(5,5,0),(1<<70,0,1)):
            self.assertTrue(self.fb.paint(*args))
        self.assertEqual(sum(self.fb.dirty),0);self.assertEqual(self.model.calls,[])
        for args in ((0,0,16),(0.0,0,1),(0,0,-1)):
            with self.assertRaises((ValueError,TypeError)):self.fb.paint(*args)
        rng=random.Random(2024)
        for n in range(6):
            for k in range(38400):
                self.fb.buffer[k]=rng.choice((0x00,0x01,0x10,0x11,0x22,0x02,0x20))
            seed=rng.randrange(320),rng.randrange(240)
            before=self.sync()
            self.fb.paint(*seed,9);self.ref.paint(*seed,9)
            self.compare();self.assert_dirty_exact(before)

    def test_paint_overflow_partial_state_is_consistent(self):
        import framebuffer_shapes as shapes
        for capacity in (2,5,16):
            for name in ('maze','comb','noise'):
                self.fb.paint_capacity=capacity
                seed=shapes.prepare(self.fb,name)
                before=self.sync()
                region=self.ref.region(*seed)
                self.assertFalse(self.fb.paint(*seed,7),(name,capacity))
                stats=self.fb.last_paint
                self.assertFalse(stats['complete']);self.assertGreater(stats['dropped'],0)
                self.assertGreater(stats['compactions'],0);self.assertLessEqual(stats['peak'],capacity)
                after=decode(self.fb.buffer);old=decode(before)
                changed={(n%320,n//320) for n in range(76800) if after[n]!=old[n]}
                self.assertTrue(changed and changed<region)
                self.assertTrue(all(after[y*320+x]==7 for x,y in changed))
                self.assertIn(seed,changed)
                self.assert_dirty_exact(before)
        self.fb.paint_capacity=1
        with self.assertRaises(ValueError):self.fb.paint(*shapes.prepare(self.fb,'box8'),3)

    def test_paint_memory_error_before_any_change(self):
        import kagura.framebuffer as module
        self.fb.fill(0);self.fb.fill_rect(10,10,30,30,2)
        before=self.sync()
        self.fb.paint_capacity=600
        with patch.object(module,'array',side_effect=MemoryError):
            with self.assertRaises(MemoryError):self.fb.paint(20,20,5)
        self.assertEqual(bytes(self.fb.buffer),before);self.assertEqual(sum(self.fb.dirty),0)
        self.assertIsNone(self.fb._paint_stack)
        self.assertTrue(self.fb.paint(20,20,5))
        self.assertEqual(len(self.fb._paint_stack),600)
        # The stack is reused: later paints allocate nothing new.
        stack=self.fb._paint_stack
        self.fb.paint(0,0,4);self.assertIs(self.fb._paint_stack,stack)

    def test_new_primitives_mixed_seeded_reference(self):
        from framebuffer_viper_cases import LINEAR, TILES, GS4_HMSB, TILE4
        rng=random.Random(1200)
        for n in range(45):
            before=self.sync()
            kind=n%3;c=rng.randrange(16)
            if kind==0:
                args=(rng.randrange(-40,360),rng.randrange(-40,280),rng.randrange(50),rng.randrange(50),c,rng.random()<.5)
                self.fb.ellipse(*args);self.ref.ellipse(*args)
            elif kind==1:
                tiles=rng.random()<.5
                source=(TILES,16,16,TILE4) if tiles else (LINEAR,30,20,GS4_HMSB)
                pixel=tile_source(TILES,16) if tiles else linear_source(LINEAR,30)
                x,y,key=rng.randrange(-20,330),rng.randrange(-20,250),rng.choice((None,c))
                self.fb.blit(source,x,y,None,None,key)
                self.ref.blit(pixel,x,y,source[1],source[2],key,0,0)
            else:
                seed=rng.randrange(320),rng.randrange(240)
                self.fb.paint(*seed,c);self.ref.paint(*seed,c)
            self.compare();self.assert_dirty_exact(before)


class ViperDifferentialTests(FramebufferTests):
    # Inherit every drawing/flush/failure test with the kernel source executed
    # through bounded pointers. Native compilation/execution is a Pico test.
    def setUp(self):
        import kagura.framebuffer as module
        from viper_emulator import load
        self.native_patch=patch.object(module,'_viper',load())
        self.native_patch.start();self.addCleanup(self.native_patch.stop)
        super().setUp()
        self.fb.set_viper(True)

    def test_large_seeded_buffers_and_dirty_identical(self):
        from framebuffer_viper_cases import cases, apply
        python=TileFramebuffer(self.d);python.set_viper(False)
        for name,args in cases(1024):
            apply(python,name,args);apply(self.fb,name,args)
            self.assertEqual(self.fb.buffer,python.buffer,(name,args))
            self.assertEqual(self.fb.dirty,python.dirty,(name,args))
            if name=='paint':self.assertEqual(self.fb.last_paint,python.last_paint)
            python.dirty[:]=bytes(1200);self.fb.dirty[:]=bytes(1200)
        # Every kernel except glyph (text is covered separately) ran natively.
        counts=self.fb.kernel_counts
        self.assertTrue(all(counts[n]>0 for n in (0,1,2,3,5,6,7)),counts)

    def test_paint_overflow_and_compaction_identical_to_python(self):
        import framebuffer_shapes as shapes
        python=TileFramebuffer(self.d);python.set_viper(False)
        for capacity in (2,7,40,2048):
            for name in shapes.NAMES:
                for fb in (python,self.fb):
                    fb.paint_capacity=capacity
                    seed=shapes.prepare(fb,name);fb.dirty[:]=bytes(1200)
                    fb.paint(*seed,12)
                self.assertEqual(self.fb.buffer,python.buffer,(capacity,name))
                self.assertEqual(self.fb.dirty,python.dirty,(capacity,name))
                self.assertEqual(self.fb.last_paint,python.last_paint,(capacity,name))

    def test_blit_fast_paths_by_native_access_width(self):
        import viper_emulator as emulator
        from kagura.framebuffer import GS4_HMSB, TILE4
        tiles=bytes(range(256))*4  # 32x32 TILE4
        linear=bytes(range(256))*2  # 32x32, stride 32 pixels
        def run(*args):
            self.fb.fill(0)
            for key in emulator.ACCESS:emulator.ACCESS[key]=0
            self.fb.blit(*args)
            counts=dict(emulator.ACCESS)
            counts['read4']-=11  # 10 params + kernel counter
            return counts
        # Tile-aligned TILE4: 16 tiles x 8 words (src+dst), bytes only for dirty marks.
        counts=run((tiles,32,32,TILE4),64,64)
        self.assertEqual((counts['read4'],counts['read1'],counts['write1']),(256,0,16))
        # x-aligned, y not: one word per tile row (32 rows x 4 tiles x 2 reads).
        counts=run((linear,32,32,GS4_HMSB),64,67)
        self.assertEqual((counts['read4'],counts['read1']),(256,0))
        # Even shift: byte path (src+dst per byte); odd shift: per pixel.
        self.assertEqual(run((linear,32,32,GS4_HMSB),66,64)['read1'],2*16*32)
        self.assertEqual(run((linear,32,32,GS4_HMSB),65,64)['read1'],2*32*32)
        # A key disables word copies but stays byte-wide for even shifts.
        counts=run((tiles,32,32,TILE4),64,64,None,None,3)
        self.assertEqual((counts['read4'],counts['read1']),(0,2*16*32))
        # An unaligned source view must never be read with ptr32.
        with patch('kagura.framebuffer._aligned',return_value=False):
            self.assertEqual(run((tiles,32,32,TILE4),64,64)['read4'],0)

    def test_native_int32_limits_new_kernels(self):
        import kagura.framebuffer as module
        from viper_emulator import int32_checked
        kernels=module._viper
        checked=T.types.SimpleNamespace(**{name:int32_checked(getattr(kernels,name))
                                           for name in ('blit','ellipse','paint')})
        python=TileFramebuffer(self.d);python.set_viper(False)
        with patch.object(module,'_viper',checked):
            self.fb.set_viper(True)
            # Largest radii accepted natively; the bound keeps error terms < 2**31.
            for args in ((160,120,475,475,3,False),(160,120,2000,40,4,True),(160,120,0,10900,5,False),
                         (-900,120,1000,40,6,False),(-14900,120,15000,0,7,True)):
                limit=9*(args[2]+1)*(args[3]+1)*(args[2]+args[3]+2)
                self.assertLess(limit,0x7FFFFFFF,args)
                before=self.fb.kernel_counts[6]
                self.fb.ellipse(*args);python.ellipse(*args)
                self.assertEqual(self.fb.kernel_counts[6],before+1,args)
                self.assertEqual(self.fb.buffer,python.buffer,args);self.assertEqual(self.fb.dirty,python.dirty)
            for fb in (python,self.fb):
                fb.blit(fb,-5,3,None,None,None,7,0);fb.paint(5,5,1)
            self.assertEqual(self.fb.buffer,python.buffer)
        # The bound is conservative (R=475 peaks near 8*R**3=0.86e9); at R=700
        # the native error terms would really overflow, so it must stay in Python.
        p=self.fb._params
        p[0],p[1],p[2],p[3],p[4],p[5]=160,120,700,700,3,0
        with self.assertRaises(AssertionError):
            checked.ellipse(self.fb.buffer,self.fb.dirty,p,self.fb._kernel_counts)
        # Beyond it the Python path is used, so results still match.
        before=self.fb.kernel_counts[6]
        self.fb.ellipse(160,120,500,500,9);python.ellipse(160,120,500,500,9)
        self.assertEqual(self.fb.kernel_counts[6],before)
        self.assertEqual(self.fb.buffer,python.buffer)

    def test_clipped_text_buffers_dirty_and_repeat_match(self):
        from viper_emulator import MonoFont
        python=TileFramebuffer(self.d);python.set_viper(False)
        framebuf=T.types.SimpleNamespace(FrameBuffer=MonoFont,MONO_HLSB=3)
        with patch.dict(sys.modules,{'framebuf':framebuf}):
            for x,y in ((-7,-7),(0,0),(7,7),(305,233),(319,239),(1<<70,0),(-(1<<70),0)):
                for color in range(16):
                    for repeat in range(2):
                        python.text('ABC abc 123',x,y,color);self.fb.text('ABC abc 123',x,y,color)
                        self.assertEqual(self.fb.buffer,python.buffer)
                        self.assertEqual(self.fb.dirty,python.dirty)
                        self.fb.dirty[:]=bytes(1200);python.dirty[:]=bytes(1200)

    def test_large_integer_fallbacks_avoid_native_overflow(self):
        python=TileFramebuffer(self.d);python.set_viper(False)
        operations=(('line',(-32768,0,1,0,4)),('circle',(32768,100,32768,3)),
                    ('line',(1<<90,0,1<<91,239,2)),
                    ('fill_rect',(-(1<<80),-1,1<<81,3,7)))
        for name,args in operations:
            getattr(python,name)(*args);getattr(self.fb,name)(*args)
            self.assertEqual(self.fb.buffer,python.buffer)
            self.assertEqual(self.fb.dirty,python.dirty)
        # Only fill_rect uses native code in the above cases.
        self.assertEqual(self.fb.kernel_counts[1:4],(0,0,0))

    def test_native_signed_coordinate_and_radius_limits(self):
        python=TileFramebuffer(self.d);python.set_viper(False)
        python.dirty[:]=bytes(1200);self.fb.dirty[:]=bytes(1200)
        for name,args in (('line',(-32767,120,32767,120,6)),
                          ('circle',(32767,120,32767,2))):
            getattr(python,name)(*args);getattr(self.fb,name)(*args)
            self.assertEqual(self.fb.buffer,python.buffer)
            self.assertEqual(self.fb.dirty,python.dirty)
        self.assertGreater(self.fb.kernel_counts[2],0)
        self.assertGreater(self.fb.kernel_counts[3],0)

    def test_switching_and_fallback_unavailable(self):
        import kagura.framebuffer as module
        self.assertTrue(self.fb.viper_enabled)
        self.fb.set_viper(False);self.assertFalse(self.fb.viper_enabled)
        self.fb.pixel(0,0,7)
        with patch.object(module,'_viper',None):
            self.fb.set_viper();self.assertFalse(self.fb.viper_enabled)
            with self.assertRaises(RuntimeError):self.fb.set_viper(True)
        with self.assertRaises(TypeError):self.fb.set_viper('yes')
        self.fb.set_viper(True);self.assertEqual(self.fb.pixel(0,0),7)

    def test_kernel_source_bounded_to_guarded_views(self):
        from framebuffer_viper_cases import run_cases
        raw=bytearray(b'\xa5'*32+bytes(38400)+b'\x5a'*32)
        marks=bytearray(b'\xa5'*32+bytes(1200)+b'\x5a'*32)
        from array import array
        stack=array('I',[0xA5A5A5A5]*8+[0]*self.fb.paint_capacity+[0x5A5A5A5A]*8)
        self.fb.buffer=memoryview(raw)[32:-32]
        self.fb.dirty=memoryview(marks)[32:-32]
        self.fb._paint_stack=memoryview(stack)[8:-8]
        run_cases(self.fb,128)
        # Force compaction and drops inside a tightly guarded 3-entry stack.
        small=array('I',[0xA5A5A5A5]*8+[0]*3+[0x5A5A5A5A]*8)
        self.fb.paint_capacity=3;self.fb._paint_stack=memoryview(small)[8:-8]
        import framebuffer_shapes as shapes
        self.assertFalse(self.fb.paint(*shapes.prepare(self.fb,'maze'),9))
        self.assertEqual(raw[:32],b'\xa5'*32);self.assertEqual(raw[-32:],b'\x5a'*32)
        self.assertEqual(marks[:32],b'\xa5'*32);self.assertEqual(marks[-32:],b'\x5a'*32)
        for guarded in (stack,small):
            self.assertEqual(list(guarded[:8]),[0xA5A5A5A5]*8);self.assertEqual(list(guarded[-8:]),[0x5A5A5A5A]*8)
        self.assertGreater(self.fb.kernel_counts[7],0)


if __name__=='__main__':main(verbosity=2)
