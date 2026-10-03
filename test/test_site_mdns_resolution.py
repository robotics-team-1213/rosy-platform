"""Fleet resolves stable robot names through host Avahi while retaining Docker DNS."""

import re
from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parents[1] / "deploy/site"


def test_image_installs_nss_with_local_only_precedence_and_dns_fallback():
    text = (SITE / "Dockerfile.fleet").read_text(encoding="utf-8")
    assert re.search(r"apt-get install[^\n]*\blibnss-mdns\b", text)
    assert "hosts: files mdns4_minimal [NOTFOUND=return] dns mdns4" in text


def test_host_avahi_directory_is_required_read_only_and_survives_socket_replacement():
    services = yaml.safe_load((SITE / "compose.yaml").read_text(encoding="utf-8"))["services"]
    fleet = services["fleet"]
    mounts = [item for item in fleet["volumes"] if isinstance(item, dict)]
    assert mounts == [{"type": "bind", "source": "/run/avahi-daemon", "target": "/run/avahi-daemon",
                       "read_only": True, "bind": {"create_host_path": False}}]
    assert fleet["networks"] == ["site_backend", "robot_egress"]
    assert fleet["read_only"] is True
    assert fleet["cap_drop"] == ["ALL"]
    assert "privileged" not in fleet and "network_mode" not in fleet and "extra_hosts" not in fleet
    for name in ("vision", "proxy"):
        assert not any(isinstance(item, dict) and item.get("source") == "/run/avahi-daemon"
                       for item in services[name].get("volumes", []))
