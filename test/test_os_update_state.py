"""Durable OS transactions use real files/flock/fsync; mount identity is modeled."""
import importlib
import json
import os
import stat
import subprocess
import sys

import pytest

from test_os_media import _card
from test_os_update_manifest import metadata

SOURCE_BOOT = "11111111-1111-4111-8111-111111111111"
TRIAL_BOOT = "22222222-2222-4222-8222-222222222222"
TRANSACTION = "33333333-3333-4333-8333-333333333333"


def _state(tmp_path, monkeypatch, *, slot="a"):
    media, root, _, _, _, _ = _card(tmp_path, monkeypatch, slot)
    m = importlib.import_module("os_update_state")
    monkeypatch.setattr(m, "mount_facts", media.mount_facts)
    facts = media.capture(root)
    directory = root / "var/lib/rosy-device/os-update"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "state.json"
    initial = dict(schema_version=1, committed=dict(slot=slot, release_id="2026.10.26-010"),
                   pending=None, failed_versions=[])
    path.write_text(json.dumps(initial))
    path.chmod(0o600)
    value = metadata()
    verified = dict(metadata=value, manifest_sha256="e" * 64,
        images=dict(rootfs=dict(filename="rootfs.ext4", sha256="f" * 64, size=value["rootfs_bytes"]),
                    boot=dict(filename="boot.vfat", sha256="a" * 64, size=value["boot_bytes"])))
    return m, root, path, initial, verified, facts


def _begin(m, root, verified, facts):
    with m.locked(root) as store:
        store.begin(verified, facts, SOURCE_BOOT, TRANSACTION)


def _advance(m, root, until):
    for phase in ("INSTALLING", "INSTALLED", "VERIFIED", "ARMED", "TRIAL", "HEALTHY", "COMMIT_INTENT"):
        boot = TRIAL_BOOT if phase in ("TRIAL", "HEALTHY", "COMMIT_INTENT") else SOURCE_BOOT
        with m.locked(root) as store:
            store.transition(TRANSACTION, phase, boot, health_sha256="b" * 64 if phase == "HEALTHY" else None)
        if phase == until:
            return


def test_transaction_survives_reopen_and_commits_only_after_bound_trial_health(tmp_path, monkeypatch):
    m, root, path, initial, verified, facts = _state(tmp_path, monkeypatch)
    assert m.read_state(root) == initial
    _begin(m, root, verified, facts)
    assert m.read_state(root)["pending"]["phase"] == "PREPARED"
    _advance(m, root, "COMMIT_INTENT")
    with m.locked(root) as store:
        store.commit(TRANSACTION, TRIAL_BOOT)
    assert m.read_state(root) == dict(initial, committed=dict(slot="b", release_id=verified["metadata"]["release_id"]))
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "duplicate", "schema_bool", "extra", "wide_mode", "hardlink", "symlink", "store_mode"])
def test_invalid_or_missing_store_is_hold_and_never_reinitialized(tmp_path, monkeypatch, damage):
    m, root, path, value, _, _ = _state(tmp_path, monkeypatch)
    if damage == "missing": path.unlink()
    elif damage == "invalid_json": path.write_text("{")
    elif damage == "duplicate": path.write_text('{"schema_version":1,"schema_version":1}')
    elif damage == "schema_bool": value["schema_version"] = True; path.write_text(json.dumps(value))
    elif damage == "extra": value["unknown"] = 1; path.write_text(json.dumps(value))
    elif damage == "wide_mode": path.chmod(0o644)
    elif damage == "store_mode": path.parent.chmod(0o755)
    elif damage == "hardlink": os.link(path, path.with_suffix(".alias"))
    elif damage == "symlink": path.rename(path.with_suffix(".target")); path.symlink_to(path.with_suffix(".target"))
    before = path.read_bytes() if path.exists() else None
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        with m.locked(root): pass
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("change", ["older", "same", "failed", "source_slot", "double_begin"])
def test_begin_refuses_non_new_failed_or_conflicting_transactions_without_mutation(tmp_path, monkeypatch, change):
    m, root, path, initial, verified, facts = _state(tmp_path, monkeypatch)
    if change in ("older", "same"):
        version = "2026.10.26-009" if change == "older" else initial["committed"]["release_id"]
        verified["metadata"]["release_id"] = version
        verified["metadata"]["bundle"]["filename"] = f"rosy-os-pinky-pro-{version}-arm64.raucb"
    elif change == "failed":
        initial["failed_versions"] = [verified["metadata"]["release_id"]]
        path.write_text(json.dumps(initial))
    elif change == "source_slot": facts["slot"] = "b"
    elif change == "double_begin": _begin(m, root, verified, facts)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        _begin(m, root, verified, facts)
    assert path.read_bytes() == before


@pytest.mark.parametrize("target,boot,transaction", [("VERIFIED", SOURCE_BOOT, TRANSACTION),
    ("INSTALLING", TRIAL_BOOT, TRANSACTION), ("INSTALLING", SOURCE_BOOT, TRIAL_BOOT),
    ("COMMIT_INTENT", SOURCE_BOOT, TRANSACTION)])
def test_phase_skips_wrong_boot_and_stale_owner_never_mutate(tmp_path, monkeypatch, target, boot, transaction):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    _begin(m, root, verified, facts)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        with m.locked(root) as store:
            store.transition(transaction, target, boot)
    assert path.read_bytes() == before


def test_trial_and_commit_require_new_boot_and_health_from_same_trial(tmp_path, monkeypatch):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    _begin(m, root, verified, facts)
    _advance(m, root, "ARMED")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with m.locked(root) as store: store.transition(TRANSACTION, "TRIAL", SOURCE_BOOT)
    assert path.read_bytes() == before
    with pytest.raises(ValueError):
        with m.locked(root) as store: store.commit(TRANSACTION, TRIAL_BOOT)
    with m.locked(root) as store: store.transition(TRANSACTION, "TRIAL", TRIAL_BOOT)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with m.locked(root) as store: store.transition(TRANSACTION, "HEALTHY", SOURCE_BOOT, health_sha256="b" * 64)
    with pytest.raises(ValueError):
        with m.locked(root) as store: store.transition(TRANSACTION, "HEALTHY", TRIAL_BOOT)
    assert path.read_bytes() == before


def test_short_state_lock_contends_and_releases_after_exception(tmp_path, monkeypatch):
    m, root, _, _, _, _ = _state(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError):
        with m.locked(root):
            with pytest.raises(ValueError, match="busy"):
                with m.locked(root): pass
            raise RuntimeError("caller failed")
    with m.locked(root) as store:
        assert store.state["pending"] is None


def test_pre_publish_fsync_failure_keeps_old_state_and_retry_reads_disk(tmp_path, monkeypatch):
    m, root, path, initial, verified, facts = _state(tmp_path, monkeypatch)
    original = os.fsync
    def fail(fd): raise OSError("injected file fsync error")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        _begin(m, root, verified, facts)
    assert json.loads(path.read_text()) == initial
    monkeypatch.setattr(os, "fsync", original)
    _begin(m, root, verified, facts)
    assert m.read_state(root)["pending"]["phase"] == "PREPARED"


def test_failed_candidate_is_recorded_only_on_source_and_never_automatically_retried(tmp_path, monkeypatch):
    m, root, path, initial, verified, facts = _state(tmp_path, monkeypatch)
    _begin(m, root, verified, facts)
    _advance(m, root, "TRIAL")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with m.locked(root) as store:
            store.record_failure(TRANSACTION, TRIAL_BOOT, "b")
    assert path.read_bytes() == before
    with m.locked(root) as store:
        store.record_failure(TRANSACTION, SOURCE_BOOT, "a")
    failed = m.read_state(root)
    assert failed == dict(initial, failed_versions=[verified["metadata"]["release_id"]])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        _begin(m, root, verified, facts)
    assert path.read_bytes() == before


def test_commit_intent_failure_requires_commit_owner_reconciliation(tmp_path, monkeypatch):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    _begin(m, root, verified, facts)
    _advance(m, root, "COMMIT_INTENT")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        with m.locked(root) as store:
            store.record_failure(TRANSACTION, SOURCE_BOOT, "a")
    assert path.read_bytes() == before


@pytest.mark.parametrize("damage", ["same_slot", "early_health", "old_trial", "boolean_image", "duplicate_failed"])
def test_corrupt_pending_bindings_are_never_read_as_idle(tmp_path, monkeypatch, damage):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    _begin(m, root, verified, facts)
    value = json.loads(path.read_text())
    pending = value["pending"]
    if damage == "same_slot": pending["target_slot"] = pending["source_slot"]
    elif damage == "early_health": pending["health_sha256"] = "b" * 64
    elif damage == "old_trial": pending["phase"] = "TRIAL"; pending["trial_boot_id"] = SOURCE_BOOT
    elif damage == "boolean_image": pending["verified"]["images"]["boot"]["size"] = True
    elif damage == "duplicate_failed": value["failed_versions"] = ["2026.10.26-001"] * 2
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="OS_UPDATE_STATE_HOLD"):
        m.read_state(root)


def test_store_cannot_publish_after_its_lock_context_exits(tmp_path, monkeypatch):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    with m.locked(root) as store: pass
    before = path.read_bytes()
    with pytest.raises(ValueError, match="lock"):
        store.begin(verified, facts, SOURCE_BOOT, TRANSACTION)
    assert path.read_bytes() == before


def test_parent_fsync_failure_preserves_published_pending_and_invalidates_the_writer(tmp_path, monkeypatch):
    m, root, path, _, verified, facts = _state(tmp_path, monkeypatch)
    original = os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected parent fsync error")
        original(fd)
    monkeypatch.setattr(os, "fsync", fail_directory)
    with m.locked(root) as store:
        with pytest.raises(OSError, match="parent fsync"):
            store.begin(verified, facts, SOURCE_BOOT, TRANSACTION)
        with pytest.raises(ValueError, match="lock"):
            store.begin(verified, facts, SOURCE_BOOT, TRIAL_BOOT)
    assert json.loads(path.read_text())["pending"]["transaction_id"] == TRANSACTION
    monkeypatch.setattr(os, "fsync", original)
    with m.locked(root) as reopened:
        assert reopened.state["pending"]["transaction_id"] == TRANSACTION


def test_frozen_state_writer_works_with_poisoned_mutable_sdk(tmp_path, monkeypatch):
    from test_os_frozen_firstboot import _prefix, _stage
    _, root, _, _, verified, facts = _state(tmp_path / "device", monkeypatch)
    prefix = _prefix(tmp_path / "installed")
    _stage(prefix)
    mutable = prefix / "native-runtime"
    names = ("os_update_state", "os_update_manifest", "os_state_layout", "os_state_io", "signing", "media_layout")
    for name in names:
        (mutable / (name + ".py")).write_text("raise RuntimeError('mutable SDK was imported')\n")
    script = """
import json, sys
from pathlib import Path
frozen = Path(sys.argv[1]) / 'os-bootstrap/native-runtime'
sys.path[:0] = [str(frozen), str(Path(sys.argv[1]) / 'native-runtime')]
import os_update_state as m
payload = json.loads(sys.stdin.read())
# Only kernel mount observation is modeled; journal/flock/fsync/imports are real.
m.mount_facts = lambda *args: []
with m.locked(Path(sys.argv[2])) as store:
    store.begin(payload['verified'], payload['media'], payload['boot'], payload['transaction'])
for name in payload['modules']:
    assert Path(sys.modules[name].__file__).is_relative_to(frozen)
assert m.read_state(Path(sys.argv[2]))['pending']['phase'] == 'PREPARED'
"""
    payload = dict(verified=verified, media=facts, boot=SOURCE_BOOT, transaction=TRANSACTION, modules=names)
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(prefix), str(root)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
