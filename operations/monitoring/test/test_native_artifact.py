"""Use the native parser without installing or starting any system service."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(not shutil.which('systemd-analyze'), reason='native systemd parser required')
def test_native_service_unit_parses_with_installed_launcher(tmp_path):
    executable = Path(sys.executable).with_name('rosy-monitoring')
    assert executable.is_file() and os.access(executable, os.X_OK), 'the wheel console entry point must be installed'
    source = Path(__file__).resolve().parents[1] / 'deploy/rosy-monitoring.service'
    text = source.read_text(encoding='utf-8')
    installed_path = '/opt/rosy-monitoring/venv/bin/rosy-monitoring'
    assert text.count(installed_path) == 1
    # Relocate only the executable for lab verification; target-host installation is separate.
    unit = tmp_path / source.name
    unit.write_text(text.replace(installed_path, str(executable)), encoding='utf-8')
    result = subprocess.run(['systemd-analyze', 'verify', '--man=no', str(unit)],
                            env={**os.environ, 'LC_ALL': 'C'}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not any(marker in result.stderr for marker in ('Unknown key', 'Unknown lvalue', 'Failed to parse')), result.stderr
