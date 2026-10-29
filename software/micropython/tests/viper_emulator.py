# SPDX-License-Identifier: Apache-2.0
"""Bounds-checked execution of the kernel source on PC; not native execution."""
import ast
import types
from pathlib import Path


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
        offset=index*self.width
        return int.from_bytes(self.buffer[offset:offset+self.width],'little')
    def __setitem__(self,index,value):
        if not isinstance(index,int) or not 0<=index<len(self.buffer)//self.width:
            raise AssertionError('out of bounds native write: %r'%index)
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


class MonoFont:
    """Synthetic byte-backed font tests bit7-at-x0 without copying real font IP."""
    def __init__(self,buffer,width,height,format):self.buffer=buffer
    def fill(self,value):self.buffer[:]=bytes((255 if value else 0,))*8
    def text(self,value,x,y,color):
        n=ord(value)
        for yy in range(8):self.buffer[yy]=((n<<yy)|(n>>(8-yy)))&255
    def pixel(self,x,y):return (self.buffer[y]>>(7-x))&1
