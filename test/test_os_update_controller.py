"""Controller files/locks are real; hardware, service manager and RAUC install are explicit models."""
import datetime as dt
import importlib
import json
import struct
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
            values = dict(ActiveState="inactive", MainPID="0", ControlGroup="")
            output = values[argv[argv.index("-p") + 1]] if "--value" in argv else "\n".join(k + "=" + v for k, v in values.items())
        return subprocess.CompletedProcess(argv, 0, output, "")
    def source_health(r, txn, *, host, run):
        m.authorize(r, txn, host=host)
        return host.current_release()
    monkeypatch.setattr(m, "source_health", source_health)
    monkeypatch.setattr(m, "admit_release", lambda *a, **k: None, raising=False)  # Signed feed is tested over real HTTP separately.
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


@pytest.mark.parametrize("fresh_boot", [False, True])
def test_source_resume_records_failure_without_rearming_or_trusting_a_client_receipt(tmp_path, monkeypatch, fresh_boot):
    m, state, _, root, _, config, host, calls, run, bundle, _ = _source(tmp_path, monkeypatch)
    if fresh_boot:
        m.start(root, bundle, b"metadata", "sig", host=host, run=run)
        (root / "proc/sys/kernel/random/boot_id").write_text("44444444-4444-4444-8444-444444444444")
    else:
        def fail(*a, **k): raise ValueError("modeled lost RAUC client result")
        monkeypatch.setattr(m, "rauc_install", fail)
        with pytest.raises(ValueError): m.start(root, bundle, b"metadata", "sig", host=host, run=run)
    calls.clear()
    before = config.read_bytes()
    result = m.resume(root, host=host, run=run)
    assert result["pending"] is None and result["failed_versions"]
    assert result == state.read_state(root) and config.read_bytes() == before
    assert not any("reboot" in argv for argv in calls)


def test_published_intent_error_preserves_good_ack_for_the_next_resume(tmp_path, monkeypatch):
    from test_os_update_health import _health
    _, state, root, _, host, calls, run, _, _, _ = _health(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_controller")
    owner = m.commit_owner
    monkeypatch.setattr(owner, "capture", lambda r: dict(slot="b", layout=json.loads((r / "etc/rosy/os-media.json").read_text())))
    write = owner._write_atomic
    def uncertain(path, data, mode):
        write(path, data, mode)
        if path.name == "autoboot.txt": raise OSError("modeled uncertain parent fsync")
    monkeypatch.setattr(owner, "_write_atomic", uncertain)
    with pytest.raises(ValueError): m.resume(root, host=host, run=run)
    assert state.read_state(root)["pending"]["phase"] == "COMMIT_INTENT"
    from os_bootloader import ACK
    assert json.loads((root / ACK).read_text())["state"] == "good"
    assert not any("reboot" in argv for argv in calls)
    monkeypatch.setattr(owner, "_write_atomic", write)
    assert m.resume(root, host=host, run=run)["committed"]["slot"] == "b"


def test_source_health_checks_real_signed_runtime_without_starting_or_restarting_services(tmp_path, monkeypatch):
    m = importlib.import_module("os_update_controller")
    observe = m.source_health
    _, _, _, root, _, _, host, _, _, _, _ = _source(tmp_path, monkeypatch)
    from test_factory_release_signature import _keys, FACTORY_ID
    from test_os_factory_release import _factory
    private, public = _keys(tmp_path / "offline", "fixture")
    release, _ = _factory(root, FACTORY_ID, private, public, signed=True)
    (root / "opt/rosy/current").symlink_to("releases/" + FACTORY_ID)
    schema = root / "var/lib/rosy-device/state/schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text('{"schema_version":1,"state_schema":1}')
    guard = root / "etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf"
    guard.parent.mkdir(parents=True)
    native = m.Path(m.__file__).parent
    guard.write_bytes((native / "rosy-os-io-guard.conf").read_bytes())
    (root / "etc/systemd/system/rosy-io.service").write_bytes((release / "deploy/robot/native/rosy-io.service").read_bytes())
    host.current_release = lambda: FACTORY_ID
    host.process_cwd = lambda pid: str(release)
    monkeypatch.setattr(m.health, "verify_ready", lambda r: dict(boot_id=SOURCE_BOOT, slot="a"))
    monkeypatch.setattr(m.health, "_probe", lambda: None)
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        data = dict(ActiveState="active", SubState="running", MainPID="123", InvocationID="a" * 32, Result="success",
                    EnvironmentFiles=m.health.IO_ENVIRONMENT_FILES,
                    DropInPaths="/etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf")
        return subprocess.CompletedProcess(argv, 0, "\n".join(k + "=" + v for k, v in data.items()), "")
    m._claim(root, TRANSACTION, host)
    assert observe(root, TRANSACTION, host=host, run=run) == FACTORY_ID
    assert all("show" in command for command in commands)
    (release / "SHA256SUMS.sig").write_text("invalid signature")
    with pytest.raises(ValueError): observe(root, TRANSACTION, host=host, run=run)


@pytest.mark.parametrize("trial", [False, True])
def test_service_calls_never_run_under_native_release_or_state_lock(tmp_path, monkeypatch, trial):
    from native_release import NativeReleaseManager
    from os_factory_release import PUBLIC_KEY
    if trial:
        from test_os_update_health import _health
        _, state, root, _, host, _, run, _, _, _ = _health(tmp_path, monkeypatch)
        m = importlib.import_module("os_update_controller")
        monkeypatch.setattr(m.commit_owner, "capture", lambda r: dict(slot="b", layout=json.loads((r / "etc/rosy/os-media.json").read_text())))
    else:
        m, state, _, root, _, _, host, _, run, bundle, _ = _source(tmp_path, monkeypatch)
    commands = []
    def unlocked(argv, **kwargs):
        with NativeReleaseManager(root=root, public_key=root / PUBLIC_KEY)._locked(), state.locked(root):
            pass
        commands.append(argv)
        return run(argv, **kwargs)
    if trial: m.resume(root, host=host, run=unlocked)
    else: m.start(root, bundle, b"metadata", "sig", host=host, run=unlocked)
    assert commands


def test_source_observational_restart_settles_before_reauthorizing_arm(tmp_path, monkeypatch):
    from native_release import IO_SETTLE_S
    m, _, _, root, _, _, host, _, run, bundle, _ = _source(tmp_path, monkeypatch)
    sleep = host.sleep
    def settling(seconds):
        sleep(seconds)
        if seconds == IO_SETTLE_S:
            host.inputs_changes = {}
            host.write_inputs()
    def restarting(argv, **kwargs):
        if argv == ["/usr/bin/systemctl", "restart", "rosy-io.service"]:
            host.inputs_changes = dict(battery_percent=None)
            host.write_inputs()
        return run(argv, **kwargs)
    host.sleep = settling
    assert m.start(root, bundle, b"metadata", "sig", host=host, run=restarting)["pending"]["phase"] == "ARMED"


def test_committed_trial_requests_one_normal_boot_for_future_automatic_updates(tmp_path, monkeypatch):
    from test_os_update_health import _health
    from test_os_update_commit import _normal
    _, _, root, _, host, calls, run, _, _, _ = _health(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_controller")
    monkeypatch.setattr(m.commit_owner, "capture", lambda r: dict(slot="b", layout=json.loads((r / "etc/rosy/os-media.json").read_text())))
    assert m.resume(root, host=host, run=run)["pending"] is None
    normal_reboot = ["/usr/bin/systemctl", "--no-block", "reboot"]
    assert calls.count(normal_reboot) == 1
    assert not any("--reboot-argument=0 tryboot" in command for command in calls)
    _normal(root, "b")
    assert m.resume(root, host=host, run=run)["pending"] is None
    assert calls.count(normal_reboot) == 1
    (root / "proc/device-tree/chosen/bootloader/tryboot").write_bytes(struct.pack(">I", 1))
    assert m.resume(root, host=host, run=run)["pending"] is None
    assert calls.count(normal_reboot) == 1  # A different boot cannot repeat this transaction's normalization.


def test_untracked_committed_tryboot_flag_does_not_request_reboot(tmp_path, monkeypatch):
    m, _, _, root, _, _, host, calls, run, _, _ = _source(tmp_path, monkeypatch)
    (root / "proc/device-tree/chosen/bootloader/tryboot").write_bytes(struct.pack(">I", 1))
    assert m.resume(root, host=host, run=run)["pending"] is None
    assert not any("reboot" in command for command in calls)


def test_rollout_is_checked_before_install_and_again_before_arm(tmp_path, monkeypatch):
    m, state, _, root, _, _, host, _, run, bundle, _ = _source(tmp_path, monkeypatch)
    phases = []
    def admission(r, metadata, *, host):
        pending = state.read_state(r)["pending"]
        phases.append(None if pending is None else pending["phase"])
    monkeypatch.setattr(m, "admit_release", admission)
    assert m.start(root, bundle, b"metadata", "sig", host=host, run=run)["pending"]["phase"] == "ARMED"
    assert phases == [None, "INSTALLING", "VERIFIED"]


def test_verified_withdrawal_after_install_returns_to_source_without_arm(tmp_path, monkeypatch):
    from os_update_feed import Withdrawn
    m, state, boot, root, _, config, host, calls, run, bundle, _ = _source(tmp_path, monkeypatch)
    def admission(r, metadata, *, host):
        pending = state.read_state(r)["pending"]
        if pending is not None and pending["phase"] == "VERIFIED": raise Withdrawn("verified fixture withdrawal")
    monkeypatch.setattr(m, "admit_release", admission)
    result = m.start(root, bundle, b"metadata", "sig", host=host, run=run)
    assert result["pending"] is None and result["failed_versions"]
    assert config.read_bytes() == boot.autoboot("a")
    assert not any("reboot" in argv for argv in calls)
