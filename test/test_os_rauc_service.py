"""Actual private files/media admission with a recording manager; no host service or block writes."""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from test_os_bootloader import _boot, _permit
from test_os_frozen_firstboot import BASE
from os_rauc_fakes import rauc_tool


class Manager:
    def __init__(self, module, root, prepared, fault=None):
        self.module, self.root, self.fault = module, root, fault
        self.calls, self.active, self.installs = [], False, 0
        self.devices = "char-rtc r\n" + "\n".join(line.removeprefix("DeviceAllow=") for line in prepared["device_dropin"].splitlines()
                                 if line.startswith("DeviceAllow=") and line != "DeviceAllow=")

    def __call__(self, argv, timeout=60):
        self.calls.append(argv)
        name = self.module.SERVICE
        code, output = 0, ""
        if argv[:2] == ["systemctl", "stop"]:
            if self.fault == "stop" and self.active: code = 1
            else:
                lingering = self.fault == "children" and self.active
                self.active = False
                events = self.root / "sys/fs/cgroup/system.slice/rosy-os-rauc.service/cgroup.events"
                events.write_text(f"populated {1 if lingering else 0}\nfrozen 0\n")
        elif argv[:2] == ["systemctl", "show"]:
            key = argv[argv.index("-p") + 1]
            values = dict(ActiveState="active" if self.active else "inactive", MainPID="123" if self.active else "0",
                ControlGroup="/system.slice/rosy-os-rauc.service" if self.active else "",
                FragmentPath="/etc/systemd/system/" + name, DropInPaths="/" + self.module.DROPIN,
                DevicePolicy="closed", DeviceAllow=self.devices,
                ReadWritePaths="/run/rosy-os-update/rauc /var/lib/rosy-device/os-update/rauc", ProtectSystem="strict")
            if self.fault == "devices": values["DeviceAllow"] += "\n/dev/block/8:4 rw"
            if self.fault == "rtc_write": values["DeviceAllow"] = values["DeviceAllow"].replace("char-rtc r\n", "char-rtc rw\n")
            if self.fault == "filesystem": values["ReadWritePaths"] += " /boot/firmware"
            output = values[key]
        elif argv[:2] == ["systemctl", "start"]:
            self.module.check(self.root, run=self)
            self.active = True
        elif "install" in argv:
            assert self.active
            self.installs += 1
            if self.fault == "install": code = 1
            elif self.fault != "finalizer":
                # Model the daemon's trusted post-handler result; its real file/mount logic has its own suite.
                from os_bootloader import _binding
                from os_state_io import _json_atomic
                from os_update_install import report_path
                pending = self.module.read_state(self.root)["pending"]
                report = dict(_binding(pending), metadata_sha256="a" * 64,
                    native_factory=dict(schema_version=1, **pending["verified"]["metadata"]["native_factory"]))
                _json_atomic(report_path(self.root, pending), report, 0o600)
        else:
            assert argv == ["systemctl", "daemon-reload"]
        return subprocess.CompletedProcess(argv, code, output, "fixture failure" if code else "")


def _case(tmp_path, monkeypatch, fault=None):
    boot, state, root, journal, config = _boot(tmp_path, monkeypatch, "INSTALLING")
    _permit(boot, state, root)
    import os_motion_guard
    os_motion_guard.reconcile(root)
    controllers = root / "sys/fs/cgroup/cgroup.controllers"
    controllers.parent.mkdir(parents=True)
    controllers.write_text("cpu io memory pids\n")
    events = controllers.parent / "system.slice/rosy-os-rauc.service/cgroup.events"
    events.parent.mkdir(parents=True)
    events.write_text("populated 0\nfrozen 0\n")
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
    for source, target in m.ASSETS:
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


@pytest.mark.parametrize("fault", ["devices", "rtc_write", "filesystem", "install"])
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


@pytest.mark.parametrize("encoding", ["utf8", "utf16"])
def test_lifecycle_uses_actual_ed_cms_and_verity_verification_with_a_modeled_manager(tmp_path, monkeypatch, rauc_tool, encoding):
    from test_os_rauc import _case as signed_case, _consumer
    from test_os_frozen_firstboot import _prefix, _stage
    m, root, bundle, _, _, manager, journal, config = _case(tmp_path / "device", monkeypatch)
    verifier = _consumer(monkeypatch, rauc_tool)
    runtime = importlib.import_module("os_rauc_runtime")
    monkeypatch.setattr(runtime, "verify_bundle", verifier.verify_bundle)
    signed_root, signed_bundle, raw, signature, private, _ = signed_case(tmp_path / "signed", rauc_tool)
    if encoding == "utf16":
        from signing import sign_checksums
        raw = json.dumps(json.loads(raw)).encode("utf-16")
        signature = sign_checksums(raw, private)
    for relative in (verifier.ED_KEY, verifier.CMS_KEY):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(signed_root / relative, target)
    bundle.chmod(0o600)
    shutil.copyfile(signed_bundle, bundle)
    bundle.chmod(0o400)
    value = json.loads(journal.read_text())
    value["pending"]["verified"] = verifier.verify_bundle(root, bundle, raw, signature)
    journal.write_text(json.dumps(value))
    before = journal.read_bytes(), config.read_bytes()
    prepared = runtime.prepare(root, bundle, raw, signature)
    prefix = _prefix(tmp_path / "installed")
    _stage(prefix)
    for folder in (prefix / "native-runtime", prefix / "deploy/sd"):
        for path in folder.glob("*.py"):
            path.write_text("raise RuntimeError('mutable SDK was imported')\n")
    code = """
import json,sys,subprocess
from pathlib import Path
frozen=Path(sys.argv[1])/'os-bootstrap/native-runtime'
sys.path[:0]=[str(frozen),str(Path(sys.argv[1])/'native-runtime')]
data=json.loads(sys.stdin.read())
import os_rauc,os_update_state,os_media
os_rauc.RAUC=sys.argv[3]
# Model only kernel and manager observations; actual frozen crypto and preflight execute.
os_update_state.mount_facts=lambda *args: []
os_media.capture=lambda *args: data['media']
import os_rauc_service as service
def manager(argv,timeout=60):
    assert argv[:2]==['systemctl','show']
    return subprocess.CompletedProcess(argv,0,data['properties'][argv[argv.index('-p')+1]],'')
service.check(Path(sys.argv[2]),run=manager)
for name in ('os_rauc_service','os_rauc_runtime','os_rauc','os_update_state','os_bootloader','os_storage_dispatch','signing','media_layout'):
    assert Path(sys.modules[name].__file__).is_relative_to(frozen)
"""
    properties = dict(FragmentPath="/etc/systemd/system/" + m.SERVICE, DropInPaths="/" + m.DROPIN,
        ProtectSystem="strict", DevicePolicy="closed", DeviceAllow=manager.devices,
        ReadWritePaths="/run/rosy-os-update/rauc /var/lib/rosy-device/os-update/rauc")
    def authorize():
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(prefix), str(root), str(rauc_tool)],
            input=json.dumps(dict(media=prepared["media"], properties=properties)),
            capture_output=True, text=True, timeout=30, cwd=tmp_path)
        assert result.returncode == 0, result.stderr
    assert m.install(root, bundle, raw, signature, run=manager, authorize=authorize)["installed"]
    assert manager.installs == 1 and not manager.active
    assert (journal.read_bytes(), config.read_bytes()) == before


def test_static_unit_is_accepted_by_the_actual_systemd_parser_in_an_offline_root(tmp_path):
    analyze = shutil.which("systemd-analyze")
    assert analyze, "systemd-analyze is required by the Ubuntu test environment"
    units = tmp_path / "etc/systemd/system"
    units.mkdir(parents=True)
    shutil.copyfile(BASE / "native/rosy-os-rauc.service", units / "rosy-os-rauc.service")
    # Only dependency fixtures: verify parses the real RAUC unit, never starts PID1 or a service.
    for target in ("sysinit.target", "basic.target", "shutdown.target", "sockets.target"):
        (units / target).write_text("[Unit]\nDescription=fixture\nDefaultDependencies=no\n")
    for name in ("dbus.service", "rosy-os-storage.service", "rosy-os-motion-guard.service", "rosy-io.service", "rosy-navigation.service"):
        (units / name).write_text("[Unit]\nDefaultDependencies=no\n[Service]\nType=oneshot\nExecStart=/usr/bin/true\n")
    (units / "dbus.socket").write_text("[Unit]\nDefaultDependencies=no\n[Socket]\nListenStream=/run/dbus/system_bus_socket\n")
    binaries = tmp_path / "usr/bin"
    binaries.mkdir(parents=True)
    for name in ("python3", "rauc", "true"):
        path = binaries / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    result = subprocess.run([analyze, "verify", "--man=no", "--root=" + str(tmp_path), "rosy-os-rauc.service"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_successful_client_without_finalizer_receipt_is_hold(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch, "finalizer")
    before = journal.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="receipt"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert (journal.read_bytes(), config.read_bytes()) == before
    assert not manager.active and not (root / m.RUNTIME).exists()


def test_prior_receipt_is_not_replayed_as_a_new_install(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch)
    m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    before = len(manager.calls)
    with pytest.raises(ValueError, match="receipt"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert manager.installs == 1 and len(manager.calls) == before


def test_parent_exit_does_not_revoke_files_while_any_cgroup_child_is_alive(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, journal, config = _case(tmp_path, monkeypatch, "children")
    before = journal.read_bytes(), config.read_bytes()
    with pytest.raises(ValueError, match="cgroup"):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    assert not manager.active  # Parent is gone, but the kernel still reports a live child.
    assert (root / m.RUNTIME / "request.json").exists()
    assert (journal.read_bytes(), config.read_bytes()) == before


def test_recovery_removes_only_known_empty_finalizer_mountpoints_after_stop(tmp_path, monkeypatch):
    m, root, bundle, raw, signature, manager, _, _ = _case(tmp_path, monkeypatch, "stop")
    with pytest.raises(ValueError):
        m.install(root, bundle, raw, signature, run=manager, authorize=lambda: None)
    from os_update_install import WORK
    work = root / WORK
    for name in ("root", "boot"):
        (work / name).mkdir(parents=True, mode=0o700)
    work.chmod(0o700)
    manager.fault = None
    m.recover(root, run=manager)
    assert not (root / m.RUNTIME).exists()
