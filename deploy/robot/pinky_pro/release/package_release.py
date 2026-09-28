"""Offline signer/packager. Run in the signing environment, never on a robot."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

from bundle import BundleError, safe_name, verify_tree
from secret_scan import scan_files
from signing import build_sha256sums, sign_checksums


def pack_signed(root: Path, output: Path, key: Path):
    root, output = root.resolve(), output.resolve()
    if root in output.parents:
        raise BundleError("PACKAGE_OUTPUT", "write the bundle outside its payload directory")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in root.rglob("*"):
        safe_name(path.relative_to(root).as_posix())
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise BundleError("ARCHIVE_TYPE", "payload contains links or special files")
        if path.name == ".env":
            raise BundleError("PACKAGE_SECRET", "runtime .env must not ship in a release")
    findings = scan_files(files, root=root, excluded_names=("SHA256SUMS", "SHA256SUMS.sig"))
    if findings:
        raise BundleError("PACKAGE_SECRET", "payload secret scan failed; inspect locally before packaging")
    manifest = verify_tree(root, key)
    if output.name != f"rosy-release-{manifest['release_id']}.tar.zst":
        raise BundleError("PACKAGE_NAME", "bundle filename must name its signed release id")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".pack-") as work:
        raw, compressed = Path(work) / "payload.tar", Path(work) / "payload.tar.zst"
        with tarfile.open(raw, "w") as tar:
            for path in files:
                name = path.relative_to(root).as_posix()
                info = tar.gettarinfo(str(path), arcname=name)
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mode = 0o644
                with path.open("rb") as source:
                    tar.addfile(info, source)
        try:
            from compression import zstd
        except ImportError:
            executable = shutil.which("zstd")
            if not executable:
                raise BundleError("ZSTD_UNAVAILABLE", "install zstd in the signing environment")
            subprocess.run([executable, "-q", "-o", str(compressed), "--", str(raw)], check=True)
        else:
            with raw.open("rb") as source, zstd.open(compressed, "wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
        os.replace(compressed, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="runtime/, images/, and populated manifest.json")
    parser.add_argument("output", type=Path)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, help="optional: sign payload here before packing")
    args = parser.parse_args()
    if args.private_key:
        if args.payload.resolve() in args.private_key.resolve().parents:
            parser.error("private key must remain outside the payload")
        paths = [p.relative_to(args.payload).as_posix() for p in sorted(args.payload.rglob("*"))
                 if p.is_file() and p.name not in {"SHA256SUMS", "SHA256SUMS.sig"}]
        sums = build_sha256sums(args.payload, paths)
        (args.payload / "SHA256SUMS").write_bytes(sums)
        (args.payload / "SHA256SUMS.sig").write_text(sign_checksums(sums, args.private_key), encoding="utf-8")
    pack_signed(args.payload, args.output, args.public_key)


if __name__ == "__main__":
    main()
