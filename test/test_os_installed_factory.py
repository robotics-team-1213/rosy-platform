"""Installed factories use real Ed25519 verification without running candidate code or enrollment."""
import importlib
import json

import pytest

from test_factory_release_signature import _keys, FACTORY_ID
from test_os_factory_release import _factory
from test_os_update_manifest import metadata


def _installed(tmp_path):
    from test_ab_image_layout import module
    module()
    private, public = _keys(tmp_path / "offline", "fixture")
    current = tmp_path / "current"
    (current / "etc/rosy/trusted-release-keys").mkdir(parents=True)
    (current / "etc/rosy/trusted-release-keys" / public.name).write_bytes(public.read_bytes())
    target = tmp_path / "inactive"
    release, _ = _factory(target, FACTORY_ID, private, public, signed=True)
    value = metadata()
    descriptor = json.loads((target / "etc/rosy/os-factory-release.json").read_text())
    value["native_factory"] = {key: descriptor[key] for key in ("release_id", "checksums_sha256")}
    # Offline root has no /proc, running CORE, enrollment, or mounted common state.
    (target / "etc/rosy/os-slot.json").write_text('{"untrusted":"offline"}')
    return current, target, release, value, private, public


def test_payload_verification_is_read_only_and_independent_of_running_root_admission(tmp_path):
    current, target, release, _, _, public = _installed(tmp_path)
    from native_release import NativeReleaseManager
    manager = NativeReleaseManager(root=target, public_key=current / "etc/rosy/trusted-release-keys" / public.name)
    before = {p: p.read_bytes() for p in (release / "SHA256SUMS", release / "SHA256SUMS.sig")}
    assert manager.verify_payload(FACTORY_ID)["release_id"] == FACTORY_ID
    with pytest.raises(ValueError, match="OS_PAYLOAD_INCOMPATIBLE"):
        manager.verify(FACTORY_ID)
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert not (target / "var").exists() and not (target / "proc").exists()


def test_offline_factory_is_pinned_to_current_key_and_authenticated_os_baseline(tmp_path):
    current, target, release, value, _, _ = _installed(tmp_path)
    module = importlib.import_module("os_installed_factory")
    before = (release / "SHA256SUMS.sig").read_bytes()
    assert module.verify(current, target, value)["release_id"] == FACTORY_ID
    assert (release / "SHA256SUMS.sig").read_bytes() == before
    assert not (target / "var").exists()


@pytest.mark.parametrize("damage", ["signature", "sums", "factory_id", "factory_hash", "key", "native", "sdk"])
def test_installed_factory_mismatch_is_hold_without_signature_repair_or_candidate_execution(tmp_path, damage):
    current, target, release, value, _, _ = _installed(tmp_path)
    module = importlib.import_module("os_installed_factory")
    if damage == "signature": (release / "SHA256SUMS.sig").unlink()
    elif damage == "sums": (release / "SHA256SUMS").write_text("bad")
    elif damage == "factory_id": value["native_factory"]["release_id"] = "2026.10.26-010"
    elif damage == "factory_hash": value["native_factory"]["checksums_sha256"] = "0" * 64
    elif damage == "key":
        _, other = _keys(tmp_path / "other", "fixture")
        (target / "etc/rosy/trusted-release-keys" / other.name).write_bytes(other.read_bytes())
    elif damage == "native": (release / "install/.rosy-release").write_text("tampered")
    else: (release / "deploy/robot/native/image_layer_boot.py").write_text("raise RuntimeError('candidate executed')")
    signature = release / "SHA256SUMS.sig"
    before = signature.read_bytes() if signature.exists() else None
    with pytest.raises(ValueError, match="OS_FACTORY_HOLD"):
        module.verify(current, target, value)
    assert (signature.read_bytes() if signature.exists() else None) == before
    assert not (target / "var").exists()


def test_authenticated_candidate_sdk_is_parsed_without_executing_its_top_level_code(tmp_path):
    import hashlib
    from build_payload_release import seal_release
    from signing import sign_checksums
    current, target, release, value, private, _ = _installed(tmp_path)
    sdk = release / "deploy/robot/native/image_layer_boot.py"
    sdk.write_text(sdk.read_text() + "\nraise RuntimeError('authenticated candidate code executed')\n")
    seal_release(release, FACTORY_ID)
    sums = (release / "SHA256SUMS").read_bytes()
    (release / "SHA256SUMS.sig").write_text(sign_checksums(sums, private) + "\n")
    descriptor = dict(schema_version=1, release_id=FACTORY_ID, checksums_sha256=hashlib.sha256(sums).hexdigest())
    (target / "etc/rosy/os-factory-release.json").write_text(json.dumps(descriptor))
    value["native_factory"] = {k: descriptor[k] for k in ("release_id", "checksums_sha256")}
    module = importlib.import_module("os_installed_factory")
    assert module.verify(current, target, value) == descriptor
