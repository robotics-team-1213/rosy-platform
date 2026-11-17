"""C7 (R2-01): the connection notice element becomes a polite live region, run with the same Node runner as CI."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_connection_notice_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(Path(__file__).resolve().parent / "connection-notice.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    (tmp_path / "connection-notice.test.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
