"""mDNS is a location hint; only an authenticated Agent can verify a robot."""

from fleet.server.discovery import DiscoveryStore


def test_ten_devices_are_visible_but_not_registered_or_verified():
    store = DiscoveryStore(clock=lambda: 100.0)
    rows = [dict(name=f"rosy-{n}", address=f"192.168.1.{n}", port=8080,
                 stage="CORE_READY", release="018", network="sta") for n in range(10, 20)]
    store.replace_scan(rows)
    result = store.snapshot({}, {})
    assert len(result["devices"]) == 10
    assert all(row["status"] == "registration_pending" for row in result["devices"])


def test_same_name_at_two_addresses_is_a_conflict():
    store = DiscoveryStore(clock=lambda: 100.0)
    store.replace_scan([dict(name="rosy-a", address=ip, port=8080, network="sta")
                        for ip in ("192.168.1.10", "192.168.1.11")])
    assert {row["status"] for row in store.snapshot({}, {})["devices"]} == {"conflict"}


def test_registered_robot_requires_authenticated_hello_to_be_verified():
    store = DiscoveryStore(clock=lambda: 100.0)
    store.replace_scan([dict(name="rosy-a", address="192.168.1.10", port=8080,
                             network="sta", stage="CORE_READY")])
    registered = {"rosy_01": "http://192.168.1.10:8080"}
    assert store.snapshot(registered, {})["devices"][0]["status"] == "pairing_pending"
    paired = {"rosy_01": {"online": True, "device_name": "rosy-a", "device_uid": "uid-a"}}
    assert store.snapshot(registered, paired)["devices"][0]["status"] == "verified_online"
    paired["rosy_01"]["device_name"] = "other"
    assert store.snapshot(registered, paired)["devices"][0]["status"] == "conflict"


def test_failed_or_ap_advertisements_cannot_become_verified():
    store = DiscoveryStore(clock=lambda: 100.0)
    store.replace_scan([dict(name="rosy-a", address="192.168.1.10", port=8080,
                             network="ap", stage="CORE_READY")])
    assert store.snapshot({}, {})["devices"] == []


def test_scan_expires_without_new_host_observation():
    now = [100.0]
    store = DiscoveryStore(clock=lambda: now[0], ttl_s=45.0)
    store.replace_scan([dict(name="rosy-a", address="192.168.1.10", port=8080,
                             network="sta")])
    now[0] = 146.0
    assert store.snapshot({}, {})["devices"] == []


def test_registered_mdns_hostname_matches_resolved_advertisement():
    store = DiscoveryStore(clock=lambda: 100.0)
    store.replace_scan([dict(name="rosy-a", hostname="rosy-a.local",
                             address="192.168.1.10", port=8080, network="sta")])
    result = store.snapshot({"rosy_01": "http://rosy-a.local:8080"}, {})
    assert result["devices"][0]["status"] == "pairing_pending"


def test_external_addresses_and_invalid_ports_are_rejected():
    store = DiscoveryStore(clock=lambda: 100.0)
    for address, port in (("8.8.8.8", 8080), ("127.0.0.1", 8080),
                          ("192.168.1.10", 0), ("192.168.1.10", 65536)):
        try:
            store.replace_scan([dict(name="rosy-a", address=address, port=port,
                                     network="sta")])
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {address}:{port}")


# D-370 5.1: the scan-row check uses the shared classifier and the shared vectors.
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

_VECTORS = json.loads((Path(__file__).resolve().parents[3]
                       / "test/fixtures/protocol/discovery-txt.v1.json").read_text(encoding="utf-8"))
# A bridge row carries host, address, port and network only; TXT-key reasons stop at the bridge.
_ROW_REASONS = {"bad_host", "bad_address", "bad_port", "ap_mode"}
_ROW_CASES = [case for case in _VECTORS["cases"] if case["service_type"] == "_rosy._tcp"
              and (case["expect"]["accepted"] or case["expect"]["reason"] in _ROW_REASONS)]


@pytest.mark.parametrize("case", _ROW_CASES, ids=lambda case: case["id"])
def test_scan_rows_follow_the_shared_robot_vectors(case):
    txt = dict(item.split("=", 1) for item in case["txt"])
    store = DiscoveryStore(clock=lambda: 100.0)
    row = dict(name=txt.get("name", "rosy-x"), hostname=case["host"], address=case["address"],
               port=case["port"], network=txt.get("network", "sta"))
    try:
        store.replace_scan([row])
    except ValueError:
        kept = False
    else:
        kept = bool(store.snapshot({}, {})["devices"])
    assert kept is case["expect"]["accepted"]


def test_row_cases_cover_every_row_reason():
    assert {case["expect"].get("reason") for case in _ROW_CASES} - {None} == _ROW_REASONS


def test_stored_hostname_is_the_classifier_normalised_host():
    store = DiscoveryStore(clock=lambda: 100.0)
    store.replace_scan([dict(name="rosy-a", hostname="Rosy-A.local.", address="192.168.1.10",
                             port=8080, network="sta"),
                        dict(name="rosy-b", address="192.168.1.11", port=8080, network="sta")])
    assert {row["name"]: row["hostname"] for row in store.rows()} == {
        "rosy-a": "rosy-a.local", "rosy-b": ""}
    registered = {"rosy_01": "http://rosy-a.local:8080"}
    assert store.snapshot(registered, {})["devices"][0]["status"] == "pairing_pending"


def test_scanner_lease_expiry_is_reported_apart_from_never_seen():
    """2026-10-01 audit #4: an expired lease stops discovery and move-address; say so."""
    now = [100.0]
    store = DiscoveryStore(clock=lambda: now[0], ttl_s=45.0)
    assert store.snapshot({}, {}) == {"devices": [], "scanner_online": False,
                                      "scanner_state": "never_seen", "scanner_age_s": None}
    store.replace_scan([dict(name="rosy-a", address="192.168.1.10", port=8080, network="sta")])
    now[0] = 145.0
    online = store.snapshot({}, {})
    assert (online["scanner_online"], online["scanner_state"], online["scanner_age_s"]) == \
        (True, "online", 45)
    now[0] = 145.5
    assert store.snapshot({}, {}) == {"devices": [], "scanner_online": False,
                                      "scanner_state": "expired", "scanner_age_s": 45}


def test_console_raises_an_alarm_when_the_scanner_lease_expires():
    source = (Path(__file__).resolve().parents[1] / "fleet/server/web/console.js").read_text(
        encoding="utf-8")
    block = source[source.index('snapshot.scanner_state === "expired"'):]
    block = block[:block.index("return;")]
    assert '"발견 검색기 끊김' in block and '"bad")' in block
    assert 'log("발견 검색기 끊김' in block
    assert "scanner_state" in block


def test_only_rfc1918_scan_addresses_are_accepted():
    """Review 2026-10-01: is_private also admits link-local, documentation, benchmark and CGNAT."""
    store = DiscoveryStore(clock=lambda: 100.0)
    for address in ("169.254.1.2", "192.0.2.5", "198.18.0.1", "100.64.0.1", "0.0.0.0",
                    "8.8.8.8", "224.0.0.1"):
        try:
            store.replace_scan([dict(name="rosy-a", address=address, port=8080, network="sta")])
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {address}")
    for address in ("10.16.36.20", "172.16.0.9", "192.168.1.10"):
        store.replace_scan([dict(name="rosy-a", address=address, port=8080, network="sta")])
        assert store.rows()[0]["address"] == address


def test_move_target_is_rfc1918_even_if_a_row_slipped_in(tmp_path):
    from enrollment_fakes import MOVED, build, scan_row

    service, network, console, discovery, store, _ = build(tmp_path, {})
    discovery._rows = [dict(scan_row(), address="192.0.2.7")]
    discovery._seen_at = 100.0
    discovery._clock = lambda: 100.0
    row = {"discovery_name": "rosy-pinky-8kcn", "hostname": "rosy-pinky-8kcn", "address": MOVED}
    assert service._current_other_address(row) is None
