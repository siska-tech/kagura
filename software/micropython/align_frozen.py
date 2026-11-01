# SPDX-License-Identifier: Apache-2.0
"""Align frozen Thumb native literal pools without changing VM/compiler code."""
from pathlib import Path
import re
import sys


def align(source):
    # v1.26 mpy-tool emits Thumb native byte arrays aligned(2). Thumb LDR
    # literal addresses use a word-aligned PC; mpy-cross lays pools out assuming
    # a word-aligned function base. A base at 2 mod 4 reads the wrong constant.
    pattern = r'(static const byte fun_data_[^\n]*__attribute__\s*\(\(aligned \()2(\)\)\))'
    return re.sub(pattern, r'\g<1>4\2', source)


if __name__ == '__main__':
    path = Path(sys.argv[1])
    before = path.read_text(encoding='utf8')
    after = align(before)
    if after != before:
        path.write_text(after, encoding='utf8', newline='\n')
