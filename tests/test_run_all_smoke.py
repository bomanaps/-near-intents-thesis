from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.mark.skipif(
    not os.environ.get("RUN_SLOW"),
    reason="full pipeline smoke test; set RUN_SLOW=1 to enable",
)
def test_run_all_no_fetch_completes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "run_all.py"), "--no-fetch"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "Done." in result.stdout
    assert (ROOT / "docs" / "data" / "forecast.json").exists()
    assert (ROOT / "docs" / "data" / "frequency.json").exists()
