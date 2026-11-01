#!/usr/bin/env python3
"""Validate approved public CMS build pins and stage only that certificate offline."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import stat
import sys
import tempfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "release"))
import ab_image_layout as ab
from os_rauc import _certificate, _run, _spki
from os_state_layout import _digest, _path, _read

CERTIFICATE = "deploy/robot/pinky_pro/release/public-keys/rosy-os-cms-2026-01.pem"


def _validate(raw):
    _certificate(raw)  # Reject private material, chains and non-certificate PEM objects.
    spki = _spki(raw)  # Only ECDSA P-256 is supported by the installed verifier.
    details = _run(["openssl", "x509", "-noout", "-ext", "extendedKeyUsage,keyUsage,basicConstraints"], data=raw)
    if any(value not in details for value in (b"Code Signing", b"Digital Signature", b"CA:FALSE")):
        raise ValueError("OS CMS certificate requires a leaf code-signing purpose")
    with tempfile.TemporaryDirectory(prefix="rosy-public-cms-") as directory:
        certificate = Path(directory) / "certificate.pem"
        certificate.write_bytes(raw)
        # Validate current notBefore/notAfter; never accept the bundle signing time instead.
        _run(["openssl", "verify", "-CAfile", str(certificate), "-purpose", "any", str(certificate)])
    return spki


def verify(section: dict, source: Path) -> bytes:
    if (not isinstance(section, dict) or section.get("cms_verified") is not True
            or section.get("cms_certificate") != CERTIFICATE):
        raise ValueError("an explicitly approved public CMS build certificate is required")
    expected, spki = section.get("cms_certificate_sha256"), section.get("cms_signer_spki_sha256")
    _digest(expected)
    _digest(spki)
    source = ab._offline_directory(source)
    path = _path(source, CERTIFICATE)
    if path.stat().st_nlink != 1:
        raise ValueError("public CMS build certificate is hard-linked")
    raw = _read(path, 32768, source.stat().st_uid)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("public CMS certificate differs from its approved build digest")
    if _validate(raw) != spki:
        raise ValueError("public CMS signer differs from the approved SPKI digest")
    return raw


def install(root: Path, raw: bytes) -> None:
    root = ab._offline_directory(root)
    _validate(raw)
    target = _path(root, "etc/rauc/keyring.pem")
    if target.exists():
        if (target.stat().st_nlink != 1 or stat.S_IMODE(target.stat().st_mode) != 0o644
                or _read(target, 32768, root.stat().st_uid) != raw):
            raise ValueError("existing offline CMS trust differs")
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    ab._write_atomic(target, raw.decode("ascii"), 0o644)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--source-tree", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    raw = verify(yaml.safe_load(args.lock.read_bytes())["os_updates"], args.source_tree)
    if args.root is not None:
        install(args.root, raw)
    print("OS_CMS_PUBLIC_TRUST_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
