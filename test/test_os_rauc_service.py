"""Actual private files/media admission with a recording manager; no host service or block writes."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from test_os_bootloader import _boot, _permit
from test_os_frozen_firstboot import BASE


class Manager:
    def __init__(self, module, root, prepared, fault=None):
        self.module, self.root, self.fault = module, root, fault
        self.calls, self.active, self.installs = [], False, 0
        self.devices = "\n".join(line.removeprefix("DeviceAllow=") for line in prepared["device_dropin"].splitlines()
                                 if line.startswith("DeviceAllow=") and line != "DeviceAllow=")

    def __call__(self, argv, timeout=60):
        self.calls.append(argv)
        name = self.module.SERVICE
        code, output = 0, ""
        if argv[:2] == ["systemctl", "stop"]:
            if self.fault == "stop" and self.active: code = 1
            else: self.active = False
        elif argv[:2] == ["systemctl", "show"]:
            key = argv[argv.index("-p") + 1]
            values = dict(ActiveState="active" if self.active else "inactive", MainPID="123" if self.active else "0",
                FragmentPath="/etc/systemd/system/" + name, DropInPaths="/" + self.module.DROPIN,
                DevicePolicy="closed", DeviceAllow=self.devices,
                ReadWritePaths="/run/rosy-os-update/rauc /var/lib/rosy-device/os-update/rauc", ProtectSystem="strict")
            if self.fault == "devices": values["DeviceAllow"] += "\n/dev/block/8:4 rw"
            if self.fault == "filesystem": values["ReadWritePaths"] += " /boot/firmware"
            output = values[key]
        elif argv[:2] == ["systemctl", "start"]:
            self.module.check(self.root, run=self)
            self.active = True
        elif "install" in argv:
            assert self.active
            self.installs += 1
            if self.fault == "install": code = 1
        else:
            assert argv == ["systemctl", "daemon-reload"]
        return subprocess.CompletedProcess(argv, code, output, "fixture failure" if code else "")


def _case(tmp_path, monkeypatch, fault=None):
    boot, state, root, journal, config = _boot(tmp_path, monkeypatch, "INSTALLING")
    _permit(boot, state, root)
    m = importlib.import_module("os_rauc_service")
    runtime = importlib.import_module("os_rauc_runtime")
    verified = state.read_state(root)["pending"]["verified"]
    # Crypto is modeled in these manager tests; separate integration uses actual RAUC/OpenSSL.
    monkeypatch.setattr(runtime, "verify_bundle", lambda *args: verified)
    stage = root / "var/lib/rosy-device/os-update/staging" / verified["metadata"]["release_id"]
    stage.mkdir(parents=True, mode=0o700)
    bundle = stage / verified["metadata"]["bundle"]["filename"]
    bundle.write_bytes(b"modeled bundle")
    bundle.chmod(0o400)
    raw, signature = json.dumps(verified["metadata"]).encode(), "fixture-signature"
    for source, target in m.ASSETS.items():
        for path in (root / target, root / "opt/rosy/os-bootstrap/native-runtime" / source):
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / "native" / source, path)
    prepared = runtime.prepare(root, bundle, raw, signature)
    manager = Manager(m, root, prepared, fault)
    return m, root, bundle, raw, signature, manager, journal, config


def test_controlled_daemon_lifecycle_rechecks_before_install_and_revokes_after_stop(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch)
    before = journal.read_bytes(), config.read_bytes()
    assert m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)["installed"] is True
    assert manager.installs == 1 and not manager.active
    commands = [argv[:2] for argv in manager.calls]
    assert commands.index(["systemctl", "stop"]) < commands.index(["systemctl", "start"])
    assert manager.calls[-1] == ["systemctl", "daemon-reload"]
    assert not (root / m.RUNTIME).exists() and not (root / m.DROPIN).exists()
    assert (journal.read_bytes(), config.read_bytes()) == before


@pytest.mark.parametrize("fault", ["devices", "filesystem", "install"])
def test_install_failure_or_effective_permission_drift_never_arms_or_changes_bootstrap(tmp_path, monkeypatch, fault):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch, fault)
    before = journal.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="OS_RAUC_SERVICE_HOLD"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert not manager.active
    assert manager.installs == (1 if fault == "install" else 0)
    assert (journal.read_bytes(), config.read_bytes()) == before
    assert not (root / m.DROPIN).exists()


def test_a_daemon_that_cannot_be_stopped_keeps_configuration_for_recovery(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch, "stop")
    before = journal.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="OS_RAUC_SERVICE_HOLD"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert manager.active and (root / m.DROPIN).exists()
    assert (root / m.RUNTIME / "request.json").exists()
    assert (journal.read_bytes(), config.read_bytes()) == before


def test_wrong_phase_refuses_before_any_manager_operation(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, _ = _case(tmp_path, monkeypatch)
    value = json.loads(journal.read_text())
    value["pending"]["phase"] = "PREPARED"
    journal.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="OS_RAUC_SERVICE_HOLD"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert manager.calls == []


def test_live_assets_must_match_the_frozen_os_owner(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch)
    (root / "etc/systemd/system" / m.SERVICE).write_text("[Service]\nExecStart=/foreign\n")
    with pytest.raises(ValueError, match="OS_RAUC_SERVICE_HOLD"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert manager.calls == []


def test_os_daemon_and_bus_policy_are_static_and_root_only():
    unit = (BASE / "native/rosy-os-rauc.service").read_text()
    for line in ("Type=dbus", "BusName=de.pengutronix.rauc", "User=root", "Group=root",
                 "NoNewPrivileges=true", "ProtectSystem=strict", "PrivateDevices=false", "PrivateMounts=true",
                 "DevicePolicy=closed", "DeviceAllow=", "RestrictAddressFamilies=AF_UNIX"):
        assert line in unit.splitlines()
    assert "ExecStart=/usr/bin/rauc --conf=/run/rosy-os-update/rauc/system.conf service" in unit
    assert "os-bootstrap/native-runtime/os_rauc_service.py check" in unit
    assert "[Install]" not in unit and "CAP_SYS_PTRACE" not in unit
    document = ET.parse(BASE / "native/rosy-rauc-dbus.conf").getroot()
    default = document.find("policy[@context='default']")
    assert default.find("deny[@send_destination='de.pengutronix.rauc']") is not None
    assert default.find("deny[@own='de.pengutronix.rauc']") is not None
    root = document.find("policy[@user='root']")
    assert root.find("allow[@send_destination='de.pengutronix.rauc']") is not None
    assert root.find("allow[@own='de.pengutronix.rauc']") is not None


def test_caller_must_supply_final_policy_authorization_before_any_manager_mutation(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch)
    with pytest.raises(TypeError, match="authorize"):
        m.install(root, bundle, raw, signature, run=manager)
    assert manager.calls == []


def test_final_policy_deferral_runs_after_start_and_before_the_install_client(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch)
    checked = []
    def authorize():
        checked.append(manager.active)
        raise ValueError("operator Hold became active")
    before = journal.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="operator Hold"):
        m.install(root, bundle, raw, signature, run=manager, authorize=authorize)
    assert checked == [True] and manager.installs == 0 and not manager.active
    assert (journal.read_bytes(), config.read_bytes()) == before


def test_media_is_recaptured_after_final_policy_authorization(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, _, config = _case(tmp_path, monkeypatch)
    def authorize():
        path = root / "sys/devices/virtual/block/sda/sda5/size"
        path.write_text(str(int(path.read_text()) - 1))
    before = config.read_bytes()
    with pytest.raises(ValueError, match="kernel partition range"):
        m.install(root, bundle, raw, signature, run=manager, authorize=authorize)
    assert manager.installs == 0 and not manager.active and config.read_bytes() == before


def test_long_bundle_verification_is_followed_by_fresh_authorization_not_a_sixty_second_replay_limit(tmp_path, monkeypatch):
    import rosy_claim
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch)
    pending = json.loads((root / "var/lib/rosy-device/os-update/state.json").read_text())["pending"]
    rosy_claim.refresh(root, "os-update:" + pending["transaction_id"], 3600)
    original, origin = m.check, m.time.monotonic_ns()
    def delayed(*args, **kwargs):
        monkeypatch.setattr(m.time, "monotonic_ns", lambda: origin + 180_000_000_000)
        return original(*args, **kwargs)
    monkeypatch.setattr(m, "check", delayed)
    authorized = []
    assert m.install(root, bundle, raw, signature, run=manager, authorize=lambda: authorized.append(manager.active))["installed"]
    assert authorized == [True] and manager.installs == 1


def test_recovery_revokes_known_runtime_after_claim_expiry_without_reinstalling(tmp_path, monkeypatch):
    import rosy_claim
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch, "stop")
    with pytest.raises(ValueError):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    manager.fault = None
    pending = json.loads((root / "var/lib/rosy-device/os-update/state.json").read_text())["pending"]
    rosy_claim.release(root, "os-update:" + pending["transaction_id"])
    m.recover(root, run=manager)
    assert not manager.active and manager.installs == 1 and not (root / m.RUNTIME).exists()
    assert not (root / m.DROPIN).exists()
