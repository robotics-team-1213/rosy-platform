from __future__ import annotations

import re
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator

from deploy.sd.personalization import (
    SHORT_CODE_ALPHABET,
    create_provision_bundle,
    create_provision_receipt,
    derive_wpa_psk,
    generate_device_identity,
    generate_short_code,
    validate_provision_bundle,
    validate_device_identity,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "deploy" / "sd" / "provision.schema.json"
BUNDLE_CLI = ROOT / "deploy" / "sd" / "create-provision-bundle.py"


class DeterministicRng:
    def __init__(self, values: str = "k7m4") -> None:
        self._values = iter(values)

    def choice(self, alphabet: str) -> str:
        value = next(self._values)
        assert value in alphabet
        return value


def test_pinky_name_is_short_human_identity():
    generated = generate_device_identity("pinky_pro", rng=DeterministicRng())

    assert re.fullmatch(r"rosy-pinky-[a-hj-km-np-z2-9]{4}", generated.device_name)
    assert generated.hostname == generated.device_name
    assert UUID(generated.device_uid).version == 4
    assert validate_device_identity(generated) is generated


def test_short_code_alphabet_is_unambiguous_and_complete():
    assert len(SHORT_CODE_ALPHABET) == 31
    assert len(set(SHORT_CODE_ALPHABET)) == 31
    assert set("01ilo").isdisjoint(SHORT_CODE_ALPHABET)


def test_collision_is_regenerated_with_a_bounded_attempt_count():
    rng = DeterministicRng("aaaa" + "k7m4")

    identity = generate_device_identity(
        "pinky_pro",
        rng=rng,
        registered_names={"rosy-pinky-aaaa"},
        max_attempts=2,
    )

    assert identity.device_name == "rosy-pinky-k7m4"


def test_exhausted_collisions_fail_clearly():
    with pytest.raises(RuntimeError, match="unique Pinky device name"):
        generate_device_identity(
            "pinky_pro",
            rng=DeterministicRng("aaaa"),
            registered_names={"rosy-pinky-aaaa"},
            max_attempts=1,
        )


def test_uuid_is_not_derived_from_the_short_name():
    first = generate_device_identity("pinky_pro", rng=DeterministicRng())
    second = generate_device_identity("pinky_pro", rng=DeterministicRng())

    assert first.device_name == second.device_name
    assert first.device_uid != second.device_uid


def test_short_code_rejects_non_positive_length():
    with pytest.raises(ValueError, match="positive"):
        generate_short_code(length=0)


def _identity():
    return generate_device_identity("pinky_pro", rng=DeterministicRng())


def _bundle(**overrides):
    values = {
        "identity": _identity(),
        "release_id": "2026.09.21-001",
        "robot_number": 1,
        "requested_preset": "hardware",
        "country_code": "KR",
        "ssid": "fixture-lab",
        "wifi_passphrase": "fixture-pass-9384",
        "fleet_endpoint": "https://fleet.fixture.invalid:8443",
        "fleet_trust_profile": "site-ca-2026",
        "pairing_required": True,
        "pairing_credential": "fixture-one-time-pairing-credential",
        "created_at": datetime(2026, 9, 21, 3, 4, 5, tzinfo=UTC),
        "nonce": "fixture-nonce-0001",
        "core_api_" + "token": "Rq" * 21 + "_",
        "core_api_" + "token_id": "0a1b2c3d4e5f",
    }
    values.update(overrides)
    return create_provision_bundle(**values)


def test_wpa_psk_uses_the_standard_pbkdf2_vector():
    # Published WPA derivation vector: SSID IEEE / passphrase password.
    assert derive_wpa_psk("IEEE", "password") == (
        "f42c6fc52df0ebef9ebb4b90b38a5f90"
        "2e83fe1b135a70e23aed762e9710a12e"
    )


@pytest.mark.parametrize(
    ("ssid", "passphrase", "message"),
    [("", "valid-passphrase", "SSID"), ("site", "short", "passphrase")],
)
def test_wpa_input_errors_do_not_echo_credentials(ssid, passphrase, message):
    with pytest.raises(ValueError, match=message) as caught:
        derive_wpa_psk(ssid, passphrase)

    rendered = str(caught.value)
    assert ssid not in rendered or not ssid
    assert passphrase not in rendered


def test_bundle_has_exact_schema_keys_and_derived_dds_identity():
    bundle = _bundle()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(bundle)
    assert set(bundle) == {
        "schema_version", "device_identity", "release", "dds", "runtime",
        "network", "fleet", "created_at", "nonce", "payload_checksum", "core_api",
    }
    assert bundle["dds"] == {
        "robot_number": 1,
        "ros_domain_id": 41,
        "namespace": "rosy_01",
    }
    assert re.fullmatch(r"[0-9a-f]{64}", bundle["network"]["wpa_psk"])
    assert validate_provision_bundle(bundle) is bundle


def test_robot_number_range_is_fail_closed():
    for number in (0, 62):
        with pytest.raises(ValueError, match="robot_number"):
            _bundle(robot_number=number)


def test_checksum_detects_bundle_tampering():
    bundle = _bundle()
    bundle["runtime"]["requested_preset"] = "core"

    with pytest.raises(ValueError, match="checksum"):
        validate_provision_bundle(bundle)


def test_receipt_omits_every_transient_secret():
    bundle = _bundle()
    receipt = create_provision_receipt(bundle)
    rendered = json.dumps(receipt, sort_keys=True)

    assert "wpa_psk" not in rendered
    assert "pairing_credential" not in rendered
    assert "fixture-pass-9384" not in rendered
    assert "fixture-one-time-pairing-credential" not in rendered
    assert receipt["network"] == {"ssid": "fixture-lab", "country_code": "KR"}


def test_bundle_cli_reads_secret_from_stdin_and_emits_only_redacted_receipt(tmp_path):
    output = tmp_path / "provision.json"
    receipt = tmp_path / "provision-receipt.json"
    request = {
        "device_uid": "9d40feaa-871f-4fd3-975a-a704e82d3af9",
        "device_name": "rosy-pinky-k7m4",
        "model": "pinky_pro",
        "release_id": "2026.09.22-001",
        "robot_number": 1,
        "requested_preset": "hardware",
        "country_code": "KR",
        "ssid": "fixture-ssid",
        "wifi_passphrase": "fixture-private-passphrase",
        "fleet_endpoint": "https://fleet.fixture.invalid:8443",
        "fleet_trust_profile": "site-ca-2026",
        "pairing_required": False,
        "core_api_" + "token": "Rq" * 21 + "_",
        "core_api_" + "token_id": "0a1b2c3d4e5f",
    }

    completed = subprocess.run(
        [sys.executable, str(BUNDLE_CLI), "--output", str(output), "--receipt", str(receipt)],
        input=json.dumps(request), capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    bundle = json.loads(output.read_text(encoding="utf-8"))
    redacted = json.loads(receipt.read_text(encoding="utf-8"))
    assert bundle["network"]["ssid"] == "fixture-ssid"
    assert re.fullmatch(r"[0-9a-f]{64}", bundle["network"]["wpa_psk"])
    rendered = completed.stdout + completed.stderr + json.dumps(redacted)
    assert "fixture-private-passphrase" not in rendered
    assert "wpa_psk" not in json.dumps(redacted)
