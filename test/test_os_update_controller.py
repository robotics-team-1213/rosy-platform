"""Controller files/locks are real; hardware, service manager and RAUC install are explicit models."""
import datetime as dt
import importlib
import json
import subprocess
import uuid

import pytest

from auto_update_fakes import FakeHost
from test_os_bootloader import _boot
from test_os_update_state import SOURCE_BOOT, TRIAL_BOOT, TRANSACTION


def _source(tmp_path, monkeypatch):
    boot, state, root, journal, config = _boot(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_controller")
    host = FakeHost(root)
    host.t = dt.datetime.now(dt.timezone.utc)
    host.write_inputs()
    directory = root / "var/lib/rosy-device/policy/updates"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text('{"enabled":true}')
    import auto_update_records
    monkeypatch.setattr(auto_update_records, "policy_file", lambda r, name: directory / name)
    from test_os_update_manifest import metadata
    value = metadata()
    verified = dict(metadata=value, manifest_sha256="e" * 64,
        images=dict(rootfs=dict(filename="rootfs.ext4", sha256="f" * 64, size=value["rootfs_bytes"]),
                    boot=dict(filename="boot.vfat", sha256="a" * 64, size=value["boot_bytes"])))
    bundle = root / "var/lib/rosy-device/os-update/staging" / value["release_id"] / value["bundle"]["filename"]
    monkeypatch.setattr(m, "verify_bundle", lambda *a: verified)
    monkeypatch.setattr(m.uuid, "uuid4", lambda: uuid.UUID(TRANSACTION))
    marker = root / "sys/fs/cgroup/cgroup.controllers"
    marker.parent.mkdir(parents=True)
    marker.write_text("cpu memory\n")
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        output = ""
        if "show" in argv:
            output = "ActiveState=inactive\nMainPID=0\nControlGroup=\n"
        return subprocess.CompletedProcess(argv, 0, output, "")
    def source_health(r, txn, *, host, run):
        m.authorize(r, txn, host=host)
        return host.current_release()
    monkeypatch.setattr(m, "source_health", source_health)
    monkeypatch.setattr(m, "watchdog_admit", lambda *a, **k: dict(boot_id=SOURCE_BOOT))
    def install(r, b, raw, signature, *, authorize, run):
        authorize()
        pending = state.read_state(r)["pending"]
        assert pending["phase"] == "INSTALLING"
        assert (r / "run/rosy-os-update/motion.env").read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"
        from os_update_install import report_path
        from os_state_io import _json_atomic
        report = dict(boot._binding(pending), native_factory=dict(schema_version=1, **value["native_factory"]),
                      metadata_sha256="c" * 64)
        _json_atomic(report_path(r, pending), report, 0o600)
        return dict(installed=True, manifest_sha256=verified["manifest_sha256"], report=report)
    monkeypatch.setattr(m, "rauc_install", install)
    return m, state, boot, root, journal, config, host, calls, run, bundle, directory


def test_source_install_reaches_verified_armed_and_requests_only_tryboot(tmp_path, monkeypatch):
    m, state, boot, root, _, config, host, calls, run, bundle, _ = _source(tmp_path, monkeypatch)
    result = m.start(root, bundle, b"signed metadata", "signature", host=host, run=run)
    assert result["pending"]["phase"] == "ARMED"
    assert config.read_bytes() == boot.autoboot("a")
    assert boot.invoke(root, ("get-primary",)) == "b"
    assert ["/usr/bin/systemctl", "--no-block", "--reboot-argument=0 tryboot", "reboot"] in calls
    assert state.read_state(root)["pending"]["transaction_id"] == TRANSACTION


@pytest.mark.parametrize("fault", ["disabled", "watchdog", "signature", "client", "receipt", "claim"])
def test_source_deferral_never_arms_or_changes_default(tmp_path, monkeypatch, fault):
    m, state, boot, root, _, config, host, calls, run, bundle, directory = _source(tmp_path, monkeypatch)
    def fail(*args, **kwargs): raise ValueError("modeled refusal")
    if fault == "disabled": (directory / "config.json").write_text('{"enabled":false}')
    elif fault in ("watchdog", "signature"):
        monkeypatch.setattr(m, "watchdog_admit" if fault == "watchdog" else "verify_bundle", fail)
    elif fault in ("client", "receipt"):
        if fault == "client": monkeypatch.setattr(m, "rauc_install", fail)
        else: monkeypatch.setattr(m, "rauc_install", lambda *a, **k: dict(installed=True, report={}))
    else:
        import rosy_claim
        rosy_claim.acquire(root, "foreign-owner", "fixture", 300, now=host.now())
    with pytest.raises(ValueError): m.start(root, bundle, b"metadata", "sig", host=host, run=run)
    assert config.read_bytes() == boot.autoboot("a")
    pending = state.read_state(root)["pending"]
    assert pending is None or pending["phase"] not in {"VERIFIED", "ARMED"}
    assert not any("reboot" in argv for argv in calls)


def test_trial_resume_runs_health_ack_and_commit_as_one_lifecycle(tmp_path, monkeypatch):
    from test_os_update_health import _health
    _, state, root, _, host, _, run, _, _, _ = _health(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_controller")
    import os_update_commit
    monkeypatch.setattr(os_update_commit, "capture", lambda r: dict(slot="b", layout=json.loads((r / "etc/rosy/os-media.json").read_text())))
    result = m.resume(root, host=host, run=run)
    assert result["pending"] is None and result["committed"]["slot"] == "b"
    assert state.read_state(root) == result


def test_failed_trial_requests_normal_fallback_without_clearing_pending(tmp_path, monkeypatch):
    from test_os_update_health import _health
    _, state, root, _, host, calls, run, _, _, _ = _health(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_controller")
    monkeypatch.setattr(m.health, "check", lambda *a, **k: (_ for _ in ()).throw(ValueError("modeled health refusal")))
    with pytest.raises(ValueError): m.resume(root, host=host, run=run)
    assert ["/usr/bin/systemctl", "--no-block", "reboot"] in calls
    assert state.read_state(root)["pending"]["phase"] == "TRIAL"


def test_busy_native_updater_prevents_posting_pending(tmp_path, monkeypatch):
    m, state, _, root, _, _, host, _, run, bundle, _ = _source(tmp_path, monkeypatch)
    import rosy_auto_update
    with rosy_auto_update.Updater._locked_file(root / "var/lib/rosy/updates/.run.lock"):
        with pytest.raises(ValueError): m.start(root, bundle, b"metadata", "sig", host=host, run=run)
    assert state.read_state(root)["pending"] is None


def test_fake_root_cannot_invoke_live_lifecycle_commands(tmp_path):
    m = importlib.import_module("os_update_controller")
    with pytest.raises(ValueError, match="explicit test runner"): m.resume(tmp_path)
    with pytest.raises(ValueError, match="explicit test runner"): m.start(tmp_path, tmp_path / "bundle", b"raw", "sig")
