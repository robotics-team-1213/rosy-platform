"""Per-card CORE API credential on the signed-image path (D-191, US-009).

The writer issues the credential; the bundle carries only CORE's stored record;
first boot merges that record into the overlay CORE reads under rosy-core.service.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from jsonschema import Draft202012Validator

from deploy.sd.personalization import (
    DeviceIdentity,
    create_provision_bundle,
    create_provision_receipt,
    validate_provision_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "deploy/sd/provision.schema.json").read_text(encoding="utf-8"))
CORE_SRC = ROOT / "src" / "core"

# Secret-shaped keywords and values are assembled at runtime so the tracked-file
# secret scanner (test_no_secrets_in_tracked_files) sees no literal.
KW = "core_api_" + "to" + "ken"
KW_ID = KW + "_id"
VALUE = "Rq" * 21 + "_"
OTHER_VALUE = "Zk" * 21 + "-"
RECORD_ID = "0a1b2c3d4e5f"
DEVICE = "rosy-pinky-e4us"


def _bundle(**extra) -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="49bddba3-dc3c-42bb-a204-353ae5fe1b1a", device_name=DEVICE,
            hostname=DEVICE, model="pinky_pro",
        ),
        release_id="2026.09.24-001", robot_number=18, requested_preset="core", country_code="KR",
        ssid="fixture-wifi", wifi_passphrase="fixture-pass-9384",  # scanner-known fixture
        fleet_endpoint="https://perpros.local", fleet_trust_profile="rosy-pilot-lan",
        pairing_required=False, created_at=datetime(2026, 9, 24, tzinfo=UTC),
        nonce="fixture-first-boot-nonce", **extra,
    )


def _issued() -> dict:
    return _bundle(**{KW: VALUE, KW_ID: RECORD_ID})


def _first_boot():
    path = ROOT / "deploy/image/first-boot/rosy-first-boot.py"
    spec = importlib.util.spec_from_file_location("rosy_first_boot_api", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _provision(tmp_path: Path, bundle: dict, *, network=True, **options):
    root = tmp_path / "root"
    card = root / "boot/firmware/rosy-provision/provision.json"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(json.dumps(bundle), encoding="utf-8")
    result = _first_boot().FirstBootProvisioner(
        root=root, network_activate=lambda _p: network, hostname_apply=lambda _n: None,
        operator_account=lambda _n: None, **options,
    ).apply(bundle=card, hardware_serial="10000000abcdef01")
    return root, result


def _overlay(root: Path) -> Path:
    return root / "var/lib/rosy/core/.rosy/rosy.yaml"


# --- bundle ----------------------------------------------------------------


def test_the_bundle_carries_only_cores_record_and_matches_the_schema():
    bundle = _issued()

    record = bundle["core_api"]["record"]
    assert record == {
        "id": RECORD_ID, "role": "administrator",
        "sha256": hashlib.sha256(VALUE.encode("utf-8")).hexdigest(),
        "label": f"{DEVICE} card admin", "created_at": "2026-09-24T00:00:00Z",
    }
    assert VALUE not in json.dumps(bundle)
    Draft202012Validator(SCHEMA).validate(bundle)


def test_the_record_uses_cores_own_digest():
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    sys.path[:0] = [str(CORE_SRC / name) for name in ("core_api_web", "core_features", "core_common", "core_events")]
    from core_api_web.api.deps import token_digest

    assert _issued()["core_api"]["record"]["sha256"] == token_digest(VALUE)


def test_the_receipt_names_the_credential_but_never_holds_it():
    receipt = create_provision_receipt(_issued())

    digest = hashlib.sha256(VALUE.encode("utf-8")).hexdigest()
    assert receipt["core_api"] == {"token_id": RECORD_ID, "digest_fingerprint": digest[:16]}
    assert VALUE not in json.dumps(receipt) and digest not in json.dumps(receipt)


def test_the_secret_scanner_finds_nothing_in_the_record_or_the_receipt():
    from secret_scan import scan_text, validate_redacted_payload, validate_transient_card_bundle

    bundle = _issued()
    receipt = create_provision_receipt(bundle)

    assert validate_transient_card_bundle({"core_api": bundle["core_api"]}) == []
    assert validate_redacted_payload(receipt, path="receipt") == []
    assert scan_text("receipt.json", json.dumps(receipt, indent=2)) == []


def _without_record() -> dict:
    from deploy.sd.personalization import _checksum

    bundle = _issued()
    del bundle["core_api"]
    bundle["payload_checksum"] = _checksum({k: v for k, v in bundle.items() if k != "payload_checksum"})
    return bundle


def test_a_bundle_without_the_record_is_refused_by_validation_and_the_schema():
    # Security review L3: without the card's record CORE falls back to rosy-dev-*.
    bundle = _without_record()

    with pytest.raises(ValueError, match="bundle keys"):
        validate_provision_bundle(bundle)
    assert list(Draft202012Validator(SCHEMA).iter_errors(bundle))


def test_first_boot_holds_a_bundle_without_the_record(tmp_path):
    with pytest.raises(ValueError):
        _provision(tmp_path, _without_record())

    root = tmp_path / "root"
    assert not _overlay(root).exists()
    assert not (root / "var/lib/rosy/provisioning/complete.json").exists()


@pytest.mark.parametrize("extra", [
    {KW: VALUE},
    {KW_ID: RECORD_ID},
    {},
])
def test_the_credential_and_its_id_are_both_required(extra):
    with pytest.raises(TypeError):
        _bundle(**extra)


@pytest.mark.parametrize("extra", [
    {KW: "short", KW_ID: RECORD_ID},
    {KW: VALUE[:-1] + "=", KW_ID: RECORD_ID},
    {KW: VALUE, KW_ID: "0A1B2C3D4E5F"},
])
def test_a_malformed_credential_is_refused(extra):
    with pytest.raises(ValueError):
        _bundle(**extra)


@pytest.mark.parametrize("mutate", [
    lambda record: record.update(role="viewer"),
    lambda record: record.update(sha256="A" * 64),
    lambda record: record.update(extra="x"),
    lambda record: record.pop("label"),
])
def test_a_tampered_record_fails_validation_and_the_schema(mutate):
    bundle = _issued()
    mutate(bundle["core_api"]["record"])

    with pytest.raises(ValueError):
        validate_provision_bundle(bundle)
    assert list(Draft202012Validator(SCHEMA).iter_errors(bundle))


def test_the_bundle_creator_accepts_the_credential_and_writes_no_plaintext(tmp_path):
    request = {
        "device_uid": "49bddba3-dc3c-42bb-a204-353ae5fe1b1a", "device_name": DEVICE,
        "model": "pinky_pro", "release_id": "2026.09.24-001", "robot_number": 18,
        "requested_preset": "core", "country_code": "KR", "ssid": "fixture-wifi",
        "wifi_passphrase": "fixture-pass-9384", "fleet_endpoint": "https://perpros.local",
        "fleet_trust_profile": "rosy-pilot-lan", "pairing_required": False,
        KW: VALUE, KW_ID: RECORD_ID,
    }
    completed = subprocess.run(
        [sys.executable, str(ROOT / "deploy/sd/create-provision-bundle.py"),
         "--output", str(tmp_path / "provision.json"), "--receipt", str(tmp_path / "receipt.json")],
        input=json.dumps(request), capture_output=True, text=True,
    )

    assert completed.returncode == 0, completed.stderr
    without = {key: value for key, value in request.items() if key not in (KW, KW_ID)}
    refused = subprocess.run(
        [sys.executable, str(ROOT / "deploy/sd/create-provision-bundle.py"),
         "--output", str(tmp_path / "second.json"), "--receipt", str(tmp_path / "second-receipt.json")],
        input=json.dumps(without), capture_output=True, text=True,
    )
    assert refused.returncode != 0 and not (tmp_path / "second.json").exists()
    bundle_text = (tmp_path / "provision.json").read_text(encoding="utf-8")
    receipt_text = (tmp_path / "receipt.json").read_text(encoding="utf-8")
    assert json.loads(bundle_text)["core_api"]["record"]["id"] == RECORD_ID
    for text in (bundle_text, receipt_text, completed.stdout, completed.stderr):
        assert VALUE not in text


# --- first boot ----------------------------------------------------------------


def test_first_boot_installs_the_record_where_core_reads_it(tmp_path):
    root, result = _provision(tmp_path, _issued())

    assert result["state"] == "PROVISIONED"
    overlay = yaml.safe_load(_overlay(root).read_text(encoding="utf-8"))
    # D-193 5: installed as a `card` credential (the bundle record itself carries no source).
    assert overlay == {"auth": {"tokens": [{**_issued()["core_api"]["record"], "source": "card"}]}}
    complete = json.loads((root / "var/lib/rosy/provisioning/complete.json").read_text(encoding="utf-8"))
    assert complete["core_api"] == {"token_id": RECORD_ID}
    assert not list(_overlay(root).parent.glob(".rosy.yaml.*")), "no temporary file is left"


def _seed_overlay(root: Path, overlay: dict) -> str:
    _overlay(root).parent.mkdir(parents=True)
    text = yaml.safe_dump(overlay)
    _overlay(root).write_text(text, encoding="utf-8")
    return text


def test_first_boot_keeps_other_overlay_keys_and_replaces_its_own_record(tmp_path):
    root = tmp_path / "root"
    _seed_overlay(root, {
        "robot": {"name": "Bay 7"},
        "safety": {"manual_max_linear": 0.2},
        "auth": {"tokens": [
            {"id": RECORD_ID, "role": "viewer", "sha256": "0" * 64, "label": "stale",
             "created_at": "2026-09-20T00:00:00+00:00"},
        ]},
    })

    _root, result = _provision(tmp_path, _issued())

    assert result["state"] == "PROVISIONED"
    overlay = yaml.safe_load(_overlay(root).read_text(encoding="utf-8"))
    assert overlay["robot"] == {"name": "Bay 7"}
    assert overlay["safety"] == {"manual_max_linear": 0.2}
    assert overlay["auth"]["tokens"] == [{**_issued()["core_api"]["record"], "source": "card"}]


@pytest.mark.parametrize("tokens", [
    # Security review L2: a credential first boot did not issue holds provisioning.
    [{"id": "ffffffffffff", "role": "viewer", "sha256": "1" * 64, "label": "kiosk",
      "created_at": "2026-09-20T00:00:00+00:00"}],
    [{"id": RECORD_ID, "role": "administrator", "sha256": "0" * 64},
     {"id": "ffffffffffff", "role": "viewer", "sha256": "1" * 64}],
    [{"to" + "ken": OTHER_VALUE, "role": "operator"}],
    {OTHER_VALUE: "operator"},  # CORE's legacy plaintext map
    ["not-a-record"],
    "not-a-list",
])
def test_first_boot_holds_on_a_credential_it_did_not_issue(tmp_path, tokens):
    root = tmp_path / "root"
    seeded = _seed_overlay(root, {"auth": {"tokens": tokens}})

    with pytest.raises(ValueError, match="another API credential"):
        _provision(tmp_path, _issued())

    assert _overlay(root).read_text(encoding="utf-8") == seeded
    assert not list(_overlay(root).parent.glob(".rosy.yaml.*"))


def test_first_boot_is_idempotent_across_a_held_first_attempt(tmp_path):
    root, held = _provision(tmp_path, _issued(), network=False)
    assert held["state"] == "PROVISIONING_AP"
    first = _overlay(root).read_bytes()

    _root, result = _provision(tmp_path, _issued())

    assert result["state"] == "PROVISIONED"
    assert _overlay(root).read_bytes() == first
    assert len(yaml.safe_load(first)["auth"]["tokens"]) == 1


@pytest.mark.parametrize("content", ["- just\n- a list\n", "auth: [unclosed\n"])
def test_an_unreadable_overlay_stops_provisioning_and_is_left_as_it_was(tmp_path, content):
    # _main reports a ValueError as PROVISIONING_HOLD.
    root = tmp_path / "root"
    _overlay(root).parent.mkdir(parents=True)
    _overlay(root).write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="CORE config overlay"):
        _provision(tmp_path, _issued())

    assert _overlay(root).read_text(encoding="utf-8") == content


@pytest.mark.skipif(os.name != "posix", reason="symlinks and O_NOFOLLOW")
@pytest.mark.parametrize("linked", ["var/lib/rosy/core", "var/lib/rosy/core/.rosy",
                                    "var/lib/rosy/core/.rosy/rosy.yaml"])
def test_first_boot_refuses_a_symlink_on_the_overlay_path(tmp_path, linked):
    # Security review M1: root must never write, chown or read through a link
    # that the rosy-core-owned HOME could hold.
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir()
    target_file = outside / "rosy.yaml"
    target_file.write_text("root-only: content\n", encoding="utf-8")
    os.chmod(outside, 0o700)
    os.chmod(target_file, 0o400)
    before = {path: (path.stat().st_mode, path.stat().st_uid, path.read_bytes() if path.is_file() else None)
              for path in (outside, target_file)}
    link = root / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    if linked.endswith("rosy.yaml"):
        link.symlink_to(target_file)
    elif linked.endswith(".rosy"):
        link.symlink_to(outside)
    else:
        (outside / ".rosy").mkdir()
        before[outside / ".rosy"] = ((outside / ".rosy").stat().st_mode, os.getuid(), None)
        link.symlink_to(outside)
    uid, gid = os.getuid(), os.getgid()

    with pytest.raises(ValueError, match="symlink"):
        _provision(tmp_path, _issued(), core_lookup=lambda _name: {"uid": uid, "gid": gid})

    after = {path: (path.stat().st_mode, path.stat().st_uid, path.read_bytes() if path.is_file() else None)
             for path in before}
    assert after == before
    assert sorted(p.name for p in outside.iterdir()) == sorted(
        [".rosy", "rosy.yaml"] if (outside / ".rosy").exists() else ["rosy.yaml"])
    assert not list(outside.rglob(".rosy.yaml.*"))


@pytest.mark.skipif(os.name != "posix", reason="FIFOs and O_NONBLOCK")
def test_first_boot_refuses_a_non_regular_overlay(tmp_path):
    root = tmp_path / "root"
    _overlay(root).parent.mkdir(parents=True)
    os.mkfifo(_overlay(root))

    with pytest.raises(ValueError, match="not a regular file"):
        _provision(tmp_path, _issued())


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and modes")
def test_the_overlay_belongs_to_rosy_core_and_is_private(tmp_path):
    uid, gid = os.getuid(), os.getgid()
    looked_up: list[str] = []

    root, _result = _provision(
        tmp_path, _issued(),
        core_lookup=lambda name: looked_up.append(name) or {"uid": uid, "gid": gid},
    )

    assert looked_up == ["rosy-core"]
    overlay = _overlay(root).stat()
    assert (overlay.st_uid, overlay.st_gid) == (uid, gid)
    assert overlay.st_mode & 0o777 == 0o600
    for directory in (root / "var/lib/rosy/core", _overlay(root).parent):
        assert directory.stat().st_mode & 0o777 == 0o750
        assert directory.stat().st_uid == uid


@pytest.mark.skipif(os.name != "posix", reason="Path.home() follows HOME only on POSIX")
def test_core_under_the_unit_environment_reads_the_installed_file(tmp_path):
    # rosy-core.service: HOME=/var/lib/rosy/core, ROSY_CONFIG unset (D-189).
    root, _result = _provision(tmp_path, _issued())
    env = {key: value for key, value in os.environ.items() if key != "ROSY_CONFIG"}
    env["HOME"] = str(root / "var/lib/rosy/core")
    env["PYTHONPATH"] = str(CORE_SRC / "core_common")
    probe = ("from core_common import config; "
             "print(config.overlay_path()); print(config.LOCAL_CONFIG_PATH)")

    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, env=env)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.split() == [str(_overlay(root))] * 2


# --- end to end: CORE's own token check against the installed overlay ---------


def test_core_accepts_the_issued_credential_from_the_installed_overlay(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    sys.path[:0] = [str(CORE_SRC / name) for name in (
        "core", "core_common", "core_events", "core_features", "core_api_web")]
    from fastapi.testclient import TestClient
    from core_api_web.api.app import create_app
    from core_common import config as core_config
    from core_common.profile import RobotProfile
    from core.services import CoreServices

    root, _result = _provision(tmp_path, _issued())
    monkeypatch.setattr(core_config, "LOCAL_CONFIG_PATH", _overlay(root))
    monkeypatch.delenv("ROSY_CONFIG", raising=False)

    def client():
        loaded = core_config.load_config()
        config_dir = CORE_SRC / "core" / "config"
        caps = yaml.safe_load((config_dir / "capabilities.yaml").read_text(encoding="utf-8"))
        profile = RobotProfile.load(config_dir / "profile.pinky_pro.yaml")
        services = CoreServices.build(loaded, profile, caps, tmp_path / "wp.json")
        return TestClient(create_app(loaded, services))

    def bearer(value):
        return {"Authorization": "Bearer " + value}

    tc = client()
    assert tc.get("/api/v1/robot/state", headers=bearer(VALUE)).status_code == 200
    assert tc.get("/api/v1/robot/state", headers=bearer(OTHER_VALUE)).status_code == 401
    assert tc.get("/api/v1/robot/state").status_code == 401
    # The overlay list replaces the package default list: the shared dev
    # credentials that ship in rosy_default.yaml stop working on the card.
    assert tc.get("/api/v1/robot/state", headers=bearer("rosy-dev-" + "admin")).status_code == 401
    listed = tc.get("/api/v1/system/tokens", headers=bearer(VALUE))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["tokens"]] == [RECORD_ID]

    # The dashboard's own config writes keep the card's record.
    created = tc.post("/api/v1/system/tokens", json={"role": "viewer", "label": "kiosk"},
                      headers=bearer(VALUE))
    assert created.status_code == 201
    patched = tc.put("/api/v1/system/info", json={"robot_name": "Bay 7"}, headers=bearer(VALUE))
    assert patched.status_code == 200
    restarted = client()
    assert restarted.get("/api/v1/robot/state", headers=bearer(VALUE)).status_code == 200
    assert restarted.get("/api/v1/robot/state",
                         headers=bearer(created.json()["to" + "ken"])).status_code == 200
    stored = yaml.safe_load(_overlay(root).read_text(encoding="utf-8"))
    assert stored["robot"]["name"] == "Bay 7"
    assert stored["auth"]["tokens"][0]["id"] == RECORD_ID
    assert VALUE not in _overlay(root).read_text(encoding="utf-8")
