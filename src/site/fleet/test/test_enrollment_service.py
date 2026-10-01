"""D-361 S2: EnrollmentService against a fake CORE (httpx.MockTransport)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from enrollment_fakes import (
    CODE, ISSUED, MOVED, NAME, PINNED, REISSUED, Clock, FakeCore, build, scan_row,
)
from fakes import FakeRobot, run
from fleet.hub.hub import HubError
from fleet.server.enrollment import STOP_PATHS, EnrollmentError


def _enroll(service, **kwargs):
    kwargs.setdefault("code", CODE)
    kwargs.setdefault("principal_id", "alice")
    if "address" not in kwargs:
        kwargs.setdefault("discovery_name", NAME)
    return run(service.enroll(**kwargs))


def _refused(service, **kwargs) -> EnrollmentError:
    with pytest.raises(EnrollmentError) as refused:
        _enroll(service, **kwargs)
    return refused.value


def _ready(tmp_path, core=None, **kwargs):
    cores = {PINNED: core or FakeCore()}
    parts = build(tmp_path, cores, **kwargs)
    parts[3].replace_scan([scan_row()])
    return parts


# --- exchange -------------------------------------------------------------------


@pytest.mark.parametrize("source,legacy", [("pair-site", False), ("pair-physical", True)])
def test_site_and_legacy_shaped_answers_both_enroll(tmp_path, source, legacy):
    lifetime = timedelta(days=90) if source == "pair-site" else timedelta(days=7)
    service, network, console, _, store, _ = _ready(tmp_path, FakeCore(source=source,
                                                                       lifetime=lifetime))
    row = _enroll(service)

    assert row["robot_id"] == "rosy_09" and row["state"] == "active"
    assert row["legacy_lifetime"] is legacy and row["origin"] == "enrolled"
    assert row["address"] == PINNED and store.get("rosy_09")["principal_id"] == "alice"
    assert "rosy_09" in console.robot_ids
    assert network.paths(PINNED)[:3] == ["/api/v1/auth/pair", "/api/v1/auth/whoami",
                                          "/api/v1/system/info"]
    assert ISSUED not in repr(row) and ISSUED not in repr(store.rows())


def test_pair_body_names_the_site_and_asks_for_site_purpose(tmp_path):
    service, network, *_ = _ready(tmp_path)
    seen = {}
    original = network.cores[PINNED].handle

    def capture(request):
        if request.url.path == "/api/v1/auth/pair":
            seen["body"] = request.read()
        return original(request)

    network.cores[PINNED].handle = capture
    _enroll(service)
    assert b'"purpose":"site"' in seen["body"] and b'"label":"site:site-a"' in seen["body"]


@pytest.mark.parametrize("role,reason", [("administrator", "admin_code_refused"),
                                         ("viewer", "role_too_low")])
def test_wrong_role_logs_out_and_reports_the_code_consumed(tmp_path, role, reason):
    service, network, console, _, store, _ = _ready(tmp_path, FakeCore(role=role))
    refused = _refused(service)
    assert refused.code == "code_consumed" and refused.reason == reason
    assert network.paths(PINNED).count("/api/v1/auth/logout") == 1
    assert "rosy_09" not in console.robot_ids and store.rows() == []


@pytest.mark.parametrize("status,detail,retry,code", [
    (401, None, None, "code_rejected"),
    (401, {"burned": True}, None, "code_burned"),
    (429, None, 17, "rate_limited"),
    (403, None, None, "lan_forbidden"),
])
def test_refusals_are_classified_and_pair_is_called_once(tmp_path, caplog, status, detail, retry,
                                                         code):
    core = FakeCore(pair_status=status, pair_detail=detail, retry_after=retry)
    service, network, *_ = _ready(tmp_path, core)
    with caplog.at_level(logging.DEBUG):
        refused = _refused(service)
    assert refused.code == code
    if code == "rate_limited":
        assert refused.retry_after == 17
    assert network.paths() == ["/api/v1/auth/pair"]
    assert CODE not in repr(refused.body()) and CODE not in caplog.text


def test_unreachable_robot_is_classified(tmp_path):
    service, network, *_ = build(tmp_path, {})
    assert _refused(service, address="192.168.1.77").code == "unreachable"


@pytest.mark.parametrize("code", ["7KXM-P3Q", "7KXM-P3Q1", "", "7KXM P3QAA"])
def test_bad_format_never_reaches_the_robot(tmp_path, code):
    service, network, *_ = _ready(tmp_path)
    assert _refused(service, code=code).code == "bad_format"
    assert network.requests == []


@pytest.mark.parametrize("address", ["rosy-pinky-8kcn.local", "8.8.8.8", "127.0.0.1:8080",
                                     "192.168.1.9:0", "example.com:8080", "192.0.2.5",
                                     "100.64.0.1", "169.254.1.1"])
def test_manual_address_must_be_private_ipv4(tmp_path, address):
    service, network, *_ = _ready(tmp_path)
    assert _refused(service, address=address).code == "bad_address"
    assert network.requests == []


def test_manual_address_defaults_to_port_8080(tmp_path):
    service, network, *_ = build(tmp_path, {PINNED: FakeCore()})
    row = _enroll(service, address="192.168.1.202")
    assert row["address"] == PINNED and row["discovery_name"] is None


@pytest.mark.parametrize("hostname", ["rosy-pinky-zzzz", ""])
def test_binding_mismatch_is_wrong_robot_and_logs_out(tmp_path, hostname):
    service, network, console, *_ = _ready(tmp_path, FakeCore(hostname=hostname))
    refused = _refused(service)
    assert refused.code == "code_consumed" and refused.reason == "wrong_robot"
    assert refused.body()["avahi_renamed"] is False
    assert network.paths(PINNED).count("/api/v1/auth/logout") == 1
    assert "rosy_09" not in console.robot_ids


def test_bridge_hostname_must_match_the_txt_name_too(tmp_path):
    service, network, _, discovery, *_ = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row(hostname="rosy-pinky-8kcn-2.local")])
    refused = _refused(service)
    assert refused.reason == "wrong_robot" and refused.body()["avahi_renamed"] is True


def test_robot_id_conflict_with_a_file_robot_is_refused(tmp_path):
    service, network, console, *_ = _ready(tmp_path, FakeCore(robot_id="rosy_01"),
                                           static=(FakeRobot("rosy_01"),))
    refused = _refused(service)
    assert refused.reason == "robot_id_conflict"
    assert network.paths(PINNED).count("/api/v1/auth/logout") == 1


def test_expiry_warning_uses_the_fleet_clock_not_the_robot_clock(tmp_path):
    warn_at = []
    for skew in (timedelta(days=-1), timedelta(0), timedelta(days=1)):
        clock = Clock()
        service, *_ = _ready(tmp_path / str(skew.days), FakeCore(skew=skew), clock=clock)
        warn_at.append(_enroll(service)["warn_at"])
    assert warn_at[0] == warn_at[1] == warn_at[2] == 1_000_000.0 + 7 * 86400 - 48 * 3600


def test_expired_enrollment_needs_a_new_code(tmp_path):
    clock = Clock()
    service, *_ = _ready(tmp_path, clock=clock)
    _enroll(service)
    clock.now += 6 * 86400
    row = service.listing()["robots"][0]
    assert row["expiry_warning"] is True and row["state"] == "active"
    clock.now += 2 * 86400
    assert service.listing()["robots"][0]["state"] == "needs_new_code"


def test_a_401_from_the_robot_means_a_new_code_is_needed(tmp_path):
    service, network, console, *_ = _ready(tmp_path)
    _enroll(service)
    network.cores[PINNED].token = "revoked"
    run(console.snapshot())
    assert service.listing()["robots"][0]["state"] == "needs_new_code"


# --- pinned address --------------------------------------------------------------


def _bearer_non_stop(network, since: int = 0) -> list:
    return [(method, where, path) for method, where, path, auth in network.requests[since:]
            if auth and path not in STOP_PATHS]


def test_address_change_sends_no_bearer_except_stop_to_the_pinned_address(tmp_path):
    cores = {PINNED: FakeCore(), MOVED: FakeCore()}
    service, network, console, discovery, store, _ = build(tmp_path, cores,
                                                           static=(FakeRobot("rosy_01"),))
    discovery.replace_scan([scan_row()])
    _enroll(service)
    network.clear()

    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    assert store.get("rosy_09")["state"] == "address_changed"

    snapshot = run(console.snapshot())
    run(console.map())
    with pytest.raises(Exception):
        run(console.goal("rosy_09", 1.0, 1.0))
    result = run(console.estop_all())

    assert _bearer_non_stop(network) == []
    assert network.paths(MOVED) == []
    assert ("POST", PINNED, "/api/v1/safety/stop", True) in network.requests
    assert {row["robot_id"]: row["stopped"] for row in result["robots"]}["rosy_09"] is True
    row = {r["robot_id"]: r for r in snapshot["robots"]}["rosy_09"]
    assert row["online"] is False and row["held"] == "address_changed"
    assert row["error"]["code"] == "ADDRESS_UNVERIFIED"


def _moved(tmp_path, moved_core):
    cores = {PINNED: FakeCore(), MOVED: moved_core}
    service, network, console, discovery, store, tasks = build(tmp_path, cores)
    discovery.replace_scan([scan_row()])
    _enroll(service)
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    assert network.paths(MOVED) == []
    network.clear()
    return service, network, console, discovery, store


def _same_robot_at_new_address():
    # The robot itself, renumbered: it still honours the old token and issues a new one.
    return FakeCore(token=REISSUED, known={ISSUED})


def test_move_address_re_pairs_with_the_screen_code_and_rebinds_the_new_token(tmp_path):
    core = _same_robot_at_new_address()
    service, network, console, _, store = _moved(tmp_path, core)

    moved = run(service.move_address("rosy_09", code=CODE, principal_id="alice"))

    assert moved["address"] == MOVED and moved["state"] == "active" and moved["hold"] is None
    assert moved["old_token_revoked"] is True
    assert network.paths(MOVED) == ["/api/v1/auth/pair", "/api/v1/auth/whoami",
                                    "/api/v1/system/info", "/api/v1/auth/logout"]
    assert core.logged_out == [ISSUED]  # the old token is revoked over the verified channel
    assert service._tokens["rosy_09"] == REISSUED
    run(console.snapshot())
    state_calls = [r for where, r in network.raw if where == MOVED and r.url.path == "/api/v1/robot/state"]
    assert state_calls and all(r.headers["Authorization"] == f"Bearer {REISSUED}" for r in state_calls)
    assert any(row["action"] == "move_address" and row["outcome"] == "moved"
               for row in store.audit_rows())
    for text in (repr(moved), repr(store.rows()), repr(store.audit_rows())):
        assert ISSUED not in text and REISSUED not in text and CODE not in text


def test_the_stored_token_never_reaches_the_new_address_before_identity_is_verified(tmp_path):
    core = _same_robot_at_new_address()
    service, network, *_ = _moved(tmp_path, core)

    run(service.move_address("rosy_09", code=CODE, principal_id="alice"))

    paths = network.paths(MOVED)
    verified = paths.index("/api/v1/system/info")
    before = [r for where, r in network.raw if where == MOVED][:verified + 1]
    assert "Authorization" not in before[0].headers  # the code exchange carries no credential
    assert all(ISSUED not in str(r.url) + repr(list(r.headers.items())) + r.content.decode()
               for r in before)
    assert network.carried(MOVED, ISSUED) == ["/api/v1/auth/logout"]


def test_a_different_device_at_the_new_address_never_sees_the_stored_token(tmp_path):
    impostor = FakeCore(token=REISSUED, serial="sn-other")
    service, network, console, _, store = _moved(tmp_path, impostor)

    with pytest.raises(EnrollmentError) as refused:
        run(service.move_address("rosy_09", code=CODE, principal_id="alice"))

    assert refused.value.code == "identity_mismatch"
    assert network.carried(MOVED, ISSUED) == []
    assert impostor.logged_out == [REISSUED]  # the impostor's own fresh token is handed back
    row = store.get("rosy_09")
    assert row["address"] == PINNED and row["state"] == "address_changed"
    assert service._tokens["rosy_09"] == ISSUED
    assert any(a["action"] == "move_address" and a["outcome"] == "identity_mismatch"
               for a in store.audit_rows())


@pytest.mark.parametrize("field,value", [("robot_id", "rosy_77"), ("hostname", "rosy-other"),
                                         ("device_uid", "uid-other")])
def test_every_stored_binding_key_must_match_before_the_move(tmp_path, field, value):
    kwargs = {"robot_id": "rosy_77"} if field == "robot_id" else (
        {"hostname": value} if field == "hostname" else {"device_uid": value})
    service, network, _, _, store = _moved(tmp_path, FakeCore(token=REISSUED, **kwargs))
    if field == "device_uid":
        store.update("rosy_09", device_uid="uid-9")
    with pytest.raises(EnrollmentError) as refused:
        run(service.move_address("rosy_09", code=CODE, principal_id="alice"))
    assert refused.value.code == "identity_mismatch"
    assert network.carried(MOVED, ISSUED) == []


def test_a_wrong_screen_code_sends_nothing_else_and_keeps_the_hold(tmp_path):
    core = FakeCore(token=REISSUED, pair_status=401)
    service, network, _, _, store = _moved(tmp_path, core)
    with pytest.raises(EnrollmentError) as refused:
        run(service.move_address("rosy_09", code=CODE, principal_id="alice"))
    assert refused.value.code == "code_rejected"
    assert network.paths(MOVED) == ["/api/v1/auth/pair"]
    assert store.get("rosy_09")["state"] == "address_changed"


def test_a_malformed_screen_code_reaches_no_robot(tmp_path):
    service, network, *_ = _moved(tmp_path, _same_robot_at_new_address())
    with pytest.raises(EnrollmentError) as refused:
        run(service.move_address("rosy_09", code="nope", principal_id="alice"))
    assert refused.value.code == "bad_format" and network.requests == []


def test_old_token_that_cannot_be_revoked_is_recorded_and_reported(tmp_path):
    core = _same_robot_at_new_address()
    core.logout_status = 500
    service, network, _, _, store = _moved(tmp_path, core)
    moved = run(service.move_address("rosy_09", code=CODE, principal_id="alice"))
    assert moved["state"] == "active" and moved["old_token_revoked"] is False
    assert any(a["action"] == "move_address" and a["outcome"] == "old_token_not_revoked"
               for a in store.audit_rows())


def test_conflict_wins_over_address_changed(tmp_path):
    cores = {PINNED: FakeCore(), MOVED: FakeCore()}
    service, network, console, discovery, store, _ = build(tmp_path, cores)
    discovery.replace_scan([scan_row()])
    _enroll(service)
    network.clear()

    discovery.replace_scan([scan_row(), scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    listed = service.listing()["robots"][0]
    snap = discovery.snapshot(console.registered_endpoints, {}, service.enrolled_names())

    assert listed["hold"] == "conflict" and listed["state"] == "active"
    assert {row["status"] for row in snap["devices"]} == {"conflict"}
    run(console.snapshot())
    run(console.estop_all())
    assert _bearer_non_stop(network) == []
    assert network.paths(MOVED) == []
    assert ("POST", PINNED, "/api/v1/safety/stop", True) in network.requests

    discovery.replace_scan([scan_row()])
    run(service.on_discovery(discovery.rows()))
    assert service.listing()["robots"][0]["hold"] is None


def test_moving_robot_address_change_raises_an_alarm_and_holds_overlapping_traffic(tmp_path):
    corridor = [(x / 10, 0.0) for x in range(0, 31)]
    core = FakeCore(navigation="NAVIGATING", pose=(0.0, 0.0), path=corridor)
    cores = {PINNED: core, MOVED: FakeCore()}
    crossing = FakeRobot("rosy_01", state={"robot_id": "rosy_01", "navigation": "IDLE",
                                           "pose": {"x": 1.5, "y": 2.0, "yaw": 0.0}})
    apart = FakeRobot("rosy_02", state={"robot_id": "rosy_02", "navigation": "IDLE",
                                        "pose": {"x": 0.0, "y": 20.0, "yaw": 0.0}})
    service, network, console, discovery, _, _ = build(tmp_path, cores, static=(crossing, apart))
    discovery.replace_scan([scan_row()])
    _enroll(service)
    run(console.goal("rosy_09", 3.0, 0.0))
    run(console.snapshot())

    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    snapshot = run(console.snapshot())

    assert snapshot["alarms"] == [{"robot_id": "rosy_09", "code": "ROBOT_ADDRESS_UNVERIFIED",
                                   "reason": "address_changed"}]
    crossing._path = [(1.5, 2.0), (1.5, 1.0), (1.5, 0.0), (1.5, -1.0)]
    held = run(console.goal("rosy_01", 1.5, -1.0))
    assert held["queued"] is True and held["blocked_by"] == "rosy_09"
    apart._path = [(0.0, 20.0), (1.0, 20.0)]
    sent = run(console.goal("rosy_02", 1.0, 20.0))
    assert sent == {"accepted": True}
    run(console.snapshot())
    assert "rosy_01" in console._queued


def test_formation_member_gets_a_stop_then_the_formation_is_dissolved(tmp_path):
    cores = {PINNED: FakeCore(), MOVED: FakeCore()}
    service, network, console, discovery, _, _ = build(tmp_path, cores,
                                                       static=(FakeRobot("rosy_01"),))
    discovery.replace_scan([scan_row()])
    _enroll(service)

    class Session:
        state = "RUNNING"
        assignment = {"rosy_09": object()}

    order = []

    async def formation_stop():
        order.append(("formation_stop", list(network.paths(PINNED))))
        console._formation = None
        return {"active": False}

    console._formation = Session()
    console._formation_leader = "rosy_01"
    console.formation_stop = formation_stop
    network.clear()
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    run(service.settle_holds())

    assert network.paths(PINNED) == ["/api/v1/safety/stop"]
    assert order == [("formation_stop", ["/api/v1/safety/stop"])]


# --- unenroll and pending logout -----------------------------------------------------


def test_unenroll_logs_out_and_deletes_the_row(tmp_path):
    service, network, console, _, store, _ = _ready(tmp_path)
    _enroll(service)
    result = run(service.unenroll("rosy_09", principal_id="alice"))
    assert result["state"] == "removed"
    assert network.paths(PINNED)[-1] == "/api/v1/auth/logout"
    assert store.get("rosy_09") is None and "rosy_09" not in console.robot_ids
    assert store.audit_rows()[-1]["outcome"] == "removed"


def test_unenroll_refuses_a_robot_with_active_tasks(tmp_path):
    service, network, console, _, store, tasks = _ready(tmp_path)
    _enroll(service)
    run(tasks.submit_navigation(robot_id="rosy_09", x=1.0, y=1.0, source="operator",
                                actor_id="alice", request_key="k-9"))
    with pytest.raises(HubError) as refused:
        run(service.unenroll("rosy_09", principal_id="alice"))
    assert refused.value.code == "ACTIVE_TASKS"
    assert store.get("rosy_09")["state"] == "active"


def _pending(tmp_path):
    parts = _ready(tmp_path, static=(FakeRobot("rosy_01"),))
    service, network, console, discovery, store, _ = parts
    _enroll(service)
    core = network.cores.pop(PINNED)
    result = run(service.unenroll("rosy_09", principal_id="alice"))
    assert result["state"] == "pending_logout"
    assert "rosy_09" not in console.robot_ids
    assert store.get("rosy_09")["state"] == "pending_logout"
    network.cores[PINNED] = core
    network.clear()
    return parts


def test_pending_logout_retries_exactly_once_on_rediscovery(tmp_path):
    service, network, console, discovery, store, _ = _pending(tmp_path)
    network.cores[PINNED].logout_status = 500
    discovery.replace_scan([scan_row()])
    run(service.on_discovery(discovery.rows()))
    run(service.on_discovery(discovery.rows()))
    assert network.paths() == ["/api/v1/auth/logout"]
    assert store.get("rosy_09")["state"] == "pending_logout"


def test_pending_logout_success_deletes_the_row(tmp_path):
    service, network, console, discovery, store, _ = _pending(tmp_path)
    discovery.replace_scan([scan_row()])
    run(service.on_discovery(discovery.rows()))
    assert network.paths() == ["/api/v1/auth/logout"]
    assert store.get("rosy_09") is None


def test_pending_logout_is_not_sent_while_the_name_is_elsewhere(tmp_path):
    service, network, console, discovery, store, _ = _pending(tmp_path)
    network.cores[MOVED] = FakeCore()
    discovery.replace_scan([scan_row(), scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    assert network.requests == []
    assert "/api/v1/system/info" not in network.paths()


def test_restart_puts_enrolled_robots_back_without_a_code(tmp_path):
    service, network, console, discovery, store, _ = _ready(tmp_path)
    _enroll(service)
    again, network2, console2, *_ = build(tmp_path, {PINNED: FakeCore()})
    again.load()
    assert "rosy_09" in console2.robot_ids
    run(console2.snapshot())
    assert network2.paths() == ["/api/v1/robot/state"]


def test_wrong_key_at_restart_is_a_runtime_state_only(tmp_path):
    service, network, console, discovery, store, _ = _ready(tmp_path)
    _enroll(service)
    before = store.rows()
    again, _, console2, *_ = build(tmp_path, {PINNED: FakeCore()}, key=bytes(32))
    again.load()
    assert again.available is False and "rosy_09" not in console2.robot_ids
    assert store.rows() == before
    with pytest.raises(EnrollmentError) as refused:
        run(again.enroll(code=CODE, principal_id="alice", address=PINNED))
    assert refused.value.status == 503


# --- review fixes (MERGE-AFTER-FIXES) ------------------------------------------------


def _moved_round_trip(tmp_path):
    cores = {PINNED: FakeCore(), MOVED: FakeCore()}
    parts = build(tmp_path, cores)
    parts[3].replace_scan([scan_row()])
    _enroll(parts[0])
    return parts


def test_needs_new_code_survives_an_address_round_trip(tmp_path):
    service, network, console, discovery, store, _ = _moved_round_trip(tmp_path)
    network.cores[PINNED].token = "revoked"
    run(console.snapshot())
    assert store.get("rosy_09")["state"] == "needs_new_code"
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    discovery.replace_scan([scan_row()])
    run(service.on_discovery(discovery.rows()))
    assert store.get("rosy_09")["state"] == "needs_new_code"
    assert service.listing()["robots"][0]["hold"] == "needs_new_code"


def test_a_dead_token_is_not_polled_again(tmp_path):
    service, network, console, discovery, store, _ = _moved_round_trip(tmp_path)
    network.cores[PINNED].token = "revoked"
    run(console.snapshot())
    network.clear()
    run(console.snapshot())
    run(console.estop_all())
    assert network.paths() == ["/api/v1/safety/stop"]


def test_expiry_on_the_fleet_clock_stops_polling_without_a_request(tmp_path):
    clock = Clock()
    service, network, console, *_ = _ready(tmp_path, clock=clock)
    _enroll(service)
    clock.now += 8 * 86400
    network.clear()
    run(console.snapshot())
    assert network.paths() == []
    assert service.listing()["robots"][0]["state"] == "needs_new_code"


def test_loading_a_needs_new_code_row_holds_it(tmp_path):
    service, network, console, discovery, store, _ = _ready(tmp_path)
    _enroll(service)
    store.update("rosy_09", state="needs_new_code")
    again, network2, console2, *_ = build(tmp_path, {PINNED: FakeCore()})
    again.load()
    run(console2.snapshot())
    assert network2.paths() == []


def test_move_address_is_refused_during_a_conflict(tmp_path):
    service, network, console, discovery, store, _ = _moved_round_trip(tmp_path)
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    discovery.replace_scan([scan_row(MOVED), scan_row("192.168.1.204:8080")])
    run(service.on_discovery(discovery.rows()))
    network.clear()
    with pytest.raises(EnrollmentError) as refused:
        run(service.move_address("rosy_09", code=CODE, principal_id="alice"))
    assert refused.value.code == "conflict" and network.requests == []


def test_a_stale_formation_flag_does_not_end_a_new_formation(tmp_path):
    cores = {PINNED: FakeCore(), MOVED: FakeCore()}
    service, network, console, discovery, _, _ = build(
        tmp_path, cores, static=(FakeRobot("rosy_01"), FakeRobot("rosy_02")))
    discovery.replace_scan([scan_row()])
    _enroll(service)

    class Session:
        state = "RUNNING"

        def __init__(self, members):
            self.assignment = {rid: object() for rid in members}

    stops = []

    async def formation_stop():
        stops.append(True)
        console._formation = None
        return {"active": False}

    console.formation_stop = formation_stop
    console._formation, console._formation_leader = Session(["rosy_09"]), "rosy_01"
    console.hold_robot("rosy_09", "address_changed")        # A held and flagged
    console._formation, console._formation_leader = Session(["rosy_02"]), "rosy_01"  # F2
    discovery.replace_scan([scan_row(MOVED)])
    run(service.on_discovery(discovery.rows()))
    run(service.settle_holds())
    assert stops == [] and console._formation is not None


def test_enroll_requires_a_server_side_enrollable_row(tmp_path):
    service, network, console, discovery, store, _ = build(
        tmp_path, {PINNED: FakeCore()}, static=(FakeRobot("rosy_01"),))
    console._registered_endpoints["rosy_01"] = "http://192.168.1.202:8080"
    discovery.replace_scan([scan_row()])
    refused = _refused(service)
    assert refused.code == "not_enrollable" and network.requests == []
