"""D-225 2.1: payload-only release build, offline signing, and packing."""

from __future__ import annotations

from pathlib import Path
import subprocess
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
