"""Trial health uses real durable files; service, projection, signature and watchdog observations are models here."""
import importlib
import subprocess

import pytest

from test_os_update_policy import _trial_policy
from test_os_update_state import TRANSACTION, TRIAL_BOOT


def _health(tmp_path, monkeypatch):
    _, state, root, journal, _, _, _, host = _trial_policy(tmp_path, monkeypatch)
    m = importlib.import_module("os_update_health")
    pending = state.read_state(root)["pending"]
    directory = journal.parent / "rauc"
    directory.mkdir(mode=0o700)
    calls = []
    ready = dict(schema_version=1, boot_id=TRIAL_BOOT, slot="b")
    factory = dict(schema_version=1, **pending["verified"]["metadata"]["native_factory"])
    monkeypatch.setattr(m, "verify_ready", lambda r: ready)
    monkeypatch.setattr(m, "verify_current", lambda r, v: factory)
    monkeypatch.setattr(m, "read_bound_report", lambda r, p: dict(native_factory=factory))
    monkeypatch.setattr(m, "observe_watchdog", lambda r, **k: dict(boot_id=TRIAL_BOOT))
    monkeypatch.setattr(m, "_probe", lambda: None)
    monkeypatch.setattr(m, "_now", lambda: 40_000_000_000)
    frozen = m.Path(m.__file__).parent / "rosy-os-io-guard.conf"
    dropin = root / "etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf"
    dropin.parent.mkdir(parents=True)
    dropin.write_bytes(frozen.read_bytes())
    data = dict(ActiveState="active", SubState="running", MainPID="123", InvocationID="a" * 32,
                Result="success", EnvironmentFiles=m.IO_ENVIRONMENT_FILES,
                DropInPaths="/etc/systemd/system/rosy-io.service.d/zz-rosy-os-guard.conf")
    def run(argv, **kwargs):
        calls.append(argv)
        if "show" in argv:
            if "rosy-navigation.service" in argv:
                value = dict(ActiveState="inactive", MainPID="0", ControlGroup="")
            else:
                value = data
            return subprocess.CompletedProcess(argv, 0, "\n".join(k + "=" + v for k, v in value.items()), "")
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(m, "_empty_cgroup", lambda *a, **kw: None)
    return m, state, root, journal, host, calls, run, data, ready, dropin


def test_trial_health_restarts_inhibited_io_and_binds_durable_receipt_without_committing(tmp_path, monkeypatch):
    m, state, root, journal, host, calls, run, _, _, _ = _health(tmp_path, monkeypatch)
    before = journal.read_bytes()
    report = m.check(root, TRANSACTION, host=host, run=run)
    assert report["boot_id"] == TRIAL_BOOT and report["target_slot"] == "b"
    assert report["samples"]["second_written_at"] > report["samples"]["first_written_at"]
    assert report == m.read_health(root, state.read_state(root)["pending"])
    assert journal.read_bytes() == before
    assert calls.index(["/usr/bin/systemctl", "stop", "rosy-navigation.service"]) < calls.index(
        ["/usr/bin/systemctl", "restart", "rosy-io.service"])
    assert not any("reboot" in command for command in calls)
    assert (root / "run/rosy-os-update/motion.env").read_text() == "ROSY_IO_DRIVE_ENABLED=false\n"


@pytest.mark.parametrize("damage", ["factory", "projection", "watchdog", "api", "environment", "dropin",
    "navigation", "restart", "pid", "invocation", "boot", "deadline", "expired_receipt"])
def test_unknown_or_changed_health_cannot_publish_usable_evidence(tmp_path, monkeypatch, damage):
    m, state, root, journal, host, _, run, data, ready, dropin = _health(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise ValueError("modeled observation unavailable")
    if damage in ("factory", "watchdog", "api"):
        monkeypatch.setattr(m, {"factory": "verify_current", "watchdog": "observe_watchdog", "api": "_probe"}[damage], fail)
    elif damage == "projection": ready["boot_id"] = TRANSACTION
    elif damage == "environment": data["EnvironmentFiles"] = "/etc/rosy/runtime.env (ignore_errors=no)"
    elif damage == "dropin": dropin.write_text("[Service]\n")
    elif damage in ("navigation", "restart"):
        original = run
        def run(argv, **kwargs):
            if (damage == "navigation" and "rosy-navigation.service" in argv and "show" in argv
                    or damage == "restart" and "restart" in argv):
                return subprocess.CompletedProcess(argv, 1, "", "unavailable")
            return original(argv, **kwargs)
    elif damage == "deadline": monkeypatch.setattr(m, "_now", lambda: 166_000_000_000)
    elif damage != "expired_receipt":
        original = host.sleep
        def sleep(seconds):
            original(seconds)
            if damage == "pid": data["MainPID"] = "456"
            elif damage == "invocation": data["InvocationID"] = "b" * 32
            else: (root / "proc/sys/kernel/random/boot_id").write_text(TRANSACTION)
        host.sleep = sleep
    before = journal.read_bytes()
    if damage == "expired_receipt":
        m.check(root, TRANSACTION, host=host, run=run)
        monkeypatch.setattr(m, "_now", lambda: 71_000_000_000)
        with pytest.raises(ValueError):
            m.read_health(root, state.read_state(root)["pending"])
    else:
        with pytest.raises(ValueError):
            m.check(root, TRANSACTION, host=host, run=run)
    assert journal.read_bytes() == before


def test_health_with_a_fake_root_never_uses_the_real_service_manager(tmp_path):
    m = importlib.import_module("os_update_health")
    with pytest.raises(ValueError, match="explicit test runner"):
        m.check(tmp_path, TRANSACTION)
