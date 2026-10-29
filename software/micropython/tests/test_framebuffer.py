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
        actual = bytearray(320 * 240)
        for tile in range(1200):
            ox, oy = tile % 40 * 8, tile // 40 * 8
            for yy in range(8):
                for pair in range(4):
                    value = self.fb.buffer[tile * 32 + yy * 4 + pair]
                    i = (oy + yy) * 320 + ox + pair * 2
                    actual[i], actual[i + 1] = value >> 4, value & 15
        self.assertEqual(actual, self.ref.p)
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
        from framebuffer_viper_cases import cases
        python=TileFramebuffer(self.d);python.set_viper(False)
        for name,args in cases(1024):
            getattr(python,name)(*args);getattr(self.fb,name)(*args)
            self.assertEqual(self.fb.buffer,python.buffer,(name,args))
            self.assertEqual(self.fb.dirty,python.dirty,(name,args))
            python.dirty[:]=bytes(1200);self.fb.dirty[:]=bytes(1200)
        self.assertGreater(sum(self.fb.kernel_counts),0)

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
        self.fb.buffer=memoryview(raw)[32:-32]
        self.fb.dirty=memoryview(marks)[32:-32]
        run_cases(self.fb,128)
        self.assertEqual(raw[:32],b'\xa5'*32);self.assertEqual(raw[-32:],b'\x5a'*32)
        self.assertEqual(marks[:32],b'\xa5'*32);self.assertEqual(marks[-32:],b'\x5a'*32)


if __name__=='__main__':main(verbosity=2)
