"""Record that consolidation uses unchanged reference implementation bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

r = Path(__file__).resolve().parents[1]
repo = r.parents[1]
base = '0214429bd0cde433fab111e7acb78bc1b3f22a3a'
git = ['git', '-C', str(repo)]
# A Windows-created worktree contains a Windows gitdir pointer. Native Linux
# git cannot resolve that pointer; use Windows Git under WSL for that case.
pointer = repo / '.git'
if pointer.is_file() and ':/' in pointer.read_text() and str(repo).startswith('/mnt/'):
    executable = shutil.which('git.exe') or '/mnt/c/Program Files/Git/cmd/git.exe'
    windows_repo = subprocess.check_output(['wslpath', '-w', str(repo)], text=True).strip()
    git = [executable, '-C', windows_repo]
directories = ['software/desktop/core', 'software/desktop/gfx', 'experiments/native-text/src',
               'experiments/native-text/include', 'experiments/wren-desktop/src',
               'experiments/wren-japanese-desktop/src']
paths = [p for directory in directories for p in (repo / directory).glob('*')
         if p.suffix in ('.c', '.h', '.wren')]
paths += [repo / path for path in ('experiments/wren-desktop/pico/main.c',
          'software/pico/kagura_host.c', 'software/pico/kagura_host.h',
          'software/pico/kagura_host.pio', 'software/micropython/fonts/misaki8.kfnt')]
result = {}
for path in sorted(paths):
    relative = path.relative_to(repo).as_posix()
    original = ('experiments/c-gem-desktop/src/' + path.name
                if path.parent.name in ('core', 'gfx') else relative)
    reference = subprocess.check_output(git + ['show', f'{base}:{original}'])
    actual = path.read_bytes()
    # Git may materialize CRLF on Windows. Compare checked-out byte hashes using
    # Git's configured clean conversion, then retain the actual input SHA too.
    expected_blob = subprocess.check_output(git + ['rev-parse', f'{base}:{original}'], text=True).strip()
    actual_blob = subprocess.check_output(git + ['hash-object', '--path', relative, relative], text=True).strip()
    assert actual_blob == expected_blob, relative
    result[relative] = dict(original=original, git_blob=actual_blob, checkout_sha256=hashlib.sha256(actual).hexdigest(),
                            reference_sha256=hashlib.sha256(reference).hexdigest())
(r / 'results/source-provenance.json').write_text(json.dumps(dict(base=base, files=result), indent=2) + '\n')
print(f'{len(result)} implementation inputs unchanged from {base}')
