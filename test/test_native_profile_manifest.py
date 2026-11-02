"""Read-only native-v2 contract; toy closures confer no runtime authority."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest

from signing import build_sha256sums, sign_checksums, verify_release_files


RELEASE = "2026.10.28-001"
REVISION = "a" * 40
ENTRY = "deploy/robot/omx/run_hardware_owner.py"
UNIT = "deploy/robot/omx/rosy-omx-owner@.service"
LOCK = "deploy/robot/omx/requirements-manual.lock"


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _duplicate_key(value, selected):
    if isinstance(value, dict):
        pairs = [_canonical(key) + b":" + _duplicate_key(item, selected) for key, item in sorted(value.items())]
        if value is selected:
            pairs.append(pairs[0])
        return b"{" + b",".join(pairs) + b"}"
    if isinstance(value, list):
        return b"[" + b",".join(_duplicate_key(item, selected) for item in value) + b"]"
    return _canonical(value)


@pytest.fixture
def keys(tmp_path):
    private, public = tmp_path / "throwaway.key", tmp_path / "toy.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    return private, public


def _seal(root, private, manifest=None, raw=None):
    if manifest is not None:
        (root / "manifest.json").write_bytes(_canonical(manifest) if raw is None else raw)
    names = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file() and p.name not in {"SHA256SUMS", "SHA256SUMS.sig"})
    sums = build_sha256sums(root, names)
    (root / "SHA256SUMS").write_bytes(sums)
    (root / "SHA256SUMS.sig").write_text(sign_checksums(sums, private), encoding="utf-8")


@pytest.fixture
def case(tmp_path, keys):
    private, public = keys
    root = tmp_path / RELEASE
    root.mkdir()
    system = b"python3\t3.14.4\tamd64\n"
    ros = b"rclpy\t1.0.0\t" + b"b" * 64 + b"\n"
    lock = b"# toy closure; no executable manual owner\n"
    identity = {
        "os_id": "ubuntu", "os_version": "26.04", "architecture": "amd64",
        "python_version": "3.14.4", "python_executable_sha256": "c" * 64,
        "python_cache_tag": "cpython-314", "python_soabi": "cpython-314-x86_64-linux-gnu",
        "ros_distro": "lyrical", "system_packages_sha256": _digest(system),
        "ros_packages_sha256": _digest(ros), "dependency_lock_sha256": _digest(lock),
        "system_site_packages": False,
    }
    profile = {
        "id": "omx-manual-device-trial.v1", "component_role": "omx-manual-owner",
        "entrypoint": ENTRY, "unit_files": [UNIT],
        "dependency_lock": {"path": LOCK, "sha256": _digest(lock)},
    }
    target = {"board": "omx", "architecture": "amd64", "os_family": "ubuntu", "os_release": "26.04"}
    runtime = {"model": "native-systemd", "python_version": "3.14.4", "ros_distro": "lyrical"}
    payload = {
        "install/.rosy-release": (RELEASE + "\n").encode(),
        "source-revision.txt": (REVISION + "\n").encode(),
        "python-runtime.sha256": (_digest(_canonical(identity)) + "\n").encode(),
        "runtime-identity.json": _canonical(identity), "runtime-system-packages.lock": system,
        "runtime-ros-packages.lock": ros, LOCK: lock, ENTRY: b"# inert fixture\n", UNIT: b"# inert unit\n",
    }
    for name, data in payload.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        "schema_version": 2, "release_id": RELEASE, "git_revision": REVISION,
        "target": target, "runtime": runtime, "signing_key_id": public.stem, "profile": profile,
        "files": [{"path": name, "sha256": _digest(data)} for name, data in sorted(payload.items())],
    }
    # These stand in for installed policy and independently observed closure, never candidate-derived policy.
    expected = copy.deepcopy({"expected_target": target, "expected_runtime": runtime,
                              "expected_profile": profile, "expected_runtime_identity": identity,
                              "expected_unit_digests": {UNIT: _digest(payload[UNIT])}})
    del expected["expected_profile"]["dependency_lock"]["sha256"]
    _seal(root, private, manifest)
    return root, private, public, manifest, expected


def _verify(case):
    root, _private, public, _manifest, expected = case
    # Import at call time: tests collect before the new feature exists; RED is interface absence only.
    module = importlib.import_module("deploy.hosts.common.release.native_profiles")
    return module.verify_native_profile(root, public, **expected)


def _refresh(case, name, data):
    root, private, _public, manifest, _expected = case
    (root / name).write_bytes(data)
    for entry in manifest["files"]:
        if entry["path"] == name:
            entry["sha256"] = _digest(data)
    _seal(root, private, manifest)


def test_signed_v2_is_readonly(case):
    root = case[0]
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert _verify(case) == case[3]
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_signed_object_key_order_is_ignored(case):
    def reversed_objects(value):
        if isinstance(value, dict):
            return {key: reversed_objects(item) for key, item in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reversed_objects(item) for item in value]
        return value

    root, private, public, manifest, expected = case
    identity = expected["expected_runtime_identity"]
    fingerprint = (root / "python-runtime.sha256").read_bytes()
    identity_raw = json.dumps(reversed_objects(identity), separators=(",", ":")).encode()
    assert identity_raw != _canonical(identity)
    _refresh(case, "runtime-identity.json", identity_raw)
    assert (root / "python-runtime.sha256").read_bytes() == fingerprint
    raw = json.dumps(reversed_objects(manifest), separators=(",", ":")).encode()
    assert raw != _canonical(manifest)
    assert json.loads(raw)["files"] == manifest["files"]
    _seal(root, private, manifest, raw)
    assert verify_release_files(root, public) == []
    assert _verify(case) == manifest


def test_independently_allowed_arm64_tuple(case):
    manifest, expected = case[3:]
    manifest["target"]["architecture"] = "arm64"
    expected["expected_target"]["architecture"] = "arm64"
    identity = json.loads((case[0] / "runtime-identity.json").read_bytes())
    for obj in [identity, expected["expected_runtime_identity"]]:
        obj["architecture"] = "arm64"
        obj["python_soabi"] = "cpython-314-aarch64-linux-gnu"
    _refresh(case, "runtime-identity.json", _canonical(identity))
    _refresh(case, "python-runtime.sha256", (_digest(_canonical(identity)) + "\n").encode())
    assert _verify(case) == manifest


def test_new_signed_lock_needs_observed_closure_without_static_digest_preapproval(case):
    lock_digest = _digest(b"# second toy closure\n")
    case[3]["profile"]["dependency_lock"]["sha256"] = lock_digest
    identity = json.loads((case[0] / "runtime-identity.json").read_bytes())
    identity["dependency_lock_sha256"] = lock_digest
    case[4]["expected_runtime_identity"]["dependency_lock_sha256"] = lock_digest
    _refresh(case, LOCK, b"# second toy closure\n")
    _refresh(case, "runtime-identity.json", _canonical(identity))
    _refresh(case, "python-runtime.sha256", (_digest(_canonical(identity)) + "\n").encode())
    assert _verify(case) == case[3]


@pytest.mark.parametrize("group,key,value", [
    (None, "schema_version", True), (None, "schema_version", 2.0),
    (None, "release_id", "2026.10.28-1"), (None, "git_revision", "A" * 40),
    (None, "signing_key_id", "other"), (None, "files", []),
    ("target", "architecture", "arm64"), ("target", "os_release", "24.04"),
    ("target", "board", "pinky_pro"), ("target", "os_family", "debian"),
    ("runtime", "python_version", "3.12.3"), ("runtime", "ros_distro", "jazzy"),
    ("runtime", "model", "container"), ("profile", "id", "observation.v1"),
    ("profile", "component_role", "observer"), ("profile", "entrypoint", "other.py"),
    ("profile", "unit_files", ["other.service"]), ("profile", "unit_files", [UNIT, UNIT]),
    ("profile", "dependency_lock", {"path": LOCK, "sha256": "d" * 64}),
    ("profile", "dependency_lock", {"path": "other.lock", "sha256": "d" * 64}),
])
def test_resigned_wrong_policy_or_type_refused(case, group, key, value):
    manifest = case[3]
    (manifest if group is None else manifest[group])[key] = value
    _seal(case[0], case[1], manifest)
    assert verify_release_files(case[0], case[2]) == []
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("group", [None, "target", "runtime", "profile", "dependency_lock", "file"])
@pytest.mark.parametrize("operation", ["missing", "extra", "duplicate"])
def test_exact_keys_recursively(case, group, operation):
    manifest = case[3]
    obj = manifest if group is None else (
        manifest["files"][0] if group == "file" else
        manifest["profile"][group] if group == "dependency_lock" else manifest[group])
    key = next(iter(obj))
    if operation == "missing":
        del obj[key]
    elif operation == "extra":
        obj["unexpected"] = "extra"
    raw = _canonical(manifest)
    if operation == "duplicate":
        raw = _duplicate_key(manifest, obj)
    _seal(case[0], case[1], manifest, raw)
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../b", "a//b", "./a", "a/./b",
                                  "a\\b", "C:/escape", "", "a/", "~root", "a\x00b"])
def test_noncanonical_inventory_paths_refused(case, path):
    case[3]["files"][0]["path"] = path
    _seal(case[0], case[1], case[3])
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("fault", ["duplicate", "unsorted", "missing", "extra", "digest", "digest_type"])
def test_signed_inventory_disagreement_refused(case, fault):
    files = case[3]["files"]
    if fault == "duplicate":
        files.insert(0, copy.deepcopy(files[0]))
    elif fault == "unsorted":
        files.reverse()
    elif fault == "missing":
        files.pop()
    elif fault == "extra":
        files.append({"path": "z-missing", "sha256": "0" * 64})
    else:
        files[0]["sha256"] = "0" * 64 if fault == "digest" else 0
    _seal(case[0], case[1], case[3])
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("name", ["install/.rosy-release", "source-revision.txt", "python-runtime.sha256",
                                  "runtime-identity.json", "runtime-system-packages.lock",
                                  "runtime-ros-packages.lock", ENTRY, UNIT, LOCK])
def test_required_payload_cannot_be_removed_from_signed_inventory(case, name):
    (case[0] / name).unlink()
    case[3]["files"] = [entry for entry in case[3]["files"] if entry["path"] != name]
    _seal(case[0], case[1], case[3])
    assert verify_release_files(case[0], case[2]) == []
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("fault", ["unsigned", "tampered", "wrong_key", "unlisted"])
def test_real_signature_and_checksum_refusals(case, keys, tmp_path, fault):
    root = case[0]
    if fault == "unsigned":
        (root / "SHA256SUMS.sig").unlink()
    elif fault == "tampered":
        (root / ENTRY).write_bytes(b"changed")
    elif fault == "unlisted":
        (root / "extra.py").write_bytes(b"untrusted")
    else:
        other = tmp_path / "other.key"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(other)],
                       check=True, capture_output=True)
        _seal(root, other, case[3])
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("metadata", ["manifest.json", "runtime-identity.json"])
def test_metadata_reopened_after_real_signature_verification_is_refused(case, monkeypatch, metadata):
    module = importlib.import_module("deploy.hosts.common.release.native_profiles")
    root, private, public, manifest, expected = case
    if metadata == "manifest.json":
        manifest["profile"]["component_role"] = "observer"
        _seal(root, private, manifest)
        replacement = copy.deepcopy(manifest)
        replacement["profile"]["component_role"] = expected["expected_profile"]["component_role"]
        unsigned = _canonical(replacement)
    else:
        identity = expected["expected_runtime_identity"]
        unsigned = json.dumps(dict(reversed(list(identity.items()))), indent=2).encode()
    signed_bytes = (root / metadata).read_bytes()
    assert signed_bytes != unsigned
    assert verify_release_files(root, public) == []
    real_verify = module.verify_release_checksums
    swapped = []

    def verify_then_swap(release, key):
        entries, rejections = real_verify(release, key)
        assert rejections == []
        assert entries[metadata] == _digest(signed_bytes)
        (release / metadata).write_bytes(unsigned)
        swapped.append(metadata)
        return entries, rejections

    monkeypatch.setattr(module, "verify_release_checksums", verify_then_swap)
    with pytest.raises(ValueError):
        _verify(case)
    assert swapped == [metadata]


@pytest.mark.parametrize("name,data", [
    ("install/.rosy-release", b"2026.10.28-999\n"), ("source-revision.txt", b"b" * 40 + b"\n"),
    ("python-runtime.sha256", b"0" * 64 + b"\n"), (LOCK, b"changed lock\n"),
    ("runtime-system-packages.lock", b"changed package\n"), ("runtime-ros-packages.lock", b"changed ROS\n"),
])
def test_resigned_runtime_binding_disagreement(case, name, data):
    _refresh(case, name, data)
    assert verify_release_files(case[0], case[2]) == []
    with pytest.raises(ValueError):
        _verify(case)


def test_resigned_template_change_requires_installed_policy(case):
    _refresh(case, UNIT, b"# changed shared template\n")
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("fault", ["missing", "extra", "duplicate", "bool_type", "digest_type"])
def test_runtime_identity_exact_shape(case, fault):
    identity = copy.deepcopy(case[4]["expected_runtime_identity"])
    if fault == "missing":
        del identity["python_soabi"]
    elif fault == "extra":
        identity["extra"] = "unexpected"
    elif fault == "bool_type":
        identity["system_site_packages"] = 0
    elif fault == "digest_type":
        identity["python_executable_sha256"] = 0
    raw = _canonical(identity)
    if fault == "duplicate":
        raw = raw.replace(b'"os_id":"ubuntu"', b'"os_id":"ubuntu","os_id":"ubuntu"')
    _refresh(case, "runtime-identity.json", raw)
    _refresh(case, "python-runtime.sha256", (_digest(_canonical(identity)) + "\n").encode())
    with pytest.raises(ValueError):
        _verify(case)


@pytest.mark.parametrize("key", ["python_executable_sha256", "python_cache_tag", "python_soabi",
                                  "python_version", "ros_distro", "architecture", "system_site_packages",
                                  "os_id", "os_version"])
def test_unchanged_lock_cannot_hide_runtime_drift(case, key):
    identity = copy.deepcopy(case[4]["expected_runtime_identity"])
    changed = {"system_site_packages": True, "python_executable_sha256": "d" * 64,
               "os_id": "debian", "os_version": "24.04"}
    identity[key] = changed.get(key, "different")
    _refresh(case, "runtime-identity.json", _canonical(identity))
    _refresh(case, "python-runtime.sha256", (_digest(_canonical(identity)) + "\n").encode())
    assert verify_release_files(case[0], case[2]) == []
    with pytest.raises(ValueError):
        _verify(case)


def test_pinky_v1_producer_bytes_and_historical_acceptance(tmp_path, keys):
    from build_payload_release import build_release
    from deploy.robot.pinky_pro.native.native_release import NativeReleaseManager

    private, public = keys
    payload = tmp_path / "payload"
    data = {"install/.rosy-release": RELEASE + "\n", "source-revision.txt": REVISION + "\n",
            "python-runtime.sha256": "1" * 64 + "\n", "rosy-packages.txt": "core\n",
            "deploy/robot/native/rosy-runtime.target": "# inert\n"}
    for name, text in data.items():
        path = payload / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    root = tmp_path / "device"
    release = root / "opt/rosy/releases" / RELEASE
    build_release(payload, RELEASE, release, signing_key_id=public.stem)
    manifest = {"schema_version": 1, "release_id": RELEASE, "git_revision": REVISION,
                "target": {"board": "pinky_pro", "host": "raspberry-pi-5", "architecture": "arm64",
                           "os_family": "ubuntu-server", "os_release": "24.04"},
                "runtime": {"model": "native-systemd", "default_mode": "core"},
                "signing_key_id": public.stem,
                "files": [{"path": name, "sha256": _digest(text.encode())} for name, text in sorted(data.items())]}
    assert (release / "manifest.json").read_bytes() == (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    assert (release / "SHA256SUMS").read_bytes() == build_sha256sums(release, ["manifest.json", *data])
    _seal(release, private)
    manager = NativeReleaseManager(root=root, public_key=public)
    assert manager.verify_payload(RELEASE) == manifest
    for schema in [True, 1.0]:
        manifest["schema_version"] = schema
        manifest["files"].reverse()
        _seal(release, private, manifest)
        assert manager.verify_payload(RELEASE) == manifest
    assert (release / "python-runtime.sha256").read_bytes() == b"1" * 64 + b"\n"
