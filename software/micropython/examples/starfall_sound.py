# SPDX-License-Identifier: Apache-2.0
"""C STARFALL score/SFX on six synthesizer channels; no PCM loading."""
import micropython
from array import array
import starfall_viper as V
from kagura import regs as R
from starfall_scores import SCORES
from starfall_core import TITLE, BOOT, INTRO, OVER, CLEAR, ENDING, PLAY


@micropython.native
def frequency(note):
    if not note: return 0
    f = (262,277,294,311,330,349,370,392,415,440,466,494)[note%12]
    oct = note//12-5
    return f << oct if oct >= 0 else f >> -oct


@micropython.native
def cue_tick(g):
    if g.state in (TITLE,BOOT,INTRO): return 0,g.state_age
    if g.state == OVER: return 8,g.state_age
    if g.state in (CLEAR,ENDING): return 7,g.state_age
    if g.boss_dead: cue,tick = 6,g.stage_frame-g.boss_defeat_tick
    elif g.stage_frame >= 2760: cue,tick = 5,g.stage_frame-2760
    elif g.stage_frame >= 2640: cue,tick = 4,g.stage_frame-2640
    elif g.attract: return 9,g.demo_frame
    elif g.stage_frame >= 1440: cue,tick = 3,g.stage_frame-1440
    elif g.stage_frame >= 1120: cue,tick = 2,g.stage_frame-1120
    else: cue,tick = 1,g.stage_frame
    return cue,tick//2 if g.attract and g.state == PLAY else tick


class Sound:
    def __init__(self,d):
        self.d = d
        self.enabled = d.caps&(R.CAPS_HDMI_AUDIO|R.CAPS_WAVE) == R.CAPS_HDMI_AUDIO|R.CAPS_WAVE
        self.cache = bytearray(b'\xff'*96)
        self.ops = bytearray(192)
        self.views = [memoryview(self.ops)[:i*2] for i in range(97)]
        self.count = self.priority = self.remaining = 0
        self.last_state = self.last_scene = -1
        self.wanted = bytearray(self.cache)
        self.scores = bytearray(560)
        for i,s in enumerate(SCORES):
            a = i*56
            self.scores[a:a+7] = bytes(s[:7])
            self.scores[a+8:a+8+len(s[7])] = bytes(s[7])
            self.scores[a+40:a+48] = bytes(s[8])
            for j in range(3):
                self.scores[a+48+j*2] = s[9+j]&255
                self.scores[a+49+j*2] = s[9+j]>>8
        self.steps = array('I',((frequency(n)*16777216+24000)//48000 for n in range(96)))

    @micropython.viper
    def field(self,ch:int,off:int,value:int):
        cache = ptr8(self.cache)
        ops = ptr8(self.ops)
        index = ch*16+off
        if int(cache[index]) != value:
            cache[index] = value
            n = int(self.count)
            ops[n] = index
            ops[n+1] = value
            self.count = n+2

    @micropython.native
    def voice(self,ch,hz,gain):
        # Divide before multiplying to keep intermediate values small on RP2.
        step = (hz*1048576+1500)//3000
        self.field(ch,R.AUDIO_STEP_L,step&255)
        self.field(ch,R.AUDIO_STEP_M,(step>>8)&255)
        self.field(ch,R.AUDIO_STEP_H,(step>>16)&255)
        self.field(ch,R.AUDIO_GAIN_L,gain)
        self.field(ch,R.AUDIO_GAIN_R,gain)
        self.field(ch,R.AUDIO_CONTROL,1 if gain else 0)

    def flush(self):
        if self.count:
            self.d.audio_writes(self.views[self.count//2])
            self.d.audio_commit()
            self.count = 0

    def load(self):
        if not self.enabled: return
        for ch in range(6): self.field(ch,R.AUDIO_CONTROL,0)
        for ch in range(2):
            if self.d.caps&R.CAPS_PSRAM:
                self.d.audio_write(R.AUDIO_PCM_BASE+ch*R.AUDIO_PCM_STRIDE+R.AUDIO_PCM_CMD,R.AUDIO_PCM_CMD_STOP)
        self.d.audio_write(R.AUDIO_MASTER_GAIN,24)
        for ch in range(3): self.field(ch,R.AUDIO_DUTY,64 if ch == 2 else 128)
        self.field(4,R.AUDIO_LEN_LOG2,5)
        self.field(5,R.AUDIO_LEN_LOG2,5)
        self.flush()
        wave = bytearray(512)
        for ch in range(2):
            for i in range(32): wave[ch*256+i] = (-96+i*12 if i < 16 else 96-(i-16)*12)&255
        for _ in range(2):
            self.d.write_memory(R.VRAM_WAVE_BASE,wave)
            self.d.audio_commit()

    @micropython.native
    def update(self,g,ticks=1):
        if not self.enabled: return
        scene = g.scene() if g.state == PLAY else 255
        if self.last_state != g.state or self.last_scene != scene:
            self.priority = self.remaining = 0
            self.last_state,self.last_scene = g.state,scene
        cue,tick = cue_tick(g)
        self.wanted[:] = self.cache
        V.music(self.wanted,self.scores,self.steps,cue,tick)
        self.count = V.audio_diff(self.cache,self.wanted,self.ops)
        if g.sound and g.sound >= self.priority:
            self.priority = g.sound
            self.remaining = 3 if g.sound == 1 else 24 if g.sound == 5 else 14
        noise = self.remaining and self.priority in (2,5)
        if self.remaining:
            if noise:
                self.voice(2,0,0)
                self.field(3,R.AUDIO_NOISE_PERIOD_L,32+(24-self.remaining)*3)
                self.field(3,R.AUDIO_NOISE_PERIOD_H,0)
                self.field(3,R.AUDIO_GAIN_L,self.remaining)
                self.field(3,R.AUDIO_GAIN_R,self.remaining)
                self.field(3,R.AUDIO_CONTROL,1)
            else:
                hz = 1400-self.remaining*160 if self.priority == 1 else 330+self.remaining%4*110 if self.priority == 4 else 600+(14-self.remaining)*60
                self.voice(2,hz,12)
            self.remaining = max(0,self.remaining-ticks)
        else:
            self.priority = 0
            self.voice(2,0,0)
        if not noise:
            self.field(3,R.AUDIO_NOISE_PERIOD_L,self.wanted[56])
            self.field(3,R.AUDIO_NOISE_PERIOD_H,0)
            self.field(3,R.AUDIO_GAIN_L,self.wanted[52])
            self.field(3,R.AUDIO_GAIN_R,self.wanted[53])
            self.field(3,R.AUDIO_CONTROL,self.wanted[54])
        self.flush()

    def stop(self):
        if not self.enabled: return
        self.count = 0
        for ch in range(6): self.field(ch,R.AUDIO_CONTROL,0)
        self.flush()
        self.d.audio_write(R.AUDIO_MASTER_GAIN,R.AUDIO_MASTER_GAIN_RESET)
        self.d.audio_commit()
