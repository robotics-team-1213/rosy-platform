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
