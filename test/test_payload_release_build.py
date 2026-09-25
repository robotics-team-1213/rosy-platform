"""D-225 2.1: payload-only release build, offline signing, and packing."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from build_payload_release import build_release, pack_release
from signing import sign_checksums


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "deploy" / "release" / "build_payload_release.py"
RELEASE_ID = "2026.09.25-001"
REVISION = "b" * 40
IMAGE_RUNTIME = "1" * 64
KEY_ID = "rosy-native-test"


def _keys(tmp_path: Path) -> tuple[Path, Path]:
    private = tmp_path / "keys" / "test.key"
    public = tmp_path / "keys" / f"{KEY_ID}.pem"
    private.parent.mkdir()
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True, capture_output=True,
    )
    return private, public


def _payload_tree(root: Path, release_id: str = RELEASE_ID) -> Path:
    """The shape build-native-payload.sh leaves in --release-root."""
    files = {
        "install/.rosy-release": release_id + "\n",
        "install/setup.bash": "# setup\n",
        "install/lib/core/core_node": "#!/usr/bin/env python3\n",
        "deploy/robot/native/rosy-runtime.target": "[Unit]\nDescription=test\n",
        "deploy/robot/native/native_release.py": "# copy\n",
        "rosy-packages.txt": "core\ninterfaces\n",
        "deb-packages.txt": "ros-jazzy-ros-base\t0.11\n",
        "required-ros-packages.txt": "core\n",
        "source-revision.txt": REVISION + "\n",
        "python-runtime.sha256": IMAGE_RUNTIME + "\n",
        "image-overlay/etc/rosy/defaults.yaml": "image: layer\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return root


def _device(tmp_path: Path, public: Path) -> tuple[Path, Path]:
    device = tmp_path / "device"
    key = device / "etc" / "rosy" / "trusted-release-keys" / public.name
    key.parent.mkdir(parents=True)
    key.write_bytes(public.read_bytes())
    marker = device / "usr" / "local" / "share" / "rosy" / "python-runtime.sha256"
    marker.parent.mkdir(parents=True)
    marker.write_text(IMAGE_RUNTIME + "\n", encoding="utf-8")
    return device, key


def _sign(release: Path, private: Path) -> None:
    sums = (release / "SHA256SUMS").read_bytes()
    (release / "SHA256SUMS.sig").write_text(sign_checksums(sums, private) + "\n", encoding="ascii")


@pytest.fixture
def case(tmp_path: Path):
    from deploy.robot.native.native_release import NativeReleaseManager

    private, public = _keys(tmp_path)
    device, key = _device(tmp_path, public)
    payload = _payload_tree(tmp_path / "payload")
    release = device / "opt" / "rosy" / "releases" / RELEASE_ID
    return NativeReleaseManager, device, key, private, payload, release


def test_built_and_signed_payload_passes_native_verify(case):
    manager_type, device, key, private, payload, release = case

    report = build_release(payload, RELEASE_ID, release, signing_key_id=KEY_ID)
    assert report["ok"] is True and report["signed"] is False
    assert not (release / "SHA256SUMS.sig").exists()
    assert not (release / "image-overlay").exists()
    _sign(release, private)

    manager = manager_type(root=device, public_key=key, runtime=lambda _a: None)
    manifest = manager.verify(RELEASE_ID)
    assert manifest["git_revision"] == REVISION
    assert manager.check_python_runtime(RELEASE_ID) == IMAGE_RUNTIME
    listed = {entry["path"] for entry in manifest["files"]}
    assert "install/lib/core/core_node" in listed
    assert not any(path.startswith("image-overlay/") for path in listed)


def test_unsigned_payload_is_refused(case):
    manager_type, device, key, _private, payload, release = case
    build_release(payload, RELEASE_ID, release, signing_key_id=KEY_ID)

    with pytest.raises(ValueError, match="SIGNATURE_MISSING"):
        manager_type(root=device, public_key=key).verify(RELEASE_ID)


@pytest.mark.parametrize("tamper", ["modify", "add"])
def test_tampered_payload_fails_native_verify(case, tamper):
    manager_type, device, key, private, payload, release = case
    build_release(payload, RELEASE_ID, release, signing_key_id=KEY_ID)
    _sign(release, private)
    if tamper == "modify":
        (release / "install" / "setup.bash").write_text("# evil\n", encoding="utf-8")
        expected = "CHECKSUM_MISMATCH"
    else:
        (release / "install" / "extra.py").write_text("x = 1\n", encoding="utf-8")
        expected = "CHECKSUM_UNLISTED_FILE"

    with pytest.raises(ValueError, match=expected):
        manager_type(root=device, public_key=key).verify(RELEASE_ID)


def test_wrong_signing_key_id_fails_native_verify(case):
    manager_type, device, key, private, payload, release = case
    build_release(payload, RELEASE_ID, release)  # default: production key id
    _sign(release, private)

    with pytest.raises(ValueError, match="NATIVE_MANIFEST_KEY"):
        manager_type(root=device, public_key=key).verify(RELEASE_ID)


def test_build_refuses_incomplete_or_mismatched_payload(tmp_path):
    payload = _payload_tree(tmp_path / "payload")
    with pytest.raises(ValueError, match="PAYLOAD_RELEASE_ID"):
        build_release(payload, "2026.09.25-002", tmp_path / "out-a")
    (payload / "python-runtime.sha256").unlink()
    with pytest.raises(ValueError, match="PAYLOAD_INCOMPLETE"):
        build_release(payload, RELEASE_ID, tmp_path / "out-b")
    assert not (tmp_path / "out-a").exists() and not (tmp_path / "out-b").exists()


def test_build_refuses_existing_release_dir(tmp_path):
    payload = _payload_tree(tmp_path / "payload")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(ValueError, match="RELEASE_DIR_EXISTS"):
        build_release(payload, RELEASE_ID, out)


def _members(tarball: Path) -> list[tarfile.TarInfo]:
    with tarfile.open(tarball, "r:gz") as tar:
        return tar.getmembers()


def test_unsigned_tarball_is_regular_files_and_dirs_only_and_reproducible(tmp_path):
    first = build_release(_payload_tree(tmp_path / "p1"), RELEASE_ID, tmp_path / "r1")
    second = build_release(_payload_tree(tmp_path / "p2"), RELEASE_ID, tmp_path / "r2")
    a = pack_release(Path(first["release_dir"]), tmp_path / "a.tar.gz", allow_unsigned=True)
    b = pack_release(Path(second["release_dir"]), tmp_path / "b.tar.gz", allow_unsigned=True)

    assert (tmp_path / "a.tar.gz").read_bytes() == (tmp_path / "b.tar.gz").read_bytes()
    assert a["sha256"] == b["sha256"] and a["signed"] is False
    members = _members(tmp_path / "a.tar.gz")
    names = [member.name for member in members]
    assert names == sorted(names)
    assert "manifest.json" in names and "SHA256SUMS" in names
    assert not any(name.startswith(("/", "./", "image-overlay")) for name in names)
    for member in members:
        assert member.isreg() or member.isdir()
        assert (member.uid, member.gid, member.mtime) == (0, 0, 946684800)


def test_pack_refuses_unsigned_release_by_default(tmp_path):
    report = build_release(_payload_tree(tmp_path / "p"), RELEASE_ID, tmp_path / "r")
    with pytest.raises(ValueError, match="SIGNATURE_MISSING"):
        pack_release(Path(report["release_dir"]), tmp_path / "x.tar.gz")
    assert not (tmp_path / "x.tar.gz").exists()


# --- D-225 2.1 offline signing + pack (sign_image_release.py fits unchanged) ---

SIGNER = ROOT / "deploy" / "release" / "sign_image_release.py"


def _run(*args: object) -> dict:
    completed = subprocess.run(
        [sys.executable, *(str(arg) for arg in args)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    report["_returncode"] = completed.returncode
    return report


def test_offline_signer_then_pack_yields_a_tarball_native_verify_accepts(case, tmp_path):
    manager_type, device, key, private, payload, _release = case
    staging = tmp_path / "staging" / RELEASE_ID

    built = _run(BUILDER, "build", "--payload-root", payload, "--release-id", RELEASE_ID,
                 "--out", staging, "--signing-key-id", KEY_ID)
    assert built["ok"] is True, built
    signed = _run(SIGNER, staging, "--private-key", private, "--public-key", key)
    assert signed["ok"] is True, signed
    tarball = tmp_path / f"{RELEASE_ID}.tar.gz"
    packed = _run(BUILDER, "pack", "--release-dir", staging, "--out", tarball, "--public-key", key)
    assert packed["ok"] is True and packed["signed"] is True, packed

    members = _members(tarball)
    assert "SHA256SUMS.sig" in [member.name for member in members]
    assert all(member.isreg() or member.isdir() for member in members)

    # What rosy-release-unpack.sh does: extract the members into releases/<id>.
    target = device / "opt" / "rosy" / "releases" / RELEASE_ID
    target.mkdir(parents=True)
    with tarfile.open(tarball, "r:gz") as tar:
        tar.extractall(target, filter="data")
    manifest = manager_type(root=device, public_key=key).verify(RELEASE_ID)
    assert manifest["release_id"] == RELEASE_ID

    again = _run(BUILDER, "pack", "--release-dir", staging, "--out", tmp_path / "again.tar.gz")
    assert again["sha256"] == packed["sha256"]


def test_pack_refuses_a_release_whose_signature_does_not_verify(case, tmp_path):
    _manager_type, _device, key, private, payload, _release = case
    staging = tmp_path / "staging" / RELEASE_ID
    build_release(payload, RELEASE_ID, staging, signing_key_id=KEY_ID)
    _sign(staging, private)
    (staging / "rosy-packages.txt").write_text("core\nevil\n", encoding="utf-8")

    report = _run(BUILDER, "pack", "--release-dir", staging,
                  "--out", tmp_path / "bad.tar.gz", "--public-key", key)
    assert report["ok"] is False and report["_returncode"] == 2
    assert "CHECKSUM_MISMATCH" in report["error"]
    assert not (tmp_path / "bad.tar.gz").exists()


def test_offline_signer_refuses_a_payload_changed_after_build(case, tmp_path):
    _manager_type, _device, key, private, payload, _release = case
    staging = tmp_path / "staging" / RELEASE_ID
    build_release(payload, RELEASE_ID, staging, signing_key_id=KEY_ID)
    (staging / "install" / "late.py").write_text("x = 1\n", encoding="utf-8")

    report = _run(SIGNER, staging, "--private-key", private, "--public-key", key)
    assert report["ok"] is False
    assert "CHECKSUM_UNLISTED_FILE" in report["error"]
    assert not (staging / "SHA256SUMS.sig").exists()


def _with_exec_bit(source: Path, out: Path, name: str) -> None:
    """Rewrite a tarball with ``name`` at 0755, as a Linux build would pack it."""
    with tarfile.open(source, "r:gz") as src, tarfile.open(out, "w:gz") as dst:
        for member in src.getmembers():
            data = src.extractfile(member) if member.isreg() else None
            if member.name == name:
                member.mode = 0o755
            dst.addfile(member, data)


def test_repack_after_signing_keeps_exec_bits_from_the_unsigned_linux_tarball(case, tmp_path):
    _manager_type, _device, key, private, payload, _release = case
    staging = tmp_path / "staging" / RELEASE_ID
    build_release(payload, RELEASE_ID, staging, signing_key_id=KEY_ID)
    plain = tmp_path / "plain.tar.gz"
    pack_release(staging, plain, allow_unsigned=True)
    unsigned = tmp_path / "unsigned.tar.gz"
    _with_exec_bit(plain, unsigned, "install/lib/core/core_node")
    _sign(staging, private)

    signed = tmp_path / "signed.tar.gz"
    report = _run(BUILDER, "pack", "--release-dir", staging, "--out", signed,
                  "--public-key", key, "--modes-from", unsigned)

    assert report["ok"] is True, report
    modes = {member.name: member.mode for member in _members(signed)}
    assert modes["install/lib/core/core_node"] == 0o755
    assert modes["install/setup.bash"] == 0o644
    assert modes["SHA256SUMS.sig"] == 0o644


def test_repack_refuses_when_members_differ_from_the_unsigned_tarball(case, tmp_path):
    _manager_type, _device, _key, _private, payload, _release = case
    staging = tmp_path / "staging" / RELEASE_ID
    build_release(payload, RELEASE_ID, staging, signing_key_id=KEY_ID)
    unsigned = tmp_path / "unsigned.tar.gz"
    pack_release(staging, unsigned, allow_unsigned=True)
    (staging / "install" / "late.py").write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="PACK_MODES_MISMATCH"):
        pack_release(staging, tmp_path / "x.tar.gz", allow_unsigned=True, modes_from=unsigned)
