"""Verify an inactive root's native factory with current trust; never repair signatures or enroll."""
from __future__ import annotations

import hashlib
from pathlib import Path

from native_release import NativeReleaseManager, PYTHON_RUNTIME_IMAGE_FILE
from os_factory_release import CHECKSUM_LIMIT, DESCRIPTOR, PUBLIC_KEY
from os_payload_compatibility import verify_contract
from os_state_layout import _object, _path, _read
from os_update_manifest import validate_metadata


def _file(root: Path, relative: str, limit: int) -> bytes:
    path = _path(root, relative)
    if path.stat().st_nlink != 1:
        raise ValueError("installed factory input is hard-linked")
    return _read(path, limit, root.stat().st_uid)


def verify(current_root: Path, target_root: Path, metadata: dict) -> dict:
    """Mount owner first binds this tree to the authenticated, inactive RAUC image."""
    try:
        current_root, target_root = Path(current_root).absolute(), Path(target_root).absolute()
        if target_root == current_root or target_root == Path("/") or target_root.is_symlink():
            raise ValueError("an independent inactive root is required")
        return _verify(current_root, target_root, metadata)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_FACTORY_HOLD: {exc}") from exc


def verify_current(root: Path, metadata: dict) -> dict:
    """Trial owner separately proves firmware/transaction binding before checking this active factory."""
    try:
        root = Path(root).absolute()
        descriptor = _verify(root, root, metadata)
        pointer = root / "opt/rosy/current"
        expected = _path(root, "opt/rosy/releases/" + descriptor["release_id"])
        if not pointer.is_symlink() or pointer.resolve(strict=True) != expected:
            raise ValueError("current native pointer is not the installed factory")
        return descriptor
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_FACTORY_HOLD: {exc}") from exc


def _verify(current_root: Path, target_root: Path, metadata: dict) -> dict:
    try:
        validate_metadata(metadata)
        descriptor = _object(_file(target_root, DESCRIPTOR, 8192),
                             {"schema_version", "release_id", "checksums_sha256"})
        expected = metadata["native_factory"]
        if any(descriptor[key] != expected[key] for key in ("release_id", "checksums_sha256")):
            raise ValueError("native factory differs from authenticated OS metadata")
        key = _file(current_root, PUBLIC_KEY, 8192)
        if _file(target_root, PUBLIC_KEY, 8192) != key:
            raise ValueError("incoming native trust differs from current authority")
        prefix = "opt/rosy/releases/" + expected["release_id"]
        sums = _file(target_root, prefix + "/SHA256SUMS", CHECKSUM_LIMIT)
        _file(target_root, prefix + "/SHA256SUMS.sig", 512)
        if hashlib.sha256(sums).hexdigest() != expected["checksums_sha256"]:
            raise ValueError("native factory checksum list differs")
        manager = NativeReleaseManager(root=target_root, public_key=_path(current_root, PUBLIC_KEY))
        manager.verify_payload(expected["release_id"])
        _file(target_root, PYTHON_RUNTIME_IMAGE_FILE.as_posix(), 128)
        manager.check_python_runtime(expected["release_id"])
        verify_contract(_path(target_root, prefix + "/deploy/robot/native"), state_schema=1, boot_abi=2)
        return descriptor
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"OS_FACTORY_HOLD: {exc}") from exc
