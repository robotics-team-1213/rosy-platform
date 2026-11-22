"""Exercise signed watchdog activation using a disposable key and filesystem."""

import subprocess
import sys

import pytest

from watchdog_update import build_asset, install_asset

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux system watchdog executable")
SCRIPT = b"#!/usr/bin/env bash\nprintf 'healthy\\n'\n"


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
