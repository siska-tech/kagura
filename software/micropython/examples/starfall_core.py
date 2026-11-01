# SPDX-License-Identifier: Apache-2.0
"""PROJECT STARFALL Stage 1 logic, ported from software/starfall (Q8, 60 Hz).

No device, filesystem or clock access. Pools are allocated once per game.
"""
import micropython

LEFT, RIGHT, UP, DOWN, FIRE, EQUIP = 1, 2, 4, 8, 16, 32
TITLE, PLAY, OVER, CLEAR, BOOT, INTRO, ENDING = range(7)
SCOUT, WAVE, TURRET, BOSS, DIVER, METEOR = range(6)
NORMAL, DOUBLE, LASER = range(3)
NAMES = ('NORMAL', 'SPEED', 'MISSILE', 'DOUBLE', 'LASER', 'OPTION', 'SHIELD')
WAVES = ((90,0,128,4,20,0),(310,0,96,4,0,1),(550,4,128,2,0,4),
         (790,1,128,4,22,3),(1030,5,80,2,48,0),(1270,1,150,4,22,6),
         (1450,2,220,2,64,0),(1630,0,128,2,22,5),(1790,2,30,2,64,0),
         (1950,1,170,3,22,2),(2130,2,220,2,64,0),(2290,0,100,3,22,1),
         (2420,1,150,3,22,6),(2600,0,128,2,20,0),(2760,3,128,1,1,0))
SINE = (0,6,12,18,23,27,30,31,32,31,30,27,23,18,12,6,
        0,-6,-12,-18,-23,-27,-30,-31,-32,-31,-30,-27,-23,-18,-12,-6)


@micropython.native
def div(a, b):
    # C integer division truncates towards zero, including negative movement.
    return a // b if a >= 0 else -((-a) // b)


@micropython.native
def terrain(col, height):
    bottom = (height // 8 - 3) * 8
    if col < 180:
        return 0, bottom
    if col >= 336:
        return 24, bottom - 8
    entrance = col - 180
    if entrance < 8:
        depth = min(entrance + 1, 3) * 8
        return depth, bottom - depth
    c = col & 63
    upper = 1 if 12 <= c < 16 else 2 if 16 <= c < 24 else 1 if 24 <= c < 28 or 44 <= c < 52 else 0
    lower = 1 if 28 <= c < 32 else 2 if 32 <= c < 40 else 1 if 40 <= c < 44 or c >= 56 else 0
    return (3 + upper) * 8, bottom - (3 + lower) * 8


@micropython.native
def overlap(x,y,w,h,bx,by,bw,bh):
    return x < bx+bw and x+w > bx and y < by+bh and y+h > by


class Item:
    def __init__(self):
        self.x = self.y = self.vx = self.vy = self.age = self.hp = 0
        self.origin_y = self.type = self.phase = self.ttl = 0
        self.active = self.carrier = False
        self.hit_mask = self.length = 0
        self.serial = [0,0,0,0]


class Game:
    def __init__(self, height=240, seed=0x53544152):
        if height not in (180,240):
            raise ValueError('height')
        self.height, self.seed = height, seed
        self.shots = [Item() for _ in range(4)]
        self.shot_vy = [0]*4
        self.enemies = [Item() for _ in range(4)]
        self.hostile = [Item() for _ in range(10)]
        self.effects = [Item() for _ in range(6)]
        self.beams = [Item() for _ in range(3)]
        self.missile = Item()
        self.boss = Item()
        self.boss.parts = [0,0]
        self.boss.dying = False
        self.boss.death_age = self.boss.slot = self.boss.max_hp = 0
        self.history_x, self.history_y = [0]*32, [0]*32
        self.enemy_group, self.enemy_world_x = [0]*4, [0]*4
        self.enemy_serial, self.enemy_flash = [0]*4, [0]*4
        self.group_remaining = [0]*16
        # Renderer is injected by the runner; budget is fitted before collision.
        self.fit = None
        self.tick = 0
        self.reset()

    def reset(self):
        self.x, self.y = 40*256, (self.height//2-8)*256
        self.lives, self.state = 3, TITLE
        for name in ('scroll','cooldown','stage_tick','score','invincible','state_age',
                     'power','options','history_pos','event_index','sound','gauge','weapon',
                     'shield','missile_cooldown','emitter','capsule_queue','group_failed',
                     'group_rewarded','wave_spawned','missile_vy','boss_defeat_tick',
                     'muzzle_mask','muzzle_timer','stage_frame','demo_frame','idle_ticks','stage_index',
                     'pickup_x','pickup_y'):
            setattr(self,name,0)
        self.pickup_active = self.boss_dead = self.fire_was_down = False
        self.missile_enabled = self.equip_was_down = self.missile_grounded = False
        self.attract = self.start_was_down = False
        self.clear_combat()
        for i in range(4):
            self.enemy_group[i] = self.enemy_serial[i] = self.enemy_flash[i] = 0
        for i in range(16):
            self.group_remaining[i] = WAVES[i][3] if i < len(WAVES) else 0

    def start(self, demo=False):
        self.reset()
        self.state, self.invincible, self.attract = INTRO, 120, demo
        for i in range(32):
            self.history_x[i], self.history_y[i] = self.x, self.y

    @micropython.native
    def clear_combat(self):
        for pool in (self.enemies,self.hostile,self.shots,self.beams):
            for e in pool:
                e.active = False
        for e in self.effects:
            e.ttl = 0
        for i in range(4):
            self.enemy_world_x[i] = 0
        self.missile.active = self.pickup_active = False
        self.capsule_queue = self.muzzle_mask = self.muzzle_timer = 0
        self.cooldown = self.missile_cooldown = 0
        b = self.boss
        b.x = b.y = b.hp = b.max_hp = b.age = b.death_age = b.phase = b.slot = 0
        b.active = b.dying = False
        b.parts[0] = b.parts[1] = 0

    @micropython.native
    def scene(self):
        if self.boss_dead: return 5
        if self.stage_frame >= 2760: return 4
        if self.stage_frame >= 2640: return 3
        if self.stage_frame >= 2200: return 2
        return 1 if self.stage_frame >= 1120 else 0

    @micropython.native
    def sound_event(self, sound):
        self.sound = max(self.sound, sound)

    @micropython.native
    def explode(self,x,y):
        for e in self.effects:
            if not e.ttl:
                e.x,e.y,e.ttl = x,y,20
                break

    @micropython.native
    def option_position(self, option):
        h = (self.history_pos+32-8*(option+1)) & 31
        x = self.history_x[h]-12*(option+1)*256
        y = self.history_y[h]+(8 if option else -8)*256
        return max(0,min(304*256,x)), max(24*256,min(((self.height//8-3)*8-16)*256,y))

    @micropython.native
    def player_step(self, keys):
        dx, dy = bool(keys&RIGHT)-bool(keys&LEFT), bool(keys&DOWN)-bool(keys&UP)
        axial = 512+min(self.power,3)*128
        speed = axial*181//256 if dx and dy else axial
        self.x = max(0,min(304*256,self.x+dx*speed))
        self.y = max(24*256,min(((self.height//8-3)*8-16)*256,self.y+dy*speed))
        self.history_pos = (self.history_pos+1)&31
        self.history_x[self.history_pos],self.history_y[self.history_pos] = self.x,self.y

    @micropython.native
    def terrain_hit(self,x,y,w,h):
        # Terrain is constant within each tile: test each intersected column.
        first, last = max(0,self.stage_tick+x)//8, (self.stage_tick+x+w-1)//8
        for col in range(first,last+1):
            top,bottom = terrain(col,self.height)
            if y < top or y+h > bottom: return True
        return False

    @micropython.native
    def hit_player(self):
        if self.state != PLAY or self.invincible or self.attract: return
        if self.shield:
            self.shield -= 1
            self.invincible = 45
            self.sound_event(3)
            return
        self.explode(div(self.x,256),div(self.y,256))
        self.sound_event(5)
        self.lives = max(0,self.lives-1)
        self.power = self.options = self.gauge = self.weapon = 0
        self.invincible = 180
        self.missile_enabled = False
        for pool in (self.shots,self.beams,self.hostile):
            for s in pool: s.active = False
        self.missile.active = False
        self.muzzle_mask = self.muzzle_timer = 0
        self.x,self.y = 40*256,(self.height//2-8)*256
        if not self.lives:
            self.clear_combat()
            self.state,self.state_age = OVER,0

    @micropython.native
    def drop_capsule(self,x,y):
        if not self.pickup_active:
            self.pickup_active,self.pickup_x,self.pickup_y = True,x,y
        elif self.capsule_queue < 8: self.capsule_queue += 1

    @micropython.native
    def equip(self):
        gauge = self.gauge
        if gauge == 1 and self.power < 3: self.power += 1
        elif gauge == 2 and not self.missile_enabled: self.missile_enabled = True
        elif gauge == 3 and self.weapon != DOUBLE: self.weapon = DOUBLE
        elif gauge == 4 and self.weapon != LASER: self.weapon = LASER
        elif gauge == 5 and self.options < 2: self.options += 1
        elif gauge == 6 and self.shield < 3: self.shield = 3
        else: return False
        self.gauge = self.cooldown = 0
        for pool in (self.beams,self.shots):
            for s in pool: s.active = False
        self.sound_event(3)
        return True

    @micropython.native
    def powerup_step(self):
        if not self.pickup_active and self.capsule_queue:
            self.capsule_queue -= 1
            self.pickup_active,self.pickup_x,self.pickup_y = True,280*256,self.height//2*256
        if not self.pickup_active: return
        self.pickup_x -= 256
        self.pickup_y = min(self.pickup_y,((self.height//8-3)*8-16)*256)
        if self.pickup_x < -16*256: self.pickup_active = False
        dx,dy = div(self.x-self.pickup_x,256),div(self.y-self.pickup_y,256)
        if -14 < dx < 14 and -14 < dy < 14:
            self.pickup_active = False
            self.gauge = self.gauge%6+1
            self.score += 500
            self.sound_event(3)

    @micropython.native
    def bullet_step(self,keys):
        if self.muzzle_timer:
            self.muzzle_timer -= 1
            if not self.muzzle_timer: self.muzzle_mask = 0
        for i in range(4):
            s = self.shots[i]
            if not s.active: continue
            s.x += 2048
            s.y += self.shot_vy[i]
            if s.x >= 81920 or s.y < 6144: s.active = False
        for b in self.beams:
            if not b.active: continue
            b.x += 3072
            b.age += 1
            if b.x >= 81920 or b.age > 28: b.active = False
        if self.cooldown: self.cooldown -= 1
        if keys&FIRE and not self.cooldown:
            if self.weapon == LASER:
                if not any(b.active for b in self.beams):
                    for source in range(self.options+1):
                        b = self.beams[source]
                        x,y = self.option_position(source-1) if source else (self.x,self.y)
                        b.x,b.y,b.hit_mask,b.age,b.length,b.active = x+3584,y+1024,0,0,64,True
                    self.muzzle_mask,self.muzzle_timer,self.cooldown = (1<<(self.options+1))-1,3,6
                    self.sound_event(1)
            else:
                for i in range(4):
                    s = self.shots[i]
                    if s.active: continue
                    source = self.emitter%(self.options+1)
                    self.emitter = (self.emitter+1)&255
                    x,y = self.option_position(source-1) if source else (self.x,self.y)
                    s.x,s.y,s.active = x+3584,y+1024,True
                    self.muzzle_mask,self.muzzle_timer = 1<<source,3
                    self.shot_vy[i] = -512 if self.weapon == DOUBLE and self.emitter%2 == 0 else 0
                    self.cooldown = 6
                    self.sound_event(1)
                    break
        if self.missile_cooldown: self.missile_cooldown -= 1
        s = self.missile
        if s.active:
            s.x += 1280 if self.missile_grounded else 128
            if not self.missile_grounded:
                if self.missile_vy < 1024: self.missile_vy += 64
                s.y += self.missile_vy
            world = self.stage_tick+div(s.x,256)
            top,bottom = terrain(world//8,self.height)
            if world < 1440:
                self.missile_grounded = False
                if s.y > ((self.height//8-3)*8-8)*256: s.active = False
            elif s.y >= (bottom-8)*256 or self.missile_grounded:
                s.y,self.missile_grounded,self.missile_vy = (bottom-8)*256,True,0
            if s.x >= 81920 or s.y < top*256: s.active = False
        if keys&FIRE and self.missile_enabled and not s.active and not self.missile_cooldown:
            s.x,s.y,s.active = self.x+1536,self.y+3072,True
            self.missile_cooldown,self.missile_vy,self.missile_grounded = 24,256,False
        for s in self.hostile:
            if not s.active: continue
            s.x += s.vx
            s.y += s.vy
            if s.x < -2048 or s.x >= 81920 or s.y < 6144 or s.y > ((self.height//8-3)*8-8)*256:
                s.active = False

    @micropython.native
    def enemy_fire(self,x,y):
        for s in self.hostile:
            if s.active: continue
            dx,dy = div(self.x-x,256),div(self.y-y,256)
            scale = max(abs(dx),abs(dy),1)
            s.x,s.y,s.vx,s.vy,s.active = x,y,div(dx*640,scale),div(dy*640,scale),True
            break

    @micropython.native
    def stage_step(self):
        before = self.scene()
        self.stage_frame += 2 if self.attract else 1
        if self.stage_frame <= 2640: self.stage_tick = self.stage_frame
        self.scroll = self.stage_tick&511
        if before != 3 and self.scene() == 3:
            self.clear_combat()
            self.sound_event(4)
        if self.scene() == 3: return
        while self.event_index < len(WAVES):
            tick,kind,lane,count,gap,formation = WAVES[self.event_index]
            if self.stage_frame < tick+self.wave_spawned*gap: break
            if kind == BOSS:
                for e in self.enemies: e.active = False
            slot = 0
            while slot < 4 and self.enemies[slot].active: slot += 1
            if slot < 4:
                y = 40+lane*((self.height//8-3)*8-88)//256
                x = -16 if formation == 5 else 320
                if formation == 1:
                    y += (self.wave_spawned*2-3)*6
                    if self.wave_spawned in (1,2): x -= 16
                if formation == 4: y = (self.height//8-3)*8-40 if self.wave_spawned%2 else 40
                if kind == TURRET:
                    top,bottom = terrain((self.stage_tick+320)//8,self.height)
                    y = top if lane < 128 else bottom-16
                e = self.enemies[slot]
                e.x,e.y,e.origin_y,e.age = x*256,y*256,y,0
                e.hp = 100 if kind == BOSS else 3 if kind in (TURRET,METEOR) else 1
                e.type,e.phase,e.active = kind,(1 if lane < 128 else 0) if kind == TURRET else formation,True
                e.carrier = self.wave_spawned == 0 and formation == 6
                self.enemy_flash[slot] = 0
                self.enemy_group[slot] = self.event_index+1
                self.enemy_world_x[slot] = self.stage_tick+x
                self.enemy_serial[slot] = self.enemy_serial[slot]%65535+1
                if kind == BOSS:
                    b = self.boss
                    b.hp,b.max_hp,b.parts[0],b.parts[1],b.slot,b.active = 100,100,12,12,slot,True
            else: self.group_failed |= 1<<self.event_index
            self.wave_spawned += 1
            if self.wave_spawned >= count:
                self.wave_spawned = 0
                self.event_index += 1

    @micropython.native
    def boss_step(self):
        b = self.boss
        if not b.active: return
        e = self.enemies[b.slot]
        b.age += 1
        if e.x > 61440: e.x -= 256
        t = (b.age//2)%128
        dy = t-32 if t < 64 else 96-t
        period = 72 if b.hp > 66 else 56 if b.hp > 33 else 40
        cycle = b.age%period
        if b.age <= 80 or 24 <= cycle < period-12:
            e.y = (self.height//2-16+div(dy*3,4))*256
        b.x,b.y = e.x,e.y
        b.phase = 0 if b.age <= 80 else 1 if b.hp > 66 else 2 if b.hp > 33 else 3
        if not b.phase: return
        if b.hp <= 33 and b.age%24 == 0: self.explode(div(e.x,256)+24,div(e.y,256)+8)
        if cycle == 0 and b.parts[0]: self.enemy_fire(e.x+8192,e.y+1536)
        if cycle == 8 and b.parts[1]: self.enemy_fire(e.x+8192,e.y+6144)
        if cycle == 16 or (not b.parts[0] and not b.parts[1] and cycle == 0):
            for n in range(-2,3):
                if b.phase == 1 and n in (-1,1): continue
                for s in self.hostile:
                    if s.active: continue
                    s.x,s.y,s.vx,s.vy,s.active = e.x,e.y+4096,-512,n*224,True
                    break

    @micropython.native
    def enemy_step(self):
        for i in range(4):
            if self.enemy_flash[i]: self.enemy_flash[i] -= 1
            e = self.enemies[i]
            if not e.active: continue
            e.age += 1
            kind,age = e.type,e.age
            if kind == SCOUT:
                e.x += 640 if e.phase&7 == 5 else -640 if age < 48 else -768
                if age >= 48: e.y = (e.origin_y+div(SINE[((age-48)//4)&31],2))*256
            elif kind == WAVE:
                e.x -= 512
                e.y = (e.origin_y+SINE[(age//(2 if e.phase&7 == 3 else 3))&31])*256
            elif kind == METEOR:
                e.x -= 384
                e.y = (e.origin_y+div(SINE[(age//5)&31],4))*256
            elif kind == TURRET:
                e.x = (self.enemy_world_x[i]-self.stage_tick)*256
                if age%80 == 40: self.enemy_fire(e.x,e.y+2048)
            elif kind == DIVER:
                e.x -= 512 if age < 32 else 896
                if age == 32: e.origin_y = div(self.y,256)
                if 32 <= age < 96: e.y += max(-384,min(384,e.origin_y*256-e.y))
            elif kind == BOSS: self.boss_step()
            if kind != TURRET:
                world = self.stage_tick+div(e.x,256)
                top,bottom = terrain(max(world,0)//8,self.height)
                for dx in range(7,48 if kind == BOSS else 16,8):
                    t,b = terrain(max(world+dx,0)//8,self.height)
                    top,bottom = max(top,t),min(bottom,b)
                e.y = max(max(top,24)*256,min(e.y,(bottom-(32 if kind == BOSS else 16))*256))
            if kind in (SCOUT,WAVE,DIVER) and age%120 == 90: self.enemy_fire(e.x,e.y+2048)
            if e.x < -8192 or e.x > 86016:
                group = self.enemy_group[i]
                if group: self.group_failed |= 1<<(group-1)
                e.active = False

    @micropython.native
    def damage(self,j,amount):
        e = self.enemies[j]
        if e.hp > amount:
            e.hp -= amount
            self.enemy_flash[j] = 6
            return
        e.active = False
        self.explode(div(e.x,256),div(e.y,256))
        self.sound_event(2)
        self.score += 300 if e.type == TURRET else 200 if e.type == METEOR else 100
        group = self.enemy_group[j]
        if e.carrier and (not group or not self.group_rewarded&(1<<(group-1))):
            self.drop_capsule(e.x,e.y)
            if group: self.group_rewarded |= 1<<(group-1)
        if not group: return
        index = group-1
        if not self.group_remaining[index]: return
        self.group_remaining[index] -= 1
        if not self.group_remaining[index] and not self.group_failed&(1<<index) and WAVES[index][1] in (SCOUT,WAVE,DIVER):
            self.score += 500
            if not self.group_rewarded&(1<<index):
                self.drop_capsule(e.x,e.y)
                self.group_rewarded |= 1<<index

    @micropython.native
    def hit(self,j,x,y,w,h,amount):
        if self.enemies[j].type != BOSS:
            self.damage(j,amount)
            return True
        b = self.boss
        if not b.active or not b.phase: return False
        e = self.enemies[b.slot]
        bx,by = div(e.x,256),div(e.y,256)
        for part in range(2):
            if b.parts[part] and overlap(x,y,w,h,bx+32,by+(20 if part else 0),16,12):
                b.parts[part] = max(0,b.parts[part]-amount)
                self.enemy_flash[b.slot] = 6
                if not b.parts[part]:
                    self.score += 1000
                    self.explode(bx+32,by+part*16)
                    self.sound_event(2)
                return True
        if not overlap(x,y,w,h,bx,by+10,24,12): return False
        b.hp = max(0,b.hp-amount)
        e.hp,self.enemy_flash[b.slot] = b.hp,6
        if not b.hp:
            px,py = e.x,e.y
            self.clear_combat()
            b.x,b.y,b.dying = px,py,True
            self.boss_dead,self.boss_defeat_tick = True,self.stage_frame
            self.score += 5000
            self.explode(div(px,256),div(py,256))
            self.sound_event(2)
        return True

    @micropython.native
    def collision_step(self):
        px,py = div(self.x,256),div(self.y,256)
        if self.terrain_hit(px+5,py+5,6,6): self.hit_player()
        for s in self.shots:
            if not s.active: continue
            sx,sy = div(s.x,256),div(s.y,256)
            if self.terrain_hit(sx,sy+2,7,4):
                s.active = False
                continue
            for j in range(4):
                e = self.enemies[j]
                if not e.active: continue
                w,h = (48,32) if e.type == BOSS else (16,16)
                if overlap(sx,sy,8,8,div(e.x,256),div(e.y,256),w,h):
                    s.active = False
                    self.hit(j,sx,sy,8,8,1)
                    break
        for b in self.beams:
            if not b.active: continue
            bx,by,length = div(b.x,256),div(b.y,256),0
            while length < b.length and bx+length < 320:
                if self.terrain_hit(bx+length,by+4,1,4): break
                length += min(8-((self.stage_tick+bx+length)&7),b.length-length,320-bx-length)
            b.length = length
            if not length: b.active = False
        if self.fit: self.fit(self,True)
        for b in self.beams:
            bx,by = div(b.x,256),div(b.y,256)
            for i in range(4):
                if not b.active: break
                e = self.enemies[i]
                if not e.active or (b.hit_mask&(1<<i) and b.serial[i] == self.enemy_serial[i]): continue
                w,h = (48,32) if e.type == BOSS else (16,16)
                if overlap(bx,by+4,b.length,4,div(e.x,256),div(e.y,256),w,h) and self.hit(i,bx,by+4,b.length,4,3):
                    if b.active:
                        b.hit_mask |= 1<<i
                        b.serial[i] = self.enemy_serial[i]
        s = self.missile
        if s.active:
            for i in range(4):
                e = self.enemies[i]
                if not e.active: continue
                w,h = (48,32) if e.type == BOSS else (16,16)
                if overlap(div(s.x,256),div(s.y,256),8,8,div(e.x,256),div(e.y,256),w,h):
                    s.active = False
                    self.hit(i,div(s.x,256),div(s.y,256),8,8,2)
                    break
        for s in self.hostile:
            if not s.active: continue
            if self.terrain_hit(div(s.x,256),div(s.y,256),8,8):
                s.active = False
                continue
            if overlap(px+5,py+5,6,6,div(s.x,256)+2,div(s.y,256)+2,4,4):
                self.hit_player()
                if self.state != PLAY: return
        for e in self.enemies:
            if not e.active: continue
            w,h = (48,32) if e.type == BOSS else (16,16)
            if overlap(px+5,py+5,6,6,div(e.x,256)+2,div(e.y,256)+2,w-4,h-4): self.hit_player()

    @micropython.native
    def demo_input(self):
        keys = FIRE
        if self.demo_frame < 300:
            keys |= (RIGHT,RIGHT|UP,UP,LEFT|UP,LEFT,LEFT|DOWN,DOWN,RIGHT|DOWN)[(self.demo_frame//24)%8]
        else:
            x,y = 72*256,(self.height//2-8)*256
            if self.pickup_active: x,y = self.pickup_x,self.pickup_y
            else:
                for e in self.enemies:
                    if e.active:
                        y = e.y
                        if e.type == BOSS: x = 220*256
                        break
            x = min(x,248*256)
            top,bottom = terrain((self.stage_tick+div(self.x,256)+8)//8,self.height)
            y = max((top+8)*256,min(y,(bottom-24)*256))
            if self.x < x-512: keys |= RIGHT
            if self.x > x+512: keys |= LEFT
            if self.y < y-512: keys |= DOWN
            if self.y > y+512: keys |= UP
        equip = self.gauge == 1 if not self.power else self.gauge == 4 if self.weapon != LASER else not self.options and self.gauge == 5
        if equip and self.demo_frame%2 == 0: keys |= EQUIP
        return keys

    @micropython.native
    def step(self,keys=0):
        real = keys
        pressed = bool(real&FIRE) and not self.start_was_down
        self.sound = 0
        self.tick += 1
        self.state_age = min(65535,self.state_age+1)
        if self.attract:
            if pressed:
                self.start()
                self.start_was_down = True
                return
            self.demo_frame += 1
            if self.demo_frame >= 2400:
                self.reset()
                return
            keys = self.demo_input()
        for e in self.effects:
            if e.ttl:
                e.ttl -= 1
                e.x -= 1
        state = self.state
        if state == BOOT: self.reset()
        elif state == TITLE:
            if pressed: self.start()
            elif real: self.idle_ticks = 0
            else:
                self.idle_ticks += 1
                if self.idle_ticks >= 900: self.start(True)
        elif state == INTRO:
            if self.state_age >= (60 if self.attract else 120): self.state,self.state_age = PLAY,0
        elif state in (OVER,CLEAR,ENDING):
            limit = 240 if state == OVER else 300
            if (state == OVER or not self.attract) and (self.state_age >= limit or pressed and self.state_age > 60): self.reset()
        else:
            if self.invincible: self.invincible -= 1
            if self.scene() == 5:
                self.stage_frame += 2 if self.attract else 1
                b = self.boss
                b.death_age += 1
                if b.death_age%8 == 0:
                    n = b.death_age//8
                    self.explode(div(b.x,256)+(n*17)%48,div(b.y,256)+(n*11)%32)
                    self.sound_event(2)
                if b.death_age >= 120:
                    self.clear_combat()
                    self.state,self.state_age = CLEAR,0
                    self.score += 5000
            else:
                self.stage_step()
                self.player_step(keys)
                self.powerup_step()
                if self.scene() != 3:
                    if self.attract and 180 <= self.demo_frame <= 1800 and (self.demo_frame-180)%90 == 0 and not self.options and not self.pickup_active and not self.capsule_queue:
                        self.drop_capsule(self.x+5120,self.y)
                    if keys&EQUIP and not self.equip_was_down: self.equip()
                    self.bullet_step(keys)
                    self.enemy_step()
                    if self.fit: self.fit(self,False)
                    self.collision_step()
        self.start_was_down = bool(real&FIRE)
        self.fire_was_down = bool(keys&FIRE)
        self.equip_was_down = bool(keys&EQUIP)
