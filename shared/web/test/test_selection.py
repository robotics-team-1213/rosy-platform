"""G6/G2/G5 pure parts (createSelection, choice-logic, robotOptions): the Node runner, same as CI."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_choice_pure_parts(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    here = Path(__file__).resolve().parent
    result = subprocess.run([node, "--test", "--test-reporter=spec", str(here / "choice.test.mjs"), str(here / "choice-gaps.test.mjs")],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    (tmp_path / "choice.test.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
