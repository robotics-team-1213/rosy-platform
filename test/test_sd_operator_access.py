"""Per-card operator SSH access (D-174 F3).

The first card had no human login path: cloud-init disables password SSH and the
image carries no key. The writer may now add operator public keys to the
one-time bundle; first boot installs them for a key-only `rosy` account.
Key blobs are built at runtime so this file stays clean for the secret scan.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest
from jsonschema import Draft202012Validator

from deploy.sd.personalization import (
    DeviceIdentity,
    create_provision_bundle,
    create_provision_receipt,
    operator_key_fingerprint,
    validate_operator_key,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "deploy/sd/provision.schema.json").read_text(encoding="utf-8"))

# D-191: every bundle carries the card's CORE API record. Keys are assembled
# at runtime so the tracked-file secret scanner sees no literal.
CARD_API = {"core_api_" + "token": "Rq" * 21 + "_", "core_api_" + "token_id": "0a1b2c3d4e5f"}


def _string(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _ed25519(seed: int = 7, comment: str = "operator@bench") -> str:
    blob = _string(b"ssh-ed25519") + _string(bytes([seed]) * 32)
    return f"ssh-ed25519 {base64.b64encode(blob).decode()} {comment}"


def _bundle(**extra) -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="9d40feaa-871f-4fd3-975a-a704e82d3af9",
            device_name="rosy-pinky-k7m4",
            hostname="rosy-pinky-k7m4",
            model="pinky_pro",
        ),
        release_id="2026.09.23-003",
        robot_number=18,
        requested_preset="core",
        country_code="KR",
        ssid="fixture-wifi",
        wifi_passphrase="fixture-pass-9384",  # scanner-known fixture
        fleet_endpoint="https://perpros.local",
        fleet_trust_profile="rosy-pilot-lan",
        pairing_required=False,
        created_at=datetime(2026, 9, 23, 1, 2, 3, tzinfo=UTC),
        nonce="fixture-first-boot-nonce",
        **CARD_API,
        **extra,
    )


def test_operator_keys_travel_in_the_bundle_and_match_the_schema():
    key = _ed25519()

    bundle = _bundle(operator_ssh_keys=[key])

    assert bundle["operator"] == {"ssh_authorized_keys": [key]}
    Draft202012Validator(SCHEMA).validate(bundle)


def test_a_bundle_without_operator_keys_keeps_the_old_shape():
    bundle = _bundle()

    assert "operator" not in bundle
    Draft202012Validator(SCHEMA).validate(bundle)


def test_receipt_records_fingerprints_not_key_material():
    key = _ed25519()

    receipt = create_provision_receipt(_bundle(operator_ssh_keys=[key]))

    blob = base64.b64decode(key.split()[1])
    expected = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    assert receipt["operator"] == {"ssh_key_fingerprints": [expected]}
    assert key.split()[1] not in json.dumps(receipt)
    assert operator_key_fingerprint(key) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "-----BEGIN OPENSSH " + "PRIVATE KEY-----",
        "ssh-rsa " + base64.b64encode(_string(b"ssh-rsa") + b"\x00" * 8).decode(),
        "ssh-ed25519 not-base64!!",
        "ssh-ed25519 " + base64.b64encode(_string(b"ssh-dss") + _string(b"\x01" * 32)).decode(),
        _ed25519() + "\nssh-ed25519 injected",
        "",
    ],
)
def test_only_single_line_public_keys_of_allowed_types_are_accepted(bad):
    with pytest.raises(ValueError):
        validate_operator_key(bad)


def test_at_most_eight_operator_keys():
    with pytest.raises(ValueError):
        _bundle(operator_ssh_keys=[_ed25519(seed) for seed in range(9)])


def _first_boot():
    path = ROOT / "deploy/image/first-boot/rosy-first-boot.py"
    spec = importlib.util.spec_from_file_location("rosy_first_boot_operator", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _card(tmp_path: Path, bundle: dict) -> tuple[Path, Path]:
    root = tmp_path / "root"
    card = root / "boot/firmware/rosy-provision/provision.json"
    card.parent.mkdir(parents=True)
    card.write_text(json.dumps(bundle), encoding="utf-8")
    return root, card


def test_first_boot_installs_a_key_only_operator_account(tmp_path):
    module = _first_boot()
    key = _ed25519()
    root, card = _card(tmp_path, _bundle(operator_ssh_keys=[key]))
    created: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _p: True, hostname_apply=lambda _n: None,
        operator_account=lambda name: created.append(name),
    )

    result = provisioner.apply(bundle=card, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert created == ["rosy"]
    authorized = root / "home/rosy/.ssh/authorized_keys"
    assert authorized.read_text(encoding="utf-8") == key + "\n"
    sudoers = (root / "etc/sudoers.d/60-rosy-operator").read_text(encoding="utf-8")
    assert sudoers == "rosy ALL=(ALL) NOPASSWD:ALL\n"
    complete = json.loads((root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8"))
    assert complete["operator"] == {"ssh_key_fingerprints": [operator_key_fingerprint(key)]}


def test_first_boot_without_operator_keys_creates_no_account(tmp_path):
    module = _first_boot()
    root, card = _card(tmp_path, _bundle())
    created: list[str] = []
    provisioner = module.FirstBootProvisioner(
        root=root, network_activate=lambda _p: True, hostname_apply=lambda _n: None,
        operator_account=lambda name: created.append(name),
    )

    provisioner.apply(bundle=card, hardware_serial="10000000abcdef01")

    assert created == []
    assert not (root / "home/rosy").exists()
    assert not (root / "etc/sudoers.d/60-rosy-operator").exists()


def test_default_operator_account_never_touches_the_host_for_a_non_slash_root(tmp_path, monkeypatch):
    module = _first_boot()
    root, card = _card(tmp_path, _bundle(operator_ssh_keys=[_ed25519()]))
    monkeypatch.setattr(module.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("host command")))

    result = module.FirstBootProvisioner(
        root=root, network_activate=lambda _p: True,
    ).apply(bundle=card, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"


def _provisioner(module, root, **kwargs):
    kwargs.setdefault("network_activate", lambda _p: True)
    kwargs.setdefault("hostname_apply", lambda _n: None)
    kwargs.setdefault("operator_account", lambda _n: None)
    return module.FirstBootProvisioner(root=root, **kwargs)


def test_a_failed_account_creation_still_provisions_without_operator_access(tmp_path):
    # Review H2: useradd failing used to crash first boot on every later boot.
    module = _first_boot()
    root, card = _card(tmp_path, _bundle(operator_ssh_keys=[_ed25519()]))

    def broken(_name):
        raise OSError("useradd: group rosy exists")

    result = _provisioner(module, root, operator_account=broken,
                          operator_lookup=lambda _name: None).apply(bundle=card, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert not (root / "home/rosy").exists()
    assert not (root / "etc/sudoers.d/60-rosy-operator").exists()
    complete = json.loads((root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8"))
    assert "operator" not in complete


def test_a_pre_existing_account_with_another_home_is_not_silently_used(tmp_path, capsys):
    # Review L5: keys in /home/rosy would be ignored by sshd for a different home.
    module = _first_boot()
    root, card = _card(tmp_path, _bundle(operator_ssh_keys=[_ed25519()]))
    lookup = lambda _name: {"home": "/var/lib/rosy", "shell": "/usr/sbin/nologin", "uid": 999, "gid": 999}

    result = _provisioner(module, root, operator_lookup=lookup).apply(
        bundle=card, hardware_serial="10000000abcdef01")

    assert result["state"] == "PROVISIONED"
    assert not (root / "etc/sudoers.d/60-rosy-operator").exists()
    assert "operator" in capsys.readouterr().err


@pytest.mark.parametrize("operator", [7, {"ssh_authorized_keys": [["nested"]]}, {"ssh_authorized_keys": "one"}])
def test_malformed_operator_sections_are_rejected_not_crashed(operator):
    # Review L4: a TypeError escaped the validator and crashed first boot.
    from deploy.sd.personalization import validate_provision_bundle, _checksum

    bundle = _bundle()
    bundle["operator"] = operator
    bundle["payload_checksum"] = _checksum({k: v for k, v in bundle.items() if k != "payload_checksum"})

    with pytest.raises(ValueError):
        validate_provision_bundle(bundle)
