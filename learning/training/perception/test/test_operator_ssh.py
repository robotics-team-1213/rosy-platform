"""D-373 decision 6: operator SSH options shared by deliver and harvest."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT / "learning" / "training" / "perception") not in sys.path:
    sys.path.insert(0, str(ROOT / "learning" / "training" / "perception"))

import operator_ssh  # noqa: E402


def test_windows_defaults_under_localappdata():
    env = {"LOCALAPPDATA": r"C:\Users\op\AppData\Local"}
    ident, kh = operator_ssh.resolve(None, None, env=env, platform="win32")
    assert ident == str(Path(env["LOCALAPPDATA"]) / "Rosy" / "ssh" / "rosy-operator-ed25519")
    assert kh == str(Path(env["LOCALAPPDATA"]) / "Rosy" / "known_hosts")


def test_linux_requires_flag_or_env():
    with pytest.raises(operator_ssh.SshConfigError, match="ROSY_OPERATOR_KEY"):
        operator_ssh.resolve(None, "/etc/rosy/kh", env={}, platform="linux")
    with pytest.raises(operator_ssh.SshConfigError, match="ROSY_KNOWN_HOSTS"):
        operator_ssh.resolve("/k", None, env={}, platform="linux")
    env = {"ROSY_OPERATOR_KEY": "/etc/rosy/key", "ROSY_KNOWN_HOSTS": "/etc/rosy/kh"}
    assert operator_ssh.resolve(None, None, env=env, platform="linux") == (
        "/etc/rosy/key", "/etc/rosy/kh")


def test_flag_beats_env():
    env = {"ROSY_OPERATOR_KEY": "/env/key", "ROSY_KNOWN_HOSTS": "/env/kh"}
    assert operator_ssh.resolve("/flag/key", "/flag/kh", env=env, platform="linux") == (
        "/flag/key", "/flag/kh")


def test_known_hosts_with_whitespace_refused():
    # ssh splits UserKnownHostsFile on whitespace into several files
    with pytest.raises(operator_ssh.SshConfigError, match="space"):
        operator_ssh.resolve("/k", "/a b/kh", env={}, platform="linux")


def test_options_are_batch_pinned_and_key_only():
    opts = operator_ssh.options("/k/id", "/k/kh")
    assert opts[:2] == ["-i", "/k/id"]
    pairs = {opts[i + 1] for i, o in enumerate(opts) if o == "-o"}
    assert pairs == {"BatchMode=yes", "IdentitiesOnly=yes", "UserKnownHostsFile=/k/kh",
                     "StrictHostKeyChecking=yes", "ConnectTimeout=10",
                     "ServerAliveInterval=15", "ServerAliveCountMax=3"}


def test_safe_name_for_host_and_user():
    for ok in ("rosy", "10.0.0.5", "pinky-005.local", "_x"):
        assert operator_ssh.safe_name(ok)
    for bad in ("", "-oProxyCommand=x", "a b", "a;b", "a/b", "$(x)", None):
        assert not operator_ssh.safe_name(bad)
