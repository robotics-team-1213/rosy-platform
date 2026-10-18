"""D-795: no DDS traffic crosses machines. Deploy/runtime files keep discovery on one host."""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("deploy", "middleware", "integrations", "operations", "learning", "tools", ".github")
SKIP_DIRS = {"test", "tests", "docs", "archive", ".worktrees", "node_modules", ".git", "build",
             "install", "log", "__pycache__", ".gradle", "dist", "assets"}
SUFFIXES = {".sh", ".py", ".yaml", ".yml", ".env", ".example", ".service", ".xml", ".conf", ".ps1",
            ".json", ".toml", ".cfg", ".ini", ""}
FORBIDDEN = (
    (re.compile(r"ROS_AUTOMATIC_DISCOVERY_RANGE[^\n;]{0,40}?\b(SUBNET|SYSTEM_DEFAULT)\b"), "subnet discovery"),
    (re.compile(r"ROS_STATIC_PEERS[ \t]*[=:][ \t]*[\"']?[^\s\"';]"), "static peers"),
    (re.compile(r"ROS_LOCALHOST_ONLY[ \t]*[=:][ \t]*[\"']?0"), "ROS_LOCALHOST_ONLY=0"),
    (re.compile(r"\b(domain_bridge|rosbridge)"), "bridge across hosts"),
)


def _files():
    yield ROOT / "env.sh"
    for top in SCAN_ROOTS:
        for folder, dirs, names in os.walk(ROOT / top):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                path = Path(folder, name)
                if (not name.startswith("test_")
                        and (path.suffix in SUFFIXES or name.startswith("Dockerfile"))
                        and path.stat().st_size < 1_000_000):
                    yield path


def _violations(text):
    return [label for pattern, label in FORBIDDEN if pattern.search(text)]


def test_no_runtime_file_widens_dds_beyond_the_host():
    found = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        found += [f"{path.relative_to(ROOT)}: {label}" for label in _violations(text)]
    assert not found, found


def _cyclone_problems(xml):
    names = re.findall(r"<NetworkInterface\b([^>]*)>", xml)
    problems = ["no NetworkInterface"] if not names else []
    for attrs in names:
        name = re.search(r'name="([^"]*)"', attrs)
        address = re.search(r'address="([^"]*)"', attrs)
        if not ((name and name.group(1) == "lo") or (address and address.group(1).startswith("127."))):
            problems.append("non-loopback interface " + attrs.strip())
    if re.search(r"<Peers?\b", xml):
        problems.append("static peers")
    return problems


def test_every_cyclone_profile_binds_loopback_only():
    profiles = [p for p in _files() if p.suffix == ".xml"
                and "<CycloneDDS" in p.read_text(encoding="utf-8", errors="ignore")]
    assert profiles, "the Pinky lo-only profile must be found"
    bad = {str(p.relative_to(ROOT)): _cyclone_problems(re.sub(r"<!--.*?-->", "", p.read_text(
        encoding="utf-8"), flags=re.S)) for p in profiles}
    assert not {k: v for k, v in bad.items() if v}, bad


@pytest.mark.parametrize("text", [
    "ROS_AUTOMATIC_DISCOVERY_RANGE: \"${X:-SUBNET}\"", "export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET",
    "ROS_STATIC_PEERS=10.0.0.5", "ENV ROS_LOCALHOST_ONLY=0", "ros2 launch rosbridge_server x"])
def test_guard_catches_cross_host_settings(text):
    assert _violations(text)


@pytest.mark.parametrize("text", [
    "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_STATIC_PEERS=", "export ROS_STATIC_PEERS=; exec x",
    'os.environ["ROS_STATIC_PEERS"] = ""', "ROS_LOCALHOST_ONLY=1"])
def test_guard_allows_localhost_settings(text):
    assert not _violations(text)


def test_guard_rejects_a_nic_bound_cyclone_profile():
    assert _cyclone_problems('<NetworkInterface name="wlan0"/>')
    assert _cyclone_problems('<NetworkInterface autodetermine="true"/>')
    assert _cyclone_problems('<NetworkInterface name="lo"/><Peers><Peer address="10.0.0.2"/></Peers>')
    assert not _cyclone_problems('<NetworkInterface name="lo"/>')
