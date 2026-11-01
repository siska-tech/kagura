# SPDX-License-Identifier: Apache-2.0
"""Byte-for-byte comparison with the independently compiled original C game."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_driver
ROOT = test_driver.ROOT
sys.path.insert(0,str(ROOT/'software/micropython/examples'))
# The host driver harness supplies the no-op MicroPython decorators.
import micropython
micropython.native = lambda f: f
micropython.viper = lambda f: f
from viper_emulator import load, Pointer
sys.modules['starfall_viper'] = load(ROOT/'software/micropython/examples/starfall_viper.py')
import starfall as S
from starfall_core import Game
from starfall_render import Renderer
from starfall_sound import Sound
import starfall_render,starfall_sound
starfall_render.ptr8 = starfall_sound.ptr8 = lambda b: Pointer(b,1)
from kagura import regs as R


class StarfallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc') or shutil.which('gcc')
        if cc is None: raise RuntimeError('host C compiler required for the STARFALL oracle')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exe = Path(cls.tmp.name)/'oracle'
        source = ROOT/'software/starfall'
        logic = ('game','player','bullet','powerup','enemy','stage','boss','collision','attract','renderer','assets','music')
        subprocess.run([cc,'-std=c11','-O2','-I',str(source),str(Path(__file__).with_name('starfall_oracle.c')),
                        *[str(source/(n+'.c')) for n in logic],'-o',str(cls.exe)],check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def compare(self,height,demo):
        raw = subprocess.check_output([str(self.exe),str(height),str(int(demo))])
        g,r = Game(height),Renderer(height)
        g.fit = r.fit
        g.start(demo)
        fields = ('tick','state','state_age','stage_frame','stage_tick','x','y','score',
                  'lives','gauge','weapon','options','shield','power','invincible','event_index',
                  'wave_spawned','group_failed','group_rewarded','demo_frame')
        size = 28*4+512
        for t in range(4000):
            keys = 0 if demo else 16|(2,8,1,4)[t//90%4]
            if not demo:
                g.invincible = 60000
                if t in (400,600,800,1000,1100,1200):
                    g.gauge = (400,600,800,1000,1100,1200).index(t)+1
                    g.equip()
            g.step(keys)
            expected = struct.unpack_from('<28I',raw,t*size)
            actual = tuple(getattr(g,n)&0xffffffff for n in fields)+(g.boss.hp,g.boss.age,g.boss.phase,int(g.boss_dead),g.sound,int(g.pickup_active),g.pickup_x&0xffffffff,g.pickup_y&0xffffffff)
            for i,(a,b) in enumerate(zip(actual,expected)):
                self.assertEqual(a,b,'height=%d demo=%s tick=%d field=%s' % (height,demo,t,(fields+('boss.hp','boss.age','boss.phase','boss_dead','sound','pickup_active','pickup_x','pickup_y'))[i]))
            self.assertEqual(bytes(r.render(g)),raw[t*size+112:(t+1)*size], 'OAM height=%d demo=%s tick=%d' % (height,demo,t))
        col = bytearray(32)
        for c in range(400):
            S.make_column(col,height,c)
            self.assertEqual(bytes(col),raw[4000*size+c*32:4000*size+(c+1)*32])

    def test_all_ten_c_scores_and_release_tails(self):
        from starfall_core import TITLE,PLAY,CLEAR,OVER
        class Device:
            caps = R.CAPS_HDMI_AUDIO|R.CAPS_WAVE
            def audio_writes(self,pairs): pass
            def audio_commit(self): pass
        raw = subprocess.check_output([str(self.exe),'240','1'])
        base = 4000*(112+512)+400*32
        g,sound = Game(),Sound(Device())
        for cue in range(10):
            for t in range(420):
                g.state = (TITLE,CLEAR,OVER)[(0,7,8).index(cue)] if cue in (0,7,8) else PLAY
                g.state_age,g.stage_frame = t,t+{2:1120,3:1440,4:2640,5:2760}.get(cue,0)
                g.attract,g.demo_frame,g.boss_dead = cue == 9,t,cue == 6
                sound.update(g)
                v = struct.unpack_from('<14I',raw,base+(cue*420+t)*56)
                from starfall_sound import cue_tick
                self.assertEqual(cue_tick(g),v[:2])
                for i,ch in enumerate((0,1,4,5)):
                    a = ch*16
                    step = (v[2+i]*16777216+24000)//48000
                    offsets = (R.AUDIO_STEP_L,R.AUDIO_STEP_M,R.AUDIO_STEP_H,R.AUDIO_GAIN_L,R.AUDIO_GAIN_R,R.AUDIO_CONTROL)
                    self.assertEqual(bytes(sound.cache[a+off] for off in offsets),bytes((step&255,step>>8&255,step>>16&255,v[6+i],v[6+i],1 if v[6+i] else 0)),(cue,t,ch))
                self.assertEqual(sound.cache[R.AUDIO_DUTY],v[10])
                self.assertEqual(sound.cache[16+R.AUDIO_DUTY],v[11])
                self.assertEqual(sound.cache[48+R.AUDIO_NOISE_PERIOD_L],v[12])
                self.assertEqual(sound.cache[48+R.AUDIO_GAIN_L],v[13])

    def test_c_demo_240(self): self.compare(240,True)
    def test_c_demo_180(self): self.compare(180,True)
    def test_c_game_240(self): self.compare(240,False)
    def test_c_game_180(self): self.compare(180,False)

    def test_asset_hash_and_cache_separation(self):
        path = ROOT/'software/micropython/examples/starfall_assets'
        raw = (path/'video.bin').read_bytes()
        m = json.loads((path/'manifest.json').read_text())
        self.assertEqual(len(raw),S.VIDEO_SIZE)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),m['sha256'])
        import binascii
        self.assertEqual(binascii.crc32(raw),S.VIDEO_CRC)
        import showcase_scenery
        self.assertGreaterEqual(S.CACHE_BASE,showcase_scenery.CACHE_BASE+showcase_scenery.TILES*32+4096)
        for name,sha in m['sources'].items():
            self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),sha)

    def device(self):
        from test_framebuffer import PsramModel
        from kagura import Kagura
        m = PsramModel()
        m.ext[R.EXT_SCREEN_HEIGHT] = 240
        return Kagura(m).probe(),m

    def test_backend_diff_oam_map_ring_and_restore(self):
        d,m = self.device()
        assets = str(ROOT/'software/micropython/examples/starfall_assets')
        S.preload(d,assets)
        b,r,g = S.Backend(d),Renderer(240),Game()
        g.fit = r.fit
        b.load()
        b.present(g,r.render(g))
        raw = (Path(assets)/'video.bin').read_bytes()
        self.assertEqual(bytes(m.memory[:S.PATTERNS]),raw[:S.PATTERNS])
        self.assertEqual(bytes(m.memory[R.VRAM_MAP_BASE:R.VRAM_MAP_BASE+4096]),raw[S.TITLE_OFFSET:S.TITLE_OFFSET+4096])
        before = b.oam_bytes
        b.present(g,r.render(g))
        self.assertEqual(b.oam_bytes,before)
        g.start(True)
        b.present(g,r.render(g))
        for _ in range(800):
            g.step()
            b.present(g,r.render(g))
        self.assertGreater(b.map_bytes,0)
        for col in range(g.stage_tick//8,g.stage_tick//8+40):
            expected = bytearray(32)
            S.make_column(expected,240,col)
            actual = bytes(m.memory[R.VRAM_MAP_BASE+(col&63)*2+row*128] for row in range(32))
            self.assertEqual(actual,bytes(expected))
        g.reset()
        b.present(g,r.render(g))
        self.assertEqual(bytes(m.memory[R.VRAM_MAP_BASE:R.VRAM_MAP_BASE+4096]),raw[S.TITLE_OFFSET:S.TITLE_OFFSET+4096])
        self.assertEqual(d.busy,0)

    def test_quit_ctrl_c_and_transfer_error_cleanup(self):
        assets = str(ROOT/'software/micropython/examples/starfall_assets')
        for error in (None,KeyboardInterrupt(),OSError('input failure')):
            d,m = self.device()
            S.preload(d,assets)
            calls = iter((0,error))
            def control():
                value = next(calls)
                if value is None: return S.QUIT
                if isinstance(value,BaseException): raise value
                return value
            if isinstance(error,OSError):
                with self.assertRaisesRegex(OSError,'input failure'):
                    S.run(device=d,cached=True,autoplay=True,input_fn=control,report=False)
            else:
                result = S.run(device=d,cached=True,autoplay=True,input_fn=control,report=False)
                if error is None: self.assertEqual(result['frames'],1)
            self.assertFalse(m.closed)
            self.assertEqual(m.reg[R.REG_DISPLAY_CTRL],0)
            self.assertEqual(d.busy,0)
            self.assertEqual([m.audio[ch*16+R.AUDIO_CONTROL] for ch in range(6)],[0]*6)

    def test_simulation_clock_catches_up_without_skipping_collision_ticks(self):
        d,m = self.device()
        S.preload(d,str(ROOT/'software/micropython/examples/starfall_assets'))
        clock,frames = [0],[0]
        def control():
            frames[0] += 1
            clock[0] = (frames[0]-1)*33367
            return S.QUIT if frames[0] == 3 else 0
        with patch.object(S.time,'ticks_us',lambda: clock[0]):
            result = S.run(device=d,cached=True,autoplay=True,input_fn=control,report=False)
        self.assertEqual(result['frames'],2)
        self.assertEqual(result['simulation_ticks'],3)
        self.assertEqual(result['lag_max_ticks'],0)


if __name__ == '__main__': unittest.main()
