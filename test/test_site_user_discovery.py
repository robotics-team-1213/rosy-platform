"""User discovery bootstrap with fake host commands; no live unit or Avahi writes."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/site/install-user-discovery.py"
spec = importlib.util.spec_from_file_location("site_user_discovery", SCRIPT)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class Host:
    def __init__(self, *, linger="yes", duplicate=None):
        self.calls = []
        self.linger = linger
        self.duplicate = duplicate

    def __call__(self, argv):
        self.calls.append(argv)
        text, code = "", 0
        if argv[0] == "loginctl":
            text = self.linger
        elif argv[:3] == ["systemctl", "--user", "is-active"]:
            code = 3
        elif argv[:2] == ["systemctl", "is-enabled"]:
            code = 0 if argv[-1] == self.duplicate else 1
        elif argv[:2] == ["systemctl", "is-active"]:
            code = 0 if argv[-1] in ("avahi-daemon.service", self.duplicate) else 3
        return subprocess.CompletedProcess(argv, code, text, "")


def test_install_keeps_one_secret_private_and_uses_user_units(tmp_path):
    host = Host()
    ca, token = tmp_path / "ca.crt", tmp_path / "selected-token"
    ca.write_text("public CA")
    token.write_text("selected-discovery-value")
    installed = tool.install(tmp_path / "home", ca, token, "site-pc.local", 8443,
                             runner=host, avahi_dir=tmp_path / "system-avahi", user="operator")
    state = tmp_path / "home/.local/share/rosy/site-discovery"
    assert (state / "discovery_token").read_text() == token.read_text()
    assert (state / "site-ca.crt").read_text() == ca.read_text()
    if os.name == "posix":
        assert (state / "discovery_token").stat().st_mode & 0o777 == 0o600
        assert (state / "site-ca.crt").stat().st_mode & 0o777 == 0o644
    assert json.loads((state / "config.json").read_text()) == {"tls_host": "site-pc.local", "port": 8443}
    for name in installed:
        text = (tmp_path / "home/.config/systemd/user" / name).read_text()
        assert "selected-discovery-value" not in text
        assert "sudo" not in text and "User=" not in text
    assert ["systemctl", "--user", "enable", "--now", *tool.ENABLED] in host.calls
    bridge = (state / "mdns-bridge.py").read_text()
    assert bridge == (ROOT / "deploy/site/mdns-bridge.py").read_text()


@pytest.mark.parametrize("duplicate", tool.SYSTEM_UNITS)
def test_install_refuses_active_root_services_before_writing(tmp_path, duplicate):
    with pytest.raises(tool.InstallError, match="system discovery"):
        tool.preflight(Host(duplicate=duplicate), tmp_path, "operator")


def test_failed_root_units_and_enabled_timer_do_not_block_fallback(tmp_path):
    host = Host(duplicate="rosy-mdns-bridge.timer")
    tool.preflight(host, tmp_path, "operator")


def test_known_unreadable_root_xml_is_left_in_place(tmp_path, monkeypatch):
    target = tmp_path / "rosy-fleet.service"
    target.write_text("unreadable Avahi artifact")
    original = Path.stat

    def metadata(path, *args, **kwargs):
        value = original(path, *args, **kwargs)
        if path == target:
            fields = list(value)
            fields[0], fields[4] = 0o100600, 0
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(Path, "stat", metadata)
    tool.preflight(Host(), tmp_path, "operator")
    assert target.read_text() == "unreadable Avahi artifact"


def test_inactive_xml_advertisement_also_blocks_fallback(tmp_path):
    (tmp_path / "rosy-fleet.service").write_text("already advertised")
    with pytest.raises(tool.InstallError, match="Avahi service"):
        tool.preflight(Host(), tmp_path, "operator")


def test_linger_is_required_without_enabling_it(tmp_path):
    host = Host(linger="no")
    with pytest.raises(tool.InstallError, match="Linger=yes"):
        tool.preflight(host, tmp_path, "operator")
    assert not any("enable-linger" in call for call in host.calls)


def test_temporary_user_advertisers_must_be_stopped_first(tmp_path):
    host = Host()

    def running(argv):
        if argv[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(argv, 0, "", "")
        return host(argv)

    with pytest.raises(tool.InstallError, match="stop it"):
        tool.preflight(running, tmp_path, "operator")


def test_bridge_command_reuses_verified_loopback_implementation(tmp_path):
    argv = tool.runtime_command("bridge", tmp_path, {"tls_host": "site-pc.local", "port": 8443})
    assert argv == ["/usr/bin/python3", str(tmp_path / "mdns-bridge.py"), "--tls-host", "site-pc.local",
                    "--port", "8443", "--ca-file", str(tmp_path / "site-ca.crt"),
                    "--token-file", str(tmp_path / "discovery_token")]


def test_advertisers_share_the_exact_existing_protocol_txt(tmp_path):
    for role, kind in (("fleet", "_rosy-fleet._tcp"), ("overhead", "_rosy-overhead._tcp")):
        argv = tool.runtime_command(role, ROOT / "deploy/site", {"tls_host": "site-pc.local", "port": 8443})
        assert argv[:2] == ["/usr/bin/avahi-publish-service", "--host=site-pc.local"]
        assert kind in argv and "tls=required" in argv and "product=rosy" in argv
        assert "tls_host=site-pc.local" in argv


def test_secret_destination_symlink_is_refused(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX symlink permissions")
    outside = tmp_path / "outside"
    outside.write_text("keep")
    destination = tmp_path / "token"
    destination.symlink_to(outside)
    with pytest.raises(tool.InstallError, match="symlink"):
        tool.write_file(destination, b"replace", 0o600)
    assert outside.read_text() == "keep"
