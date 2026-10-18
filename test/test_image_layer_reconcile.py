"""D-798: rosy-release-recover settles a power-cut image-layer sync before any service starts.

deploy/robot/pinky_pro/native/image-layer-reconcile.py runs sync-image-layer.py's reconcile() on
a temporary root holding a sync's backup manifest as a power loss left it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

NATIVE = Path(__file__).resolve().parents[1] / "deploy" / "robot" / "pinky_pro" / "native"
spec = importlib.util.spec_from_file_location("image_layer_reconcile", NATIVE / "image-layer-reconcile.py")
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)

RUNTIME = "opt/rosy/native-runtime"
BACKUPS = "var/lib/rosy/image-layer-backup"
LOCK = "var/lib/rosy/releases/native-release.lock"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _cut_off_sync(root: Path, *, entry_landed: bool, unit: bool = False) -> Path:
    """A sync that added a sibling and changed the entry (or a unit) but never set files_applied."""
    folder = root / BACKUPS / "000001-20261019T000000Z-2026.10.01-022"
    changed = "etc/systemd/system/rosy-core.service" if unit else f"{RUNTIME}/rosy_auto_update.py"
    _write(root / changed, "new entry" if entry_landed else "old entry")
    _write(folder / changed, "old entry")
    _write(root / RUNTIME / "auto_update_new.py", "new sibling")
    _write(folder / "backup-manifest.json", json.dumps({
        "release_id": "2026.10.01-022", "created": "20261019T000000Z",
        "files_applied": False, "complete": False, "files": [
            {"path": f"/{RUNTIME}/auto_update_new.py", "state": "new", "mode": "0o644",
             "sha256": _sha("new sibling"), "backup": None, "previous_sha256": None},
            {"path": f"/{changed}", "state": "changed", "mode": "0o644", "sha256": _sha("new entry"),
             "backup": changed, "previous_sha256": _sha("old entry")},
        ]}))
    return folder / "backup-manifest.json"


def _runner(calls: list):
    return lambda argv: calls.append(argv)


def test_a_cut_off_sync_is_undone_back_to_one_release(tmp_path):
    manifest = _cut_off_sync(tmp_path, entry_landed=False)
    calls: list = []
    result = boot.reconcile_at_boot(tmp_path, _runner(calls))
    assert [item["outcome"] for item in result["reconciled"]] == ["undone"]
    assert not (tmp_path / RUNTIME / "auto_update_new.py").exists()
    assert (tmp_path / RUNTIME / "rosy_auto_update.py").read_text() == "old entry"
    assert json.loads(manifest.read_text())["abandoned"] is True
    assert calls == []


def test_a_sync_cut_off_after_its_last_file_is_flagged_applied(tmp_path):
    manifest = _cut_off_sync(tmp_path, entry_landed=True)
    result = boot.reconcile_at_boot(tmp_path, _runner([]))
    assert [item["outcome"] for item in result["reconciled"]] == ["applied"]
    assert (tmp_path / RUNTIME / "auto_update_new.py").is_file()
    assert json.loads(manifest.read_text())["files_applied"] is True


def test_an_undone_unit_file_is_reloaded_before_the_units_start(tmp_path):
    _cut_off_sync(tmp_path, entry_landed=True, unit=True)
    (tmp_path / RUNTIME / "auto_update_new.py").unlink()  # the unit landed, the sibling did not
    calls: list = []
    result = boot.reconcile_at_boot(tmp_path, _runner(calls))
    assert [item["outcome"] for item in result["reconciled"]] == ["undone"]
    assert (tmp_path / "etc/systemd/system/rosy-core.service").read_text() == "old entry"
    assert calls == [["systemctl", "daemon-reload"]]


def test_a_clean_boot_takes_no_lock_and_writes_nothing(tmp_path):
    calls: list = []
    assert boot.reconcile_at_boot(tmp_path, _runner(calls)) == {"reconciled": []}
    assert not (tmp_path / LOCK).exists()
    assert not (tmp_path / BACKUPS).exists()
    assert calls == []
