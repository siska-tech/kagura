# SPDX-License-Identifier: Apache-2.0
"""Deterministic draw-only cases shared by PC and Pico (no hardware imports)."""
import binascii


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
    state=1200
    for n in range(count):
        values=[]
        for k in range(6):
            state=(state*1664525+1013904223)&0xFFFFFFFF
            values.append(state)
        x=values[0]%380-30;y=values[1]%300-30;c=values[2]%16
        w=values[3]%85-5;h=values[4]%85-5
        kind=n%8
        if kind==0:op=('pixel',(x,y,c))
        elif kind==1:op=('fill_rect',(x,y,w,h,c))
        elif kind==2:op=('hline',(x,y,w,c))
        elif kind==3:op=('vline',(x,y,h,c))
        elif kind==4:op=('line',(x,y,values[3]%380-30,values[4]%300-30,c))
        elif kind==5:op=('circle',(x,y,values[3]%45,c))
        elif kind==6:op=('rect',(x,y,w,h,c))
        else:op=('fill_rect',(x,y,w,h,c))
        yield op
        # Repeat every primitive after a dirty reset: output stays unchanged.
        yield op


def run_cases(fb,count=512):
    fb.fill(0)
    fb.dirty[:]=bytes(1200)
    rolling=0;number=0
    for name,args in cases(count):
        getattr(fb,name)(*args)
        rolling=binascii.crc32(fb.buffer,rolling)
        rolling=binascii.crc32(fb.dirty,rolling)
        fb.dirty[:]=bytes(1200)
        number+=1
    return dict(operations=number,rolling_crc32=rolling&0xFFFFFFFF,
                buffer_crc32=binascii.crc32(fb.buffer)&0xFFFFFFFF,
                dirty_crc32=binascii.crc32(fb.dirty)&0xFFFFFFFF)
