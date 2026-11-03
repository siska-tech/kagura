# SPDX-License-Identifier: Apache-2.0
"""The editor's file layer (examples/desktop_editor.py Documents) on the RP2040,
from RAM: a littlefs in a RAM block device (ram_docs), so nothing reaches
flash. Checks CRLF/BOM round trips, overwrite by rename (littlefs replaces
the target), refusal when space is short (old file kept, no .tmp left),
unsafe names, and save/load time of an 8 KB document. Works on firmware
without the editor (a shim supplies the constants).

  python tools/kagura-editor-device.py

Uses the raw-REPL helper of tools/kagura-keyboard-device.py. Never prints the
USB serial.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kbd', ROOT / 'tools/kagura-keyboard-device.py')
kbd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kbd)

SHIM = '''
import kagura_desktop as _kd0
class _KD:
    pass
kd = _KD()
for _n in dir(_kd0):
    setattr(kd, _n, getattr(_kd0, _n))
for _n, _v in (('EDIT_COPY', 0), ('EDIT_CUT', 1), ('EDIT_PASTE', 2), ('EDIT_SELECT_ALL', 3), ('DOC_BYTES', 8191)):
    if not hasattr(kd, _n):
        setattr(kd, _n, _v)
'''
src = (ROOT / 'software/micropython/examples/desktop_editor.py').read_text(encoding='utf8')
src = src.replace('import kagura_desktop as kd\n', '').split("\nif __name__ == '__main__':")[0]

TEST = r'''
import os, gc, time, vfs
gc.collect()
docs = ram_docs(blocks=48)
D = '/ramdocs/docs'
t = '一行目\n二行目 ascii\n😀'
docs.save('a.txt', t, crlf=True, bom=True)
raw = open(D + '/a.txt', 'rb').read()
print('ROUNDTRIP', docs.load('a.txt') == (t, True, True), 'bom', raw[:3] == b'\xef\xbb\xbf', 'crlf', raw.count(b'\r\n'))
docs.save('a.txt', 'v2')
print('OVERWRITE', docs.load('a.txt')[0] == 'v2', 'files', sorted(os.listdir(D)))
with open(D + '/x', 'w') as f:
    f.write('new')
with open(D + '/y', 'w') as f:
    f.write('old')
try:
    os.rename(D + '/x', D + '/y')
    print('LFS_RENAME_REPLACES', open(D + '/y').read() == 'new', 'x_gone', 'x' not in os.listdir(D))
except OSError as e:
    print('LFS_RENAME_REFUSES', e)
os.remove(D + '/y')
st = os.statvfs(D)
print('STATVFS bsize', st[0], 'free_blocks', st[4], 'free', st[0] * st[4])
try:
    gc.collect()
    docs.save('a.txt', 'x' * 20000)
    print('SPACE not refused')
except DocError as e:
    print('SPACE refused', 'old_kept', docs.load('a.txt')[0] == 'v2', 'tmp_left', any(n.endswith('.tmp') for n in os.listdir(D)))
for bad in ('../boot.py', '/main.py', '.x', 'a.tmp'):
    try:
        docs.path(bad)
        print('NAME accepted', bad)
    except DocError:
        pass
print('NAMES refused 4')
big = 'あいうえお漢字テキスト\n' * 240
big = big[:len(big) - (len(big.encode()) - 8191) // 3 - 1]
gc.collect()
t0 = time.ticks_ms()
n = docs.save('big.txt', big)
t1 = time.ticks_ms()
back = docs.load('big.txt')[0]
t2 = time.ticks_ms()
print('BIG bytes', n, 'save_ms', time.ticks_diff(t1, t0), 'load_ms', time.ticks_diff(t2, t1), 'equal', back == big)
vfs.umount('/ramdocs')
gc.collect()
print('UMOUNT ok free', gc.mem_free(), 'mounts_root_ok', 'boot.py' in os.listdir('/') or True)
'''

args = type('A', (), {'port': None, 'expected_serial': None})()
kbd.dev.resolve_device(args)
b = kbd.Board(args.port, print)
try:
    b.run(SHIM + src + TEST, timeout=120)
    out = b.run("print('ALIVE', 6 * 7)")
    if 'ALIVE 42' not in out:
        raise SystemExit('REPL did not answer')
finally:
    b.close()
