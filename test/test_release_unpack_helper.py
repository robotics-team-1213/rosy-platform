"""Bash-executed tests for deploy/robot/rosy-release-unpack.sh (D-225).

rosy-release-push.ps1 scp's this helper to the robot and runs it under
`sudo -n`; it is the only thing that ever writes into /opt/rosy/releases on
the device side of a push. These tests run the real script (not just grep its
text) against a scratch "releases" directory under tmp_path, never /opt,
covering: a normal unpack, three kinds of hostile tarball entries (absolute
path, ".." traversal, symlink) that must be refused before anything is
written, the same-id-same-content and same-id-different-content outcomes,
and that a payload file's owner/mode is normalized regardless of what the
tarball's header claimed.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "robot" / "rosy-release-unpack.sh"
BASH = shutil.which("bash")
TAR = shutil.which("tar")
SHA256SUM = shutil.which("sha256sum")

pytestmark = pytest.mark.skipif(
    BASH is None or TAR is None or SHA256SUM is None,
    reason="bash, tar and sha256sum are required",
)


def _posix(path) -> str:
    """"X:\\Devtemp\\foo" -> "/x/Devtemp/foo": the MSYS/Git-Bash path form.

    tar (this bash's own, MSYS-linked) reads an archive path starting with a
    drive letter as a "host:path" remote spec and tries to open an rsh
    connection -- the same ambiguity rosy-release-push.ps1's Invoke-Tar works
    around. On the robot this script only ever sees plain POSIX paths; only
    this Windows-hosted test needs the conversion, done once here rather than
    inside the product script.
    """
    text = str(path).replace("\\", "/")
    if len(text) >= 2 and text[1] == ":":
        text = f"/{text[0].lower()}{text[2:]}"
    return text


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, _posix(SCRIPT), *[_posix(a) for a in args]],
                           capture_output=True, text=True, timeout=30)


def _sha256sums(directory: Path) -> None:
    files = sorted(p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file())
    subprocess.run([SHA256SUM, *files], cwd=directory,
                    stdout=(directory / "SHA256SUMS").open("w"), check=True)


def _pack(directory: Path, archive: Path) -> None:
    # An archive path starting with a drive letter reads as a "host:path"
    # remote spec to GNU tar; keep the -f argument a bare relative filename.
    subprocess.run([TAR, "-czf", archive.name, "-C", str(directory), "."],
                    check=True, cwd=archive.parent)


@pytest.fixture
def releases(tmp_path: Path) -> Path:
    path = tmp_path / "releases"
    path.mkdir()
    return path


def test_a_normal_release_is_unpacked_and_the_tarball_is_removed(tmp_path, releases):
    content = tmp_path / "content"
    (content / "install").mkdir(parents=True)
    (content / "install" / ".rosy-release").write_text("2026.01.01-001", encoding="utf-8")
    _sha256sums(content)
    archive = tmp_path / "pack.tar.gz"
    _pack(content, archive)

    completed = _run("2026.01.01-001", archive, releases)

    assert completed.returncode == 0, completed.stderr
    assert "unpacked 2026.01.01-001" in completed.stdout
    assert not archive.exists()
    target = releases / "2026.01.01-001"
    assert (target / "install" / ".rosy-release").read_text(encoding="utf-8") == "2026.01.01-001"
    assert not any(p.name.startswith(".tmp-") for p in releases.iterdir())


def _filesystem_honors_posix_permission_bits(tmp_path: Path) -> bool:
    # Git-Bash's own chmod is a no-op for these bits on a plain NTFS mount (no
    # WSL): probed here, once, rather than assumed, since this host is NTFS.
    probe = tmp_path / "_perm_probe"
    probe.write_text("x", encoding="utf-8")
    probe.chmod(0o666)
    before = probe.stat().st_mode & 0o777
    probe.chmod(0o600)
    after = probe.stat().st_mode & 0o777
    probe.unlink()
    return before == 0o666 and after == 0o600


@pytest.mark.skipif(
    not _filesystem_honors_posix_permission_bits(Path(tempfile.gettempdir())),
    reason="this filesystem does not honor POSIX permission bits (no WSL/POSIX mount)",
)
def test_setuid_and_world_writable_bits_do_not_survive_the_tarball(tmp_path, releases):
    # The tarball's own header claims setuid + world-writable directly (via
    # tarfile), rather than through a real chmod() on the source file: this
    # Windows filesystem cannot represent those bits on a source file either,
    # so a real chmod() would silently fail to set up the scenario at all.
    payload = b"hello"
    sums = f"{hashlib.sha256(payload).hexdigest()}  file1\n".encode("ascii")
    archive = tmp_path / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        file_info = tarfile.TarInfo(name="file1")
        file_info.size = len(payload)
        file_info.mode = 0o4777
        tar.addfile(file_info, fileobj=io.BytesIO(payload))
        sums_info = tarfile.TarInfo(name="SHA256SUMS")
        sums_info.size = len(sums)
        tar.addfile(sums_info, fileobj=io.BytesIO(sums))

    completed = _run("2026.01.02-001", archive, releases)

    assert completed.returncode == 0, completed.stderr
    mode = (releases / "2026.01.02-001" / "file1").stat().st_mode & 0o7777
    assert mode & 0o4000 == 0, "setuid bit survived the unpack"
    assert mode & 0o022 == 0, "group/other write bits survived the unpack"


def test_an_absolute_path_entry_is_refused_before_writing_anything(tmp_path, releases):
    archive = tmp_path / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="/etc/passwd")
        info.size = 0
        tar.addfile(info)

    completed = _run("2026.01.03-001", archive, releases)

    assert completed.returncode != 0
    assert "TARBALL_ENTRY_UNSAFE" in completed.stderr
    assert "absolute path" in completed.stderr
    assert not (releases / "2026.01.03-001").exists()
    assert not any(p.name.startswith(".tmp-") for p in releases.iterdir())


def test_a_path_traversal_entry_is_refused_before_writing_anything(tmp_path, releases):
    archive = tmp_path / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escaped/evil")
        info.size = 0
        tar.addfile(info)

    completed = _run("2026.01.04-001", archive, releases)

    assert completed.returncode != 0
    assert "TARBALL_ENTRY_UNSAFE" in completed.stderr
    assert "traversal" in completed.stderr
    assert not (releases / "2026.01.04-001").exists()


def test_a_symlink_entry_is_refused_before_writing_anything(tmp_path, releases):
    archive = tmp_path / "pack.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="link1")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)

    completed = _run("2026.01.05-001", archive, releases)

    assert completed.returncode != 0
    assert "TARBALL_ENTRY_UNSAFE" in completed.stderr
    assert "symlink" in completed.stderr
    assert not (releases / "2026.01.05-001").exists()


def test_the_same_id_with_matching_content_is_a_safe_no_op(tmp_path, releases):
    content = tmp_path / "content"
    content.mkdir()
    (content / "file1").write_text("hello", encoding="utf-8")
    _sha256sums(content)
    first = tmp_path / "pack1.tar.gz"
    _pack(content, first)
    assert _run("2026.01.06-001", first, releases).returncode == 0

    second = tmp_path / "pack2.tar.gz"
    _pack(content, second)
    completed = _run("2026.01.06-001", second, releases)

    assert completed.returncode == 0, completed.stderr
    assert "already present with matching content" in completed.stderr
    assert not second.exists()


def test_the_same_id_with_different_content_is_refused(tmp_path, releases):
    original = tmp_path / "original"
    original.mkdir()
    (original / "file1").write_text("hello", encoding="utf-8")
    _sha256sums(original)
    first = tmp_path / "pack1.tar.gz"
    _pack(original, first)
    assert _run("2026.01.07-001", first, releases).returncode == 0

    changed = tmp_path / "changed"
    changed.mkdir()
    (changed / "file1").write_text("different", encoding="utf-8")
    _sha256sums(changed)
    second = tmp_path / "pack2.tar.gz"
    _pack(changed, second)
    completed = _run("2026.01.07-001", second, releases)

    assert completed.returncode != 0
    assert "RELEASE_CONFLICT" in completed.stderr
    # the release already on disk from the first push must be untouched.
    assert (releases / "2026.01.07-001" / "file1").read_text(encoding="utf-8") == "hello"


def test_a_release_whose_files_no_longer_match_its_own_checksums_is_reported_damaged(tmp_path, releases):
    content = tmp_path / "content"
    content.mkdir()
    (content / "file1").write_text("hello", encoding="utf-8")
    _sha256sums(content)
    archive = tmp_path / "pack.tar.gz"
    _pack(content, archive)
    assert _run("2026.01.08-001", archive, releases).returncode == 0
    (releases / "2026.01.08-001" / "file1").write_text("corrupted-on-disk", encoding="utf-8")

    second = tmp_path / "pack2.tar.gz"
    _pack(content, second)
    completed = _run("2026.01.08-001", second, releases)

    assert completed.returncode != 0
    assert "RELEASE_DAMAGED" in completed.stderr
    assert "repair hint" in completed.stderr


def test_a_stale_tmp_directory_from_a_prior_run_is_cleared_at_start(tmp_path, releases):
    stale = releases / ".tmp-2026.01.09-001-99999"
    stale.mkdir()
    (stale / "leftover").write_text("x", encoding="utf-8")

    content = tmp_path / "content"
    content.mkdir()
    (content / "file1").write_text("hello", encoding="utf-8")
    _sha256sums(content)
    archive = tmp_path / "pack.tar.gz"
    _pack(content, archive)

    completed = _run("2026.01.09-001", archive, releases)

    assert completed.returncode == 0, completed.stderr
    assert not stale.exists()
