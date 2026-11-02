#!/usr/bin/env python3
from pathlib import Path
import subprocess
import os
import re
import shutil
r=Path(__file__).resolve().parents[3]
git='git'; repo=str(r)
# Windows-created worktrees contain a Windows gitdir path; use Windows Git
# when verification is invoked from WSL, rather than rewriting any metadata.
if os.name=='posix' and (r/'.git').is_file() and re.search(r'gitdir: [A-Za-z]:',(r/'.git').read_text()):
    git=shutil.which('git.exe') or '/mnt/c/Program Files/Git/cmd/git.exe'
    repo=subprocess.check_output(['wslpath','-w',str(r)],text=True).strip()
for revision,path in [('be344f5c742101f0cff170a29f63d09c0a17c441','experiments/c-gem-desktop'),
                      ('d03912b4339495379302b286383eb40cf8a6d53e','experiments/wren-rp2040'),
                      ('d03912b4339495379302b286383eb40cf8a6d53e','software')]:
    subprocess.run([git,'-C',repo,'diff','--exit-code',revision,'--',path],check=True)
print('Pinned Desktop, Wren experiment, MicroPython/native software and HAL unchanged')
