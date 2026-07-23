"""Compatibility wrapper — prefer: python scripts/derive.py --gt"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "derive.py"
sys.argv = [str(SCRIPT), "--gt", *sys.argv[1:]]
runpy.run_path(str(SCRIPT), run_name="__main__")
