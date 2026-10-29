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


def run(sdk='kagura',count=512,expected=None):
    FB=__import__(sdk+'.framebuffer',None,None,['TileFramebuffer']).TileFramebuffer
    gc.collect();fb=FB(Device())
    # Drop the original plane before allocating a guarded replacement. One plane.
    fb._view=None;fb.buffer=None;fb.dirty=None;gc.collect()
    raw=bytearray(38464);marks=bytearray(1264)
    raw[:32]=marks[:32]=b'\xa5'*32
    raw[-32:]=marks[-32:]=b'\x5a'*32
    fb.buffer=memoryview(raw)[32:-32];fb._view=memoryview(fb.buffer)
    fb.dirty=memoryview(marks)[32:-32]
    results={};text={}
    for enabled in (False,True):
        fb.set_viper(enabled)
        assert fb.viper_enabled==enabled
        result=run_cases(fb,count)
        results[str(enabled)]=result
        text[str(enabled)]=text_cases(fb)
        assert raw[:32]==b'\xa5'*32 and raw[-32:]==b'\x5a'*32
        assert marks[:32]==b'\xa5'*32 and marks[-32:]==b'\x5a'*32
        if expected is not None:assert result==expected,(result,expected)
        report('differential_backend',viper_enabled=enabled,result=result,
               text_crc32=text[str(enabled)],kernel_counts=fb.kernel_counts,
               guards_intact=True,heap_free=gc.mem_free())
        gc.collect()
    assert results['False']==results['True']
    assert text['False']==text['True']
    assert all(n>0 for n in fb.kernel_counts),fb.kernel_counts
    report('differential_pass',passed=True,pc_reference_match=expected is not None,
           result=results['True'],text_crc32=text['True'],guards_intact=True,
           kernel_counts=fb.kernel_counts)
    return results['True']
