"""Regression tests for the solar operations dashboard.

Puts ``src/`` on ``sys.path`` so ``import sbepv`` resolves without requiring an
editable install. unittest imports this package before any test module, so the
bootstrap runs exactly once and early enough for every import below it.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
