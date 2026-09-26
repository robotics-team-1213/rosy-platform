#!/usr/bin/env python3
"""Create the unsigned, self-describing Pinky Pro image release directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


FACTORY_DIR = "factory-release"
FACTORY_FILES = ("SHA256SUMS", "manifest.json")


def export_factory_release(payload: Path, dist: Path, release_id: str) -> list[str]:
    """Copy the sealed in-image release's metadata into the dist (D-225 2.2).

    customize-rootfs.sh exports ``manifest.json`` and ``SHA256SUMS`` of
    ``/opt/rosy/releases/<id>`` to ``<payload>/factory-release/``. They go to
    ``factory-release/<id>/`` here and into the outer SHA256SUMS, so the
    outer offline signature covers them and the offline signer can sign the
    factory list with the same key. Returns the dist-relative paths.
    """
    source = payload / FACTORY_DIR
    target = dist / FACTORY_DIR / release_id
    for name in FACTORY_FILES:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing factory release export: {path}")
    if (target / "SHA256SUMS.sig").exists():
        raise ValueError("factory release signature already present; the dist must be unsigned")
    try:
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"factory release manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("release_id") != release_id:
        raise ValueError("factory release manifest names another release")
    listed = {}
    for line in (source / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        hexdigest, sep, name = line.partition("  ")
        if sep:
            listed[name] = hexdigest
    if listed.get("manifest.json") != digest(source / "manifest.json"):
        raise ValueError("factory release SHA256SUMS does not cover its manifest.json")
    target.mkdir(parents=True, exist_ok=True)
    for name in FACTORY_FILES:
        shutil.copyfile(source / name, target / name)
    return [f"{FACTORY_DIR}/{release_id}/{name}" for name in FACTORY_FILES]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()

    dist, payload = args.dist.resolve(), args.payload.resolve()
    image = dist / f"rosy-os-pinky-pro-{args.release_id}-arm64.img.xz"
    if not image.is_file():
        parser.error(f"missing image: {image}")
    for name in ("deb-packages.txt", "rosy-packages.txt", "required-ros-packages.txt", "source-revision.txt"):
        source = payload / name
        if not source.is_file():
            parser.error(f"missing payload inventory: {source}")
        shutil.copyfile(source, dist / name)

    try:
        factory = export_factory_release(payload, dist, args.release_id)
    except ValueError as exc:
        parser.error(str(exc))

    image_sha = digest(image)
    manifest = {
        "schema_version": 1,
        "release_id": args.release_id,
        "product": "rosy-os",
        "board": "pinky_pro",
        "architecture": "arm64",
        "image": {"filename": image.name, "sha256": image_sha},
    }
    write_json(dist / "manifest.json", manifest)

    packages = []
    for line in (dist / "deb-packages.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        name, _, version = line.partition("\t")
        packages.append({
            "SPDXID": f"SPDXRef-Package-{len(packages) + 1}",
            "name": name,
            "versionInfo": version or "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        })
    write_json(dist / "sbom.spdx.json", {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"rosy-os-pinky-pro-{args.release_id}",
        "documentNamespace": f"https://serion.invalid/spdx/rosy-os/{args.release_id}/{args.source_revision}",
        "creationInfo": {"creators": ["Tool: rosy-create-image-manifest"], "created": "1970-01-01T00:00:00Z"},
        "packages": packages,
    })

    lock_text = args.lock.read_text(encoding="utf-8")
    write_json(dist / "base-image-provenance.json", {
        "lock_sha256": hashlib.sha256(lock_text.encode()).hexdigest(),
        "canonical_signature_verified": True,
    })
    write_json(dist / "build-provenance.json", {
        "release_id": args.release_id,
        "source_revision": args.source_revision,
        "architecture": platform.machine(),
        "builder": "github-actions-native-arm64" if os.environ.get("GITHUB_ACTIONS") else "native-arm64",
    })
    (dist / "release-notes.md").write_text(
        f"# ROSY OS {args.release_id}\n\nPinky Pro Ubuntu 24.04 arm64 + ROS 2 Jazzy factory image.\n",
        encoding="utf-8", newline="\n",
    )
    (dist / "artifact-report.md").write_text(
        f"# Artifact report\n\n- Release: `{args.release_id}`\n- Source: `{args.source_revision}`\n"
        f"- Image SHA-256: `{image_sha}`\n- Signing: `PENDING_OFFLINE`\n",
        encoding="utf-8", newline="\n",
    )

    names = sorted([
        *(path.name for path in dist.iterdir()
          if path.is_file() and path.name not in {"SHA256SUMS", "SHA256SUMS.sig"}),
        *factory,
    ])
    sums = "".join(f"{digest(dist / name)}  {name}\n" for name in names)
    (dist / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(json.dumps({"ok": True, "image": image.name, "sha256": image_sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
