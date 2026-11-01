# SPDX-License-Identifier: Apache-2.0
"""Read-only RAM import fixture, executed explicitly by kagura-ui-device.py.

No flash writes. 512-byte chunks avoid large import-source copies. Reserve the
contiguous framebuffer allocation before the temporary SDK imports fragment RAM.
This fixture is not part of the production GUI or its frozen manifest.
"""
import sys, io, vfs, gc
import kagura
gc.collect()
_ui_reserve = bytearray(40000)

class UIRamFile(io.IOBase):
    def __init__(self, data):
        self.size, self.data = data
        self.pos = 0
    def readinto(self, buffer):
        count = min(len(buffer),self.size-self.pos)
        for i in range(count):
            position = self.pos+i
            buffer[i] = self.data[position//512][position%512]
        self.pos += count
        return count
    def ioctl(self, request, argument):
        if request == 4:
            self.data = None
            return 0
        if request == 11:
            return 256
        return -1

class UIRamFS:
    def __init__(self):
        self.files = {}
    def mount(self, readonly, mkfs):
        pass
    def umount(self):
        pass
    def stat(self, path):
        if path in self.files:
            return (0x8000,0,0,0,0,0,self.files[path][0],0,0,0)
        prefix = path.rstrip('/')+'/'
        if any(name.startswith(prefix) for name in self.files):
            return (0x4000,0,0,0,0,0,0,0,0,0)
        raise OSError(2)
    def open(self, path, mode):
        if 'w' in mode or '+' in mode:
            raise OSError(30)
        return UIRamFile(self.files.pop(path))

_ui_fs = UIRamFS()
_ui_old_path = kagura.__path__
vfs.mount(_ui_fs, '/ui_ram', readonly=True)
kagura.__path__ = '/ui_ram/kagura'
sys.path.insert(0, '/ui_ram')
gc.collect()
print('UI_RAMFS_READY',gc.mem_free())
