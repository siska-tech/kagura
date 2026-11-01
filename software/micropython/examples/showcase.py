# SPDX-License-Identifier: Apache-2.0
"""KAGURA-9 live presentation. Run on 480p FULL+PSRAM, ABI 0.6.

Slides use the existing image256 streaming/COPY API, without a 38 KB CPU
framebuffer. Animated chapters import their own modules only while needed.
No firmware/SDK changes. See showcase.md for assets, timing and controls.
"""
import gc
import sys
import time
import kagura
from kagura import regs as R

SLIDES = ('opening', 'architecture', 'colour', 'game', 'orchestra', 'create', 'closing')
REQUIRED = R.CAPS_HDMI_AUDIO | R.CAPS_WAVE | R.CAPS_PSRAM | R.CAPS_SPR16 | R.CAPS_RSCROLL


class _Stop(Exception):
    pass


class _Controls:
    def __init__(self):
        import select
        self.poller = select.poll()
        self.poller.register(sys.stdin, select.POLLIN)
        self.ready = getattr(self.poller, 'ipoll', self.poller.poll)

    def poll(self):
        for _ in range(16):
            found = False
            for event in self.ready(0):
                found = True
                key = sys.stdin.read(1)
                if key in ('q', 'Q'):
                    raise _Stop()
                if key in (' ', 'n', 'N'):
                    return True
            if not found:
                break
        return False


def _unload(*prefixes):
    # No module is unloaded while one of its functions is executing.
    for name in tuple(sys.modules):
        if any(name == p or name.startswith(p + '_') for p in prefixes):
            sys.modules.pop(name, None)
    gc.collect()


def _silence(d):
    for ch in range(6):
        d.audio_write(ch * 16 + R.AUDIO_CONTROL, 0)
    for ch in range(2):
        d.audio_write(R.AUDIO_PCM_BASE + ch * R.AUDIO_PCM_STRIDE + R.AUDIO_PCM_CMD,
                      R.AUDIO_PCM_CMD_STOP)
    d.audio_write(R.AUDIO_MASTER_GAIN, R.AUDIO_MASTER_GAIN_RESET)
    d.audio_commit()


def _preload(d, control, assets, star_assets):
    import showcase_slides
    import showcase_scenery
    import starfall_video
    try:
        showcase_slides.preload(d, control.poll, assets)
        showcase_scenery.preload(d, assets + '/sakura.scenery')
        starfall_video.preload(d, star_assets)
    finally:
        showcase_slides = None
        showcase_scenery = None
        starfall_video = None
        _unload('showcase_slides', 'showcase_scenery', 'starfall')


def _cards(d, control, assets, cards, speed):
    import showcase_slides
    try:
        showcase_slides.run(d, control.poll, assets, cards, speed)
    finally:
        showcase_slides = None
        _unload('showcase_slides', 'showcase_music')


def _graphics(d, control, assets, speed, arena=None):
    # Claim the contiguous block before importing animation code fragments it.
    reserve = arena.pop() if arena else bytearray(38400)
    import showcase_graphics
    reserve = None
    gc.collect()
    try:
        showcase_graphics.run(d, control.poll, assets, speed)
    finally:
        showcase_graphics = None
        _unload('showcase_graphics', 'framebuffer_demo')


def _warm_names():
    try:
        import showcase_names
    except ImportError:
        return False
    for name in showcase_names.NAMES:
        getattr(None,name,None)
    showcase_names = None
    _unload('showcase_names')
    return True


def _game(d, control, assets, seconds):
    import starfall
    try:
        print('SHOWCASE live PROJECT STARFALL')
        result = starfall.run(device=d, autoplay=True, assets=assets, duration=seconds,
                              cached=True, input_fn=lambda: starfall.QUIT if control.poll() else 0)
        if result is None:
            raise _Stop()
    finally:
        starfall = None
        _unload('starfall')


def _sakura(d, control, assets, font, seconds, scenery=None):
    import sakura
    demo = None
    loader = None
    try:
        print('SHOWCASE live SAKURA')
        print('SHOWCASE free before SAKURA', gc.mem_free())
        sakura._keyboard = lambda: control.poll
        if scenery is not None:
            import showcase_scenery as loader
        demo = sakura.Sakura(d, assets=assets, font=font)
        if scenery is not None:
            demo._scenery_loader = loader.restore
        if not demo.run(seconds):
            raise RuntimeError('SAKURA reported an error')
        if getattr(demo, 'interrupted', False):
            raise _Stop()
    finally:
        try:
            if demo is not None:
                demo.sound.stop()
        finally:
            demo = None
            loader = None
            sakura = None
            _unload('sakura', 'showcase_scenery')


def run(device=None, assets='showcase_assets', star_assets='starfall_assets',
        sakura_assets='sakura_assets', font='/fonts/misaki8.kfnt', loops=1, speed=1):
    """One four-minute pass by default; 0 loops experimentally repeats.

    Space/N advances. speed scales chapter holds for installation checks;
    scene generation and sample loading still take their normal time.
    An explicit device stays owned by the caller and ends with a dark screen.
    Normal-speed repeated graphics can exhaust contiguous RAM; see showcase.md.
    """
    if not isinstance(loops, int) or loops < 0 or not 0 < speed <= 10:
        raise ValueError('loops >= 0, 0 < speed <= 10')
    if not gc.isenabled():
        raise ValueError('showcase requires GC enabled')
    own = device is None
    d = kagura.connect(mode='qspi', baudrate=5000000) if own else device
    started = False
    try:
        if d.abi != (0, 6) or d.height != 240:
            raise ValueError('showcase requires ABI 0.6, 480p / 320x240')
        d.require(REQUIRED)
        # No silent PCM fallback in an introduction promising the full system.
        for path in (star_assets + '/video.bin',
                     sakura_assets + '/piano_c4.pcm', assets + '/sakura.scenery', font):
            with open(path, 'rb') as f:
                f.read(1)
        control = _Controls()
        arena = [bytearray(38400)]
        if not _warm_names() and loops != 1:
            raise ValueError('repeat requires showcase_names.mpy: run tools/prepare-showcase.py')
        started = True
        _silence(d)
        _preload(d, control, assets, star_assets)
        count = 0
        while loops == 0 or count < loops:
            count += 1
            print('SHOWCASE loop', count)
            _cards(d, control, assets, ((0, 10), (1, 13), (2, 13)), speed)
            _graphics(d, control, assets, speed, arena)
            _cards(d, control, assets, ((3, 11),), speed)
            _game(d, control, star_assets, max(1, 40 * speed))
            _cards(d, control, assets, ((4, 13),), speed)
            _sakura(d, control, sakura_assets, font, max(1, 40 * speed), assets + '/sakura.scenery')
            _cards(d, control, assets, ((5, 16), (6, 8)), speed)
            d.check_errors()
    except (_Stop, KeyboardInterrupt):
        pass
    finally:
        try:
            if started:
                try:
                    _silence(d)
                finally:
                    d.write_reg(R.REG_DISPLAY_CTRL, 0)
                    d.commit()
        finally:
            if own:
                d.deinit()
