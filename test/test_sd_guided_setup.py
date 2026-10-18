"""Run the guided SD orchestration against disposable PowerShell fixtures."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required for the Windows SD guide")
def test_fresh_card_plan_and_write_keep_the_existing_writer_guards():
    check = ROOT / "deploy/robot/pinky_pro/sd/test/Setup-MovedDevice.Tests.ps1"
    completed = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(check)], capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "All 6 guided SD self-checks passed" in completed.stdout
