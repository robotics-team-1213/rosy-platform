"""Fake shell hosts must not read the operator host's reboot units."""
import os
from pathlib import Path
import shutil
import sys

import pytest

import test_remote_pytest as remote_tests
from test_remote_test_tools import native_stage, prepare_installer


pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"), reason="POSIX shell fixtures"
)


def assert_no_operator_units(tmp_path, env):
    command = remote_tests._sh("command -v systemctl", env)
    assert command.returncode == 0
    assert Path(os.fsdecode(command.stdout).strip()).is_relative_to(tmp_path)
    timer = remote_tests._sh(
        "systemctl show -P NextElapseUSecRealtime rosy-nightly-reboot.timer", env
    )
    assert timer.returncode != 0 and timer.stdout == b""


def test_fake_job_host_does_not_resolve_operator_units(tmp_path):
    _, env = remote_tests._job_env(tmp_path, "exit 0\n")
    assert_no_operator_units(tmp_path, env)


def test_fake_installer_host_does_not_resolve_operator_units(tmp_path, native_stage):
    root, _, fakebin = native_stage
    assert_no_operator_units(tmp_path, prepare_installer(root, fakebin, "valid"))


def test_busy_marker_probe_ignores_the_operator_reboot_schedule(tmp_path, monkeypatch):
    operator = tmp_path / "operator"
    operator.mkdir()
    control = operator / "systemctl"
    control.write_text(
        '#!/bin/sh\nif [ "$1" = show ]; then date -d "+60 seconds"; fi\nexit 0\n'
    )
    control.chmod(0o755)
    monkeypatch.setenv("PATH", str(operator) + os.pathsep + os.environ["PATH"])
    remote_tests.test_probe_script_busy_marker_needs_a_live_expiry_or_this_boot(tmp_path)
