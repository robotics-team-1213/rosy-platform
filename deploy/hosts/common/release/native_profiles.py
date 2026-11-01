"""Read-only native-v2 metadata verification, separate from Pinky v1.

The installed caller supplies protected policy and independently measured runtime
identity. Success certifies signed metadata agreement only; it grants no runtime,
activation, ancestry, instance-placement or device authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .signing import verify_release_checksums


_HEX64 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_RELEASE = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9]{3}")
_TOP = {"schema_version", "release_id", "git_revision", "target", "runtime",
        "signing_key_id", "files", "profile"}
_TARGET = {"board", "architecture", "os_family", "os_release"}
_RUNTIME = {"model", "python_version", "ros_distro"}
_PROFILE = {"id", "component_role", "entrypoint", "unit_files", "dependency_lock"}
_IDENTITY = {"os_id", "os_version", "architecture", "python_version",
             "python_executable_sha256", "python_cache_tag", "python_soabi", "ros_distro",
             "system_packages_sha256", "ros_packages_sha256", "dependency_lock_sha256",
             "system_site_packages"}
_REQUIRED = {"install/.rosy-release", "source-revision.txt", "python-runtime.sha256",
             "runtime-identity.json", "runtime-system-packages.lock", "runtime-ros-packages.lock"}


def _refuse(detail: str) -> None:
    raise ValueError(f"NATIVE_PROFILE_INVALID: {detail}")


def _object(value, keys: set[str], field: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        _refuse(f"{field}: exact object keys required")
    return value


def _string(value, field: str) -> str:
    if type(value) is not str or not value:
        _refuse(f"{field}: nonempty string required")
    return value


def _hex(value, field: str) -> str:
    if not _HEX64.fullmatch(_string(value, field)):
        _refuse(f"{field}: lowercase 64-hex digest required")
    return value


def _path(value, field: str) -> str:
    value = _string(value, field)
    if (value.startswith(("/", "~")) or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        _refuse(f"{field}: canonical relative POSIX path required")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _refuse(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _authenticated_bytes(release: Path, name: str, signed: dict[str, str]) -> bytes:
    try:
        data = (release / name).read_bytes()
    except OSError as exc:
        raise ValueError(f"NATIVE_PROFILE_INVALID: {name}: unreadable metadata") from exc
    if hashlib.sha256(data).hexdigest() != signed.get(name):
        _refuse(f"{name}: metadata differs from authenticated bytes")
    return data


def _read_json(data: bytes, field: str):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"NATIVE_PROFILE_INVALID: {field}: unreadable JSON") from exc


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _strings(value, keys: set[str], field: str) -> dict:
    value = _object(value, keys, field)
    for key, item in value.items():
        _string(item, f"{field}.{key}")
    return value


def _identity(value, field: str) -> dict:
    value = _object(value, _IDENTITY, field)
    for key, item in value.items():
        if key == "system_site_packages":
            if type(item) is not bool:
                _refuse(f"{field}.{key}: boolean required")
        elif key.endswith("_sha256"):
            _hex(item, f"{field}.{key}")
        else:
            _string(item, f"{field}.{key}")
    return value


def verify_native_profile(
    release: Path,
    public_key: Path,
    *,
    expected_target: dict,
    expected_runtime: dict,
    expected_profile: dict,
    expected_runtime_identity: dict,
    expected_unit_digests: dict[str, str],
) -> dict:
    """Verify signed metadata against independently supplied installed policy.

    ``expected_profile.dependency_lock`` contains only the protected lock path;
    the release-specific digest is authenticated and bound to runtime identity.
    ``expected_unit_digests`` pins installed shared templates. Actual host/closure
    observation and all update/admission transactions belong to the caller.
    Package locks are authenticated opaque bytes here; the closure collector and
    builder own reviewed sorted records and proof of installed dependencies.
    """
    release, public_key = Path(release), Path(public_key)
    if release.is_symlink() or not release.is_dir():
        _refuse("release must be a real directory")
    if public_key.is_symlink() or not public_key.is_file():
        _refuse("trusted public key must be a real file")
    for name in ("SHA256SUMS", "SHA256SUMS.sig", "manifest.json"):
        if (release / name).is_symlink():
            _refuse(f"{name}: symlink metadata is forbidden")
    signed, rejections = verify_release_checksums(release, public_key)
    if rejections:
        first = rejections[0]
        raise ValueError(f"{first.code}: {first.detail}")
    if "manifest.json" not in signed:
        _refuse("manifest must be covered by the signature")
    manifest = _object(_read_json(_authenticated_bytes(release, "manifest.json", signed),
                                  "manifest.json"), _TOP, "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 2:
        _refuse("schema_version must be integer 2")
    if not _RELEASE.fullmatch(_string(manifest["release_id"], "release_id")):
        _refuse("release_id must be YYYY.MM.DD-NNN")
    if manifest["release_id"] != release.name:
        _refuse("release_id does not match release directory")
    if not _REVISION.fullmatch(_string(manifest["git_revision"], "git_revision")):
        _refuse("git_revision must be lowercase 40-hex")
    if _string(manifest["signing_key_id"], "signing_key_id") != public_key.stem:
        _refuse("signing_key_id does not match trusted key")
    target = _strings(manifest["target"], _TARGET, "target")
    runtime = _strings(manifest["runtime"], _RUNTIME, "runtime")
    if target != _strings(expected_target, _TARGET, "expected_target"):
        _refuse("target differs from installed policy")
    if runtime != _strings(expected_runtime, _RUNTIME, "expected_runtime"):
        _refuse("runtime differs from installed policy")
    profile = _object(manifest["profile"], _PROFILE, "profile")
    for key in ("id", "component_role"):
        _string(profile[key], f"profile.{key}")
    entrypoint = _path(profile["entrypoint"], "profile.entrypoint")
    units = profile["unit_files"]
    if type(units) is not list or not units:
        _refuse("profile.unit_files must be a nonempty array")
    for unit in units:
        _path(unit, "profile.unit_files")
    if units != sorted(set(units)):
        _refuse("profile.unit_files must be sorted and unique")
    lock = _object(profile["dependency_lock"], {"path", "sha256"}, "dependency_lock")
    lock_path = _path(lock["path"], "dependency_lock.path")
    _hex(lock["sha256"], "dependency_lock.sha256")
    policy = _object(expected_profile, _PROFILE, "expected_profile")
    _object(policy["dependency_lock"], {"path"}, "expected_profile.dependency_lock")
    static_profile = {**profile, "dependency_lock": {"path": lock_path}}
    if static_profile != policy:
        _refuse("profile differs from installed policy")
    entries = manifest["files"]
    if type(entries) is not list or not entries:
        _refuse("files must be a nonempty array")
    declared = {}
    for entry in entries:
        _object(entry, {"path", "sha256"}, "file")
        name = _path(entry["path"], "file.path")
        if name in declared:
            _refuse("duplicate file path")
        declared[name] = _hex(entry["sha256"], "file.sha256")
    if list(declared) != sorted(declared):
        _refuse("files must be sorted by path")
    if declared != {name: digest for name, digest in signed.items() if name != "manifest.json"}:
        _refuse("manifest inventory disagrees with signed payload")
    if not (_REQUIRED | {entrypoint, lock_path} | set(units)) <= set(declared):
        _refuse("required payload is missing")
    if type(expected_unit_digests) is not dict or set(expected_unit_digests) != set(units):
        _refuse("installed template pins must match profile units")
    for unit, digest in expected_unit_digests.items():
        if declared[unit] != _hex(digest, "expected_unit_digests"):
            _refuse("unit template differs from installed policy")
    if declared[lock_path] != lock["sha256"]:
        _refuse("dependency lock digest disagrees with inventory")
    identity = _identity(_read_json(_authenticated_bytes(release, "runtime-identity.json", signed),
                                   "runtime-identity.json"), "runtime identity")
    if identity != _identity(expected_runtime_identity, "expected runtime identity"):
        _refuse("runtime identity differs from independently measured closure")
    if (identity["os_id"] != target["os_family"] or identity["os_version"] != target["os_release"]
            or identity["architecture"] != target["architecture"]
            or identity["python_version"] != runtime["python_version"]
            or identity["ros_distro"] != runtime["ros_distro"]):
        _refuse("runtime identity disagrees with target/runtime")
    if identity["dependency_lock_sha256"] != lock["sha256"]:
        _refuse("runtime identity disagrees with dependency lock")
    fingerprint = hashlib.sha256(_canonical(identity)).hexdigest()
    if _authenticated_bytes(release, "python-runtime.sha256", signed) != (fingerprint + "\n").encode("ascii"):
        _refuse("runtime fingerprint does not match canonical identity")
    for name, field in [("runtime-system-packages.lock", "system_packages_sha256"),
                        ("runtime-ros-packages.lock", "ros_packages_sha256")]:
        if declared[name] != identity[field]:
            _refuse("runtime identity disagrees with package lock")
    for name, expected in [("install/.rosy-release", manifest["release_id"]),
                           ("source-revision.txt", manifest["git_revision"])]:
        if _authenticated_bytes(release, name, signed) != (expected + "\n").encode("ascii"):
            _refuse(f"{name}: manifest identity mismatch")
    return manifest
