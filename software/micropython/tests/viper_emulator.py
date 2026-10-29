# SPDX-License-Identifier: Apache-2.0
"""Bounds-checked execution of the kernel source on PC; not native execution."""
import ast
import sys
import types
from pathlib import Path

# Locals holding uint words (nibble-replicated colours, XOR tests).
UNSIGNED = {'word', 'oldword', 'newword', 'ones', 'highs', 'allones', 'v'}
# Per-width access counts, so tests can prove which copy path ran.
ACCESS = {'read1': 0, 'read4': 0, 'write1': 0, 'write4': 0}


def int32(value):
    n=int(value)&0xFFFFFFFF
    return n-0x100000000 if n&0x80000000 else n


class Pointer:
    def __init__(self,buffer,width):
        self.buffer=memoryview(buffer).cast('B')
        self.width=width
    def __getitem__(self,index):
        if not isinstance(index,int) or not 0<=index<len(self.buffer)//self.width:
            raise AssertionError('out of bounds native read: %r'%index)
        ACCESS['read%d'%self.width]+=1
        offset=index*self.width
        return int.from_bytes(self.buffer[offset:offset+self.width],'little')
    def __setitem__(self,index,value):
        if not isinstance(index,int) or not 0<=index<len(self.buffer)//self.width:
            raise AssertionError('out of bounds native write: %r'%index)
        ACCESS['write%d'%self.width]+=1
        offset=index*self.width
        self.buffer[offset:offset+self.width]=(value&((1<<(8*self.width))-1)).to_bytes(self.width,'little')


def load():
    path=Path(__file__).resolve().parents[1]/'kagura/framebuffer_viper.py'
    tree=ast.parse(path.read_text())
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef)]
    for node in functions:node.decorator_list=[]
    module=ast.Module(body=functions,type_ignores=[])
    namespace=dict(ptr8=lambda b:Pointer(b,1),ptr32=lambda b:Pointer(b,4),
                   int=int32,uint=lambda n:int(n)&0xFFFFFFFF)
    exec(compile(module,str(path),'exec'),namespace)
    return types.SimpleNamespace(**{node.name:namespace[node.name] for node in functions})


def int32_checked(function):
    """Fail if any local leaves the native 32-bit range at a line boundary.

    Python ints never wrap, so this exposes values that would overflow a
    Viper machine word. Intermediate sub-expressions are bounded by the
    documented argument limits rather than traced individually.
    """
    code=function.__code__
    def local(frame,event,arg):
        for name,value in frame.f_locals.items():
            if type(value) is int:
                low,high=(-1,1<<32) if name in UNSIGNED else (-(1<<31),1<<31)
                if not low<=value<high:
                    raise AssertionError('native int32 overflow: %s=%d'%(name,value))
        return local
    def tracer(frame,event,arg):
        return local if frame.f_code is code else None
    def run(*args):
        previous=sys.gettrace();sys.settrace(tracer)
        try:return function(*args)
        finally:sys.settrace(previous)
    return run


class MonoFont:
    """Synthetic byte-backed font tests bit7-at-x0 without copying real font IP."""
    def __init__(self,buffer,width,height,format):self.buffer=buffer
    def fill(self,value):self.buffer[:]=bytes((255 if value else 0,))*8
    def text(self,value,x,y,color):
        n=ord(value)
        for yy in range(8):self.buffer[yy]=((n<<yy)|(n>>(8-yy)))&255
    def pixel(self,x,y):return (self.buffer[y]>>(7-x))&1
