"""Moving a personalized card to a new Pi archives the old device before reuse."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json

import pytest

from deploy.sd.personalization import DeviceIdentity, create_provision_bundle
from test_first_boot_provisioning import FIRST_BOOT, _case, _module


def _rebind():
    path = FIRST_BOOT / "rosy-rebind-board.py"
    spec = importlib.util.spec_from_file_location("rosy_rebind_board", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh_bundle(root):
    path = root / "run/rosy-new-device-bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="1e134919-11c0-4273-a51e-29f7af1aeac9",
            device_name="rosy-pinky-p8q4", hostname="rosy-pinky-p8q4", model="pinky_pro",
        ),
        release_id="2026.09.22-001", robot_number=4,
        requested_preset="core", country_code="KR", ssid="fixture-wifi",
        wifi_passphrase="fixture-pass-9384",
        fleet_endpoint="https://fleet.fixture.invalid:8443",
        fleet_trust_profile="site-ca-2026", pairing_required=True,
        pairing_credential="fixture-new-pairing-credential",
        core_api_token="Tq" * 21 + "_", core_api_token_id="1a2b3c4d5e6f",
        created_at=datetime(2026, 9, 26, 1, 2, 3, tzinfo=UTC),
        nonce="fixture-new-board-nonce",
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_rebind_archives_previous_device_and_can_provision_new_board(tmp_path):
    first_boot = _module()
    rebind = _rebind()
    root, old_bundle = _case(tmp_path)
    provisioner = first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: True)
    provisioner.apply(bundle=old_bundle, hardware_serial="10000000abcdef01")
    old_core = root / "var/lib/rosy/core/.rosy/audit.jsonl"
    old_core.parent.mkdir(parents=True, exist_ok=True)
    old_core.write_text("old robot record", encoding="utf-8")
    fresh = _fresh_bundle(root)

    archive = rebind.quarantine_previous(root, fresh, "10000000deadbeef")
    assert (archive / "var/lib/rosy/core/.rosy/audit.jsonl").read_text() == "old robot record"
    assert (archive / "var/lib/rosy/provisioning/complete.json").exists()
    assert (archive / "etc/rosy/device-identity.json").exists()
    assert not (root / "var/lib/rosy/core/.rosy/audit.jsonl").exists()
    assert (root / "etc/NetworkManager/system-connections/rosy-site-sta.nmconnection").exists()
    result = provisioner.apply(bundle=fresh, hardware_serial="10000000deadbeef")
    assert result["state"] == "PROVISIONED"
    complete = json.loads((root / "var/lib/rosy/provisioning/complete.json").read_text())
    assert complete["device_name"] == "rosy-pinky-p8q4"
    assert complete["dds"]["robot_number"] == 4


def test_rebind_rejects_old_identity_and_wifi_mismatch_before_moving(tmp_path):
    first_boot = _module()
    rebind = _rebind()
    root, old_bundle = _case(tmp_path)
    first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=old_bundle, hardware_serial="10000000abcdef01")
    fresh = _fresh_bundle(root)
    payload = json.loads(fresh.read_text())
    payload["device_identity"]["device_uid"] = "9d40feaa-871f-4fd3-975a-a704e82d3af9"
    fresh.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        rebind.quarantine_previous(root, fresh, "10000000deadbeef")
    assert (root / "var/lib/rosy/provisioning/complete.json").exists()


def test_rebind_can_resume_archive_after_interrupted_move(tmp_path):
    first_boot = _module()
    rebind = _rebind()
    root, old_bundle = _case(tmp_path)
    first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=old_bundle, hardware_serial="10000000abcdef01")
    fresh = _fresh_bundle(root)
    archive = rebind.quarantine_previous(root, fresh, "10000000deadbeef")
    assert rebind.quarantine_previous(root, fresh, "10000000deadbeef") == archive


def test_rebind_retries_after_new_provisioning_waits_for_network(tmp_path):
    first_boot = _module()
    rebind = _rebind()
    root, old_bundle = _case(tmp_path)
    first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=old_bundle, hardware_serial="10000000abcdef01")
    fresh = _fresh_bundle(root)
    archive = rebind.quarantine_previous(root, fresh, "10000000deadbeef")
    waiting = first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: False).apply(
        bundle=fresh, hardware_serial="10000000deadbeef")
    assert waiting["ok"] is False
    assert rebind.quarantine_previous(root, fresh, "10000000deadbeef") == archive
    result = first_boot.FirstBootProvisioner(root=root, network_activate=lambda _: True).apply(
        bundle=fresh, hardware_serial="10000000deadbeef")
    assert result["state"] == "PROVISIONED"
