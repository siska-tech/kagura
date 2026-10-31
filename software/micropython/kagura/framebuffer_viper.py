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
def lines(buffer, dirty, segments, params) -> int:
    # params[0] records of (x0, y0, x1, y1, colour) in an array('i');
    # params[1] >= 0 replaces every colour. All records are checked before
    # any pixel changes; returns the first bad record or -1. Same stepping
    # as line() above.
    dst=ptr8(buffer);marks=ptr8(dirty);s=ptr32(segments);p=ptr32(params)
    n=int(p[0]);override=int(p[1])
    for k in range(n):
        for j in range(4):
            v=int(s[k*5+j])
            if v<-32767 or v>32767:return k
        c=int(s[k*5+4])
        if override<0 and (c<0 or c>15):return k
    for k in range(n):
        x=int(s[k*5]);y=int(s[k*5+1]);endx=int(s[k*5+2]);endy=int(s[k*5+3])
        c=override
        if c<0:c=int(s[k*5+4])
        # Wholly off screen: line() returns before stepping, so skip too.
        if (x<0 and endx<0) or (x>=320 and endx>=320) or (y<0 and endy<0) or (y>=240 and endy>=240):
            continue
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
    return -1


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


@micropython.viper
def ellipse(buffer, dirty, params, counters):
    dst=ptr8(buffer);words=ptr32(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    calls[6]+=1
    cx=int(p[0]);cy=int(p[1]);rx=int(p[2]);ry=int(p[3]);c=int(p[4]);solid=int(p[5])
    pair=c*17
    word=uint(c)*uint(0x11111111)
    rx2=rx*rx;ry2=ry*ry
    # a: row-rounded half width, U1(a,b)=4rx^2(ry^2-b^2)-(2a-1)^2ry^2 (>0 inside).
    # col: column-rounded, U2(col,b)=4ry^2(rx^2-col^2)-(2b-1)^2rx^2 (>0 inside).
    a=rx;u1=ry2*(4*rx-1);col=rx;u2=0
    ext=rx;b=0
    while b<=ry:
        if cy-b<0 and cy+b>239:break
        nb=b+1
        following=-1
        if nb<=ry:
            u1-=4*rx2*(2*nb-1)
            while a>0 and u1<=0:
                a-=1
                u1+=8*a*ry2
            if nb==1:u2=0-rx2
            else:u2-=8*(nb-1)*rx2
            while col>=0 and u2<=0:
                col-=1
                if col>=0:u2+=4*ry2*(2*col+1)
            following=a
            if col>following:following=col
        low=following+1
        if low>ext:low=ext
        for k in range(4):
            y=cy-b
            if k&1:
                if b==0:continue
                y=cy+b
            if y<0 or y>239:continue
            xa=cx-ext;xb=cx+ext
            if solid==0 and low>0:
                if k&2:xb=cx-low
                else:xa=cx+low
            elif k&2:continue
            if xa<0:xa=0
            if xb>319:xb=319
            rowbase=(y>>3)*1280+(y&7)*4;trow=(y>>3)*40
            x=xa
            while x<=xb:
                tile=trow+(x>>3);address=rowbase+((x>>3)<<5)+((x&7)>>1)
                if (x&7)==0 and x+7<=xb:
                    if uint(words[address>>2])!=word:
                        words[address>>2]=word;marks[tile]=1
                    x+=8
                elif (x&1)==0 and x+1<=xb:
                    if int(dst[address])!=pair:
                        dst[address]=pair;marks[tile]=1
                    x+=2
                else:
                    shift=4
                    if x&1:shift=0
                    old=int(dst[address]);value=(old&(255^(15<<shift)))|(c<<shift)
                    if old!=value:
                        dst[address]=value;marks[tile]=1
                    x+=1
        ext=following;b=nb


@micropython.viper
def paint(buffer, dirty, params, counters, stack):
    dst=ptr8(buffer);words=ptr32(buffer);marks=ptr8(dirty);p=ptr32(params);calls=ptr32(counters)
    st=ptr32(stack)
    calls[7]+=1
    sx=int(p[0]);sy=int(p[1]);old=int(p[2]);c=int(p[3]);cap=int(p[4])
    oldpair=old*17;newpair=c*17
    ones=uint(0x11111111);highs=ones<<3;allones=uint(0)-uint(1)
    oldword=uint(old)*ones;newword=uint(c)*ones
    sp=0;peak=0;dropped=0;spans=0;pixels=0;compactions=0
    # Entry: parent row | down<<8 | left<<9 | right<<18. Mirrors _python_paint:
    # a push is skipped unless its target segment still holds an old pixel.
    for k in range(2):
        pr=sy;pd=1
        if k==1:
            pr=sy+1;pd=-1
        t=pr+pd
        if t<0 or t>239:continue
        address=(t>>3)*1280+(t&7)*4+((sx>>3)<<5)+((sx&7)>>1)
        value=int(dst[address])>>4
        if sx&1:value=int(dst[address])&15
        if value==old:
            st[sp]=pr|((pd+1)<<7)|(sx<<9)|(sx<<18);sp+=1
    peak=sp
    while sp>0:
        sp-=1
        entry=int(st[sp])
        spans+=1
        dy=-1
        if entry&256:dy=1
        y=(entry&255)+dy;x1=(entry>>9)&511;x2=(entry>>18)&511
        rowbase=(y>>3)*1280+(y&7)*4;trow=(y>>3)*40
        x=x1
        while x>=0:
            address=rowbase+((x>>3)<<5)+((x&7)>>1)
            if (x&7)==7 and uint(words[(address-3)>>2])==oldword:
                x-=8
            elif (x&1)==1 and int(dst[address])==oldpair:
                x-=2
            else:
                value=int(dst[address])>>4
                if x&1:value=int(dst[address])&15
                if value!=old:break
                x-=1
        skip=1;leak=0;left=0
        if x<x1:
            skip=0
            left=x+1
            if left<x1:leak=1
            x=x1+1
        while True:
            if skip==0:
                while x<=319:
                    address=rowbase+((x>>3)<<5)+((x&7)>>1)
                    if (x&7)==0 and uint(words[address>>2])==oldword:
                        x+=8
                    elif (x&1)==0 and int(dst[address])==oldpair:
                        x+=2
                    else:
                        value=int(dst[address])>>4
                        if x&1:value=int(dst[address])&15
                        if value!=old:break
                        x+=1
                # Every pixel in [left,x) was old and becomes c: all tiles change.
                pixels+=x-left
                z=left
                while z<x:
                    tile=trow+(z>>3);address=rowbase+((z>>3)<<5)+((z&7)>>1)
                    marks[tile]=1
                    if (z&7)==0 and z+8<=x:
                        words[address>>2]=newword;z+=8
                    elif (z&1)==0 and z+2<=x:
                        dst[address]=newpair;z+=2
                    else:
                        if z&1:dst[address]=(int(dst[address])&240)|c
                        else:dst[address]=(int(dst[address])&15)|(c<<4)
                        z+=1
                # Single push site: continuation, then left/right leaks.
                for k in range(3):
                    pl=left;ph=x-1;pd=dy
                    if k==1:
                        if leak==0:continue
                        ph=x1-1;pd=0-dy;leak=0
                    elif k==2:
                        if x<=x2+1:continue
                        pl=x2+1;pd=0-dy
                    t=y+pd
                    if t<0 or t>239:continue
                    live=0;rb=(t>>3)*1280+(t&7)*4;q=pl
                    while q<=ph:
                        address=rb+((q>>3)<<5)+((q&7)>>1)
                        if (q&7)==0 and q+7<=ph:
                            # Nibble-wise zero test of word^old: any old pixel.
                            v=uint(words[address>>2])^oldword
                            if ((v-ones)&(v^allones)&highs)!=uint(0):
                                live=1;break
                            q+=8
                        else:
                            value=int(dst[address])>>4
                            if q&1:value=int(dst[address])&15
                            if value==old:
                                live=1;break
                            q+=1
                    if live==0:continue
                    if sp==cap:
                        # Full: drop stale entries in place, keeping LIFO order.
                        compactions+=1;keep=0
                        for n in range(cap):
                            e=int(st[n])
                            et=(e&255)-1
                            if e&256:et=(e&255)+1
                            ez=(e>>18)&511;eq=(e>>9)&511
                            rb=(et>>3)*1280+(et&7)*4;live=0
                            while eq<=ez:
                                address=rb+((eq>>3)<<5)+((eq&7)>>1)
                                if (eq&7)==0 and eq+7<=ez:
                                    v=uint(words[address>>2])^oldword
                                    if ((v-ones)&(v^allones)&highs)!=uint(0):
                                        live=1;break
                                    eq+=8
                                else:
                                    value=int(dst[address])>>4
                                    if eq&1:value=int(dst[address])&15
                                    if value==old:
                                        live=1;break
                                    eq+=1
                            if live:
                                st[keep]=e;keep+=1
                        sp=keep
                    if sp<cap:
                        st[sp]=y|((pd+1)<<7)|(pl<<9)|(ph<<18);sp+=1
                        if sp>peak:peak=sp
                    else:dropped+=1
            skip=0
            x+=1
            while x<=x2:
                address=rowbase+((x>>3)<<5)+((x&7)>>1)
                if (x&7)==0 and x+7<=x2 and uint(words[address>>2])==newword:
                    x+=8
                else:
                    value=int(dst[address])>>4
                    if x&1:value=int(dst[address])&15
                    if value==old:break
                    x+=1
            left=x
            if x>x2:break
    p[5]=peak;p[6]=dropped;p[7]=spans;p[8]=pixels;p[9]=compactions
