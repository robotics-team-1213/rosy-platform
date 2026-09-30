"""First-boot entrypoints must import from their installed place, /opt/rosy/first-boot.

customize-rootfs.sh runs each one with --help inside the image. Host tests import
them from the deep checkout, so a module-level path such as parents[5] (only four
parents exist at /opt/rosy/first-boot) passed here and failed the image build.
"""

import subprocess
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


@pytest.mark.parametrize("script", sorted(p.name for p in FIRST_BOOT.glob("*.py")))
def test_entrypoint_runs_from_the_installed_path(script):
    result = subprocess.run(
        [sys.executable, "-c", RUN_AS_INSTALLED, str(FIRST_BOOT / script), INSTALLED + script],
        capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-2000:]
