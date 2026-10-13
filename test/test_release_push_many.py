"""D-553 addendum 2: rosy-release-push-many.ps1 runs one unchanged
rosy-release-push.ps1 per robot at the same time and fails if any of them fails.

Only the preview/failure paths run here: a real push needs a robot.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "pinky_pro" / "rosy-release-push-many.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
RELEASE_ID = "2026.09.25-001"

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


def _run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ROSY_API_TOKEN", None)
    return subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120, env=env)


def _unsigned_tarball(tmp_path: Path) -> Path:
    tarball = tmp_path / f"{RELEASE_ID}.tar.gz"
    data = json.dumps({"release_id": RELEASE_ID}).encode()
    with tarfile.open(tarball, "w:gz") as bundle:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    return tarball


def test_every_robot_gets_its_own_push_and_log_and_one_failure_fails_all(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    logs = tmp_path / "logs"
    completed = _run("-Robot", "rosy-a.local,rosy-b.local", "-Tarball", str(_unsigned_tarball(tmp_path)),
                     "-LogDir", str(logs), "-PrintCommands")

    assert completed.returncode == 1, completed.stdout + completed.stderr
    for robot in ("rosy-a.local", "rosy-b.local"):
        assert "SIGNATURE_VERIFY_FAILED" in (logs / f"push-{robot}.txt").read_text(errors="replace")
        assert f"=== {robot}: exit 1" in completed.stdout
    assert "push FAILED on: rosy-a.local, rosy-b.local" in completed.stdout
    assert not list(logs.glob("*.err"))


@pytest.mark.parametrize("robots", ["rosy-a.local,rosy-a.local", "rosy-a.local,bad;name"])
def test_refuses_duplicate_or_unsafe_robot_before_starting_anything(tmp_path, robots):
    logs = tmp_path / "logs"
    completed = _run("-Robot", robots, "-Tarball", str(_unsigned_tarball(tmp_path)),
                     "-LogDir", str(logs), "-PrintCommands")

    assert completed.returncode != 0
    assert "started push" not in completed.stdout
    assert not logs.exists()
