"""C23: dockEntries pure projection (node)."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_robot_dock_model(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(Path(__file__).resolve().parent / "robot-dock-model.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
