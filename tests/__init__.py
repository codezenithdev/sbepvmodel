"""Regression tests for the solar operations dashboard.

Puts ``src/`` on ``sys.path`` so ``import sbepv`` resolves without requiring an
editable install. unittest imports this package before any test module, so the
bootstrap runs exactly once and early enough for every import below it.
"""

import sys
import os
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# API imports create directories and initialize SQLite before individual setUp
# methods can patch config/state. A plain unittest command must isolate those
# import-time writes too. Explicit runner-owned output directories retain priority.
_TEST_OUTPUT = None
if not os.environ.get("PV_DASHBOARD_OUTPUT_DIR"):
    _TEST_OUTPUT = tempfile.TemporaryDirectory(prefix="sbepv-tests-")
    os.environ["PV_DASHBOARD_OUTPUT_DIR"] = _TEST_OUTPUT.name
