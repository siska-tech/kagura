"""Run PR #70's unchanged emulator acceptance checker against Stage 4 artifacts.
Only output/input directory routing changes; counts and assertions stay intact.
"""
from pathlib import Path
r=Path(__file__).resolve().parents[1]
original=(r/'../wren-desktop/tools/arm_checks.py').resolve()
exec(compile(original.read_text(),str(original),'exec'),{'__file__':str(r/'tools/arm_checks.py'),'__name__':'__main__'})
