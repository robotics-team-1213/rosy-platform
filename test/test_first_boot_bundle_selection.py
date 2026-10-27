"""Exercise the shipped shell wrapper without taking a host lock or running firstboot."""
import os
from pathlib import Path
import subprocess

import pytest

FIRST_BOOT = Path(__file__).resolve().parents[1] / "deploy/robot/pinky_pro/image/first-boot"


@pytest.mark.parametrize("override", [None, "/run/rosy-provision-boot/rosy-provision/provision.json"])
def test_wrapper_leaves_default_bundle_selection_to_the_validating_cli(tmp_path, override):
    binary = tmp_path / "flock"
    binary.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="ascii")
    binary.chmod(0o755)
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"])
    env.pop("ROSY_PROVISION_BUNDLE", None)
    env["ROSY_ROOT"] = str(tmp_path / "root")
    if override is not None:
        env["ROSY_PROVISION_BUNDLE"] = override
    result = subprocess.run(["bash", str(FIRST_BOOT / "rosy-first-boot.sh"), "--network", "check"],
                            env=env, capture_output=True, text=True, check=False, timeout=10)
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    assert args[:3] == ["-w", "200", "/run/rosy-first-boot.lock"]
    assert args[-2:] == ["--network", "check"]
    assert args[args.index("--root") + 1] == env["ROSY_ROOT"]
    if override is None:
        assert "--bundle" not in args
    else:
        assert args[args.index("--bundle") + 1] == override


def test_retry_service_admits_either_bundle_location_with_or_conditions():
    service = (FIRST_BOOT / "rosy-first-boot-retry.service").read_text(encoding="utf-8")
    conditions = [line.partition("=")[2] for line in service.splitlines()
                  if line.startswith("ConditionPathExists=")]
    assert "!/var/lib/rosy/provisioning/complete.json" in conditions
    assert "|/boot/firmware/rosy-provision/provision.json" in conditions
    assert "|/run/rosy-provision-boot/rosy-provision/provision.json" in conditions
    assert "/boot/firmware/rosy-provision/provision.json" not in conditions
