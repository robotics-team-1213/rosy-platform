"""Read-only bundle manifest & file extraction for completed canonical runs (D-1072 PR-6)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from experiment_io import identifier

FILE_LIMIT = 256 * 1024 * 1024


def _completed_bundle_dir(root: Path, run: dict[str, Any]) -> Path:
    if run.get("status") != "succeeded":
        raise ValueError(f"completed succeeded run required, got {run.get('status')!r}")
    bdir = root / "runs" / identifier(str(run["id"])) / "output" / "bundle"
    if bdir.is_symlink() or not bdir.is_dir():
        raise KeyError("bundle missing for run")
    return bdir


def bundle_manifest(root: Path, run: dict[str, Any]) -> dict[str, Any]:
    """Return size/SHA-256 manifest for a completed canonical run bundle without loading files into RAM."""
    bdir = _completed_bundle_dir(root, run)
    base, files = bdir.resolve(), []
    for p in sorted(bdir.rglob("*")):
        if p.is_symlink():
            raise ValueError("symlink forbidden inside bundle directory")
        if p.is_dir():
            continue
        if not p.is_file() or not p.resolve().is_relative_to(base):
            raise ValueError("unsafe file inside bundle directory")
        size = p.stat().st_size
        if size > FILE_LIMIT:
            raise ValueError(f"bundle file {p.name!r} exceeds {FILE_LIMIT} bytes")
        with p.open("rb") as fh:
            digest = hashlib.file_digest(fh, "sha256").hexdigest()
        files.append({"path": p.relative_to(bdir).as_posix(), "bytes": size, "sha256": digest})
    by_path = {f["path"]: f["sha256"] for f in files}
    return {
        "schema": "rosy.canonical-bundle-manifest.v1",
        "run_id": run["id"],
        "policy_revision": by_path.get("model.safetensors"),
        "onnx_sha256": by_path.get("model.onnx"),
        "files": files,
    }


def bundle_file(root: Path, run: dict[str, Any], relpath: str) -> bytes:
    """Return bytes of a single non-symlink file inside a completed canonical run bundle."""
    bdir = _completed_bundle_dir(root, run)
    if (
        not relpath
        or "\x00" in relpath
        or relpath.startswith(("/", "\\"))
        or "\\" in relpath
        or any(part in ("", ".", "..") for part in Path(relpath).parts)
    ):
        raise ValueError("invalid bundle file relpath")
    cur = bdir
    for part in Path(relpath).parts:
        cur = cur / part
        if cur.is_symlink():
            raise ValueError("symlink forbidden inside bundle directory")
    if not cur.is_file():
        raise FileNotFoundError(relpath)
    if not cur.resolve().is_relative_to(bdir.resolve()):
        raise ValueError("unsafe bundle file path")
    if cur.stat().st_size > FILE_LIMIT:
        raise ValueError(f"bundle file {relpath!r} exceeds {FILE_LIMIT} bytes")
    return cur.read_bytes()
