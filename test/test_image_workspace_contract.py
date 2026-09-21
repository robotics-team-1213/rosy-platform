"""Fail-closed contracts for the disposable Raspberry Pi image workspace."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
IMAGE_DIR = ROOT / "deploy" / "image"
SCRIPT = IMAGE_DIR / "image-workspace.sh"
BUILD_SCRIPT = IMAGE_DIR / "build-image.sh"


def _bash_is_usable() -> bool:
    try:
        result = subprocess.run(
            ["bash", "-c", "true"], capture_output=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


bash_only = pytest.mark.skipif(not _bash_is_usable(), reason="bash is required")


def _write_tool(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -eu\n{body}\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    shutil.copy(SCRIPT, tmp_path / SCRIPT.name)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    work_root = tmp_path / "work"
    work_root.mkdir()
    (tmp_path / "base.img.xz").write_bytes(b"immutable-base-image")

    _write_tool(fake_bin, "uname", "printf 'aarch64\\n'")
    _write_tool(
        fake_bin,
        "xz",
        'for item in "$@"; do last="$item"; done\ncat -- "$last"',
    )
    _write_tool(fake_bin, "truncate", "printf 'truncate %s\\n' \"$*\" >> events.log")
    _write_tool(
        fake_bin,
        "losetup",
        "printf 'losetup %s\\n' \"$*\" >> events.log\n"
        "if [[ $1 == --find ]]; then printf '/dev/loop-test\\n'; fi",
    )
    _write_tool(
        fake_bin,
        "lsblk",
        "printf 'lsblk %s\\n' \"$*\" >> events.log\n"
        "printf '/dev/loop-test1 1\\n/dev/loop-test2 2\\n'",
    )
    _write_tool(
        fake_bin,
        "blkid",
        "printf 'blkid %s\\n' \"$*\" >> events.log\n"
        "case \"${@: -1}\" in\n"
        "  /dev/loop-test1) printf 'vfat\\n' ;;\n"
        "  /dev/loop-test2) printf 'ext4\\n' ;;\n"
        "  *) exit 2 ;;\n"
        "esac",
    )
    _write_tool(fake_bin, "udevadm", "printf 'udevadm %s\\n' \"$*\" >> events.log")
    _write_tool(fake_bin, "growpart", "printf 'growpart %s\\n' \"$*\" >> events.log")
    _write_tool(fake_bin, "partprobe", "printf 'partprobe %s\\n' \"$*\" >> events.log")
    _write_tool(fake_bin, "resize2fs", "printf 'resize2fs %s\\n' \"$*\" >> events.log")
    _write_tool(
        fake_bin,
        "mount",
        "printf 'mount %s\\n' \"$*\" >> events.log\n"
        "if [[ -f fail-boot-mount && $2 == */boot/firmware ]]; then exit 23; fi",
    )
    _write_tool(fake_bin, "umount", "printf 'umount %s\\n' \"$*\" >> events.log")

    callback = tmp_path / "callback.sh"
    callback.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "printf 'callback\\n' >> events.log\n"
        "printf '%s|%s|%s|%s\\n' \"$ROSY_IMAGE_WORK_DIR\" \"$ROSY_IMAGE_FILE\" "
        "\"$ROSY_IMAGE_ROOT\" \"$ROSY_IMAGE_BOOT\" >> callback-paths.log\n"
        "[[ ! -f fail-callback ]]\n",
        encoding="utf-8",
        newline="\n",
    )
    callback.chmod(0o755)
    return work_root, callback


def _run(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    command = [
        'PATH="$PWD/fake-bin:/usr/bin:/bin"',
        "bash",
        SCRIPT.name,
        "--base-image",
        "base.img.xz",
        "--output-image",
        "result.img",
        "--work-root",
        "work",
        "--expand-mib",
        "64",
        *extra,
        "--",
        "./callback.sh",
    ]
    return subprocess.run(
        ["bash", "-c", " ".join(command)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_workspace_script_and_build_integration_exist():
    assert SCRIPT.is_file()
    source = SCRIPT.read_text(encoding="utf-8")
    build = BUILD_SCRIPT.read_text(encoding="utf-8")

    for command in (
        "xz", "truncate", "losetup", "lsblk", "blkid", "udevadm", "growpart", "partprobe",
        "resize2fs", "mount", "umount",
    ):
        assert f'command -v "$command"' in source
    assert "[[ $EUID -eq 0 ]]" in source
    assert '[[ "$ARCH" == "aarch64" ]]' in source
    assert "image-workspace.sh" in build


def test_boot_mountpoint_is_created_inside_the_mounted_root_filesystem():
    source = SCRIPT.read_text(encoding="utf-8")

    root_mount = source.index('mount "$ROOT_DEVICE" "$ROSY_IMAGE_ROOT"')
    boot_directory = source.index('mkdir -p -- "$ROSY_IMAGE_BOOT"')
    boot_mount = source.index('mount "$BOOT_DEVICE" "$ROSY_IMAGE_BOOT"')
    assert root_mount < boot_directory < boot_mount


@bash_only
def test_workspace_rejects_a_non_native_host_before_mutation(tmp_path):
    work_root, _ = _fixture(tmp_path)
    _write_tool(tmp_path / "fake-bin", "uname", "printf 'x86_64\\n'")

    result = _run(tmp_path)

    assert result.returncode != 0
    assert "native arm64" in result.stderr.lower()
    assert not (tmp_path / "result.img").exists()
    assert not any(work_root.iterdir())


@bash_only
def test_workspace_never_mutates_the_cached_base_and_is_disposable(tmp_path):
    work_root, _ = _fixture(tmp_path)
    base = tmp_path / "base.img.xz"
    before = _sha256(base)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _sha256(base) == before
    assert (tmp_path / "result.img").read_bytes() == base.read_bytes()
    assert not any(work_root.iterdir())


@bash_only
def test_each_run_uses_a_unique_workspace_and_exports_mount_paths(tmp_path):
    _fixture(tmp_path)

    first = _run(tmp_path)
    (tmp_path / "result.img").unlink()
    second = _run(tmp_path)

    assert first.returncode == second.returncode == 0
    rows = (tmp_path / "callback-paths.log").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    first_work, first_image, first_root, first_boot = rows[0].split("|")
    second_work, *_ = rows[1].split("|")
    assert first_work != second_work
    assert first_image.startswith(first_work)
    assert first_root == f"{first_work}/root"
    assert first_boot == f"{first_root}/boot/firmware"


@bash_only
def test_workspace_discovers_pi_partitions_and_cleans_up_in_reverse(tmp_path):
    _fixture(tmp_path)

    result = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    settle = next(i for i, line in enumerate(events) if line == "udevadm settle")
    scan = next(i for i, line in enumerate(events) if line.startswith("lsblk "))
    boot_probe = next(
        i for i, line in enumerate(events)
        if line.startswith("blkid ") and line.endswith("/dev/loop-test1")
    )
    root_probe = next(
        i for i, line in enumerate(events)
        if line.startswith("blkid ") and line.endswith("/dev/loop-test2")
    )
    assert settle < scan < boot_probe < root_probe
    assert any(line.startswith("growpart /dev/loop-test 2") for line in events)
    assert any(line.startswith("resize2fs /dev/loop-test2") for line in events)
    root_mount = next(i for i, line in enumerate(events) if line.startswith("mount /dev/loop-test2 "))
    boot_mount = next(i for i, line in enumerate(events) if line.startswith("mount /dev/loop-test1 "))
    callback = events.index("callback")
    boot_unmount = next(i for i, line in enumerate(events) if "umount" in line and "/boot/firmware" in line)
    root_unmount = next(i for i, line in enumerate(events) if "umount" in line and line.endswith("/root"))
    detach = next(i for i, line in enumerate(events) if line == "losetup --detach /dev/loop-test")
    assert root_mount < boot_mount < callback < boot_unmount < root_unmount < detach


@bash_only
def test_partial_mount_failure_detaches_loop_and_removes_workspace(tmp_path):
    work_root, _ = _fixture(tmp_path)
    (tmp_path / "fail-boot-mount").touch()

    result = _run(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / "result.img").exists()
    assert not any(work_root.iterdir())
    events = (tmp_path / "events.log").read_text(encoding="utf-8").splitlines()
    assert not any("umount" in line and "/boot/firmware" in line for line in events)
    root_unmount = next(i for i, line in enumerate(events) if "umount" in line and line.endswith("/root"))
    detach = next(i for i, line in enumerate(events) if line == "losetup --detach /dev/loop-test")
    assert root_unmount < detach


@bash_only
def test_callback_failure_does_not_publish_a_raw_image(tmp_path):
    work_root, _ = _fixture(tmp_path)
    (tmp_path / "fail-callback").touch()

    result = _run(tmp_path)

    assert result.returncode != 0
    assert not (tmp_path / "result.img").exists()
    assert not any(work_root.iterdir())
