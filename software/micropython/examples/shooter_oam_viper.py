# SPDX-License-Identifier: Apache-2.0
"""Optional whole-OAM Viper kernel; same admission/order as the Python path.

Compile native .mpy with mpy-cross -march=armv6m for RP2040. Only buffers owned
by Game are accessed, and all slot/band indices are checked before writes.
"""
import micropython


@micropython.viper
def build(g) -> int:
    output = ptr8(g.oam)
    bands_used = ptr8(g.scanlines)
    hud = ptr8(g.hud_records)
    frame = int(g.frame)
    height = int(g.height)
    enhanced = int(g.enhanced)
    dead = int(g.dead)
    power = int(g.power)
    load = 0
    if g.load == 'HEAVY':
        load = 1
    elif g.load == 'STRESS':
        load = 2
    elif g.load == 'EXTREME':
        load = 3
    count = 32
    if enhanced or load != 0:
        count = 64
        if load == 3:
            count = int(g.extreme_sprites)
        elif load < 2 and int(g.particle_limit) >= 32:
            count = 128
    previous = int(g.oam_count)
    upload = count
    if previous > upload:
        upload = previous
    for i in range(upload):
        output[i * 8 + 3] = 0
    for i in range(32):
        bands_used[i] = 0
    bands_used[1] = 16
    slot = 0
    active = 16
    culled = 0
    capacity = count - 16
    # Groups preserve Python's exact priority: ship, option, bullets, enemies,
    # hostile shots, pickup, explosion, stars, particles, stress filler.
    for group in range(10):
        size = 0
        if group == 0:
            if dead == 0 and (int(g.invincible) == 0 or (frame & 2) != 0):
                size = 2 + enhanced
        elif group == 1:
            if power >= 3 and dead == 0:
                size = 1
        elif group >= 2 and group <= 4:
            pool = g.bullets
            if group == 3:
                pool = g.enemies
            elif group == 4:
                pool = g.hostile
            px = ptr16(pool.x)
            py = ptr16(pool.y)
            life = ptr16(pool.life)
            size = int(pool.size)
        elif group == 5:
            if int(g.pickup_x) > -16:
                size = 1
        elif group == 6:
            if int(g.burst_life) != 0:
                size = 1
        elif group == 7:
            if enhanced:
                px = ptr16(g.stars_x)
                py = ptr16(g.stars_y)
                size = 8
        elif group == 8:
            if enhanced:
                pool = g.particles
                px = ptr16(pool.x)
                py = ptr16(pool.y)
                life = ptr16(pool.life)
                kind = ptr8(pool.kind)
                size = int(g.particle_limit)
        elif group == 9:
            if load >= 2:
                px = ptr16(g.stress_x)
                size = capacity - slot
        for j in range(size):
            if group >= 2 and slot >= capacity:
                break
            x = 0
            y = 0
            tile = 0
            index = slot
            if group == 0:
                x = int(g.x)
                y = int(g.y)
                tile = j + 1
                if j == 1:
                    x += 8
                elif j == 2:
                    x -= 8
                    tile = 5
                    if frame & 1:
                        tile = 11
            elif group == 1:
                tx = ptr16(g.trail_x)
                ty = ptr16(g.trail_y)
                head = int(g.trail_index)
                x = int(tx[head])
                y = int(ty[head])
                tile = 5
            elif group >= 2 and group <= 4:
                if int(life[j]) == 0:
                    continue
                x = int(px[j])
                y = int(py[j])
                tile = 3
                if group == 2:
                    if enhanced and (frame & 2):
                        tile = 15
                elif group == 3:
                    tile = 4
                else:
                    tile = 10
            elif group == 5:
                x = int(g.pickup_x)
                y = int(g.pickup_y)
                tile = 7
            elif group == 6:
                x = int(g.burst_x)
                y = int(g.burst_y)
                tile = 6
            elif group == 7:
                x = int(px[j]) // 4
                y = int(py[j])
                tile = 13 + (j & 1)
            elif group == 8:
                if int(life[j]) == 0:
                    continue
                x = int(px[j])
                y = int(py[j])
                tile = 12
                if int(kind[j]):
                    tile = 14
            else:
                # slot advances after each filler, exactly as index j+start.
                index = slot
                x = (int(px[index]) - frame * (1 + index % 3)) % 312
                if x < 0:
                    x += 312
                y = 24 + (index % ((height - 40) // 10)) * 10
                if load == 3:
                    y = 40 + (index % 4) * 4
                tile = 12 + (index & 1)
            # array('h') is read through an unsigned pointer in Viper.
            if x >= 32768:
                x -= 65536
            if y >= 32768:
                y -= 65536
            admitted = 0
            if x >= -8 and x < 320 and y >= 0 and y < height:
                first = y >> 3
                last = (y + 7) >> 3
                limited = 1
                if group == 9 and load == 3:
                    limited = 0
                if limited and (int(bands_used[first]) >= 16 or int(bands_used[last]) >= 16):
                    culled += 1
                else:
                    if int(bands_used[first]) < 255:
                        bands_used[first] += 1
                    if last != first and int(bands_used[last]) < 255:
                        bands_used[last] += 1
                    offset = index * 8
                    output[offset] = x & 255
                    output[offset + 1] = (x >> 8) & 3
                    output[offset + 2] = y & 255
                    output[offset + 3] = ((y >> 8) & 3) | 4
                    output[offset + 4] = tile
                    active += 1
                    admitted = 1
            # Only particles compact rejected entries; all other groups retain
            # their disabled slots, including offscreen/culling failures.
            if group != 8 or admitted:
                slot += 1
    for i in range(128):
        output[capacity * 8 + i] = hud[i]
    g.oam_count = count
    g.oam_bytes = upload * 8
    g.active_sprites = active
    old_culled = int(g.stats.particle_culled)
    g.stats.particle_culled = old_culled + culled
    return upload
