#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile and stage the live presentation for mpremote mount; never flash.

Run with a native mpy-cross, or under WSL/Linux with the pinned build:
python3 tools/prepare-showcase.py
"""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('showcase', 'showcase_slides', 'showcase_music', 'showcase_graphics', 'showcase_scenery',
           'framebuffer_demo', 'starfall', 'starfall_core', 'starfall_render',
           'starfall_sound', 'starfall_scores', 'starfall_viper', 'starfall_video', 'sakura', 'sakura_viper', 'sakura_hud', 'sakura_hud_viper')
ASSETS = ('showcase_assets', 'starfall_assets', 'sakura_assets')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mpy-cross', type=Path, default=ROOT / 'build/micropython-src/mpy-cross/build/mpy-cross')
    p.add_argument('--output', type=Path, default=ROOT / 'build/showcase-live/run')
    args = p.parse_args()
    if not args.mpy_cross.is_file():
        p.error('build mpy-cross first or provide --mpy-cross')
    args.output.mkdir(parents=True, exist_ok=True)
    examples = ROOT / 'software/micropython/examples'
    for name in MODULES:
        subprocess.run([str(args.mpy_cross.resolve()), '-march=armv6m', '-o',
                        str(args.output / (name + '.mpy')), str(examples / (name + '.py'))], check=True)
    # Intern dynamic identifiers before releasing the framebuffer arena.
    # MicroPython's qstr pools persist across module unloading; letting a new
    # pool occupy the released 38 KB hole fragments the next loop's framebuffer.
    names = set(MODULES)
    for name in MODULES:
        path = examples / (name + '.py')
        names.add(str(path))
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Name): names.add(node.id)
            elif isinstance(node,ast.Attribute): names.add(node.attr)
            elif isinstance(node,ast.arg): names.add(node.arg)
            elif isinstance(node,(ast.FunctionDef,ast.ClassDef)): names.add(node.name)
            elif isinstance(node,ast.Constant) and isinstance(node.value,str) and len(node.value) <= 32:
                names.add(node.value)
            elif isinstance(node,ast.alias):
                names.update(node.name.split('.'))
                if node.asname: names.add(node.asname)
            elif isinstance(node,ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(node.module.split('.'))
    warm = args.output / 'showcase_names.py'
    warm.write_text('NAMES = '+repr(tuple(sorted(names)))+'\n',encoding='utf-8')
    subprocess.run([str(args.mpy_cross.resolve()),'-march=armv6m','-o',
                    str(args.output/'showcase_names.mpy'),str(warm)],check=True)
    warm.unlink()
    for name in ASSETS:
        shutil.copytree(examples / name, args.output / name, dirs_exist_ok=True)
    print('Prepared %d ARMv6-M modules and %d asset directories in %s' % (len(MODULES)+1, len(ASSETS), args.output))


if __name__ == '__main__':
    main()
