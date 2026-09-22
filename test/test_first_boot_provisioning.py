from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
import os
from pathlib import Path

import pytest

from deploy.sd.personalization import DeviceIdentity, create_provision_bundle


ROOT = Path(__file__).resolve().parents[1]
FIRST_BOOT = ROOT / "deploy" / "image" / "first-boot"


def _module():
    path = FIRST_BOOT / "rosy-first-boot.py"
    spec = importlib.util.spec_from_file_location("rosy_first_boot", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bundle() -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="9d40feaa-871f-4fd3-975a-a704e82d3af9",
            device_name="rosy-pinky-k7m4",
            hostname="rosy-pinky-k7m4",
            model="pinky_pro",
        ),
        release_id="2026.09.22-001",
        robot_number=3,
        requested_preset="hardware",
        country_code="KR",
        ssid="fixture-wifi",
        wifi_passphrase="fixture-pass-9384",
        fleet_endpoint="https://fleet.fixture.invalid:8443",
        fleet_trust_profile="site-ca-2026",
        pairing_required=True,
        pairing_credential="fixture-one-time-pairing-credential",
        created_at=datetime(2026, 9, 22, 1, 2, 3, tzinfo=UTC),
        nonce="fixture-first-boot-nonce",
    )


def _case(tmp_path: Path):
    root = tmp_path / "root"
    bundle = root / "boot/firmware/rosy-provision/provision.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    return root, bundle


def test_valid_bundle_personalizes_ubuntu_and_is_consumed_once(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    calls: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root,
        network_activate=lambda profile: calls.append(profile) or True,
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": True, "state": "PROVISIONED", "device_name": "rosy-pinky-k7m4"}
    assert not bundle.exists()
    assert calls == ["rosy-site-sta"]
    assert (root / "etc/hostname").read_text(encoding="utf-8") == "rosy-pinky-k7m4\n"
    runtime = (root / "etc/rosy/runtime.env").read_text(encoding="utf-8")
    assert "ROSY_ROBOT_NUMBER=3" in runtime
    assert "ROS_DOMAIN_ID=43" in runtime
    assert "ROSY_NAMESPACE=rosy_03" in runtime
    assert "ROSY_RUNTIME_MODE=core" in runtime
    network = root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection"
    rendered = network.read_text(encoding="utf-8")
    assert "ssid=fixture-wifi" in rendered
    assert "psk=" in rendered and "fixture-pass-9384" not in rendered
    if os.name == "posix":
        assert os.stat(network).st_mode & 0o777 == 0o600
    complete = json.loads(
        (root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8")
    )
    assert complete["hardware_serial"] == "10000000abcdef01"
    assert complete["requested_preset"] == "hardware"
    assert complete["active_runtime"] == "core"
    assert "wpa_psk" not in json.dumps(complete)
    fleet = json.loads((root / "etc/rosy/fleet-bootstrap.json").read_text(encoding="utf-8"))
    assert fleet["pairing_credential"] == "fixture-one-time-pairing-credential"
    if os.name == "posix":
        assert os.stat(root / "etc/rosy/fleet-bootstrap.json").st_mode & 0o777 == 0o600
    source = (FIRST_BOOT / "rosy-first-boot.py").read_text(encoding="utf-8")
    assert "network_path, self._network_profile(payload), 0o600" in source
    assert '"etc/rosy/fleet-bootstrap.json"), payload["fleet"], 0o600' in source


def test_wrong_wifi_returns_to_provisioning_hold_without_consuming_bundle(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: False)

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result == {"ok": False, "state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
    assert bundle.exists(), "the powered-off card must remain repairable"
    assert not (root / "var/lib/rosy/provisioning/complete.json").exists()
    assert not (root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection").exists()
    state = json.loads((root / "var/lib/rosy/provisioning/state.json").read_text(encoding="utf-8"))
    assert state == {"state": "PROVISIONING_AP", "reason": "site_wifi_unreachable"}
    assert "fixture-pass-9384" not in json.dumps(result) + json.dumps(state)


def test_failed_network_still_binds_card_identity_to_first_hardware_serial(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _profile: False
    )
    provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    binding = json.loads(
        (root / "var/lib/rosy/provisioning/hardware-binding.json").read_text(
            encoding="utf-8"
        )
    )
    assert binding["hardware_serial"] == "10000000abcdef01"
    assert binding["device_uid"] == "9d40feaa-871f-4fd3-975a-a704e82d3af9"
    with pytest.raises(ValueError, match="hardware serial"):
        provisioner.apply(bundle=bundle, hardware_serial="10000000deadbeef")


def test_completed_device_does_not_replay_a_reinserted_bundle(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    first = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)
    first.apply(bundle=bundle, hardware_serial="10000000abcdef01")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps(_bundle()), encoding="utf-8")
    calls: list[str] = []

    result = module.FirstBootProvisioner(
        root=root, network_activate=lambda profile: calls.append(profile) or True
    ).apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "ALREADY_PROVISIONED"
    assert calls == []


def test_hardware_serial_change_is_a_fail_closed_identity_mismatch(tmp_path):
    module = _module()
    root, bundle = _case(tmp_path)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)
    provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    with pytest.raises(ValueError, match="hardware serial"):
        provisioner.apply(bundle=bundle, hardware_serial="10000000deadbeef")


def test_first_boot_unit_orders_personalization_before_network_and_runtime():
    unit = (FIRST_BOOT / "rosy-first-boot.service").read_text(encoding="utf-8")
    script = (FIRST_BOOT / "rosy-first-boot.sh").read_text(encoding="utf-8")

    assert "After=local-fs.target NetworkManager.service" in unit
    assert "Before=network-online.target rosy-sd-provision.service rosy-runtime.target" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "ExecStart=/opt/rosy/first-boot/rosy-first-boot.sh" in unit
    assert "rosy-first-boot.py" in script
    assert "apt " not in script
    assert "curl " not in script
    assert "docker" not in (unit + script).lower()


def test_provisioning_gate_requires_first_boot_to_finish():
    gate = (ROOT / "deploy/robot/native/rosy-sd-provision.service").read_text(encoding="utf-8")

    assert "Requires=rosy-first-boot.service" in gate
    assert "After=rosy-first-boot.service" in gate


def test_hostname_is_applied_live_before_the_network_comes_up(tmp_path):
    # D-174 F2: only /etc/hostname was written, so avahi kept announcing ubuntu.local
    # and DHCP sent the old name until a reboot.
    module = _module()
    root, bundle = _case(tmp_path)
    order: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root,
        network_activate=lambda profile: order.append(f"network:{profile}") or True,
        hostname_apply=lambda name: order.append(f"hostname:{name}"),
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert order == ["hostname:rosy-pinky-k7m4", "network:rosy-site-sta"]


def test_live_hostname_failure_does_not_block_personalization(tmp_path, capsys):
    module = _module()
    root, bundle = _case(tmp_path)

    def broken(_name):
        raise OSError("hostnamectl unavailable")

    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _profile: True, hostname_apply=broken,
    )

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert (root / "etc/hostname").read_text(encoding="utf-8") == "rosy-pinky-k7m4\n"
    assert "live hostname" in capsys.readouterr().err


def test_default_live_hostname_never_touches_the_host_when_root_is_not_slash(tmp_path, monkeypatch):
    module = _module()
    root, bundle = _case(tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("must not run host commands for a non-/ root")

    monkeypatch.setattr(module.subprocess, "run", refuse)
    provisioner = module.FirstBootProvisioner(root=root, network_activate=lambda _profile: True)

    result = provisioner.apply(bundle=bundle, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"


def test_default_live_hostname_uses_hostnamectl_then_restarts_avahi(monkeypatch):
    module = _module()
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(module.subprocess, "run", lambda command, **_kw: calls.append(command) or Done())

    module._default_hostname_apply("rosy-pinky-k7m4")

    assert calls[0] == ["hostnamectl", "set-hostname", "rosy-pinky-k7m4"]
    assert ["systemctl", "try-restart", "avahi-daemon.service"] in calls
