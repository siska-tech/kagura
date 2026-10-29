# SPDX-License-Identifier: Apache-2.0
"""Internal Viper raster kernels. Only validated bounded arguments may enter.

params: signed 32-bit array; counters: eight uint32 entries. Caller owns buffer
lifetimes and clips rectangles to [0,320] x [0,240]. No device I/O here.
"""
import micropython


@micropython.viper
def fill_rect(buffer, dirty, params, counters):
    dst=ptr8(buffer)
    words=ptr32(buffer)
    marks=ptr8(dirty)
    p=ptr32(params)
    calls=ptr32(counters)
    calls[0]+=1
    x0=int(p[0]);y0=int(p[1]);x1=int(p[2]);y1=int(p[3]);c=int(p[4])
    pair=c*17
    word=uint(c)*uint(0x11111111)
    for ty in range(y0>>3, (y1+7)>>3):
        top=y0-(ty<<3)
        bottom=y1-(ty<<3)
        if top<0:top=0
        if bottom>8:bottom=8
        for tx in range(x0>>3, (x1+7)>>3):
            left=x0-(tx<<3)
            right=x1-(tx<<3)
            if left<0:left=0
            if right>8:right=8
            tile=ty*40+tx
            changed=0
            if left==0 and right==8 and top==0 and bottom==8:
                # Bytearrays and tile offsets are word-aligned on RP2040.
                base=tile*8
                for k in range(8):
                    if uint(words[base+k])!=word:
                        words[base+k]=word
                        changed=1
            else:
                for yy in range(top,bottom):
                    base=tile*32+yy*4
                    for xx in range(left>>1,(right+1)>>1):
                        address=base+xx
                        old=int(dst[address])
                        value=pair
                        if (xx<<1)<left:
                            value=(old&240)|c
                        elif (xx<<1)+1>=right:
                            value=(old&15)|(c<<4)
                        if old!=value:
                            dst[address]=value
                            changed=1
            if changed:marks[tile]=1


@micropython.viper
def pixel(buffer, dirty, params, counters):
    dst=ptr8(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    calls[1]+=1
    x=int(p[0]);y=int(p[1]);c=int(p[2])
    tile=(y>>3)*40+(x>>3)
    address=tile*32+(y&7)*4+((x&7)>>1)
    shift=4
    if x&1:shift=0
    old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
    if old!=value:
        dst[address]=value;marks[tile]=1


@micropython.viper
def line(buffer, dirty, params, counters):
    dst=ptr8(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    calls[2]+=1
    x=int(p[0]);y=int(p[1]);endx=int(p[2]);endy=int(p[3]);c=int(p[4])
    dx=endx-x;dy=endy-y;sx=1;sy=1
    if dx<0:dx=-dx;sx=-1
    if dy<0:dy=-dy;sy=-1
    error=dx-dy
    while True:
        if x>=0 and x<320 and y>=0 and y<240:
            tile=(y>>3)*40+(x>>3)
            address=tile*32+(y&7)*4+((x&7)>>1)
            shift=4
            if x&1:shift=0
            old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
            if old!=value:dst[address]=value;marks[tile]=1
        if x==endx and y==endy:break
        twice=error*2
        if twice>=-dy:error-=dy;x+=sx
        if twice<=dx:error+=dx;y+=sy


@micropython.viper
def circle(buffer, dirty, params, counters):
    dst=ptr8(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    calls[3]+=1
    cx=int(p[0]);cy=int(p[1]);a=int(p[2]);c=int(p[3]);b=0;decision=1-a
    while b<=a:
        for k in range(8):
            xx=a;yy=b
            if k&1:xx=b;yy=a
            if k&2:xx=-xx
            if k&4:yy=-yy
            x=cx+xx;y=cy+yy
            if x>=0 and x<320 and y>=0 and y<240:
                tile=(y>>3)*40+(x>>3)
                address=tile*32+(y&7)*4+((x&7)>>1)
                shift=4
                if x&1:shift=0
                old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
                if old!=value:dst[address]=value;marks[tile]=1
        b+=1
        if decision<0:decision+=b*2+1
        else:a-=1;decision+=(b-a)*2+1


@micropython.viper
def glyph(buffer, dirty, params, counters, bitmap):
    dst=ptr8(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters);bits=ptr8(bitmap)
    calls[4]+=1
    x0=int(p[0]);y0=int(p[1]);c=int(p[2])
    # MONO_HLSB is bit7 at x=0 in MicroPython v1.26 modframebuf.c.
    for yy in range(8):
        row=int(bits[yy]);y=y0+yy
        if y>=0 and y<240:
            for xx in range(8):
                x=x0+xx
                if x>=0 and x<320 and row&(128>>xx):
                    tile=(y>>3)*40+(x>>3)
                    address=tile*32+(y&7)*4+((x&7)>>1)
                    shift=4
                    if x&1:shift=0
                    old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
                    if old!=value:dst[address]=value;marks[tile]=1


@micropython.viper
def blit(buffer, dirty, params, counters, source):
    dst=ptr8(buffer);words=ptr32(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    src=ptr8(source);swords=ptr32(source)
    calls[5]+=1
    x0=int(p[0]);y0=int(p[1]);x1=int(p[2]);y1=int(p[3]);ox=int(p[4]);oy=int(p[5])
    fmt=int(p[6]);pitch=int(p[7]);key=int(p[8]);aligned=int(p[9])
    # Source above/left of the destination: walk backwards (memmove order).
    backx=0
    if ox<0:backx=1
    backy=0
    if oy<0:backy=1
    tfirst=x0>>3;tlast=(x1-1)>>3
    if fmt==1 and key<0 and aligned!=0 and ((x0|y0|x1|y1|ox|oy)&7)==0:
        for ny in range((y1-y0)>>3):
            ty=(y0>>3)+ny
            if backy:ty=((y1>>3)-1)-ny
            for nt in range(tlast-tfirst+1):
                tx=tfirst+nt
                if backx:tx=tlast-nt
                tile=ty*40+tx
                s=((ty+(oy>>3))*pitch+tx+(ox>>3))*8
                d=tile*8
                changed=0
                for k in range(8):
                    w=int(swords[s+k])
                    if int(words[d+k])!=w:
                        words[d+k]=w
                        changed=1
                if changed:marks[tile]=1
        return
    for ny in range(y1-y0):
        y=y0+ny
        if backy:y=y1-1-ny
        v=y+oy
        srow=v*pitch
        if fmt==1:srow=(v>>3)*pitch*32+(v&7)*4
        drow=(y>>3)*1280+(y&7)*4
        for nt in range(tlast-tfirst+1):
            tx=tfirst+nt
            if backx:tx=tlast-nt
            xa=tx<<3;xb=xa+8
            if xa<x0:xa=x0
            if xb>x1:xb=x1
            tile=(y>>3)*40+tx
            dbase=drow+(tx<<5)
            changed=0
            if key<0 and aligned!=0 and (ox&7)==0 and xb-xa==8:
                u=xa+ox
                s=srow+(u>>1)
                if fmt==1:s=srow+(u>>3)*32
                w=int(swords[s>>2])
                if int(words[dbase>>2])!=w:
                    words[dbase>>2]=w
                    changed=1
            elif (ox&1)==0:
                ba=xa>>1;bb=(xb-1)>>1
                for nb in range(bb-ba+1):
                    bx=ba+nb
                    if backx:bx=bb-nb
                    px=bx<<1
                    # Even ox: both nibbles come from one source byte; never index u<0.
                    u=px+ox
                    if px<xa:u=xa+ox
                    s=srow+(u>>1)
                    if fmt==1:s=srow+(u>>3)*32+((u&7)>>1)
                    sv=int(src[s])
                    address=dbase+((px&7)>>1)
                    old=int(dst[address])
                    value=old
                    if px>=xa:
                        if key<0 or (sv>>4)!=key:value=(value&15)|(sv&240)
                    if px+1<xb:
                        if key<0 or (sv&15)!=key:value=(value&240)|(sv&15)
                    if value!=old:
                        dst[address]=value
                        changed=1
            else:
                for nx in range(xb-xa):
                    x=xa+nx
                    if backx:x=xb-1-nx
                    u=x+ox
                    s=srow+(u>>1)
                    if fmt==1:s=srow+(u>>3)*32+((u&7)>>1)
                    sv=int(src[s])
                    c=sv>>4
                    if u&1:c=sv&15
                    if c!=key:
                        address=dbase+((x&7)>>1)
                        shift=4
                        if x&1:shift=0
                        old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
                        if old!=value:
                            dst[address]=value
                            changed=1
            if changed:marks[tile]=1

