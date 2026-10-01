"""Pinned robot address vs the latest discovery scan (site renumber audit, D-361 3, D-370 5.3)."""

from fleet.server.address_drift import classify_addresses


def _row(name, address, port=8080, hostname=None):
    return {"name": name, "hostname": hostname if hostname is not None else f"{name}.local",
            "address": address, "port": port}


def _by_id(result):
    return {entry["robot_id"]: entry for entry in result["robots"]}


def test_no_scan_or_offline_scanner_is_unknown():
    pinned = {"rosy_01": "http://192.168.1.10:8080"}
    for rows in (None, []):
        result = classify_addresses(pinned, rows, names={"rosy_01": "rosy-a"})
        entry = _by_id(result)["rosy_01"]
        assert entry["status"] == "unknown"
        assert entry["in_subnet"] is None
        assert result["all_outside"] is False


def test_pinned_inside_a_scanned_subnet():
    result = classify_addresses({"rosy_01": "http://10.16.36.40:8080"},
                                [_row("rosy-b", "10.16.36.20")], names={})
    entry = _by_id(result)["rosy_01"]
    assert entry["status"] == "in_scanned_subnet"
    assert entry["in_subnet"] is True
    assert entry["pinned"] == "10.16.36.40:8080"


def test_pinned_outside_every_scanned_subnet_and_the_banner_flag():
    pinned = {"rosy_01": "http://192.168.1.10:8080", "rosy_02": "https://192.168.1.11:8443"}
    result = classify_addresses(pinned, [_row("rosy-x", "10.16.36.20")], names={})
    entries = _by_id(result)
    assert {e["status"] for e in entries.values()} == {"outside_scanned_subnets"}
    assert all(e["in_subnet"] is False for e in entries.values())
    assert result["all_outside"] is True


def test_site_networks_count_as_scanned_subnets():
    result = classify_addresses({"rosy_01": "http://10.16.37.5:8080"},
                                [_row("rosy-x", "10.16.36.20")], names={},
                                site_networks=["10.16.36.0/22"])
    assert _by_id(result)["rosy_01"]["status"] == "in_scanned_subnet"


def test_same_identity_at_another_address():
    result = classify_addresses({"rosy_09": "http://192.168.1.202:8080"},
                                [_row("rosy-pinky-8kcn", "10.16.36.20")],
                                names={"rosy_09": "rosy-pinky-8kcn"}, movable={"rosy_09"})
    entry = _by_id(result)["rosy_09"]
    assert entry["status"] == "seen_at_other_address"
    assert entry["seen_addresses"] == ["10.16.36.20:8080"]
    assert entry["in_subnet"] is False
    assert entry["movable"] is True
    # Every pinned robot is outside, even the one seen elsewhere.
    assert result["all_outside"] is True


def test_identity_is_the_robot_name_not_a_different_robot_at_the_old_address():
    # Another robot took the old address: that row is not this robot.
    result = classify_addresses({"rosy_09": "http://192.168.1.202:8080"},
                                [_row("rosy-other", "192.168.1.202")],
                                names={"rosy_09": "rosy-pinky-8kcn"})
    entry = _by_id(result)["rosy_09"]
    assert entry["status"] == "in_scanned_subnet"
    assert entry["seen_addresses"] == []


def test_same_name_at_the_pinned_address_is_in_subnet_and_not_movable():
    result = classify_addresses({"rosy_09": "http://192.168.1.202:8080"},
                                [_row("rosy-pinky-8kcn", "192.168.1.202")],
                                names={"rosy_09": "rosy-pinky-8kcn"}, movable={"rosy_09"})
    entry = _by_id(result)["rosy_09"]
    assert entry["status"] == "in_scanned_subnet"
    assert entry["movable"] is False


def test_a_name_seen_at_several_other_addresses_is_not_movable():
    rows = [_row("rosy-pinky-8kcn", "10.16.36.20"), _row("rosy-pinky-8kcn", "10.16.36.21")]
    result = classify_addresses({"rosy_09": "http://192.168.1.202:8080"}, rows,
                                names={"rosy_09": "rosy-pinky-8kcn"}, movable={"rosy_09"})
    entry = _by_id(result)["rosy_09"]
    assert entry["status"] == "seen_at_other_address"
    assert entry["seen_addresses"] == ["10.16.36.20:8080", "10.16.36.21:8080"]
    assert entry["movable"] is False


def test_robot_without_an_identity_is_never_matched_by_name():
    result = classify_addresses({"rosy_01": "http://192.168.1.10:8080"},
                                [_row("rosy_01", "10.16.36.20")], names={})
    assert _by_id(result)["rosy_01"]["status"] == "outside_scanned_subnets"


def test_local_name_is_not_resolved_and_the_scan_address_is_only_a_suggestion():
    pinned = {"rosy_01": "http://rosy-a.local:8080"}
    result = classify_addresses(pinned, [_row("rosy-a", "10.16.36.20")],
                                names={"rosy_01": "rosy-a"})
    entry = _by_id(result)["rosy_01"]
    assert entry["status"] == "seen_at_other_address"
    assert entry["pinned_is_name"] is True
    assert entry["in_subnet"] is None
    assert entry["seen_addresses"] == ["10.16.36.20:8080"]
    assert entry["movable"] is False


def test_local_name_not_in_the_scan_is_unknown_and_blocks_the_banner():
    pinned = {"rosy_01": "http://rosy-a.local:8080", "rosy_02": "http://192.168.1.11:8080"}
    result = classify_addresses(pinned, [_row("rosy-x", "10.16.36.20")],
                                names={"rosy_01": "rosy-a"})
    assert _by_id(result)["rosy_01"]["status"] == "unknown"
    assert result["all_outside"] is False


def test_port_change_alone_is_not_an_address_change():
    result = classify_addresses({"rosy_02": "https://192.168.1.11:8443"},
                                [_row("rosy-b", "192.168.1.11", port=8080)],
                                names={"rosy_02": "rosy-b"})
    assert _by_id(result)["rosy_02"]["status"] == "in_scanned_subnet"


def test_payload_carries_no_credentials_or_path():
    result = classify_addresses({"rosy_01": "http://user:pw-secret@192.168.1.10:8080/x?t=tok-secret"},
                                [_row("rosy-x", "10.16.36.20")], names={})
    assert "secret" not in repr(result)
    assert _by_id(result)["rosy_01"]["pinned"] == "192.168.1.10:8080"


def test_empty_roster_never_raises_the_banner():
    assert classify_addresses({}, [_row("rosy-x", "10.16.36.20")], names={})["all_outside"] is False
