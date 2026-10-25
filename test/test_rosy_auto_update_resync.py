"""D-798: an updater whose siblings come from two releases resyncs the image layer once.

sync-image-layer.py replaces /opt/rosy/native-runtime files one at a time under a journal. A power
loss mid-sync leaves files from two releases there until the next sync, and that next sync normally
comes from this updater. The device layout is rebuilt under tmp_path; the active release's sync is a
fake that restores the good sibling and counts its runs.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy" / "robot" / "pinky_pro" / "native"
SIGNING = ROOT / "deploy" / "hosts" / "common" / "release" / "signing.py"
RUNTIME_FILES = ("rosy_auto_update.py", "auto_update_host.py", "auto_update_records.py",
                 "auto_update_stage.py", "auto_update_apply.py", "rosy_claim.py", "rosy_transfer.py")
FAKE_SYNC = '''import json, pathlib, shutil
here = pathlib.Path(__file__).resolve().parent
root = here.parents[5]  # <root>/opt/rosy/current/deploy/robot/native
with open(root / "sync-runs.txt", "a") as log:
    log.write("run\\n")
good = here / "auto_update_stage.py"
if good.is_file():
    shutil.copy(good, root / "opt/rosy/native-runtime/auto_update_stage.py")
print(json.dumps({"ok": True}))
'''


def _device(tmp_path: Path, *, release_has_fix: bool) -> Path:
    runtime = tmp_path / "opt/rosy/native-runtime"
    release = tmp_path / "opt/rosy/current/deploy/robot/native"
    runtime.mkdir(parents=True)
    release.mkdir(parents=True)
    for name in RUNTIME_FILES:
        shutil.copy(NATIVE / name, runtime / name)
    shutil.copy(SIGNING, runtime / "signing.py")
    # An older sibling: the entry's import of UpdaterStage fails.
    (runtime / "auto_update_stage.py").write_text("", encoding="utf-8")
    if release_has_fix:
        shutil.copy(NATIVE / "auto_update_stage.py", release / "auto_update_stage.py")
    (release / "sync-image-layer.py").write_text(FAKE_SYNC, encoding="utf-8")
    return runtime / "rosy_auto_update.py"


def _run(entry: Path, **env: str) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items() if key != "ROSY_AUTO_UPDATE_RESYNCED"}
    return subprocess.run([sys.executable, "-I", "-B", str(entry), "--help"], capture_output=True,
                          text=True, timeout=60, env={**environment, **env})


def _runs(tmp_path: Path) -> int:
    log = tmp_path / "sync-runs.txt"
    return len(log.read_text().splitlines()) if log.is_file() else 0


def test_mixed_siblings_resync_from_the_active_release_and_run(tmp_path):
    result = _run(_device(tmp_path, release_has_fix=True))
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert _runs(tmp_path) == 1


def test_a_resync_that_does_not_help_fails_once_without_a_loop(tmp_path):
    result = _run(_device(tmp_path, release_has_fix=False))
    assert result.returncode != 0
    assert "ImportError" in result.stderr
    assert _runs(tmp_path) == 1


def test_an_already_resynced_run_does_not_sync_again(tmp_path):
    result = _run(_device(tmp_path, release_has_fix=True), ROSY_AUTO_UPDATE_RESYNCED="1")
    assert result.returncode != 0
    assert _runs(tmp_path) == 0


def test_a_copy_outside_the_image_layer_never_syncs(tmp_path):
    entry = _device(tmp_path, release_has_fix=True)
    elsewhere = tmp_path / "checkout"
    shutil.copytree(entry.parent, elsewhere)
    result = _run(elsewhere / "rosy_auto_update.py")
    assert result.returncode != 0
    assert _runs(tmp_path) == 0
