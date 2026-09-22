import pytest
from uuid import uuid4
from deploy.sd.personalization import (
    DeviceIdentity,
    generate_short_code,
    validate_device_identity,
    derive_wpa_psk,
    create_provision_bundle,
    validate_provision_bundle,
    create_provision_receipt,
)

def test_generate_short_code():
    code = generate_short_code()
    assert len(code) == 4
    assert code.isalnum()
    assert code.islower()

def test_validate_device_identity():
    uid = str(uuid4())
    identity = DeviceIdentity(
        device_uid=uid,
        device_name="rosy-pinky-a2cd",
        hostname="rosy-pinky-a2cd",
        model="pinky_pro",
    )
    validated = validate_device_identity(identity)
    assert validated.device_uid == uid

def test_derive_wpa_psk():
    psk = derive_wpa_psk("MySSID", "secret123")
    assert len(psk) == 64

def test_create_provision_bundle():
    uid = str(uuid4())
    identity = DeviceIdentity(
        device_uid=uid,
        device_name="rosy-pinky-a2cd",
        hostname="rosy-pinky-a2cd",
        model="pinky_pro",
    )
    bundle = create_provision_bundle(
        identity=identity,
        release_id="2026.09.22-001",
        robot_number=1,
        requested_preset="hardware",
        country_code="KR",
        ssid="MySSID",
        wifi_passphrase="secretpassphrase",
        fleet_endpoint="https://fleet.local",
        fleet_trust_profile="production",
        pairing_required=True,
    )
    assert bundle["device_identity"]["device_uid"] == uid
    assert bundle["fleet"]["endpoint"] == "https://fleet.local"
    assert "network" in bundle
    assert bundle["network"]["ssid"] == "MySSID"
    assert validate_provision_bundle(bundle) == bundle

def test_create_provision_receipt():
    uid = str(uuid4())
    identity = DeviceIdentity(
        device_uid=uid,
        device_name="rosy-pinky-a2cd",
        hostname="rosy-pinky-a2cd",
        model="pinky_pro",
    )
    bundle = create_provision_bundle(
        identity=identity,
        release_id="2026.09.22-001",
        robot_number=1,
        requested_preset="hardware",
        country_code="KR",
        ssid="MySSID",
        wifi_passphrase="secretpassphrase",
        fleet_endpoint="https://fleet.local",
        fleet_trust_profile="production",
        pairing_required=True,
    )
    receipt = create_provision_receipt(bundle)
    assert "schema_version" in receipt
    assert "device_identity" in receipt
    assert "fleet" in receipt
    assert "wifi_passphrase" not in receipt.get("network", {})
