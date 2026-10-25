"""First-boot entrypoints must import from their installed place, /opt/rosy/first-boot.

customize-rootfs.sh runs each one with --help inside the image. Host tests import
them from the deep checkout, so a module-level path such as parents[5] (only four
parents exist at /opt/rosy/first-boot) passed here and failed the image build.
"""

import subprocess
import shutil
import sys
from pathlib import Path

import pytest

FIRST_BOOT = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/image/first-boot"
INSTALLED = "/opt/rosy/first-boot/"
RUN_AS_INSTALLED = (
    "import sys; path, name = sys.argv[1], sys.argv[2]; sys.argv = [name, '--help']; "
    "code = compile(open(path, encoding='utf-8').read(), name, 'exec'); "
    "exec(code, {'__name__': '__main__', '__file__': name})"
)


@pytest.mark.parametrize("script", sorted(p.name for p in FIRST_BOOT.glob("*.py") if p.name != "rosy-first-boot.py"))
def test_entrypoint_runs_from_the_installed_path(script):
    result = subprocess.run(
        [sys.executable, "-c", RUN_AS_INSTALLED, str(FIRST_BOOT / script), INSTALLED + script],
        capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-2000:]


def test_firstboot_imports_only_the_staged_image_helpers(tmp_path):
    """The image must run without the checkout's deploy package on sys.path."""
    prefix = tmp_path / "opt/rosy"
    shutil.copytree(FIRST_BOOT, prefix / "first-boot")
    shutil.copytree(FIRST_BOOT.parents[1] / "native", prefix / "native-runtime")
    shutil.copytree(FIRST_BOOT.parents[1] / "sd", prefix / "deploy/sd")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(prefix / "first-boot/rosy-first-boot.py"), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "--hardware-serial" in result.stdout


def test_installed_rebind_refuses_ab_without_checkout_imports_or_state_moves(tmp_path):
    prefix = tmp_path / "opt/rosy"
    shutil.copytree(FIRST_BOOT, prefix / "first-boot")
    shutil.copytree(FIRST_BOOT.parents[1] / "native", prefix / "native-runtime")
    shutil.copytree(FIRST_BOOT.parents[1] / "sd", prefix / "deploy/sd")
    root = tmp_path / "device"
    (root / "etc/rosy").mkdir(parents=True)
    (root / "etc/rosy/os-slot.json").write_text("{}")
    code = """
import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
root = Path(sys.argv[2])
try:
    module['quarantine_previous'](root, root / 'missing-bundle.json', '10000000abcdef02')
except ValueError as exc:
    assert 'fresh provisioned card' in str(exc), str(exc)
else:
    raise AssertionError('A/B registration was allowed')
assert not (root / 'var').exists()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code,
         str(prefix / "first-boot/rosy-rebind-board.py"), str(root)],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
