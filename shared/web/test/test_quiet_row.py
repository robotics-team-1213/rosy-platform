"""C14 quiet row texts (quietRowTexts): row-level unknown merge and delay-age quieting, run with the same Node runner as CI."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_quiet_row_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(Path(__file__).resolve().parent / "quiet-row.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    (tmp_path / "quiet-row.test.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
