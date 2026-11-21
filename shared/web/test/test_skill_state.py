"""C20/A3: skillState, the sample-data contract and the 3D skill text (pure, node)."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_skill_state_and_sample_contract(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(Path(__file__).resolve().parent / "skill-state.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
