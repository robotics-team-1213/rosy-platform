"""The frozen-head experiment must not mint an approved v13 artifact directly."""

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "training" / "drivable_head.py"


def test_direct_cli_requires_trusted_owner_before_loading_model_or_dataset(tmp_path):
    out = tmp_path / "model"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--lane", str(tmp_path / "missing.pt"),
         "--lane-manifest", str(tmp_path / "missing.json"), "--dataset", str(tmp_path / ("a" * 64)),
         "--out", str(out), "--ignore-top", "110"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "trusted owner" in result.stderr.lower()
    assert not out.exists()
