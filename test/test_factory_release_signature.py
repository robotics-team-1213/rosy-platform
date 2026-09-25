"""D-225 2.2: the factory release inside the image becomes signed at first boot.

End to end with a throwaway Ed25519 key: seal an installed factory release,
build the image dist with create-image-manifest.py, sign it offline, verify it
as the SD writer does, carry the factory signature into the bundle, run first
boot against a temporary root, then native_release verify(), rollback and
recovery all accept the factory release. A signature from another key is
refused and removed.
"""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from build_payload_release import build_release, seal_release
from sign_image_release import sign_image_release
from signing import sign_checksums

from deploy.sd.personalization import DeviceIdentity, create_provision_bundle


ROOT = Path(__file__).resolve().parents[1]
FACTORY_ID = "2026.09.25-001"
UPDATE_ID = "2026.09.25-002"
KEY_ID = "rosy-release-2026-01"  # the stem first boot and the sealed manifest expect
REVISION = "c" * 40
IMAGE_RUNTIME = "2" * 64
CARD_API = {"core_api_" + "token": "Rq" * 21 + "_", "core_api_" + "token_id": "0a1b2c3d4e5f"}


def _keys(directory: Path, name: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    private, public = directory / f"{name}.private.pem", directory / f"{KEY_ID}.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True, timeout=30)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True, timeout=30)
    return private, public


def _payload(root: Path, release_id: str) -> Path:
    """The tree build-native-payload.sh leaves, reduced to what verify() requires."""
    files = {
        "install/.rosy-release": release_id + "\n",
        "install/setup.bash": "# colcon\n",
        "install/lib/core/core": "#!/usr/bin/python3\n",
        "deploy/robot/native/rosy-runtime.target": "[Unit]\n",
        "rosy-packages.txt": "core\n",
        "deb-packages.txt": "python3\t3.12\n",
        "required-ros-packages.txt": "core\n",
        "source-revision.txt": REVISION + "\n",
        "python-runtime.sha256": IMAGE_RUNTIME + "\n",
        "image-overlay/etc/rosy/defaults.yaml": "image: layer\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return root


def _first_boot():
    spec = importlib.util.spec_from_file_location(
        "rosy_first_boot_d225", ROOT / "deploy/image/first-boot/rosy-first-boot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryLinks:
    def __init__(self, current: str) -> None:
        self.values = {"current": current, "previous": None}

    def get(self, name: str) -> str | None:
        return self.values[name]

    def set(self, name: str, release_id: str | None) -> None:
        self.values[name] = release_id


def _bundle(factory_release: dict | None) -> dict:
    return create_provision_bundle(
        identity=DeviceIdentity(
            device_uid="9d40feaa-871f-4fd3-975a-a704e82d3af9", device_name="rosy-pinky-k7m4",
            hostname="rosy-pinky-k7m4", model="pinky_pro"),
        release_id=FACTORY_ID, robot_number=3, requested_preset="core", country_code="KR",
        ssid="fixture-wifi", wifi_passphrase="fixture-pass-9384",
        fleet_endpoint="https://fleet.fixture.invalid:8443", fleet_trust_profile="site-ca-2026",
        pairing_required=False, factory_release=factory_release,
        created_at=datetime(2026, 9, 25, 1, 2, 3, tzinfo=UTC), nonce="fixture-d225-factory",
        **CARD_API,
    )


@pytest.fixture
def pipeline(tmp_path: Path):
    """Image build -> offline signing -> SD writer, up to the card's bundle."""
    private, public = _keys(tmp_path / "offline", "release")
    payload = _payload(tmp_path / "payload", FACTORY_ID)

    # customize-rootfs.sh: install the payload, drop the image layer, seal, export.
    device = tmp_path / "device"
    release = device / "opt/rosy/releases" / FACTORY_ID
    shutil.copytree(payload, release)
    shutil.rmtree(release / "image-overlay")
    seal_release(release, FACTORY_ID)
    (payload / "factory-release").mkdir()
    for name in ("manifest.json", "SHA256SUMS"):
        shutil.copyfile(release / name, payload / "factory-release" / name)
    key = device / "etc/rosy/trusted-release-keys" / public.name
    key.parent.mkdir(parents=True)
    key.write_bytes(public.read_bytes())
    marker = device / "usr/local/share/rosy/python-runtime.sha256"
    marker.parent.mkdir(parents=True)
    marker.write_text(IMAGE_RUNTIME + "\n", encoding="utf-8")

    # build-image.sh: the dist create-image-manifest.py writes.
    dist = tmp_path / "dist" / FACTORY_ID
    dist.mkdir(parents=True)
    image = dist / f"rosy-os-pinky-pro-{FACTORY_ID}-arm64.img.xz"
    image.write_bytes(b"compressed image fixture")
    lock = tmp_path / "inputs.lock.yaml"
    lock.write_text("schema_version: 1\n", encoding="utf-8")
    subprocess.run([
        sys.executable, str(ROOT / "deploy/image/create-image-manifest.py"), "--dist", str(dist),
        "--payload", str(payload), "--lock", str(lock), "--release-id", FACTORY_ID,
        "--source-revision", REVISION,
    ], check=True, capture_output=True, timeout=60)

    # Operator PC, offline: sign, then verify as prepare-rosy-sd.ps1 does.
    report = sign_image_release(dist, private, public)
    assert report["factory_releases"] == [FACTORY_ID]
    verified = subprocess.run([
        sys.executable, str(ROOT / "deploy/sd/verify-image-release.py"), "--release-root", str(dist),
        "--public-key", str(public), "--image", str(image), "--release-id", FACTORY_ID,
    ], capture_output=True, text=True, check=False, timeout=60)
    assert verified.returncode == 0, verified.stderr

    return {"tmp": tmp_path, "private": private, "public": public, "payload": payload,
            "device": device, "release": release, "key": key, "dist": dist}


def _card_bundle(case: dict, request_release_id: str = FACTORY_ID) -> dict:
    """create-provision-bundle.py with the verified release, as the SD writer runs it."""
    out = case["tmp"] / "card"
    request = {
        "device_uid": "9d40feaa-871f-4fd3-975a-a704e82d3af9", "device_name": "rosy-pinky-k7m4",
        "model": "pinky_pro", "release_id": request_release_id, "robot_number": 3,
        "requested_preset": "core", "country_code": "KR", "ssid": "fixture-wifi",
        "wifi_passphrase": "fixture-pass-9384", "fleet_endpoint": "https://fleet.fixture.invalid:8443",
        "fleet_trust_profile": "site-ca-2026", "pairing_required": False, **CARD_API,
    }
    completed = subprocess.run([
        sys.executable, str(ROOT / "deploy/sd/create-provision-bundle.py"),
        "--output", str(out / "provision.json"), "--receipt", str(out / "receipt.json"),
        "--release-root", str(case["dist"]), "--public-key", str(case["public"]),
    ], input=json.dumps(request), capture_output=True, text=True, check=False, timeout=60)
    assert completed.returncode == 0, completed.stderr
    return json.loads((out / "provision.json").read_text(encoding="utf-8"))


def _apply(case: dict, bundle: dict, *, network: bool = True) -> dict:
    card = case["device"] / "boot/firmware/rosy-provision/provision.json"
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(json.dumps(bundle), encoding="utf-8")
    provisioner = _first_boot().FirstBootProvisioner(
        root=case["device"], network_activate=lambda _profile: network)
    return provisioner.apply(bundle=card, hardware_serial="10000000abcdef01")


def _manager(case: dict, links: MemoryLinks):
    from deploy.robot.native.native_release import NativeReleaseManager

    return NativeReleaseManager(root=case["device"], public_key=case["key"],
                                runtime=lambda _action: None, links=links)


def _install_update(case: dict) -> None:
    """A signed payload-only update (D-225 2.1) next to the factory release."""
    update = case["device"] / "opt/rosy/releases" / UPDATE_ID
    build_release(_payload(case["tmp"] / "payload-update", UPDATE_ID), UPDATE_ID, update)
    sums = (update / "SHA256SUMS").read_bytes()
    (update / "SHA256SUMS.sig").write_text(sign_checksums(sums, case["private"]) + "\n", encoding="ascii")


def test_image_ships_the_factory_release_sealed_but_unsigned(pipeline):
    """Without D-225 2.2 this is where rollback to the factory release died."""
    links = MemoryLinks(FACTORY_ID)
    assert (pipeline["release"] / "SHA256SUMS").is_file()
    assert not (pipeline["release"] / "SHA256SUMS.sig").exists()
    with pytest.raises(ValueError, match="SIGNATURE_MISSING"):
        _manager(pipeline, links).verify(FACTORY_ID)
    # The dist carries the signature the image does not.
    assert (pipeline["dist"] / "factory-release" / FACTORY_ID / "SHA256SUMS.sig").is_file()


def test_first_boot_signs_the_factory_release_so_rollback_and_recovery_reach_it(pipeline):
    bundle = _card_bundle(pipeline)
    assert bundle["factory_release"]["release_id"] == FACTORY_ID

    result = _apply(pipeline, bundle)

    assert result["state"] == "PROVISIONED"
    complete = json.loads((pipeline["device"] / "var/lib/rosy/provisioning/complete.json")
                          .read_text(encoding="utf-8"))
    assert complete["factory_release"] == {"release_id": FACTORY_ID, "signed": True}
    links = MemoryLinks(FACTORY_ID)
    manager = _manager(pipeline, links)
    assert manager.verify(FACTORY_ID)["release_id"] == FACTORY_ID

    _install_update(pipeline)
    assert manager.activate(UPDATE_ID)["previous"] == FACTORY_ID
    assert manager.rollback() == {"ok": True, "release_id": FACTORY_ID, "previous": UPDATE_ID}
    assert links.values == {"current": FACTORY_ID, "previous": UPDATE_ID}

    # Power lost mid-way through the first activation: recovery verifies the factory release.
    manager._write_journal(operation="activate", candidate=UPDATE_ID, old_current=FACTORY_ID,
                           old_previous=None, phase="switched")
    links.values = {"current": UPDATE_ID, "previous": FACTORY_ID}
    assert manager.recover() == {"ok": True, "recovered": True, "release_id": FACTORY_ID}
    assert links.values["current"] == FACTORY_ID


def test_first_boot_signature_install_is_idempotent_across_a_held_attempt(pipeline):
    bundle = _card_bundle(pipeline)
    signature = pipeline["release"] / "SHA256SUMS.sig"

    held = _apply(pipeline, bundle, network=False)
    assert held["ok"] is False and held["state"] == "PROVISIONING_AP"
    first = signature.read_bytes()
    done = _apply(pipeline, bundle)

    assert done["state"] == "PROVISIONED"
    assert signature.read_bytes() == first
    assert _manager(pipeline, MemoryLinks(FACTORY_ID)).verify(FACTORY_ID)


def test_a_signature_from_another_key_is_refused_removed_and_recorded(pipeline):
    other, _ = _keys(pipeline["tmp"] / "other", "other")
    sums = (pipeline["release"] / "SHA256SUMS").read_bytes()
    forged = {"release_id": FACTORY_ID, "sha256sums_sig_b64": sign_checksums(sums, other)}

    result = _apply(pipeline, _bundle(forged))

    assert result["state"] == "PROVISIONED"  # the robot still provisions, unsigned as before
    assert not (pipeline["release"] / "SHA256SUMS.sig").exists()
    assert not list(pipeline["release"].glob(".SHA256SUMS.sig.*"))
    complete = json.loads((pipeline["device"] / "var/lib/rosy/provisioning/complete.json")
                          .read_text(encoding="utf-8"))
    assert complete["factory_release"]["signed"] is False
    assert "SIGNATURE_INVALID" in complete["factory_release"]["reason"]
    links = MemoryLinks(UPDATE_ID)
    links.values["previous"] = FACTORY_ID
    _install_update(pipeline)
    with pytest.raises(ValueError, match="SIGNATURE_MISSING"):
        _manager(pipeline, links).rollback()


def test_a_factory_release_changed_on_the_card_keeps_its_signature_out(pipeline):
    bundle = _card_bundle(pipeline)
    (pipeline["release"] / "install/setup.bash").write_text("# changed\n", encoding="utf-8")

    _apply(pipeline, bundle)

    assert not (pipeline["release"] / "SHA256SUMS.sig").exists()
    complete = json.loads((pipeline["device"] / "var/lib/rosy/provisioning/complete.json")
                          .read_text(encoding="utf-8"))
    assert complete["factory_release"]["signed"] is False
    assert "CHECKSUM_MISMATCH" in complete["factory_release"]["reason"]


def test_a_stale_invalid_signature_and_temporary_are_replaced(pipeline):
    bundle = _card_bundle(pipeline)
    (pipeline["release"] / "SHA256SUMS.sig").write_text("garbage\n", encoding="ascii")
    (pipeline["release"] / ".SHA256SUMS.sig.x1y2").write_text("partial", encoding="ascii")

    _apply(pipeline, bundle)

    assert not (pipeline["release"] / ".SHA256SUMS.sig.x1y2").exists()
    assert _manager(pipeline, MemoryLinks(FACTORY_ID)).verify(FACTORY_ID)


def _mounted_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_mounted_image_d225", ROOT / "deploy/image/verify-mounted-image.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("defect", [None, "image-changed", "dist-unsigned", "wrong-key", "image-signed"])
def test_build_go_proves_the_image_release_verifies_with_the_dist_signature(pipeline, defect):
    """verify-artifacts.sh step: unsigned in the image, verified with the dist's signature."""
    verifier = _mounted_verifier()
    key = pipeline["public"]
    if defect == "image-changed":
        (pipeline["release"] / "install/setup.bash").write_text("# changed\n", encoding="utf-8")
    elif defect == "dist-unsigned":
        (pipeline["dist"] / "factory-release" / FACTORY_ID / "SHA256SUMS.sig").unlink()
    elif defect == "wrong-key":
        _other, key = _keys(pipeline["tmp"] / "other", "other")

    findings = verifier.verify_factory_release(pipeline["device"], FACTORY_ID, pipeline["dist"], key)
    if defect == "image-signed":
        shutil.copyfile(pipeline["dist"] / "factory-release" / FACTORY_ID / "SHA256SUMS.sig",
                        pipeline["release"] / "SHA256SUMS.sig")
        findings = verifier.inspect(pipeline["device"], FACTORY_ID)
        assert any("must be unsigned in the image" in finding for finding in findings)
        return

    if defect is None:
        assert findings == []
        assert not (pipeline["release"] / "SHA256SUMS.sig").exists()  # the image was not touched
    else:
        expected = {"image-changed": "CHECKSUM_MISMATCH", "dist-unsigned": "no factory release signature",
                    "wrong-key": "SIGNATURE_INVALID"}[defect]
        assert findings and expected in findings[0]


def test_a_bundle_without_a_factory_signature_changes_nothing(pipeline):
    result = _apply(pipeline, _bundle(None))

    assert result["state"] == "PROVISIONED"
    assert not (pipeline["release"] / "SHA256SUMS.sig").exists()
    complete = json.loads((pipeline["device"] / "var/lib/rosy/provisioning/complete.json")
                          .read_text(encoding="utf-8"))
    assert "factory_release" not in complete
