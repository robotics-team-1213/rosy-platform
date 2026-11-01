"""Inspect and verify a signed payload before choosing its publication channel."""

import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile

import signing

NATIVE = Path(__file__).resolve().parents[2] / "deploy/robot/pinky_pro/native"
if str(NATIVE) not in sys.path:
    sys.path.insert(0, str(NATIVE))
from image_layer_boot import catalog_entries

REVISION = re.compile(r"[0-9a-f]{40}")


def _load_prepare():
    spec = importlib.util.spec_from_file_location("prepare_payload_release",
                                                  Path(__file__).with_name("prepare_payload_release.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = _load_prepare()


class PublishError(RuntimeError):
    pass


def _rejections(rejections) -> str:
    return "; ".join(f"{r.code} {r.field}: {r.detail}" for r in rejections)


def read_tarball_identity(tarball: Path) -> tuple[str, str]:
    """(release_id from manifest.json, source_revision from source-revision.txt)."""
    found: dict[str, bytes] = {}
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            name = str(PurePosixPath(member.name)).removeprefix("./")
            if name in ("manifest.json", "source-revision.txt", "source-ref.txt") and member.isreg():
                found[name] = tar.extractfile(member).read()
            if name == ".rosy-delta-base":
                # D-553 addendum 3: deltas are manual pushes only; a robot that
                # auto-updates may not hold the delta's base release.
                raise PublishError(f"{tarball.name} is a delta payload; publish only full releases")
    if "source-ref.txt" in found and found["source-ref.txt"].decode("ascii", "replace").strip() != "main":
        # D-553 addendum 3: branch builds are bench pushes, never the D-412 channel.
        raise PublishError(f"{tarball.name} was built from "
                           f"{found['source-ref.txt'].decode('ascii', 'replace').strip()!r}, not main")
    for name in ("manifest.json", "source-revision.txt"):
        if name not in found:
            raise PublishError(f"{tarball.name} has no top-level {name}")
    release_id = json.loads(found["manifest.json"].decode("utf-8")).get("release_id")
    if release_id != tarball.name.removesuffix(".tar.gz"):
        raise PublishError(f"manifest.json release_id is {release_id!r}, not the tarball name {tarball.name}")
    revision = found["source-revision.txt"].decode("ascii").strip()
    if not REVISION.fullmatch(revision):
        raise PublishError(f"source-revision.txt is not a full Git commit: {revision!r}")
    return release_id, revision


def verify_tarball(tarball: Path, public_key: Path, work_dir: Path) -> bool:
    """Verify every signed file, then classify the fixed boot catalog without executing payload code."""
    work_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".verify-", dir=work_dir))
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    raise PublishError(f"{tarball.name} has a link member {member.name!r}")
            tar.extractall(temporary, filter="tar")
        rejections = signing.verify_release_files(temporary, public_key)
        if rejections:
            raise PublishError(f"{tarball.name} release signature does not verify: {_rejections(rejections)}")
        return bool(catalog_entries(temporary / "deploy/robot/native"))
    finally:
        prepare._remove_tree(temporary)


def build_rollout(release_id: str, tarball_sha256: str, source_revision: str, published_at: str,
                  canary: str, wave_delay_s: int) -> dict:
    return {"schema": 1, "release_id": release_id, "tarball": f"{release_id}.tar.gz",
            "tarball_sha256": tarball_sha256, "source_revision": source_revision,
            "published_at": published_at, "canary": [canary], "canary_ok": False,
            "wave_delay_s": wave_delay_s, "withdrawn": False, "reason": ""}


def rollout_bytes(rollout: dict) -> bytes:
    """The exact bytes that are signed: sorted keys, LF, UTF-8, no BOM."""
    return (json.dumps(rollout, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def verify_transport_delta(full: Path, delta: Path, binding: dict, public_key: Path, work_dir: Path) -> None:
    """Authenticate the optional transport against the already verified full target."""
    if (binding.get("full_tarball_sha256") != signing.sha256_file(full)
            or binding.get("sha256") != signing.sha256_file(delta)
            or binding.get("size") != delta.stat().st_size or binding.get("tarball") != delta.name):
        raise PublishError("delta transport bytes differ from the signed full target binding")
    temporary = Path(tempfile.mkdtemp(prefix=".delta-verify-", dir=work_dir))
    try:
        with tarfile.open(delta, "r:gz") as archive:
            names = set()
            for member in archive:
                name = PurePosixPath(member.name).as_posix()
                if not (member.isfile() or member.isdir()) or name in names:
                    raise PublishError("delta archive contains a link or duplicate member")
                names.add(name)
            archive.extractall(temporary, filter="data")
        rejected = signing.verify_delta_files(temporary, public_key)
        if rejected:
            raise PublishError("delta signature does not verify: " + _rejections(rejected))
        marker = f"{binding['base_release_id']}\n{binding['base_sums_sha256']}\n".encode("ascii")
        if (temporary / signing.DELTA_MARKER).read_bytes() != marker:
            raise PublishError("delta marker differs from its rollout binding")
        if signing.sha256_file(temporary / "SHA256SUMS") != binding.get("target_sums_sha256"):
            raise PublishError("delta target checksum identity differs")
        with tarfile.open(full, "r:gz") as archive:
            for name in ("manifest.json", "SHA256SUMS", "SHA256SUMS.sig"):
                if archive.extractfile(name).read() != (temporary / name).read_bytes():
                    raise PublishError("delta metadata differs from signed full target")
    finally:
        prepare._remove_tree(temporary)
