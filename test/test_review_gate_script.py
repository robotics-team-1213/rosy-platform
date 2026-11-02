"""The review gate script parses and keeps the strict mode its own comment relies on (a failing git log inside
$(...) must fail the gate, not read as "no overlap"). Naming the path here also maps it for the affected selector:
on 2026-11-02 it was "unknown -> full" and sent a landing's turn back (D-889)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".github/review-gate.sh"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_review_gate_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_review_gate_script_keeps_its_strict_mode():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "shopt -s inherit_errexit" in text
