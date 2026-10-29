# SPDX-License-Identifier: Apache-2.0
"""Pico native execution proof, guard bytes and PC rolling-CRC comparison."""
import gc
import json
import binascii
from framebuffer_viper_cases import run_cases


def report(event,**values):
    values['event']=event
    print('VIPERFB '+json.dumps(values))


class Device:
    abi=(0,6)
    height=240


def text_cases(fb):
    fb.fill(0);fb.dirty[:]=bytes(1200)
    crc=0
    for n in range(95):
        for duplicate in range(2):
            fb.text(chr(32+n),(n*17)%335-7,(n*13)%255-7,n%16)
            crc=binascii.crc32(fb.buffer,crc)
            crc=binascii.crc32(fb.dirty,crc)
            fb.dirty[:]=bytes(1200)
    for x,y in ((-7,232),(300,-7)):
        fb.text('KAGURA 1200 Viper',x,y,15)
        crc=binascii.crc32(fb.buffer,crc);crc=binascii.crc32(fb.dirty,crc)
        fb.dirty[:]=bytes(1200)
    return crc&0xFFFFFFFF


def paint_stress(fb,enabled,stack):
    """Overflow/compaction paths with tiny guarded stacks; same result per backend."""
    import framebuffer_shapes as shapes
    crc=0;stats=[]
    for capacity in (3,40):
        for name in ('maze','noise','comb'):
            fb.set_viper(True)  # fast, backend-independent preparation
            seed=shapes.prepare(fb,name);fb.dirty[:]=bytes(1200)
            fb.set_viper(enabled)
            fb.paint_capacity=capacity;fb._paint_stack=memoryview(stack)[8:8+capacity]
            stack[8+capacity]=0xC3C3C3C3  # sentinel right after the tiny stack
            complete=fb.paint(seed[0],seed[1],12)
            assert stack[8+capacity]==0xC3C3C3C3,'paint stack overrun'
            stack[8+capacity]=0
            crc=binascii.crc32(fb.buffer,crc);crc=binascii.crc32(fb.dirty,crc)
            stats.append((name,capacity,complete,fb.last_paint['peak'],fb.last_paint['dropped'],
                          fb.last_paint['compactions'],fb.last_paint['pixels']))
    fb.paint_capacity=len(stack)-16;fb._paint_stack=memoryview(stack)[8:-8]
    return crc&0xFFFFFFFF,stats


def run(sdk='kagura',count=512,expected=None):
    from array import array
    FB=__import__(sdk+'.framebuffer',None,None,['TileFramebuffer']).TileFramebuffer
    gc.collect();fb=FB(Device())
    # Drop the original plane before allocating a guarded replacement. One plane.
    fb._view=None;fb.buffer=None;fb.dirty=None;gc.collect()
    raw=bytearray(38464);marks=bytearray(1264)
    raw[:32]=marks[:32]=b'\xa5'*32
    raw[-32:]=marks[-32:]=b'\x5a'*32
    fb.buffer=memoryview(raw)[32:-32];fb._view=memoryview(fb.buffer)
    fb.dirty=memoryview(marks)[32:-32]
    # paint() work stack with 8 guard words on each side.
    stack=array('I',bytes(4*(fb.paint_capacity+16)))
    for n in range(8):stack[n]=0xA5A5A5A5;stack[-1-n]=0x5A5A5A5A
    fb._paint_stack=memoryview(stack)[8:-8]
    def guards():
        assert raw[:32]==b'\xa5'*32 and raw[-32:]==b'\x5a'*32
        assert marks[:32]==b'\xa5'*32 and marks[-32:]==b'\x5a'*32
        assert all(stack[n]==0xA5A5A5A5 and stack[-1-n]==0x5A5A5A5A for n in range(8))
    results={};text={};stress={}
    for enabled in (False,True):
        fb.set_viper(enabled)
        assert fb.viper_enabled==enabled
        result=run_cases(fb,count)
        results[str(enabled)]=result
        text[str(enabled)]=text_cases(fb)
        stress[str(enabled)]=paint_stress(fb,enabled,stack)
        guards()
        if expected is not None:assert result==expected,(result,expected)
        report('differential_backend',viper_enabled=enabled,result=result,
               text_crc32=text[str(enabled)],paint_stress=stress[str(enabled)],
               kernel_counts=fb.kernel_counts,guards_intact=True,heap_free=gc.mem_free())
        gc.collect()
    assert results['False']==results['True']
    assert text['False']==text['True']
    assert stress['False']==stress['True']
    assert all(n>0 for n in fb.kernel_counts),fb.kernel_counts
    report('differential_pass',passed=True,pc_reference_match=expected is not None,
           result=results['True'],text_crc32=text['True'],paint_stress=stress['True'],
           guards_intact=True,kernel_counts=fb.kernel_counts)
    return results['True']
