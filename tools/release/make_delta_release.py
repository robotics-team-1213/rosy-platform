"""Signed delta payload for a change that only edits files the payload ships verbatim (D-553 addendum 3).

    python tools/release/make_delta_release.py --base-dir X:/DevTemp/rosy-release-<base>/x/<base> \
        --base-tarball X:/DevTemp/rosy-release-<base>/<base>.tar.gz --release-id <new-id>

The base is a signed release this PC prepared earlier and the robots already hold. The
tool rebuilds the complete new release locally (base files + the changed files from
HEAD), writes manifest.json and SHA256SUMS over all of it, signs it with the same key
(sign_image_release.py) and verifies the full tree, exactly as for a GitHub build. Only
the delta tarball differs: it carries the new metadata, the changed files and
`.rosy-delta-base` (base id + sha256 of the base SHA256SUMS). rosy-release-unpack.sh
copies the base on the robot, lays the delta over it, and activation verifies the
whole rebuilt release against the signature (native_release.py verify()).

A changed path is shipped in the delta only when its content at the base revision is
byte-identical to payload files whose last two path parts match (a verbatim copy:
Python modules, launch/config/data files, native-runtime scripts). Anything else
refuses, and the change needs a full build:
- added, deleted or renamed shipped files, and build inputs (C/C++ sources and
  headers, interfaces, CMakeLists.txt, package.xml, setup.py, setup.cfg);
- a changed file with no verbatim copy in the payload, unless it is under docs/,
  test(s)/, tools/, .github/, .claude/, a *.md file, or a prefix passed with
  --not-shipped (recorded in the output).
Stale checked-hash .pyc files stay: Python checks the source hash and recompiles the
changed modules in memory.

Never pushes and never publishes: a delta is for manual pushes only, never the D-412
channel (publish_payload_release.py refuses it).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
RELEASE_TOOLS = ROOT / "deploy" / "robot" / "pinky_pro" / "release"
sys.path.insert(0, str(RELEASE_TOOLS))
from build_payload_release import (  # noqa: E402
    FIXED_MTIME, MANIFEST_FILENAME, seal_release,
)
from signing import (  # noqa: E402
    CHECKSUM_FILENAME, DELTA_MARKER, SIGNATURE_FILENAME, sha256_file, verify_release_files,
)

RELEASE_ID = re.compile(r"\d{4}\.\d{2}\.\d{2}-\d{3}")
REVISION = re.compile(r"[0-9a-f]{40}")
BUILD_INPUT_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
                        ".msg", ".srv", ".action", ".idl"}
BUILD_INPUT_NAMES = {"CMakeLists.txt", "package.xml", "setup.py", "setup.cfg"}
NOT_SHIPPED_TOPS = {"docs", "tools", "test", ".github", ".claude"}
GENERATED = {"install/.rosy-release", "source-revision.txt", "source-ref.txt"}


class DeltaError(Exception):
    pass


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout


def not_shipped(path: str, extra: list[str]) -> bool:
    parts = PurePosixPath(path).parts
    return (parts[0] in NOT_SHIPPED_TOPS or path.endswith(".md")
            or any(part in ("test", "tests") for part in parts[:-1])
            or any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in extra))


def changed_paths(base_rev: str, rev: str) -> list[tuple[str, str]]:
    out = git("diff", "--name-status", "--no-renames", "-z", base_rev, rev).decode("utf-8")
    fields = out.split("\0")[:-1]
    return [(fields[i], fields[i + 1]) for i in range(0, len(fields), 2)]


def plan_delta(base_files: dict[str, str], changes: list[tuple[str, str]], blob,
               extra_not_shipped: list[str], twins=lambda path: 1) -> tuple[dict[str, bytes], list[str]]:
    """{payload path: new bytes} for every shipped copy, and the ignored paths.

    ``base_files`` is the base manifest {path: sha256}; ``blob(side, path)`` returns
    the file's bytes at the base ('old') or new ('new') revision; ``twins(path)``
    counts the source files at the base revision with the same name and content.
    A payload file is a copy of the changed source when it has the same name and
    old content. When other sources share both (an empty __init__.py), the last
    two path parts must match too, so their copies are not overwritten.
    """
    by_digest: dict[str, list[str]] = {}
    for path, digest in base_files.items():
        by_digest.setdefault(digest, []).append(path)
    replace: dict[str, bytes] = {}
    ignored: list[str] = []
    refusals: list[str] = []
    for status, path in changes:
        name = PurePosixPath(path)
        if name.name in BUILD_INPUT_NAMES or name.suffix in BUILD_INPUT_SUFFIXES:
            if not_shipped(path, extra_not_shipped):
                ignored.append(path)
            else:
                refusals.append(f"{path}: build input ({status}); needs a full build")
            continue
        targets = []
        if status == "M":
            old = hashlib.sha256(blob("old", path)).hexdigest()
            targets = [p for p in by_digest.get(old, []) if PurePosixPath(p).name == name.name]
            if twins(path) > 1:
                targets = [p for p in targets if PurePosixPath(p).parts[-2:] == name.parts[-2:]]
        if targets:
            new = blob("new", path)
            for target in targets:
                if target in GENERATED:
                    refusals.append(f"{path}: maps to generated {target}")
                replace[target] = new
        elif not_shipped(path, extra_not_shipped):
            ignored.append(path)
        elif status == "M":
            refusals.append(f"{path}: no verbatim copy in the payload; needs a full build "
                            "(or --not-shipped if it never reaches the robot)")
        else:
            refusals.append(f"{path}: {'added' if status == 'A' else 'deleted' if status == 'D' else status}"
                            " file; needs a full build (or --not-shipped)")
    if refusals:
        raise DeltaError("delta refused:\n  " + "\n  ".join(refusals))
    if not replace:
        raise DeltaError("nothing shipped changed between the base and this revision")
    return replace, ignored


def read_modes(tarball: Path) -> dict[str, int]:
    with tarfile.open(tarball, "r:gz") as bundle:
        return {m.name: m.mode for m in bundle.getmembers() if m.isreg()}


def pack_delta(release_dir: Path, members: list[str], modes: dict[str, int], marker: bytes, out: Path) -> None:
    import gzip
    import io
    temporary = out.with_name(f".{out.name}.tmp")
    with temporary.open("wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        directories = sorted({str(p) for m in members for p in PurePosixPath(m).parents if str(p) != "."})
        for name in directories:
            info = tarfile.TarInfo(name)
            info.type, info.mode, info.mtime, info.uname, info.gname = tarfile.DIRTYPE, 0o755, FIXED_MTIME, "root", "root"
            tar.addfile(info)
        for name in sorted(members):
            path = release_dir / name
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.uname, info.gname = path.stat().st_size, FIXED_MTIME, "root", "root"
            info.mode = 0o755 if modes.get(name, 0o644) & 0o111 else 0o644
            with path.open("rb") as handle:
                tar.addfile(info, handle)
        info = tarfile.TarInfo(DELTA_MARKER)
        info.size, info.mtime, info.mode, info.uname, info.gname = len(marker), FIXED_MTIME, 0o644, "root", "root"
        tar.addfile(info, io.BytesIO(marker))
    os.replace(temporary, out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-dir", type=Path, required=True, help="signed base release directory (<out>/x/<base>)")
    parser.add_argument("--base-tarball", type=Path, required=True, help="the base's signed tarball (file modes)")
    parser.add_argument("--release-id", required=True, help="new YYYY.MM.DD-NNN, never used before")
    parser.add_argument("--revision", default="HEAD", help="commit to ship (default HEAD)")
    parser.add_argument("--source-ref", default="", help="ref the revision came from (default: current branch)")
    parser.add_argument("--not-shipped", action="append", default=[], help="path prefix that never reaches a robot")
    parser.add_argument("--out-dir", type=Path, help=r"default X:\DevTemp\rosy-release-<id>")
    parser.add_argument("--key-name", default="rosy-release-2026-01")
    args = parser.parse_args(argv)
    started = time.monotonic()
    try:
        if not RELEASE_ID.fullmatch(args.release_id):
            raise DeltaError("--release-id must be YYYY.MM.DD-NNN")
        public_key = RELEASE_TOOLS / "public-keys" / f"{args.key_name}.pem"
        local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        private_key = local_appdata / "Rosy" / "signing" / f"{args.key_name}.private.pem"
        base = args.base_dir.resolve(strict=True)
        rejections = verify_release_files(base, public_key)
        if rejections:
            raise DeltaError(f"base release does not verify: {rejections[0]}")
        base_manifest = json.loads((base / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        base_id = base_manifest["release_id"]
        if args.release_id == base_id:
            raise DeltaError("the delta needs a new release id")
        base_rev = (base / "source-revision.txt").read_text(encoding="utf-8").strip()
        rev = git("rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
        if not (REVISION.fullmatch(base_rev) and REVISION.fullmatch(rev)):
            raise DeltaError("base or new revision is not a full commit")
        source_ref = args.source_ref or git("rev-parse", "--abbrev-ref", "HEAD").decode().strip()
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", source_ref):
            raise DeltaError(f"source ref {source_ref!r} is not a plain ref name")
        base_files = {e["path"]: e["sha256"] for e in base_manifest["files"]}

        def blob(side: str, path: str) -> bytes:
            return git("show", f"{base_rev if side == 'old' else rev}:{path}")

        same: dict[tuple[str, str], int] = {}
        source_blob: dict[str, str] = {}
        for entry in git("ls-tree", "-r", "-z", base_rev).decode("utf-8").split("\0")[:-1]:
            meta, path = entry.split("\t", 1)
            key = (meta.split()[2], PurePosixPath(path).name)
            source_blob[path] = key[0]
            same[key] = same.get(key, 0) + 1

        def twins(path: str) -> int:
            return same.get((source_blob.get(path, ""), PurePosixPath(path).name), 0)

        replace, ignored = plan_delta(base_files, changed_paths(base_rev, rev), blob, args.not_shipped, twins)

        out_dir = args.out_dir or Path("X:/DevTemp") / f"rosy-release-{args.release_id}"
        release_dir = out_dir / "x" / args.release_id
        tarball = out_dir / f"{args.release_id}.tar.gz"
        if release_dir.exists() or tarball.exists():
            raise DeltaError(f"{release_dir} or {tarball} already exists; use a new release id")
        partial = out_dir / "x" / f".{args.release_id}.partial"
        shutil.rmtree(partial, ignore_errors=True)
        shutil.copytree(base, partial, ignore=shutil.ignore_patterns(MANIFEST_FILENAME, CHECKSUM_FILENAME,
                                                                      SIGNATURE_FILENAME))
        for path, content in replace.items():
            (partial / path).write_bytes(content)
        (partial / "install" / ".rosy-release").write_text(args.release_id + "\n", encoding="utf-8", newline="\n")
        (partial / "source-revision.txt").write_text(rev + "\n", encoding="utf-8", newline="\n")
        (partial / "source-ref.txt").write_text(source_ref + "\n", encoding="utf-8", newline="\n")
        seal_release(partial, args.release_id, signing_key_id=args.key_name)
        signed = subprocess.run([sys.executable, str(RELEASE_TOOLS / "sign_image_release.py"), str(partial),
                                 "--private-key", str(private_key), "--public-key", str(public_key)],
                                cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"})
        if signed.returncode:
            raise DeltaError("signing failed")
        rejections = verify_release_files(partial, public_key)
        if rejections:
            raise DeltaError(f"rebuilt release does not verify: {rejections[0]}")
        os.replace(partial, release_dir)
        members = sorted({*replace, *GENERATED, MANIFEST_FILENAME, CHECKSUM_FILENAME, SIGNATURE_FILENAME})
        marker = f"{base_id}\n{sha256_file(base / CHECKSUM_FILENAME)}\n".encode()
        pack_delta(release_dir, members, read_modes(args.base_tarball), marker, tarball)
    except (DeltaError, OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"delta {args.release_id} on base {base_id}: {len(replace)} payload files from "
          f"{rev[:12]} ({source_ref}); ignored (not shipped): {len(ignored)}")
    for path in sorted(replace):
        print(f"  {path}")
    print(f"signed delta tarball: {tarball} ({tarball.stat().st_size} bytes, {time.monotonic() - started:.1f}s)")
    print("Not pushed. The robots must hold the base release "
          f"{base_id}. From the repo root, dry run first:")
    print(rf"deploy\robot\pinky_pro\rosy-release-push-many.ps1 -Robot <ip-a>,<ip-b> -Tarball '{tarball}' -PrintCommands")
    return 0


if __name__ == "__main__":
    sys.exit(main())
