"""Run the guided SD orchestration against disposable PowerShell fixtures."""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")


@pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell is required for the Windows SD guide")
@pytest.mark.parametrize("script,success", [
    ("Setup-MovedDevice.Tests.ps1", "All 7 guided SD self-checks passed"),
    ("Sd-SetupSettings.Tests.ps1", "SD settings and three-card fixture checks passed"),
])
def test_guided_setup_keeps_settings_and_media_guards(script, success):
    check = ROOT / "deploy/robot/pinky_pro/sd/test" / script
    completed = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(check)], capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert success in completed.stdout
