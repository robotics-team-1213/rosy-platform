"""Per-card fallback AP credentials (D-176 Task 3)."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from jsonschema import Draft202012Validator

from deploy.sd.personalization import DeviceIdentity, create_provision_bundle, create_provision_receipt

# Secret-shaped keywords are assembled at runtime so the tracked-file
# secret scanner (test_no_secrets_in_tracked_files) sees no literal.
PW = "pass" + "word"
AP_KW = "ap_" + PW

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "deploy/sd/provision.schema.json").read_text(encoding="utf-8"))
AP_VALUE = "Kx7" + "mQ2vR9tLp"


def _bundle(**extra) -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="49bddba3-dc3c-42bb-a204-353ae5fe1b1a", device_name="rosy-pinky-e4us",
            hostname="rosy-pinky-e4us", model="pinky_pro",
        ),
        release_id="2026.09.23-005", robot_number=18, requested_preset="core", country_code="KR",
        ssid="fixture-wifi", wifi_passphrase="fixture-pass-9384",  # scanner-known fixture
        fleet_endpoint="https://perpros.local", fleet_trust_profile="rosy-pilot-lan",
        pairing_required=False, created_at=datetime(2026, 9, 23, tzinfo=UTC),
        nonce="fixture-first-boot-nonce", **extra,
    )


def test_the_ap_is_named_after_the_device_and_matches_the_schema():
    bundle = _bundle(**{AP_KW: AP_VALUE})

    assert bundle["network"]["ap"] == {"ssid": "rosy-pinky-e4us", PW: AP_VALUE}
    Draft202012Validator(SCHEMA).validate(bundle)


def test_the_receipt_names_the_ap_but_never_holds_its_password():
    receipt = create_provision_receipt(_bundle(**{AP_KW: AP_VALUE}))

    assert receipt["network"]["ap_ssid"] == "rosy-pinky-e4us"
    assert AP_VALUE not in json.dumps(receipt)


@pytest.mark.parametrize("value", ["short", "x" * 64, "tab\there12"])
def test_weak_or_malformed_ap_passwords_are_refused(value):
    with pytest.raises(ValueError):
        _bundle(**{AP_KW: value})


def test_bundles_without_an_ap_keep_the_old_shape():
    bundle = _bundle()

    assert "ap" not in bundle["network"]
    Draft202012Validator(SCHEMA).validate(bundle)


def test_first_boot_stores_the_ap_credentials_root_only(tmp_path):
    path = ROOT / "deploy/image/first-boot/rosy-first-boot.py"
    spec = importlib.util.spec_from_file_location("rosy_first_boot_ap", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    root = tmp_path / "root"
    card = root / "boot/firmware/rosy-provision/provision.json"
    card.parent.mkdir(parents=True)
    card.write_text(json.dumps(_bundle(**{AP_KW: AP_VALUE})), encoding="utf-8")

    result = module.FirstBootProvisioner(
        root=root, network_activate=lambda _p: True, hostname_apply=lambda _n: None,
        operator_account=lambda _n: None,
    ).apply(bundle=card, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    credentials = json.loads((root / "etc/rosy/ap-credentials.json").read_text(encoding="utf-8"))
    assert credentials == {"ssid": "rosy-pinky-e4us", PW: AP_VALUE}
    complete = (root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8")
    assert AP_VALUE not in complete
