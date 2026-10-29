# SPDX-License-Identifier: Apache-2.0
"""Behavioral host tests; hardware performance is never simulated here."""
import gc
import builtins
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_driver
time.ticks_ms = lambda: time.monotonic_ns() // 1000000
time.ticks_add = lambda value, delta: value + delta
time.sleep_ms = lambda ms: None
ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / 'software/micropython/examples'
sys.path.insert(0, str(EXAMPLES))
import shooter
import shooter_sound as S
import shooter_stats as T
R = shooter.R
ASSETS = str(EXAMPLES / 'star_runner_assets')


class Transport:
    lanes, baudrate, _dma_tx = 4, 5000000, True
    def write(self, *args):
        pass
    def readinto(self, offset, buffer, inc=False):
        for i in range(len(buffer)):
            buffer[i] = 0


class Device:
    def __init__(self, height=240, caps=0x7B):
        self.height, self.caps, self.busy = height, caps, 0
        self.transport = Transport()
        self.memory = bytearray(0x800000)
        self.registers, self.audio_registers, self.ext = {}, {}, {}
        self.audio_log, self.memory_log, self.wave_banks = [], [], []
        self.commits = self.audio_commits = self.counter = 0
        self.closed = self.pending = self.stop_fail = False
        self.pcm_state = [0, 0]
    def write_memory(self, address, data):
        if not 0 <= address <= address + len(data) <= len(self.memory):
            raise AssertionError('invalid memory write')
        if address == 0xA000 and self.pending:
            raise AssertionError('OAM overwritten during COMMIT')
        self.memory_log.append((address, len(data)))
        self.memory[address:address + len(data)] = data
    def fill(self, address, count, value=0):
        self.write_memory(address, bytes([value]) * count)
    def write_reg(self, address, value):
        if address == R.REG_COMMAND and value == R.CMD_COMMIT:
            self.commit(wait=False)
        self.registers[address] = self.registers.get(address, 0) & ~value if address in (R.REG_ERROR_CODE, R.REG_IRQ_STATUS) else value
    def read_reg(self, address):
        if address == R.REG_FRAME_COUNT_L:
            self.counter = (self.counter + 1) & 255
            return self.counter
        return self.registers.get(address, 0)
    def ext_write(self, address, value):
        self.ext[address] = value
    def audio_write(self, address, value):
        if self.stop_fail and address == R.AUDIO_CONTROL:
            raise OSError('injected audio disconnect')
        self.audio_log.append((address, value))
        self.audio_registers[address] = value
        if address in (0x6F, 0x8F):
            ch = int(address == 0x8F)
            if value & R.AUDIO_PCM_CMD_STOP:
                self.pcm_state[ch] = 0
            if value & R.AUDIO_PCM_CMD_CLEAR:
                self.pcm_state[ch] &= 3
            if value & R.AUDIO_PCM_CMD_PREPARE:
                self.pcm_state[ch] = R.AUDIO_PCM_STATUS_READY
    def audio_read(self, address):
        return self.pcm_state[int(address == 0x8F)] if address in (0x6F, 0x8F) else self.audio_registers.get(address, 0)
    def _wait(self, predicate, name, *args):
        if not predicate():
            raise OSError('mock timeout ' + name)
    def wait_status(self, *args):
        self.pending = False
    def require(self, mask):
        if self.caps & mask != mask:
            raise AssertionError('unsupported capability')
    def fence(self):
        pass
    def clear_errors(self):
        self.registers[R.REG_ERROR_CODE] = 0
    def check_errors(self):
        if self.registers.get(R.REG_ERROR_CODE, 0):
            raise OSError('mock FPGA error')
    def commit(self, wait=True):
        self.commits += 1
        self.pending = not wait
    def audio_commit(self):
        self.audio_commits += 1
        self.wave_banks.append(bytes(self.memory[0x9800:0x9A00]))
        for ch in (0, 1):
            enabled = self.audio_registers.get(0x60 + ch * 32 + R.AUDIO_PCM_CONTROL, 0) & 1
            if enabled and self.pcm_state[ch] & R.AUDIO_PCM_STATUS_READY:
                self.pcm_state[ch] |= R.AUDIO_PCM_STATUS_ACTIVE
    def deinit(self):
        self.closed = True


def console_for(device):
    class Console:
        def __init__(self):
            self.screen = type('Screen', (), {'device': device})()
            self.paused = False
        def pause(self):
            self.paused = True
        def resume(self):
            self.paused = False
    return Console()


class ShooterTests(unittest.TestCase):
    def test_optional_native_import_failures_keep_reference_driver(self):
        original_import = builtins.__import__
        for module, native, symbol in (('dma_pack','dma_pack_viper','viper_pack'),
                                        ('fifo_xfer','fifo_xfer_viper','pump')):
            path = ROOT / ('software/micropython/kagura/'+module+'.py')
            for error in (ImportError('missing helper'), SyntaxError('unsupported emitter'),
                          ValueError('incompatible .mpy file')):
                def unavailable(name,*args,**kwargs):
                    if native in name:
                        raise error
                    return original_import(name,*args,**kwargs)
                namespace = {'__name__':'kagura.fallback_test','__package__':'kagura'}
                with patch.object(sys.implementation,'name','micropython'),patch.object(builtins,'__import__',unavailable):
                    exec(compile(path.read_text(encoding='utf-8'),str(path),'exec'),namespace)
                self.assertIsNone(namespace[symbol])
                self.assertTrue(namespace['native_error'])
                if module == 'dma_pack':
                    words = [0]*4
                    namespace['pack'](b'\x01\x02',list(range(256)),words,0,2)
                    self.assertEqual(words,[0,1,0,2])

    def test_acceleration_unavailable_never_mutates_transport(self):
        from kagura import acceleration as A
        for pack, pack32, fifo, dma in ((None,None,None,True),(1,1,None,True),(1,1,1,None)):
            raw = types.SimpleNamespace(_active=False,_closed=False,_dma_tx=dma)
            before = raw.__dict__.copy()
            with patch.object(A.dma_pack,'viper_pack',pack),patch.object(A.dma_pack,'viper_pack32',pack32),patch.object(A.fifo_xfer,'pump',fifo):
                with A.Acceleration(raw,RuntimeError) as session:
                    self.assertFalse(session.enabled)
                    self.assertTrue(session.reason)
            self.assertEqual(raw.__dict__,before)

    def test_game_falls_back_when_native_helpers_missing(self):
        original_import = builtins.__import__
        def missing(name,*args,**kwargs):
            if name in ('kagura.acceleration','kagura_acceleration','shooter_oam_viper'):
                raise ImportError('native helper intentionally absent')
            return original_import(name,*args,**kwargs)
        d = Device(caps=0)
        raw = d.transport
        with patch.object(builtins,'__import__',missing):
            result = shooter.run(device=d,mode='BASE',frames=4,report=False,
                                 input_fn=lambda:0,target_fps=0,renderer='viper',dma='accelerated')
        self.assertEqual(result['frames'],4)
        self.assertEqual(result['dma_effective'],'driver')
        self.assertTrue(result['acceleration_reason'])
        self.assertEqual(result['renderer'],'python')
        self.assertTrue(result['renderer_reason'])
        self.assertIs(d.transport,raw)

    def test_game_falls_back_when_viper_unavailable(self):
        from kagura import acceleration as A
        d = Device(caps=0)
        d.transport._active = d.transport._closed = False
        raw = d.transport
        before = raw.__dict__.copy()
        with patch.object(A.dma_pack,'viper_pack',None):
            result = shooter.run(device=d,mode='BASE',frames=4,report=False,
                                 input_fn=lambda:0,target_fps=0,dma='accelerated')
        self.assertEqual(result['dma_effective'],'driver')
        self.assertEqual(result['acceleration_reason'],'Viper DMA kernel unavailable')
        self.assertEqual(raw.__dict__,before)

    def test_partial_acceleration_install_is_rolled_back(self):
        from kagura import acceleration as A
        from array import array
        class Interrupted(types.SimpleNamespace):
            def __setattr__(self,name,value):
                if name=='write' and self.__dict__.get('interrupt'):
                    self.__dict__['interrupt'] = False
                    raise KeyboardInterrupt
                super().__setattr__(name,value)
        fn = lambda *args,**kwargs:None
        raw = Interrupted(_active=False,_closed=False,_dma_tx=types.SimpleNamespace(active=lambda:False),
                          _dma_rx=types.SimpleNamespace(active=lambda:False),_words=array('H',[0]*256),
                          _sm_id=0,lanes=4,timeout_us=100000,_xfer=fn,write=fn,readinto=fn,interrupt=True)
        before = raw.__dict__.copy()
        before['interrupt'] = False
        with patch.object(A.dma_pack,'viper_pack',1),patch.object(A.dma_pack,'viper_pack32',1),patch.object(A.fifo_xfer,'pump',fn):
            with self.assertRaises(KeyboardInterrupt):
                A.Acceleration(raw,RuntimeError,chunk=512)
        self.assertEqual(raw.__dict__,before)

    def test_exclusive_statistics_and_detail_ring(self):
        stats = T.Stats(16, detail=True)
        for _ in range(33):
            for category, duration in ((T.MOVE,1),(T.COLLIDE,2),(T.COMMIT_WAIT,3),
                                       (T.COMMIT_ISSUE,4),(T.COMMIT,7)):
                stats.add(category,duration)
            stats.finish(100)
        result = stats.summary()
        self.assertEqual(result['mean_us']['logic'],3)
        self.assertEqual(result['exclusive_stage_sum_us'],10)
        self.assertEqual(result['unclassified_mean_us'],90)
        self.assertEqual(result['detail_window_frames'],16)
        self.assertEqual(result['median_us']['commit_wait'],3)
        self.assertEqual(result['p95_us']['commit_issue'],4)
        self.assertEqual(result['frame_median_us'],100)
        self.assertIsNone(result['actual_pixel_update_hz'])
        stats = T.Stats(16)
        stats.finish(100,begin=1000)
        stats.finish(100,begin=1120)
        stats.period_end(1260)
        result = stats.summary()
        self.assertEqual(result['loop_frame_mean_us'],130)
        self.assertEqual(result['loop_frame_median_us'],130)
        self.assertEqual(result['loop_frame_p95_us'],140)

    def test_memory_poll_cadence_and_commit_completions(self):
        with patch.object(gc,'mem_free',lambda:100000,create=True) as free:
            result = shooter.run(device=Device(), mode='BASE', frames=20,
                                 report=False, input_fn=lambda:0, target_fps=0,
                                 profile=True, instrument_transport=False)
        self.assertEqual(result['commit_successes'],20)
        self.assertEqual(result['commit_completions_observed'],20)
        self.assertEqual(result['minimum_free_bytes'],100000)
        self.assertIsNone(result['wire_bytes'])
        self.assertLessEqual(result['exclusive_stage_sum_us'],result['frame_mean_us'])

    def test_acceleration_restores_transport_and_buffer(self):
        from array import array
        from kagura import acceleration as A
        fn = lambda *args,**kwargs:None
        raw = types.SimpleNamespace(_active=False,_closed=False,_dma_tx=types.SimpleNamespace(active=lambda:False),
                                    _dma_rx=types.SimpleNamespace(active=lambda:False),
                                    _words=array('H',[0]*256),_sm_id=0,lanes=4,timeout_us=100000,
                                    _xfer=fn,write=fn,readinto=fn)
        before = raw.__dict__.copy()
        with patch.object(A.dma_pack,'viper_pack',object()),patch.object(A.dma_pack,'viper_pack32',object()),patch.object(A.fifo_xfer,'pump',fn):
            with self.assertRaises(KeyboardInterrupt):
                with A.Acceleration(raw,RuntimeError,chunk=512):
                    self.assertEqual(len(raw._words),1024)
                    self.assertIsNot(raw.write,fn)
                    raise KeyboardInterrupt
        self.assertEqual(raw.__dict__,before)

    def test_native_read_rejects_readonly_and_short_buffers(self):
        from kagura import fifo_xfer as F
        calls = []
        raw = types.SimpleNamespace(_sm_id=0,lanes=4,timeout_us=100000,
                                    _xfer=lambda *a:calls.append(a),
                                    write=lambda *a:None,readinto=lambda *a:None)
        with patch.object(F,'pump',lambda *a:1):
            pump = F.Pump(raw,RuntimeError)
            for buffer in (b'x',memoryview(b'x')):
                with self.assertRaises(TypeError):
                    pump.readinto(0,buffer)
            pump.transfer(b'long',bytearray(1))
        self.assertEqual(len(calls),1)
        def timeout(tx,rx,settings):
            settings[9] = 5  # Conservative completed count including prefix.
            return 0
        with patch.object(F,'pump',timeout):
            with self.assertRaises(RuntimeError) as caught:
                pump._packet(b'xx',bytearray(8),11,2,3,11,release=True)
        self.assertEqual(caught.exception.args,(2,))

    def test_oam_kernel_reference_semantics(self):
        spec = importlib.util.spec_from_file_location('kernel_test', EXAMPLES / 'shooter_oam_viper.py')
        kernel = importlib.util.module_from_spec(spec)
        with patch.object(sys.modules['micropython'], 'viper', lambda fn: fn, create=True):
            spec.loader.exec_module(kernel)
        kernel.ptr8 = lambda data: data
        kernel.ptr16 = lambda data: [value & 65535 for value in data]
        for height in (180, 240):
            g = shooter.Game(Device(height), mode='BASE')
            g.initialize()
            for frame in range(96):
                g.enhanced = frame % 7 != 0
                g.load = ('NORMAL', 'HEAVY', 'STRESS', 'EXTREME')[(frame // 8) % 4]
                g.extreme_sprites = 128 if frame < 48 else 256
                g.particle_limit = 8 << ((frame // 24) % 4)
                g.step()
                g.power = 3 if frame & 4 else 0
                if frame % 9 == 0:
                    g.emit(56, height // 2, True)
                    g.hostile.spawn(-7, 24)
                before, count, culled = bytes(g.oam), g.oam_count, g.stats.particle_culled
                g._oam_builder = None
                g.build_oam()
                expected = bytes(g.oam), bytes(g.scanlines), g.oam_count, g.oam_bytes, g.active_sprites, g.stats.particle_culled
                g.oam[:] = before
                g.oam_count, g.stats.particle_culled = count, culled
                g._oam_builder = kernel.build
                g.build_oam()
                self.assertEqual(expected, (bytes(g.oam), bytes(g.scanlines), g.oam_count, g.oam_bytes, g.active_sprites, g.stats.particle_culled))

    def test_dma_pack_multi_byte_fallback(self):
        from array import array
        from kagura import dma_pack
        data = memoryview(array('H', [1, 2, 255]))
        high = array('H', [value << 7 for value in range(256)])
        words = array('H', [0x55AA] * 6)
        dma_pack.pack(data, high, words, 0, 3)
        self.assertEqual(list(words), [0x55AA, 128, 0x55AA, 256, 0x55AA, 32640])

    def test_dma_override_restored_on_interrupt(self):
        d = Device(caps=0)
        console = console_for(d)
        sentinel = lambda data, queued: None
        d.transport._xfer_dma = sentinel
        def interrupt():
            self.assertIsNot(d.transport._xfer_dma, sentinel)
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            shooter.run(console=console, dma='python', input_fn=interrupt, report=False)
        self.assertIs(d.transport._xfer_dma, sentinel)
        self.assertFalse(console.paused)

    def test_keyboard_split_arrow_hold_and_toggle(self):
        class Stream:
            data = list('\x1b[')
            def read(self, count):
                return self.data.pop(0)
        stream = Stream()
        class Poll:
            def register(self, *args):
                pass
            def poll(self, timeout):
                return [(1, 1)] if stream.data else []
        select = types.SimpleNamespace(POLLIN=1, poll=Poll)
        with patch.dict(sys.modules, {'select': select}), patch('sys.stdin', stream):
            keyboard = shooter.Keyboard()
            with patch.object(shooter, 'ticks_ms', return_value=1000):
                self.assertEqual(keyboard(), 0)
                stream.data.extend('A')
                self.assertEqual(keyboard(), shooter.UP)
            with patch.object(shooter, 'ticks_ms', return_value=1200):
                self.assertEqual(keyboard(), 0)
                stream.data.extend('t')
                self.assertEqual(keyboard(), shooter.AUTO)
                self.assertEqual(keyboard(), 0)

    def test_phase1_retains_v1_autopilot_gameplay(self):
        spec = importlib.util.spec_from_file_location('shooter_v1', ROOT / 'software/micropython/benchmarks/shooter_v1.py')
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        old = legacy.Game(Device(), sound=False)
        new = shooter.Game(Device(), mode='BASE', enhanced=False)
        for _ in range(500):
            old.step()
            new.step()
            self.assertEqual((new.x, new.y, new.score, new.lives, new.power),
                             (old.x, old.y, old.score, old.lives, old.power))

    def test_both_heights_pools_and_scanline_limit(self):
        for height in (180, 240):
            for load in ('NORMAL', 'HEAVY', 'STRESS'):
                game = shooter.Game(Device(height), mode='BASE', load=load)
                game.initialize()
                pools = (game.bullets, game.enemies, game.hostile, game.particles)
                identities = [(id(p.x), id(p.life)) for p in pools]
                peak = 0
                for _ in range(600):
                    game.step()
                    game.draw()
                    peak = max(peak, game.power)
                    self.assertLessEqual(max(game.scanlines), 16)
                    self.assertEqual([(id(p.x), id(p.life)) for p in pools], identities)
                self.assertGreaterEqual(peak, 1)
    def test_hit_pickup_damage_restart(self):
        game = shooter.Game(Device(), autoplay=False, mode='BASE', enhanced=False)
        game.enemies.spawn(150, 100, -3, kind=1)
        game.bullets.spawn(138, 100)
        game.step()
        self.assertEqual(game.score, 100)
        self.assertFalse(any(game.enemies.life))
        for power in (1, 2, 3, 3):
            game.pickup_x, game.pickup_y = game.x + 7, game.y
            game.step()
            self.assertEqual(game.power, power)
        game.invincible = 0
        game.damage()
        self.assertEqual((game.lives, game.power), (2, 0))
        game.damage()
        self.assertEqual(game.lives, 2)
        game.invincible, game.lives = 0, 1
        game.damage()
        for _ in range(90):
            game.step()
        self.assertEqual((game.lives, game.dead, game.score), (3, 0, 0))
    def test_batch_transfer_and_shadow_wait(self):
        d = Device()
        game = shooter.Game(d, mode='BASE')
        game.initialize()
        d.memory_log.clear()
        for _ in range(4):
            game.step()
            game.draw()
        self.assertEqual([n for a, n in d.memory_log if a == 0xA000], [512] * 4)
        self.assertEqual(game.stats.commits, 4)
        game.load = 'EXTREME'
        game.extreme_sprites = 256
        game.draw()
        game.load = 'NORMAL'
        game.draw()
        self.assertEqual(game.oam_bytes, 2048)  # Clear the old high tail once.
        self.assertFalse(any(d.memory[0xA000 + i * 8 + 3] & 4 for i in range(64, 256)))
        game.draw()
        self.assertEqual(game.oam_bytes, 512)
    def test_extreme_and_particle_controls(self):
        for count in (128, 256):
            game = shooter.Game(Device(180), mode='BASE', load='EXTREME', sprites=count)
            game.initialize()
            game.step()
            game.build_oam()
            self.assertEqual(game.active_sprites, count)
            self.assertGreater(max(game.scanlines), 16)
        game = shooter.Game(Device(), mode='BASE')
        for limit in (16, 32, 64, 8):
            game.step(shooter.PARTICLE_KEY)
            self.assertEqual(game.particle_limit, limit)
    def test_cleanup_on_interrupt_quit_and_disconnect(self):
        for interrupt, disconnect in ((False, False), (True, False), (True, True)):
            d = Device()
            console = console_for(d)
            def keyboard():
                d.stop_fail = disconnect
                if interrupt:
                    raise KeyboardInterrupt
                return shooter.QUIT
            if interrupt:
                with self.assertRaises(KeyboardInterrupt):
                    shooter.run(console=console, input_fn=keyboard, assets=ASSETS, report=False)
            else:
                shooter.run(console=console, input_fn=keyboard, assets=ASSETS, report=False)
            self.assertFalse(console.paused)
            self.assertTrue(gc.isenabled())
            self.assertFalse(d.closed)
            if not disconnect:
                self.assertEqual(d.pcm_state, [0, 0])
                for ch in range(6):
                    self.assertEqual(d.audio_registers[ch * 16 + R.AUDIO_CONTROL], 0)
    def test_silent_modes_and_owned_cleanup(self):
        for caps, sound, mode in ((0, True, 'FULL'), (0x7B, False, 'FULL'), (0x7B, True, 'BASE')):
            d = Device(caps=caps)
            shooter.run(device=d, frames=20, sound=sound, mode=mode, report=False,
                        input_fn=lambda: shooter.FIRE, target_fps=0)
            if caps & R.CAPS_HDMI_AUDIO:
                self.assertEqual(d.audio_commits, 1)  # Initial silence only.
                self.assertTrue(all(value in (0, R.AUDIO_PCM_CMD_STOP) for _, value in d.audio_log))
            else:
                self.assertEqual(d.audio_log, [])
        d = Device(caps=0)
        with patch('kagura.connect', return_value=d):
            shooter.run(input_fn=lambda: shooter.QUIT, mode='BASE', report=False)
        self.assertTrue(d.closed)
    def test_error_logging_sticky_and_counter_wrap(self):
        d = Device()
        game = shooter.Game(d, assets=ASSETS)
        game.initialize()
        d.pcm_state[0] = R.AUDIO_PCM_STATUS_MEMORY_ERROR
        d.registers[R.REG_IRQ_STATUS] = R.IRQ_STATUS_SPR_OVERFLOW
        d.registers[R.REG_SPR_OVERFLOW_INDEX] = 17
        d.registers[R.REG_SPR_OVERFLOW_LINE] = 40
        game.monitor(1234)
        self.assertEqual((game.stats.audio_errors, game.stats.sprite_overflows), (1, 1))
        self.assertEqual(list(game.stats.errors[3:10]), [1234, 0, 0, 32, 0, 17, 40])
        game.monitor()
        self.assertEqual(game.stats.audio_errors, 1)
        stats = T.Stats(16)
        stats.counter(250, 0)
        stats.counter(4, 100000)
        self.assertEqual(stats.counter_delta, 10)
        stats.counter(8, 5000000)
        self.assertFalse(stats.counter_valid)

    def test_bounded_statistics_and_transport_bytes(self):
        stats = T.Stats(16)
        for frame in range(40):
            stats.finish(frame * 100)
            stats.error(64, 512, 600, 0, 0, 0, 0)
        stats.elapsed_us = 1000000
        report = stats.summary()
        self.assertEqual(report['logic_fps'], 40)
        self.assertEqual(report['p95_window_frames'], 16)
        self.assertEqual(report['frame_p95_us'], 3900)
        self.assertEqual(len(report['errors']), 32)
        meter = T.TransportMeter(Transport())
        meter.write(7, bytes(512))
        meter.readinto(1, bytearray(2))
        self.assertEqual((meter.wire_bytes, meter.dma_payload), (518, 512))


class SoundTests(unittest.TestCase):
    def test_pcm_prepare_fault_preserves_sticky_evidence(self):
        d = Device()
        sound = S.Sound(d, assets=ASSETS)
        sound.initialize()
        sound.count = 0
        sound.enqueue(S.SPECIAL)
        sound.service(1000)
        d.pcm_state[1] = R.AUDIO_PCM_STATUS_CONFIG_ERROR
        sound.service(1100)
        self.assertEqual(sound.pcm_fault[1], 1)
        self.assertIsNone(sound.pending_pcm)
        d.audio_log.clear()
        sound.enqueue(S.EXPLOSION)
        sound.service(1200)
        self.assertFalse(any(a == 0x8F and value & R.AUDIO_PCM_CMD_PREPARE for a, value in d.audio_log))
        self.assertTrue(d.pcm_state[0] & R.AUDIO_PCM_STATUS_ACTIVE)

    def test_bgm_isolation_wave_banks_and_commit_budget(self):
        d = Device()
        sound = S.Sound(d, assets=ASSETS)
        sound.initialize()
        self.assertEqual(d.audio_registers[0x60 + R.AUDIO_PCM_GAIN_L], 224)
        self.assertEqual(d.audio_registers[0x60 + R.AUDIO_PCM_GAIN_R], 224)
        for channel, gain in enumerate((48, 40, 72, 72, 64, 64)):
            self.assertEqual(d.audio_registers[channel * 16 + R.AUDIO_GAIN_L], gain)
            self.assertEqual(d.audio_registers[channel * 16 + R.AUDIO_GAIN_R], gain)
        self.assertEqual(d.audio_registers[0x80 + R.AUDIO_PCM_GAIN_L], 144)
        self.assertEqual(d.wave_banks[1], d.wave_banks[2])
        self.assertTrue(d.pcm_state[0] & R.AUDIO_PCM_STATUS_ACTIVE)
        d.audio_log.clear()
        for event in range(7):
            sound.enqueue(event)
        for now in range(1000, 2200, 100):
            before = d.audio_commits
            sound.service(now)
            self.assertLessEqual(d.audio_commits - before, 1)
        self.assertFalse(any(0x60 <= a < 0x80 for a, _ in d.audio_log))
        self.assertTrue(d.pcm_state[0] & R.AUDIO_PCM_STATUS_ACTIVE)
        enabled = {address // 16 for address, value in d.audio_log
                   if address < 0x60 and address % 16 == R.AUDIO_CONTROL and value & 1}
        self.assertEqual(enabled, set(range(6)))

    def test_cached_shot_register_cost(self):
        d = Device()
        sound = S.Sound(d, pcm=False)
        sound.initialize()
        sound.count = 0
        d.audio_log.clear()
        sound.enqueue(S.SHOT)
        sound.service(1000)
        self.assertEqual(d.audio_log, [(R.AUDIO_CONTROL, 3)])
    def test_priority_dedup_and_missing_assets(self):
        with self.assertRaises(ValueError):
            S.Sound(Device(), bgm_gain=256)
        sound = S.Sound(Device(), pcm=False)
        for _ in range(100):
            sound.enqueue(S.SHOT)
        sound.enqueue(S.SPECIAL)
        self.assertEqual((sound.count, sound.dropped), (2, 99))
        sound.service(1000)
        d = Device(caps=R.CAPS_HDMI_AUDIO | R.CAPS_PSRAM)
        sound = S.Sound(d, assets='/missing/star-runner')
        sound.initialize()
        self.assertFalse(sound.pcm)
        self.assertFalse(sound.wave)
        self.assertIn('missing', sound.reason)
    def test_generator_pcm_contract_and_reproducibility(self):
        spec = importlib.util.spec_from_file_location('gen_sr', ROOT / 'tools/gen-star-runner-audio.py')
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        (ROOT / 'build').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'build') as directory:
            output = Path(directory)
            manifest = generator.generate(output)
            self.assertEqual(manifest['music']['progression'], ['B7', 'C', 'D', 'E'])
            self.assertEqual(manifest['music']['bpm'], 160)
            self.assertEqual(manifest['music']['seconds'], 6)
            previous = 0x400000
            for sample in manifest['samples']:
                data = (output / sample['file']).read_bytes()
                self.assertEqual(data, (EXAMPLES / 'star_runner_assets' / sample['file']).read_bytes())
                self.assertEqual((data[0], data[-1]), (0, 0))
                self.assertEqual(len(data), sample['end'] - sample['start'])
                self.assertGreaterEqual(sample['start'], previous)
                previous = sample['end']
            self.assertLessEqual(previous, 0x800000)


if __name__ == '__main__':
    unittest.main()
