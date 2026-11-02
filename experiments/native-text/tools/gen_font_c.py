"""Embed the existing licensed KJ8F unchanged; no download or new font source."""
import hashlib
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[3]
data=(root/'software/micropython/fonts/misaki8.kfnt').read_bytes()
assert hashlib.sha256(data).hexdigest()=='cbfb1071801f7ed3b6637bb6763219e59d86c13bd149169bbbab5bca753d9238'
out=['/* SPDX-License-Identifier: LicenseRef-Misaki */',
     '/* Copyright (C) 2002-2021 Num Kadoma. See software/micropython/fonts/README.md.',
     '   Generated from the pinned KJ8F, bytes/glyphs unchanged. */',
     '#include "kj_text.h"','static const uint8_t font_bytes[] = {']
for i in range(0,len(data),20):out.append(','.join('0x%02x'%b for b in data[i:i+20])+',')
out+=['};','const kj_font kj_misaki8={font_bytes,sizeof font_bytes,7171,NULL,0,0};','']
Path(sys.argv[1]).write_text('\n'.join(out),encoding='utf-8')
