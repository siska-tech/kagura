# SPDX-License-Identifier: Apache-2.0
"""The SDK's public API surface, for compatibility checks across repositories.

  python3 -I tools/api-snapshot.py           print the snapshot
  python3 -I tools/api-snapshot.py --check   compare with software/api-snapshot.txt
  python3 -I tools/api-snapshot.py --write   update software/api-snapshot.txt

Read statically, so nothing is imported (no machine, rp2 or MicroPython):
- MicroPython packages (kagura, kagura.ui, kagura_ja): public module-level
  functions, classes with their public methods, and constants, with the
  parameters and defaults of every callable. Names starting with '_' and the
  internal kernel modules are left out.
- the kagura_audio native module: its globals table;
- the public C headers: function prototypes, typedef names, enum constants
  and #define names.

A removed or changed line is an API break: update the snapshot only together
with the change that makes it, and say so in the pull request.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / 'software/api-snapshot.txt'
PY = ROOT / 'software/micropython'
PACKAGES = ('kagura', 'kagura/ui', 'kagura_ja')
# Kernels behind public wrappers; their functions are documented as internal.
INTERNAL = {'kagura/framebuffer_viper.py', 'kagura/link_viper.py', 'kagura/dma_pack.py'}
GENERATED = {'kagura/regs.py'}   # checked against spec/registers.json by gen-registers.ps1 -Check
BINDINGS = ('software/audio/binding/modkagura_audio.c',)
HEADERS = (
    'software/audio/hal/ka_audio.h',
    'software/audio/hal/ka_render.h',
    'software/audio/seq/ks_song.h',
    'software/audio/seq/ks_player.h',
    'software/audio/backend/ka_kagura_host.h',
    'software/pico/kagura_host.h',
    'software/pico/tile_fb.h',
    'software/pico/img_quant.h',
)


def signature(fn):
    a = fn.args
    parts = []
    positional = a.posonlyargs + a.args
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    for arg, default in zip(positional, defaults):
        parts.append(arg.arg if default is None else '%s=%s' % (arg.arg, ast.unparse(default)))
    if a.vararg:
        parts.append('*' + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append('*')
    for arg, default in zip(a.kwonlyargs, a.kw_defaults):
        parts.append(arg.arg if default is None else '%s=%s' % (arg.arg, ast.unparse(default)))
    if a.kwarg:
        parts.append('**' + a.kwarg.arg)
    return '(%s)' % ', '.join(parts)


def python_api():
    out = []
    for package in PACKAGES:
        for path in sorted((PY / package).glob('*.py')):
            rel = path.relative_to(PY).as_posix()
            if rel in INTERNAL or rel in GENERATED:
                continue
            module = rel[:-3].replace('/', '.')
            if module.endswith('.__init__'):
                module = module[:-9]
            tree = ast.parse(path.read_text(encoding='utf8'))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
                    out.append('py %s.%s%s' % (module, node.name, signature(node)))
                elif isinstance(node, ast.ClassDef) and not node.name.startswith('_'):
                    bases = ', '.join(ast.unparse(b) for b in node.bases)
                    out.append('py %s.%s(%s)' % (module, node.name, bases))
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                                not item.name.startswith('_') or item.name in ('__init__', '__enter__', '__exit__')):
                            kind = ''
                            for d in item.decorator_list:
                                name = ast.unparse(d)
                                if name in ('property', 'staticmethod', 'classmethod'):
                                    kind = ' @' + name
                            out.append('py %s.%s.%s%s%s' % (module, node.name, item.name, signature(item), kind))
                        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
                            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                            for t in targets:
                                for n in (t.elts if isinstance(t, ast.Tuple) else [t]):
                                    if isinstance(n, ast.Name) and not n.id.startswith('_'):
                                        out.append('py %s.%s.%s' % (module, node.name, n.id))
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for t in targets:
                        for n in (t.elts if isinstance(t, ast.Tuple) else [t]):
                            if isinstance(n, ast.Name) and not n.id.startswith('_'):
                                out.append('py %s.%s' % (module, n.id))
    return out


def binding_api():
    out = []
    for rel in BINDINGS:
        text = (ROOT / rel).read_text(encoding='utf8')
        name = re.search(r'MP_REGISTER_MODULE\(MP_QSTR_(\w+)', text).group(1)
        table = re.search(r'module_table\[\] = \{(.*?)\};', text, re.S).group(1)
        for kind, member in re.findall(r'\b(FUN|CONST)\((\w+)', table):
            out.append('mod %s.%s%s' % (name, member, '()' if kind == 'FUN' else ''))
    return out


def header_api():
    out = []
    for rel in HEADERS:
        text = (ROOT / rel).read_text(encoding='utf8')
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'//[^\n]*', '', text)
        name = Path(rel).name
        for macro in re.findall(r'^\s*#\s*define\s+(\w+)', text, re.M):
            if not macro.endswith('_H'):
                out.append('h %s #define %s' % (name, macro))
        for body in re.findall(r'\benum\b[^{;]*\{(.*?)\}', text, re.S):
            for const in re.findall(r'(\w+)\s*(?:=[^,]*)?(?:,|$)', body.strip()):
                out.append('h %s enum %s' % (name, const))
        for typedef in re.findall(r'\}\s*(\w+)\s*;', text):
            out.append('h %s typedef %s' % (name, typedef))
        for typedef in re.findall(r'^\s*typedef\s+[^;{]*?(\w+)\s*;', text, re.M):
            out.append('h %s typedef %s' % (name, typedef))
        flat = re.sub(r'\{[^{}]*\}', ';', text)        # drop inline bodies and struct members
        flat = re.sub(r'\{[^{}]*\}', ';', flat)
        for decl in re.findall(r'^[ \t]*((?:static\s+inline\s+|extern\s+)?[A-Za-z_][\w \t\*]*?\b\w+\s*\([^;{]*\))\s*[;{]',
                               flat, re.M):
            decl = ' '.join(decl.split())
            if decl.startswith(('typedef', 'return', 'if ', 'while', 'for ')) or '#' in decl:
                continue
            out.append('h %s %s' % (name, decl))
    return out


def snapshot():
    lines = python_api() + binding_api() + header_api()
    return ''.join(sorted(set(line + '\n' for line in lines)))


def main():
    text = snapshot()
    if '--write' in sys.argv:
        SNAPSHOT.write_text(text, encoding='utf8', newline='\n')
        print('wrote %s (%d lines)' % (SNAPSHOT.relative_to(ROOT), text.count('\n')))
    elif '--check' in sys.argv:
        old = SNAPSHOT.read_text(encoding='utf8').splitlines()
        new = text.splitlines()
        removed = sorted(set(old) - set(new))
        added = sorted(set(new) - set(old))
        for line in removed:
            print('- ' + line)
        for line in added:
            print('+ ' + line)
        if removed or added:
            print('API snapshot differs: %d removed or changed, %d added '
                  '(tools/api-snapshot.py --write, and say so in the PR)' % (len(removed), len(added)))
            sys.exit(1)
        print('API snapshot: %d lines, unchanged' % len(new))
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
