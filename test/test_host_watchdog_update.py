"""Exercise signed watchdog activation using a disposable key and filesystem."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from deploy.hosts.common import watchdog_update
from deploy.hosts.common.test_rosy_ssh_watchdog import SCRIPT as BASELINE_SCRIPT
from deploy.hosts.common.test_rosy_ssh_watchdog import run as run_watchdog
from deploy.hosts.common.watchdog_update import build_asset, install_asset

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux system watchdog executable")
SCRIPT = b"#!/usr/bin/env bash\nprintf 'healthy\\n'\n"


def test_systemd_recognizes_the_baseline_watchdog_condition():
    analyze = shutil.which("systemd-analyze")
    if not analyze:
        pytest.skip("systemd-analyze is not installed")
    unit = Path(__file__).resolve().parents[1] / "deploy/hosts/common/host-state/rosy-watchdog-update.service"
    condition, = (line for line in unit.read_text().splitlines() if line.startswith("Condition") and
                  line.endswith("=/usr/local/sbin/rosy-ssh-watchdog"))
    directive = condition.split("=", 1)[0]
    result = subprocess.run([analyze, "condition", f"{directive}={sys.executable}"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def keys(tmp_path):
    private, public = tmp_path / "private.pem", tmp_path / "public.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "Ed25519", "-out", private], check=True)
    subprocess.run(["openssl", "pkey", "-in", private, "-pubout", "-out", public], check=True)
    return private, public


def test_only_a_new_signed_sequence_replaces_executable(keys, tmp_path):
    private, public = keys
    active = tmp_path / "active"
    config = tmp_path / "rosy-ssh-watchdog"
    config.write_text("MAX_REBOOTS=0\n")
    current = build_asset(private, 2, SCRIPT)
    assert install_asset(current, public, active) == "installed 2"
    assert subprocess.check_output([active]) == b"healthy\n"
    baseline = active.read_bytes()
    assert install_asset(current, public, active) == "already installed 2"
    assert install_asset(build_asset(private, 1, SCRIPT), public, active) == "ignored older sequence 1"
    assert active.read_bytes() == baseline
    assert config.read_text() == "MAX_REBOOTS=0\n"


def test_invalid_asset_leaves_the_executable_in_place(keys, tmp_path):
    private, public = keys
    active = tmp_path / "active"
    install_asset(build_asset(private, 2, SCRIPT), public, active)
    baseline = active.read_bytes()
    changed = build_asset(private, 3, SCRIPT).replace(b"healthy", b"changed")
    invalid_script = build_asset(private, 3, SCRIPT + b"if true; then\n")
    with pytest.raises(ValueError, match="signature"):
        install_asset(changed, public, active)
    with pytest.raises(ValueError, match="syntax"):
        install_asset(invalid_script, public, active)
    assert active.read_bytes() == baseline
    assert not list(tmp_path.glob(".watchdog-*"))


def test_failed_replacement_keeps_the_sequence_and_script(keys, tmp_path, monkeypatch):
    private, public = keys
    active = tmp_path / "active"
    install_asset(build_asset(private, 2, SCRIPT), public, active)
    baseline = active.read_bytes()

    def reject_replace(staging, target):
        assert staging.is_file() and target == active
        raise OSError("replacement failed")

    monkeypatch.setattr(watchdog_update.os, "replace", reject_replace)
    with pytest.raises(OSError, match="replacement failed"):
        install_asset(build_asset(private, 3, SCRIPT), public, active)
    assert active.read_bytes() == baseline
    assert not list(tmp_path.glob(".watchdog-*"))


def test_signed_watchdog_retains_cell_policy_through_repeated_ssh_failure(keys, tmp_path):
    private, public = keys
    active = tmp_path / "active"
    script = BASELINE_SCRIPT.read_bytes().replace(b"\r\n", b"\n")
    install_asset(build_asset(private, 1, script), public, active)
    actions = [run_watchdog(tmp_path, env={"MAX_REBOOTS": "0"}, script=active)[1] for _ in range(3)]
    assert actions == [["restart ssh"], ["restart NetworkManager", "restart ssh"], ["restart ssh"]]
