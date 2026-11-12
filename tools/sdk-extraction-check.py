# SPDX-License-Identifier: Apache-2.0
"""Dry run of the kagura-sdk extraction (docs/sdk-extraction.md).

  python3 -I tools/sdk-extraction-check.py [--list]

Reads docs/sdk-extraction-paths.txt (git filter-repo --paths-from-file
format) and the tracked files, and reports every reference that would cross
the boundary between kagura (hardware) and kagura-sdk:
  - repository paths named in files (software/..., docs/..., tools/..., rtl/...);
  - relative Markdown links, resolved from the linking file.
A reference to a path that does not exist in the tree is reported apart, as
already broken. Nothing is changed. --list prints every crossing reference.
"""
import fnmatch
import re
import subprocess
import sys
from collections import Counter
from pathlib import PurePosixPath

ROOT = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                      check=True).stdout.strip()
MANIFEST = 'docs/sdk-extraction-paths.txt'
TOP = ('software', 'docs', 'tools', 'rtl', 'sim', 'spec', 'boards', 'third_party', 'experiments')
PATH_RE = re.compile(r'(?<![\w./-])((?:%s)/[\w./-]*[\w/])' % '|'.join(TOP))
LINK_RE = re.compile(r'\]\(([^)\s#]+)(?:#[^)]*)?\)')
TEXT = ('.md', '.py', '.sh', '.ps1', '.c', '.h', '.txt', '.cmake', '.mk', '.yml', '.json', '.s', '.inc',
        '.tcl', '.sv', '.svh', '.v', 'CMakeLists.txt', 'Makefile')


def rules():
    out = []
    with open('%s/%s' % (ROOT, MANIFEST), encoding='utf8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                out.append(line)
    return out


def moves(path, manifest):
    for rule in manifest:
        if rule.startswith('glob:'):
            if fnmatch.fnmatchcase(path, rule[5:]):
                return True
        elif path == rule or (rule.endswith('/') and path.startswith(rule)):
            return True
    return False


def normalize(path):
    parts = []
    for p in PurePosixPath(path).parts:
        if p == '..':
            if not parts:
                return None
            parts.pop()
        elif p != '.':
            parts.append(p)
    return '/'.join(parts)


def target_moves(target, files, moved, manifest):
    """True/False for an existing file or directory, None if it does not exist."""
    target = target.rstrip('/')
    if target in files:
        return target in moved
    inside = [f for f in files if f.startswith(target + '/')]
    if inside:
        flags = {f in moved for f in inside}
        return flags.pop() if len(flags) == 1 else 'split'
    return None


def main():
    manifest = rules()
    files = subprocess.run(['git', '-C', ROOT, 'ls-files'], capture_output=True, text=True,
                           check=True).stdout.split('\n')
    files = {f for f in files if f}
    moved = {f for f in files if moves(f, manifest)}
    crossing, broken, split = [], Counter(), Counter()
    for path in sorted(files):
        if not path.endswith(TEXT):
            continue
        try:
            with open('%s/%s' % (ROOT, path), encoding='utf8') as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            continue
        side = path in moved
        refs = set(m.group(1) for m in PATH_RE.finditer(text))
        if path.endswith('.md'):
            base = str(PurePosixPath(path).parent)
            for m in LINK_RE.finditer(text):
                link = m.group(1)
                if '://' in link or link.startswith(('mailto:', '/')):
                    continue
                resolved = normalize('%s/%s' % (base, link) if base != '.' else link)
                if resolved:
                    refs.add(resolved)
        for ref in sorted(refs):
            where = target_moves(ref, files, moved, manifest)
            if where is None:
                broken[path] += 1
            elif where == 'split':
                split[ref] += 1
            elif where != side:
                crossing.append((path, ref, side))
    to_hw = [c for c in crossing if c[2]]
    to_sdk = [c for c in crossing if not c[2]]
    print('files: %d tracked, %d move to kagura-sdk, %d stay' % (len(files), len(moved), len(files) - len(moved)))
    print('references from kagura-sdk to kagura: %d in %d files' % (len(to_hw), len({c[0] for c in to_hw})))
    print('references from kagura to kagura-sdk: %d in %d files' % (len(to_sdk), len({c[0] for c in to_sdk})))
    print('references to directories split between both: %d (%s)' % (
        sum(split.values()), ', '.join('%s %d' % kv for kv in split.most_common(6))))
    print('references to paths that do not exist (already broken or generated): %d in %d files' % (
        sum(broken.values()), len(broken)))
    for title, group in (('kagura-sdk -> kagura, by target', to_hw), ('kagura -> kagura-sdk, by source', to_sdk)):
        key = 1 if group is to_hw else 0
        top = Counter(c[key].split('/')[0] + '/' + c[key].split('/')[1] if '/' in c[key] else c[key]
                      for c in group)
        print('%s: %s' % (title, ', '.join('%s %d' % kv for kv in top.most_common(10))))
    if '--list' in sys.argv:
        for path, ref, side in crossing:
            print('%s %s -> %s' % ('sdk' if side else 'hw ', path, ref))


if __name__ == '__main__':
    main()
