"""Exercise real image cleanup functions with rootless, disposable mount stand-ins."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "deploy/robot/pinky_pro/image"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required")


def _function(source, name):
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.MULTILINE | re.DOTALL)
    assert match, name
    return match.group()


def _bash(tmp_path, script, **env):
    return subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, **env}, timeout=10,
    )


@pytest.mark.parametrize("failure", ["root", "boot", "detach"])
def test_failed_deactivation_preserves_workspace_and_never_detaches_a_mounted_loop(tmp_path, failure):
    source = (IMAGE / "image-workspace.sh").read_text(encoding="utf-8")
    work = tmp_path / "rosy-image.fixture"
    work.mkdir()
    marker = work / "keep-image"
    marker.write_text("must survive failed cleanup")
    functions = "\n".join(_function(source, name) for name in (
        "deactivate_image", "remove_workspace", "cleanup_on_exit",
    ))
    script = functions + r'''
set -eu
WORK_ROOT_REAL="$PWD"
WORK_DIR="$PWD/rosy-image.fixture"
ROSY_IMAGE_ROOT="$WORK_DIR/root"
ROSY_IMAGE_BOOT="$ROSY_IMAGE_ROOT/boot/firmware"
ROOT_MOUNTED=1
BOOT_MOUNTED=1
LOOP_DEVICE=/dev/loop-fixture
OUTPUT_PART="$PWD/output.part"
umount() {
    printf 'umount %s\n' "$*" >> events
    case "$FAILURE:${@: -1}" in
        root:*/root|boot:*/boot/firmware) return 23 ;;
    esac
}
losetup() {
    printf 'detach\n' >> events
    [[ "$FAILURE" != detach ]]
}
trap cleanup_on_exit EXIT
exit 7
'''
    result = _bash(tmp_path, script, FAILURE=failure)

    assert result.returncode == 7, result.stderr
    assert marker.is_file(), "failed unmount/detach must never recursively delete the workspace"
    if failure != "detach":
        assert "detach" not in (tmp_path / "events").read_text()


@pytest.mark.parametrize("failure", ["none", "propagation", "busy"])
def test_chroot_bind_cleanup_removes_children_in_reverse_order_and_propagates_failure(tmp_path, failure):
    source = (IMAGE / "customize-rootfs.sh").read_text(encoding="utf-8")
    start = source.index('mkdir -p "$ROOT/dev/pts"')
    end = source.index("cp --remove-destination /etc/resolv.conf", start)
    bindings = source[start:end]
    script = _function(source, "cleanup") + r'''
set -eu
ROOT="$PWD/root"
MOUNTS=()
ROS_SOURCE_TMP=""
WIRINGPI_TMP=""
WS281X_TMP=""
mount() {
    printf 'mount %s\n' "$*" >> events
    if [[ "$1" == --make-rslave && "$FAILURE" == propagation && "${@: -1}" == */sys ]]; then
        return 23
    fi
}
umount() {
    printf 'umount %s\n' "$*" >> events
    # A nested sysfs mount reproduces the real builder's busy-parent failure.
    if [[ "${@: -1}" == */sys ]]; then
        [[ "$FAILURE" != busy && "$1" == --recursive ]] || return 24
    fi
}
trap cleanup EXIT
''' + bindings
    result = _bash(tmp_path, script, FAILURE=failure)
    events = (tmp_path / "events").read_text().splitlines()

    if failure == "none":
        assert result.returncode == 0, result.stderr
        expected = ["run", "sys", "proc", "dev/pts", "dev"]
        assert [line.removeprefix(f"umount --recursive -- {tmp_path}/root/")
                for line in events if line.startswith("umount ")] == expected
        for target in reversed(expected):
            assert f"mount --make-rslave {tmp_path}/root/{target}" in events
    elif failure == "propagation":
        assert result.returncode == 23, result.stderr
        assert f"umount --recursive -- {tmp_path}/root/sys" in events
        assert not any(line.startswith("mount --bind /run ") for line in events)
    else:
        assert result.returncode != 0, "cleanup failure after successful customization must fail the build"
