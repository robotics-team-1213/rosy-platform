"""Real PowerShell must launch the Python environment selected by the test gateway."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


def test_powershell_child_python_uses_the_selected_environment():
    marker = Path(sys.prefix) / ".test-tools"
    if not marker.is_file() or marker.read_text().strip() != "sd-writer":
        pytest.skip("requires the explicit sd-writer native test profile")
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    assert powershell
    command = "& python -c 'import sys,json; print(json.dumps(dict(prefix=sys.prefix, executable=sys.executable)))'"
    completed = subprocess.run([powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                               capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert Path(report["prefix"]).resolve() == Path(sys.prefix).resolve()
    assert Path(report["executable"]).resolve() == Path(sys.executable).resolve()
