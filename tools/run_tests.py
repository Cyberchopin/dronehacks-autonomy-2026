"""Run the selected suite with a repository-local temporary directory."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / ".deps"
SRC = ROOT / "src"
TMP = ROOT / ".test-tmp"

sys.path[:0] = [str(DEPS), str(SRC)]

if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir()
tempfile.tempdir = str(TMP)

import pytest  # noqa: E402

raise SystemExit(pytest.main(["-q", f"--basetemp={TMP / 'pytest'}"]))
