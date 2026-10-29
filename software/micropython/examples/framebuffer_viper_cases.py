# SPDX-License-Identifier: Apache-2.0
"""Deterministic draw-only cases shared by PC and Pico (no hardware imports)."""
import binascii

GS4_HMSB, TILE4 = 2, 0x40


def lcg_bytes(count, seed):
    out = bytearray(count)
    for n in range(count):
        seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        out[n] = seed >> 24
    return bytes(out)


# 30x20 linear image (stride 30 pixels) and a 16x16 tile-native image.
LINEAR = lcg_bytes(30 * 20 // 2, 7)
TILES = lcg_bytes(16 * 16 // 2, 11)


def cases(count=512):
    for color in range(16):
        yield ('fill_rect',(0,0,320,240,color))
        yield ('fill_rect',(0,0,320,240,color))
    for args in ((0,0,1),(1,0,2),(7,7,3),(8,8,4),(319,239,15),
                 (184,200,7),(192,200,8),(319,239,15),(-1,-1,1),(320,240,2)):
        yield ('pixel',args)
    for args in ((-9,-9,18,18,3),(319,239,10,10,12),(7,7,3,3,15),
                 (184,200,17,8,4),(312,232,8,8,9),(0,0,0,10,1),
                 (0,0,-1,-2,5),(-(1<<70),0,1<<71,1,6)):
        yield ('fill_rect',args)
    # Fixed edges for the newer primitives: tiles 1023/1024/1199 and clipping.
    for args in ((184,200,15,10,1,False),(312,232,30,30,9,False),(0,0,0,0,4,True),
                 (5,5,0,4,7,False),(160,120,159,119,2,True),(160,120,200,150,3,False),
                 (-30,-30,40,40,5,True)):
        yield ('ellipse',args)
    for args in (((LINEAR,30,20,GS4_HMSB),184,200),((TILES,16,16,TILE4),184,200),
                 ((TILES,16,16,TILE4),304,224),((LINEAR,30,20,GS4_HMSB),-7,-5,None,None,3),
                 ((TILES,16,16,TILE4),183,201,9,7,None,3,2)):
        yield ('blit',args)
    yield ('blit_self',(8,0,None,None,None,0,0))
    yield ('blit_self',(0,0,317,239,None,3,1))
    yield ('paint',(0,0,6))
    yield ('paint',(186,203,11))
    state=1200
    for n in range(count):
        values=[]
        for k in range(8):
            state=(state*1664525+1013904223)&0xFFFFFFFF
            values.append(state)
        x=values[0]%380-30;y=values[1]%300-30;c=values[2]%16
        w=values[3]%85-5;h=values[4]%85-5
        kind=n%12
        if kind==0:op=('pixel',(x,y,c))
        elif kind==1:op=('fill_rect',(x,y,w,h,c))
        elif kind==2:op=('hline',(x,y,w,c))
        elif kind==3:op=('vline',(x,y,h,c))
        elif kind==4:op=('line',(x,y,values[3]%380-30,values[4]%300-30,c))
        elif kind==5:op=('circle',(x,y,values[3]%45,c))
        elif kind==6:op=('rect',(x,y,w,h,c))
        elif kind==7:op=('ellipse',(x,y,values[3]%60,values[4]%60,c,bool(values[5]&1)))
        elif kind==8:
            key=None if values[5]&1 else values[6]%16
            source=(LINEAR,30,20,GS4_HMSB) if values[5]&2 else (TILES,16,16,TILE4)
            op=('blit',(source,x,y,None,None,key,values[7]%9,(values[7]>>8)%9))
        elif kind==9:
            key=None if values[5]&1 else c
            op=('blit_self',(x,y,w,h,key,values[6]%320,values[7]%240))
        elif kind==10:op=('paint',(values[0]%320,values[1]%240,c))
        else:op=('fill_rect',(x,y,w,h,c))
        yield op
        # Repeat every primitive after a dirty reset: output stays unchanged.
        yield op


def apply(fb,name,args):
    if name=='blit_self':
        x,y,w,h,key,sx,sy=args
        return fb.blit(fb,x,y,w,h,key,sx,sy)
    return getattr(fb,name)(*args)


def run_cases(fb,count=512):
    fb.fill(0)
    fb.dirty[:]=bytes(1200)
    rolling=0;number=0
    for name,args in cases(count):
        apply(fb,name,args)
        rolling=binascii.crc32(fb.buffer,rolling)
        rolling=binascii.crc32(fb.dirty,rolling)
        fb.dirty[:]=bytes(1200)
        number+=1
    return dict(operations=number,rolling_crc32=rolling&0xFFFFFFFF,
                buffer_crc32=binascii.crc32(fb.buffer)&0xFFFFFFFF,
                dirty_crc32=binascii.crc32(fb.dirty)&0xFFFFFFFF)
