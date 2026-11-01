# SPDX-License-Identifier: Apache-2.0
"""Integer-only OAM packing and scanline admission, shared by all game states."""
import micropython


@micropython.viper
def span(lines,y:int,size:int,height:int)->int:
    line = ptr8(lines)
    start = y if y > 0 else 0
    end = y+size if y+size < height else height
    for j in range(start,end):
        if int(line[j]) >= 16: return -1
    peak = 0
    for j in range(start,end):
        n = int(line[j])+1
        line[j] = n
        if n > peak: peak = n
    return peak


@micropython.viper
def rectangles(lines,rects,n:int,height:int)->int:
    line = ptr8(lines)
    r = ptr32(rects)
    for y in range(height): line[y] = 0
    for i in range(0,n,2):
        y = int(r[i])
        size = int(r[i+1])
        start = y if y > 0 else 0
        end = y+size if y+size < height else height
        for j in range(start,end):
            if int(line[j]) >= 16: return -1
        for j in range(start,end): line[j] = int(line[j])+1
    return 0


@micropython.viper
def music(wanted, scores, steps, cue:int, tick:int):
    w = ptr8(wanted)
    s = ptr8(scores)
    pitches = ptr32(steps)
    a = cue*56
    frames = int(s[a])
    length = int(s[a+1])
    step = tick//frames
    phase = tick%frames
    stopped = int(s[a+6]) and step >= length
    step = step%length
    root = int(s[a+40+(step%8 if length <= 8 else (step//4)%8)])
    arp = 0 if step%4 == 0 else int(s[a+2]) if step%4 == 1 else 7 if step%4 == 2 else 12
    melody = int(s[a+8+step])
    fade = tick//3
    if fade > 4: fade = 4
    for v in range(4):
        ch = v if v < 2 else v+2
        note = melody if v == 0 else root+12+arp if v == 1 else root if v == 2 else root+19
        gain = int(s[a+4]) if v == 0 else 8 if v == 1 else 14 if v == 2 else int(s[a+5])
        if stopped or not note or (v < 2 and phase >= frames-2) or (v == 3 and not melody): gain = 0
        gain = gain*fade//4
        pitch = 0 if stopped else int(pitches[note])
        b = ch*16
        w[b] = pitch&255
        w[b+1] = (pitch>>8)&255
        w[b+2] = (pitch>>16)&255
        w[b+4] = gain
        w[b+5] = gain
        w[b+6] = 1 if gain else 0
    w[3] = int(s[a+3])
    w[19] = 128
    period = 0
    gain = 0
    if phase < 2 and fade and not stopped:
        bit = 1<<(step%16)
        kicks = int(s[a+48])|(int(s[a+49])<<8)
        snares = int(s[a+50])|(int(s[a+51])<<8)
        hats = int(s[a+52])|(int(s[a+53])<<8)
        if kicks&bit:
            period = 80
            gain = 11
        elif snares&bit:
            period = 26
            gain = 9
        elif hats&bit:
            period = 5
            gain = 5
    w[56] = period
    w[57] = 0
    w[52] = gain
    w[53] = gain
    w[54] = 1 if gain else 0


@micropython.viper
def audio_diff(cache, wanted, ops)->int:
    old = ptr8(cache)
    new = ptr8(wanted)
    out = ptr8(ops)
    n = 0
    for i in range(96):
        value = int(new[i])
        if value != int(old[i]):
            out[n] = i
            out[n+1] = value
            n += 2
            old[i] = value
    return n


@micropython.viper
def sprite(oam,slot:int,x:int,y:int,tile:int,flags:int,palette:int):
    o = ptr8(oam)
    a = slot*8
    x = x&1023
    y = y&1023
    o[a] = x&255
    o[a+1] = x>>8
    o[a+2] = y&255
    o[a+3] = (y>>8)|4|flags
    o[a+4] = tile&255
    o[a+5] = ((tile>>8)&3)|((tile>>4)&64)|(palette<<2)


@micropython.viper
def dirty(oam, previous, spans)->int:
    current = ptr32(oam)
    old = ptr32(previous)
    out = ptr16(spans)
    i = 0
    n = 0
    while i < 64:
        if current[i*2] == old[i*2] and current[i*2+1] == old[i*2+1]:
            i += 1
            continue
        first = i
        i += 1
        while i < 64:
            if current[i*2] == old[i*2] and current[i*2+1] == old[i*2+1]: break
            i += 1
        out[n] = first*8
        out[n+1] = i*8
        n += 2
    return n


@micropython.viper
def text(oam, message, slot:int, y:int, length:int):
    o = ptr8(oam)
    s = ptr8(message)
    x = (320-length*8)//2
    for i in range(length):
        ch = int(s[i])
        if ch == 32: continue
        a = (slot+i)*8
        sx = x+i*8
        o[a] = sx&255
        o[a+1] = sx>>8
        o[a+2] = y&255
        o[a+3] = (y>>8)|4
        o[a+4] = 32+ch


@micropython.viper
def count(oam, lines, slot:int, height:int, optional:int)->int:
    o = ptr8(oam)
    line = ptr8(lines)
    a = slot*8
    flags = int(o[a+3])
    if not flags&4: return 0
    y = int(o[a+2])|((flags&3)<<8)
    if y&512: y -= 1024
    size = 16 if flags&8 else 8
    start = y if y > 0 else 0
    end = y+size if y+size < height else height
    for j in range(start,end):
        if int(line[j]) >= 16:
            if optional:
                for k in range(8): o[a+k] = 0
            return -1
    peak = 0
    for j in range(start,end):
        n = int(line[j])+1
        line[j] = n
        if n > peak: peak = n
    return peak


@micropython.viper
def admission(oam, lines, height:int, mode:int)->int:
    # One native call for all 64 records. Mode 0=all, 1=gameplay, 2=decorations.
    o = ptr8(oam)
    line = ptr8(lines)
    if mode != 2:
        for y in range(height): line[y] = 0
    peak = 0
    for slot in range(64):
        decorative = (slot >= 16 and slot < 22) or (slot >= 54 and slot < 57)
        if mode == 1 and decorative: continue
        if mode == 2 and not decorative: continue
        a = slot*8
        flags = int(o[a+3])
        if not flags&4: continue
        y = int(o[a+2])|((flags&3)<<8)
        if y&512: y -= 1024
        size = 16 if flags&8 else 8
        start = y if y > 0 else 0
        end = y+size if y+size < height else height
        fits = 1
        for j in range(start,end):
            if int(line[j]) >= 16: fits = 0
        if not fits:
            if mode != 2: return -1
            for k in range(8): o[a+k] = 0
            continue
        for j in range(start,end):
            n = int(line[j])+1
            line[j] = n
            if n > peak: peak = n
    return peak
