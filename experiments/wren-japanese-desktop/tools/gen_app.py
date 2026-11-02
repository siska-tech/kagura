import json
import sys
from pathlib import Path
r=Path(__file__).resolve().parents[1]
text=(r/'src/app.wren').read_text(encoding='utf-8')
output=Path(sys.argv[1]) if len(sys.argv)>1 else r/'src/japanese_app_source.h'
output.write_text('/* Generated from app.wren; UTF8 byte literals, no runtime encoder. */\nstatic const char app_source[] = '+json.dumps(text,ensure_ascii=False)+';\n',encoding='utf-8')
