"""tools/remote/robot_status.py: read-only robot release table from avahi output."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "remote"))

import robot_status  # noqa: E402

BROWSE = "\n".join([
    '+;wlo1;IPv4;ROSY\\032rosy-pinky-aa11;_rosy._tcp;local',
    '=;wlo1;IPv4;ROSY\\032rosy-pinky-aa11;_rosy._tcp;local;rosy-pinky-aa11.local;192.0.2.18;8080;'
    '"release=2026.10.29-001" "stage=CORE_READY" "tls=required" "role=robot"',
    '=;wlo1;IPv6;ROSY\\032rosy-pinky-aa11;_rosy._tcp;local;rosy-pinky-aa11.local;fe80::1;8080;"release=x"',
    '=;wlo1;IPv4;ROSY\\032rosy-pinky-bb22;_rosy._tcp;local;rosy-pinky-bb22.local;192.0.2.14;8080;'
    '"release=2026.10.19-168" "stage=CORE_READY" "name=rosy-pinky-bb22"',
    '=;wlo1;IPv4;ROSY\\032fleet;_rosy._tcp;local;site.local;192.0.2.5;443;"role=fleet" "release=2027.01.01-001"',
    '=;wlo1;IPv4;ROSY\\032rosy-pinky-cc33;_rosy._tcp;local;rosy-pinky-cc33.local;192.0.2.20;8080;'
    '"release=2026.10.29-001" "stage=BOOTING" "tls=none"',
])


def test_parse_keeps_resolved_ipv4_robots_including_legacy_rows():
    found = robot_status.parse_browse(BROWSE)
    assert set(found) == {"rosy-pinky-aa11", "rosy-pinky-bb22", "rosy-pinky-cc33"}
    assert found["rosy-pinky-aa11"] == {"address": "192.0.2.18", "release": "2026.10.29-001",
                                        "stage": "CORE_READY", "tls": "required"}
    assert found["rosy-pinky-bb22"]["tls"] == ""


def test_report_matches_by_name_or_address_and_marks_behind_and_missing():
    known = {"aa11": "rosy-pinky-aa11.local", "bb22": "192.0.2.14", "dd44": "rosy-pinky-dd44.local"}
    lines, missing = robot_status.report(known, robot_status.parse_browse(BROWSE))
    text = "\n".join(lines)
    assert missing
    assert "dd44   NOT FOUND (rosy-pinky-dd44.local)" in lines
    bb22 = next(line for line in lines if line.startswith("bb22"))
    assert "2026.10.19-168" in bb22 and bb22.endswith("BEHIND")
    assert not next(line for line in lines if line.startswith("aa11")).endswith("BEHIND")
    assert "rosy-pinky-cc33" in text and "not in lab_hosts.robots()" in text
    assert "2027" not in text


def test_nothing_known_nothing_found_is_not_missing():
    assert robot_status.report({}, {}) == ([], False)
