# SPDX-License-Identifier: Apache-2.0
"""Fixed 512-byte OAM and scanline admission; C STARFALL slot layout."""
import micropython
from array import array
from starfall_core import TITLE, PLAY, BOOT, INTRO, OVER, ENDING, BOSS, NAMES, div
import starfall_viper as V


class Renderer:
    def __init__(self, height):
        self.oam = bytearray(512)
        self.zero = bytes(512)
        self.lines = bytearray(height)
        self.clear_lines = bytes(height)
        self.peak = self.dropped = 0
        self.rects = array('i',[0]*64)

    @micropython.native
    def combat_lines(self,g,hostiles):
        # Scanline admission needs only y and size; don't build textures/HUD.
        r,n = self.rects,0
        if not g.invincible or g.tick//5%2 == 0:
            r[n],r[n+1],n = div(g.y,256),16,n+2
        if not any(b.active for b in g.beams):
            for s in g.shots:
                if s.active: r[n],r[n+1],n = div(s.y,256),8,n+2
        for e in g.enemies:
            if not e.active: continue
            y = div(e.y,256)
            if e.type == BOSS:
                for part in range(6):
                    if part in (2,5) and not g.boss.parts[1 if part == 5 else 0]: continue
                    r[n],r[n+1],n = y+part//3*16,16,n+2
            else: r[n],r[n+1],n = y,16,n+2
        if hostiles:
            for s in g.hostile:
                if s.active: r[n],r[n+1],n = div(s.y,256),8,n+2
        if g.missile.active: r[n],r[n+1],n = div(g.missile.y,256),8,n+2
        if g.pickup_active: r[n],r[n+1],n = div(g.pickup_y,256),16,n+2
        for i in range(g.options):
            x,y = g.option_position(i)
            r[n],r[n+1],n = div(y,256),16,n+2
        if V.rectangles(self.lines,r,n,g.height) < 0: raise RuntimeError('STARFALL combat budget')

    @micropython.native
    def sprite(self,slot,x,y,tile,large=False,palette=0,flip=False):
        V.sprite(self.oam,slot,x,y,tile,(8 if large else 0)|(32 if flip else 0),palette)

    @micropython.native
    def text(self,slot,y,s):
        length = min(len(s),64-slot)
        V.text(self.oam,s.encode(),slot,y,length)

    @micropython.native
    def beam(self,b,slot,palette):
        if not b.active: return
        for i in range(4):
            if i*16 >= b.length: break
            length = min(16,b.length-i*16)
            self.sprite(slot+i,div(b.x,256)+i*16,div(b.y,256),192+(length-1)*4,True,palette)

    @micropython.native
    def build(self,g,rays=True):
        self.oam[:] = self.zero
        self.peak = self.dropped = 0
        if g.state == BOOT: return
        if g.state == TITLE:
            if g.tick//30%2 == 0: self.text(0,112,'PRESS START')
            self.text(16,128,'1 PLAYER')
            self.text(32,144,'FREE PLAY')
            self.text(46,160,'SISKA-TECH LAB')
            self.text(60,172,'2026')
            self.sprite(15,g.state_age*2%352-16,24,300 if g.tick//4%2 else 4,True)
            return
        if g.state == INTRO:
            self.text(0,g.height//2-24,'STAGE 1')
            self.text(16,g.height//2,'STAR FRONTIER')
            self.text(32,g.height//2+24,'READY')
            return
        label = NAMES[g.gauge] if g.gauge else 'SPACE' if g.stage_tick < 1120 else 'ENTRY' if g.stage_tick < 1440 else 'BASE'
        if g.state == PLAY and g.scene() == 3 and g.tick%30 < 20: label = 'WARNING'
        if g.attract: label = 'DEMO'
        hud = '%06dL%d %s' % (g.score%1000000,g.lives,label)
        if g.boss.active and not g.attract: hud = 'CORE %03d PHASE %d' % (g.boss.hp,g.boss.phase)
        self.text(32,8,hud)
        if g.state == PLAY and (1120 <= g.stage_frame < 1440 or g.scene() == 3) and g.tick//12%2:
            for i in range(32,48): self.oam[i*8+5] |= 4
        if g.state != PLAY:
            self.text(0,g.height//2-16,'GAME OVER' if g.state == OVER else 'ALL CLEAR' if g.state == ENDING else 'STAGE 1 CLEAR')
            self.text(16,g.height//2+8,'RETURN TO TITLE' if g.state == OVER else 'STAR FRONTIER')
            return
        owned = (g.power>0,g.missile_enabled,g.weapon==1,g.weapon==2,g.options>0,g.shield>0)
        for i in range(6):
            self.sprite(48+i,88+i*24,(g.height//8-3)*8+4,144+i*4,True,1 if g.gauge == i+1 else 2 if owned[i] else 0)
        if g.scene() == 3:
            self.text(0,g.height//2-16,'ENEMY APPROACH')
            if g.tick//10%2 == 0: self.text(16,g.height//2+8,'WARNING')
            return
        if not g.invincible or g.tick//5%2 == 0:
            self.sprite(0,div(g.x,256),div(g.y,256),300 if g.tick//4%2 else 4,True,2 if g.shield else 0)
        if g.shield: self.oam[5] |= 8
        if rays:
            self.beam(g.beams[0],1,0)
            self.beam(g.beams[1],22,1)
            self.beam(g.beams[2],26,1)
        if not any(b.active for b in g.beams):
            for i in range(4):
                s = g.shots[i]
                if s.active: self.sprite(i+1,div(s.x,256),div(s.y,256),8)
        slots = (5,6,30,7,8,31)
        b = g.boss
        if b.dying and b.death_age < 96 and b.death_age//4%2 == 0:
            for part in range(6):
                tile = 640+(part//3)*4 if part%3 == 2 else 48+(part//3*2+part%3)*4
                self.sprite(slots[part],div(b.x,256)+part%3*16,div(b.y,256)+part//3*16,tile,True,3)
        for i in range(4):
            e = g.enemies[i]
            if not e.active: continue
            if e.type == BOSS:
                period = 72 if b.hp > 66 else 56 if b.hp > 33 else 40
                charging = b.phase and b.age%period >= period-12
                for part in range(6):
                    turret = part in (2,5)
                    p = 1 if part == 5 else 0
                    if turret and not b.parts[p]: continue
                    tile = 640+p*4 if turret else (272 if charging else 48)+(part//3*2+part%3)*4
                    palette = 3 if g.enemy_flash[i] else 1 if charging and b.age//3%2 else 0
                    self.sprite(slots[part],div(e.x,256)+part%3*16,div(e.y,256)+part//3*16,tile,True,palette)
            else:
                alternate = e.age//8%2
                tile = (660 if alternate else 656) if e.type == 5 else 20 if e.type == 2 else (260 if alternate else 16) if e.type == 1 else (268 if alternate else 264) if e.type == 4 else (256 if alternate else 12)
                palette = 3 if g.enemy_flash[i] else 1 if e.carrier else 2 if e.phase&7 == 5 and e.type in (0,1,4) else 0
                self.sprite(5+i,div(e.x,256),div(e.y,256),tile,True,palette,e.type == 2 and e.phase != 0)
        for i in range(10):
            s = g.hostile[i]
            if s.active: self.sprite(9+i if i < 3 else 54+i,div(s.x,256),div(s.y,256),10)
        s = g.missile
        if s.active: self.sprite(12,div(s.x,256),div(s.y,256),11 if g.missile_grounded else 176)
        if g.pickup_active: self.sprite(13,div(g.pickup_x,256),div(g.pickup_y,256),36,True)
        for i in range(g.options):
            x,y = g.option_position(i)
            self.sprite(14+i,div(x,256),div(y,256),304 if g.tick//6%2 else 28,True)
        for i in range(6):
            e = g.effects[i]
            if e.ttl and e.y+16 <= (g.height//8-3)*8:
                self.sprite(16+i,e.x,e.y,288 if e.ttl > 14 else 32 if e.ttl > 7 else 44,True)
        if g.muzzle_timer:
            for source in range(g.options+1):
                if g.muzzle_mask&(1<<source):
                    x,y = g.option_position(source-1) if source else (g.x,g.y)
                    self.sprite(54+source,div(x,256)+13,div(y,256)+3,292)

    @micropython.native
    def count(self,slot,optional=False):
        peak = V.count(self.oam,self.lines,slot,len(self.lines),int(optional))
        if peak < 0:
            if optional: self.dropped += 1
            return False
        self.peak = max(self.peak,peak)
        return True

    @micropython.native
    def reserve(self):
        peak = V.admission(self.oam,self.lines,len(self.lines),1)
        if peak < 0: raise RuntimeError('STARFALL sprite budget')
        self.peak = max(self.peak,peak)

    @micropython.native
    def fit(self,g,rays):
        if rays:
            if not any(b.active for b in g.beams): return
        elif not any(s.active for s in g.hostile): return
        # HUD and gauge live outside the combat band. If even the sum of all
        # combat records fits one line, detailed admission cannot reject any.
        budget = 1+g.options+int(g.missile.active)+int(g.pickup_active)
        for e in g.enemies:
            if e.active: budget += 6 if e.type == BOSS else 1
        for s in g.hostile:
            if s.active: budget += 1
        if not any(b.active for b in g.beams):
            for s in g.shots:
                if s.active: budget += 1
        if rays:
            for b in g.beams:
                if b.active: budget += (b.length+15)//16
        if budget <= 16: return
        self.combat_lines(g,rays)
        if rays:
            segments = [0,0,0]
            for p in range(4):
                for ray in range(3):
                    b = g.beams[ray]
                    if not b.active or segments[ray] != p or b.length <= p*16: continue
                    if V.span(self.lines,div(b.y,256),16,g.height) >= 0: segments[ray] += 1
            for ray in range(3):
                b = g.beams[ray]
                b.length = min(b.length,segments[ray]*16)
                if not b.length: b.active = False
        else:
            for i in range(10):
                s = g.hostile[i]
                if not s.active: continue
                if V.span(self.lines,div(s.y,256),8,g.height) < 0: s.active = False

    @micropython.native
    def render(self,g):
        self.build(g)
        if g.state == PLAY:
            self.reserve()
            self.peak = max(self.peak,V.admission(self.oam,self.lines,g.height,2))
        else:
            peak = V.admission(self.oam,self.lines,g.height,0)
            if peak < 0: raise RuntimeError('STARFALL sprite budget')
            self.peak = max(self.peak,peak)
        return self.oam
