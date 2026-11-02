"""Reuse every PR #70/#72 acceptance assertion, routing artifacts only."""
from pathlib import Path
r = Path(__file__).resolve().parents[1]
checker = r.parents[1] / 'experiments/wren-desktop/tools/arm_checks.py'
exec(compile(checker.read_text(), str(checker), 'exec'),
     {'__file__': str(r / 'tools/arm_checks.py'), '__name__': '__main__'})
