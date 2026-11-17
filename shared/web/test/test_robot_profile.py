"""C14 robotProfile: the pure model behind the shared robot row, run with the same Node runner as CI."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_robot_profile_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(Path(__file__).resolve().parent / "robot-profile.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    (tmp_path / "robot-profile.test.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
