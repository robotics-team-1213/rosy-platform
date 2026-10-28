"""D-541: the CORE trip lease — a Fleet trip holds the robot; others stop or take over."""

import inspect

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
#: The lease owner: in production Fleet's own enrolment token (D-541 1).
FLEET = {"Authorization": "Bearer rosy-dev-operator"}
#: Another token of at least operator rank: a robot screen, Pilot, a script.
OTHER = {"Authorization": "Bearer rosy-dev-admin"}
RESOLVER = {"Authorization": "Bearer fleet-stuck-resolver-token-0001"}
URL = "/api/v1/trip-lease"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Executor:
    def __init__(self) -> None:
        self.goals, self.cancels = [], 0

    def send_goal(self, spec, *, correlation_id=None):
        self.goals.append(spec)

    def cancel_goal(self):
        self.cancels += 1

    def send_initial_pose(self, *a):
        return None


@pytest.fixture
def robot(core_client):
    client, services = core_client()
    clock = _Clock()
    services.trip_lease._monotonic = clock
    services.state.set_velocity(0.0, 0.0)
    services.nav.executor = _Executor()
    return client, services, clock


def _open(client, headers=FLEET, **body):
    payload = {"lease_id": "lease-1", "trip_id": "trip-7", "holder": "site-a",
               "operator_name": "kim", "ttl_s": 5}
    payload.update(body)
    return client.put(URL, json=payload, headers=headers)


def _events(client, prefix="trip_lease."):
    body = client.get("/api/v1/events", headers=VIEWER).json()
    return [e for e in body["events"] if e["type"].startswith(prefix)]


def _state(client):
    return client.get("/api/v1/robot/state", headers=VIEWER).json()


def _lane(client, headers=FLEET):
    return client.put("/api/v1/line-follow/mode", json={"mode": "IR_LINE"}, headers=headers)


def _goal(client, headers=FLEET):
    return client.post("/api/v1/navigation/goal", json={"x": 1.0, "y": 0.0}, headers=headers)


# --- open, renew, release ----------------------------------------------------------------


def test_open_renew_release_and_the_snapshot_fields(robot):
    client, _, clock = robot
    assert "trip_lease" not in _state(client)          # no lease: no key
    assert "trip_lease_ended" not in _state(client)
    opened = _open(client)
    assert opened.status_code == 200, opened.text
    lease = opened.json()["trip_lease"]
    assert opened.json()["renewed"] is False
    assert {k: lease[k] for k in ("lease_id", "trip_id", "holder", "operator_name", "expires_in_s")} == {
        "lease_id": "lease-1", "trip_id": "trip-7", "holder": "site-a", "operator_name": "kim",
        "expires_in_s": 5.0}
    assert "since" in lease
    clock.now += 3
    assert _state(client)["trip_lease"]["expires_in_s"] == 2.0
    renewed = _open(client)
    assert renewed.status_code == 200 and renewed.json()["renewed"] is True
    assert _state(client)["trip_lease"]["expires_in_s"] == 5.0
    released = client.delete(f"{URL}/lease-1", headers=FLEET)
    assert released.status_code == 200, released.text
    state = _state(client)
    assert "trip_lease" not in state
    assert state["trip_lease_ended"] == {"lease_id": "lease-1", "reason": "released", "by": "owner"}
    types = [e["type"] for e in _events(client)]
    assert types == ["trip_lease.opened", "trip_lease.ended"]


def test_release_does_not_stop_the_robot(robot):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200
    assert client.delete(f"{URL}/lease-1", headers=FLEET).status_code == 200
    assert services.line_follow.active and services.modes.mode.value == "NAVIGATION"


def test_only_the_owner_releases(robot):
    client, services, _ = robot
    _open(client)
    assert client.delete(f"{URL}/lease-1", headers=OTHER).status_code == 403
    assert client.delete(f"{URL}/nope", headers=FLEET).status_code == 404
    assert services.trip_lease.current() is not None


def test_viewer_cannot_open(robot):
    client, _, _ = robot
    assert _open(client, headers=VIEWER).status_code == 403


@pytest.mark.parametrize("field,value", [
    ("ttl_s", 0.5), ("ttl_s", 10.5), ("holder", ""), ("holder", "x" * 65),
    ("operator_name", ""), ("lease_id", ""), ("lease_id", "has space"), ("trip_id", ""),
])
def test_open_validates(robot, field, value):
    client, _, _ = robot
    response = _open(client, **{field: value})
    assert response.status_code == 400, response.text


def test_ttl_defaults_to_five_and_takes_ten(robot):
    client, _, _ = robot
    payload = {"lease_id": "a", "trip_id": "t", "holder": "h", "operator_name": "o"}
    assert client.put(URL, json=payload, headers=FLEET).json()["trip_lease"]["expires_in_s"] == 5.0
    assert _open(client, lease_id="a", ttl_s=10).json()["trip_lease"]["expires_in_s"] == 10.0


def test_different_lease_id_is_refused_even_from_the_same_token(robot):
    client, _, _ = robot
    _open(client)
    for headers, lease_id in ((FLEET, "lease-2"), (OTHER, "lease-1"), (OTHER, "lease-2")):
        response = _open(client, headers=headers, lease_id=lease_id)
        assert response.status_code == 409, (headers, lease_id)
        assert response.json()["error"]["code"] == "TRIP_LEASED"
        assert response.json()["error"]["detail"]["lease_id"] == "lease-1"


# --- open refusals -------------------------------------------------------------------------


def test_open_is_refused_during_another_tokens_calibration(robot):
    client, services, _ = robot
    started = client.post("/api/v1/calibration/session", json={"kind": "drive"}, headers=OTHER)
    assert started.status_code == 201
    refused = _open(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert services.trip_lease.current() is None


def test_open_is_refused_in_manual_even_after_the_driver_let_go(robot):
    client, services, _ = robot
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200
    assert not services.command.manual_active
    refused = _open(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "MANUAL_MODE"


def test_open_is_refused_under_estop(robot):
    client, _, _ = robot
    assert client.post("/api/v1/safety/stop", headers=VIEWER).status_code == 200
    refused = _open(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "EMERGENCY_ACTIVE"


def test_calibration_open_is_refused_during_a_trip_lease(robot):
    client, services, _ = robot
    _open(client)
    for headers in (OTHER, FLEET):
        refused = client.post("/api/v1/calibration/session", json={"kind": "drive"}, headers=headers)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "TRIP_LEASED"
    assert services.calibration.current() is None


# --- non-owner refusals: every route that passes require_calibration_owner -------------------

#: Every motion/mode write. The completeness test below collects the routes from the routers.
FENCED = [
    ("post", "/api/v1/mode", {"mode": "MANUAL"}),
    ("post", "/api/v1/mode", {"mode": "NAVIGATION"}),
    ("post", "/api/v1/teleop", {"linear": 0.1, "angular": 0.0}),
    ("post", "/api/v1/navigation/goal", {"x": 1.0, "y": 0.0}),
    ('post', '/api/v1/navigation/handover', dict(expected_boot_id='00000000-0000-0000-0000-000000000001',
        run_id='00000000-0000-0000-0000-000000000001', expected_owner_generation=0, correlation_id='work-attempt')),
    ("post", "/api/v1/navigation/home", None),
    ("post", "/api/v1/localization/initialpose", {"x": 0.0, "y": 0.0, "yaw": 0.0}),
    ("post", "/api/v1/motion/rotate_to", {"delta_deg": 30.0, "operator_name": "lee"}),  # D-603
    ("post", "/api/v1/slam/start", None),
    ("post", "/api/v1/slam/stop", None),
    ("post", "/api/v1/slam/reset", None),
    ("put", "/api/v1/line-follow/mode", {"mode": "IR_LINE"}),
    ("post", "/api/v1/line-follow/hold", None),
    ("post", "/api/v1/line-follow/junction", {"action": "straight", "place_id": "p", "expires_s": 5}),
    ("post", "/api/v1/line-follow/authority", {"authority_id": "a", "leg_id": "l", "pose_stamp": 1.0,
                                               "until_m": 0.5, "ttl_s": 1.0}),
    ("post", "/api/v1/line-follow/stuck/decision", {"stuck_id": "s", "decision": "RESUME"}),
    ("post", "/api/v1/line-follow/stuck/decision", {"stuck_id": "s", "decision": "BACK_AND_RETRY"}),
    ("post", "/api/v1/line-follow/stuck/decision", {"stuck_id": "s", "decision": "MANUAL"}),
    ("post", "/api/v1/line-follow/stuck/decision", {"stuck_id": "s", "decision": "YIELD",
                                                     "yield_m": 0.1, "yield_turn_rad": 0.2}),
    ("post", "/api/v1/line-follow/stuck/decision", {"stuck_id": "s", "decision": "REALIGN"}),
    ("post", "/api/v1/swarm/follow", {"target_robot_id": "rosy_02"}),
    ("post", "/api/v1/docking/dock", {"dock": "d1"}),
    ("post", "/api/v1/docking/undock", None),
    ("post", "/api/v1/power/mode", {"mode": "STANDBY"}),
    ("put", "/api/v1/safety/limits", {"manual_linear": 0.05}),
    ("post", "/api/v1/host/release/install", {"release_id": "2026.10.01-001", "confirmed": True}),
    ("post", "/api/v1/host/release/rollback", {"confirmed": True}),
    ("post", "/api/v1/host/reboot", {"confirmed": True}),
]
_GATES = ("require_calibration_owner", "enter_navigation_mode", "apply_mode", "_calibration_fence",
          " _lease(svc", "trip_lease.blocking")

# Fixed-principal station writes have their own configured fixture and test for
# every row in test_station_return_authority; the generic robot disables this profile.
STATION_FENCED = [
    ('put', '/api/v1/docking/station-target'),
    ('post', '/api/v1/docking/station-dock'),
    ('put', '/api/v1/docking/station-return'),
    ('post', '/api/v1/docking/station-return/finish'),
    ('post', '/api/v1/docking/station-undock'),
    ('put', '/api/v1/docking/station-departure'),
    ('post', '/api/v1/docking/station-departure/finish'),
]


def test_the_fenced_table_covers_every_gated_route(core_client):
    """A new drive route that calls the gate must be added to FENCED (and is fenced by the gate)."""
    from fastapi.routing import APIRoute

    def api_routes(routes):
        # FastAPI >= 0.13x keeps included routers lazily (`original_router`); walk into them.
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from api_routes(inner.routes)

    client, _ = core_client()
    gated = set()
    for route in api_routes(client.app.routes):
        if any(g in inspect.getsource(route.endpoint) for g in _GATES):
            for method in route.methods:
                gated.add((method.lower(), route.path))
    tabled = {(method, path) for method, path, _ in FENCED} | set(STATION_FENCED)
    # /do runs the routes above (each of them fenced); /mode IDLE stays open (apply_mode).
    # The D-395 localization writes have their own tests below (423 / lowercase-code conventions).
    localization = {("post", "/api/v1/localization/decision"), ("post", "/api/v1/localization/suspect"),
                    ("post", "/api/v1/localization/mission")}
    assert localization <= gated, gated
    assert gated - tabled - localization in ({("post", "/api/v1/do")}, set()), gated - tabled


@pytest.mark.parametrize("method,path,body", FENCED)
def test_non_owner_motion_and_mode_writes_get_trip_leased(core_client, method, path, body):
    client, services = core_client(capabilities={"docking": {"supported": True}})
    services.state.set_velocity(0.0, 0.0)
    if path == "/api/v1/teleop":
        assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200
        assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=OTHER).status_code == 200
    assert _open(client).status_code == 200
    response = getattr(client, method)(path, json=body, headers=OTHER)
    assert response.status_code == 409, (path, response.text)
    error = response.json()["error"]
    assert error["code"] == "TRIP_LEASED", (path, error)
    assert {k: error["detail"][k] for k in ("lease_id", "trip_id", "holder", "operator_name")} == {
        "lease_id": "lease-1", "trip_id": "trip-7", "holder": "site-a", "operator_name": "kim"}
    assert "expires_in_s" in error["detail"]
    assert services.trip_lease.current() is not None
    assert services.command.select_output().linear == 0.0


def test_non_owner_teleop_refusal_is_an_intent_record(robot):
    client, services, _ = robot
    seen = []
    services.command.intent_sink = lambda **kw: seen.append(kw)
    _open(client)
    client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OTHER)
    assert [(s["accepted"], s["code"]) for s in seen] == [(False, "TRIP_LEASED")]


def test_swarm_reference_frames_from_non_owners_are_dropped(robot):
    from core_common.protocol.schemas import EnvelopeType

    client, services, _ = robot
    received = []
    services.swarm.on_reference_pose = received.append
    _open(client)
    frame = {"type": EnvelopeType.POSE.value,
             "payload": {"robot_id": "rosy_02", "pose": {"x": 1.0, "y": 0.0, "yaw": 0.0}, "seq": 1}}
    for token, expected in (("rosy-dev-admin", 0), ("rosy-dev-operator", 1)):
        with client.websocket_connect(f"/ws/swarm/reference?token={token}") as socket:
            socket.send_json(frame)
            socket.send_json({"type": "ping"})
        assert len(received) == expected, token


# --- open stops ----------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v1/safety/stop", None),
    ("post", "/api/v1/mode", {"mode": "IDLE"}),
    ("post", "/api/v1/navigation/cancel", None),
    ("put", "/api/v1/line-follow/mode", {"mode": "OFF"}),
    ("post", "/api/v1/swarm/cancel", None),
])
def test_stops_stay_open_to_non_owners(robot, method, path, body):
    client, _, _ = robot
    _open(client)
    response = getattr(client, method)(path, json=body, headers=OTHER)
    assert response.status_code == 200, (path, response.text)


def test_estop_wins_and_ends_the_lease_and_release_does_not_restore_it(robot):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200
    assert client.post("/api/v1/safety/stop", headers=VIEWER).status_code == 200
    assert services.trip_lease.current() is None
    assert _state(client)["trip_lease_ended"]["reason"] == "estop"
    assert client.post("/api/v1/safety/release", headers=OTHER).status_code == 200
    assert services.trip_lease.current() is None
    assert "trip_lease" not in _state(client)


# --- the owner's lane <-> free keeps the lease ----------------------------------------------


def test_owner_lane_free_lane_keeps_the_lease(robot):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200                  # lane
    assert services.modes.mode.value == "NAVIGATION" and services.line_follow.active
    goal = _goal(client)                                     # free: the goal ends line-follow
    assert goal.status_code == 200, goal.text
    assert not services.line_follow.active and services.modes.mode.value == "NAVIGATION"
    assert _lane(client).status_code == 200                  # lane again
    assert services.trip_lease.current() is not None
    assert [e["type"] for e in _events(client)] == ["trip_lease.opened"]


def test_owner_cancel_keeps_the_lease(robot):
    client, services, _ = robot
    _open(client)
    assert _goal(client).status_code == 200
    assert client.post("/api/v1/navigation/cancel", headers=FLEET).status_code == 200
    assert services.trip_lease.current() is not None
    assert services.modes.mode.value == "NAVIGATION"


def test_goal_during_line_follow_is_still_refused_without_a_lease(robot):
    client, _, _ = robot
    assert _lane(client).status_code == 200
    refused = _goal(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LINE_FOLLOW_ACTIVE"


# --- what ends a lease ---------------------------------------------------------------------


def test_non_owner_cancel_in_a_free_segment_ends_the_lease_and_goes_idle(robot):
    client, services, _ = robot
    _open(client)
    assert _goal(client).status_code == 200
    assert client.post("/api/v1/navigation/cancel", headers=OTHER).status_code == 200
    assert services.trip_lease.current() is None
    assert services.modes.mode.value == "IDLE"
    assert _state(client)["trip_lease_ended"]["reason"] == "mode_left"


def test_non_owner_line_follow_off_in_a_free_segment_ends_the_lease_and_goes_idle(robot):
    client, services, _ = robot
    _open(client)
    assert _goal(client).status_code == 200
    off = client.put("/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=OTHER)
    assert off.status_code == 200
    assert services.trip_lease.current() is None and services.modes.mode.value == "IDLE"


def test_non_owner_line_follow_off_in_a_lane_segment_ends_the_lease(robot):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200
    assert client.put("/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=OTHER).status_code == 200
    assert services.trip_lease.current() is None and services.modes.mode.value == "IDLE"
    assert not services.line_follow.active


@pytest.mark.parametrize("who", ["owner", "other"])
def test_idle_from_anyone_ends_the_lease(robot, who):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200
    headers = FLEET if who == "owner" else OTHER
    assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=headers).status_code == 200
    assert services.trip_lease.current() is None
    assert _state(client)["trip_lease_ended"]["reason"] == "mode_left"


def test_owner_manual_ends_the_lease(robot):
    client, services, _ = robot
    _open(client)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=FLEET).status_code == 200
    assert services.trip_lease.current() is None
    assert _state(client)["trip_lease_ended"]["reason"] == "mode_left"


def test_docking_start_ends_the_lease(core_client):
    client, services = core_client(capabilities={"docking": {"supported": True}})
    _open(client)
    services.modes.transition(services.modes.mode.__class__("DOCKING"))
    assert services.trip_lease.current() is None
    assert services.trip_lease.ended()["reason"] == "mode_left"


def test_expiry_halts_a_moving_robot_to_idle(robot):
    from core_features.command.manager import Twist

    client, services, clock = robot
    _open(client)
    assert _lane(client).status_code == 200
    clock.now += 4.9
    services.trip_lease.expire_due()
    assert services.trip_lease.current() is not None       # not yet
    clock.now += 0.2
    # A lapsed lease still refuses non-owners until the timer processes it (safe side).
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 409
    services.trip_lease.expire_due()
    assert services.trip_lease.current() is None
    assert services.modes.mode.value == "IDLE" and not services.line_follow.active
    services.command.set_nav_twist(Twist(0.12, 0.0))
    assert services.command.select_output().linear == 0.0   # IDLE: nothing reaches the wheels
    assert _state(client)["trip_lease_ended"]["reason"] == "expired"
    renew = _open(client)            # Fleet comes back with the lost lease_id: refused, never reopened
    assert renew.status_code == 404, renew.text
    assert renew.json()["error"]["detail"]["ended"]["reason"] == "expired"
    assert services.trip_lease.current() is None
    assert _open(client, lease_id="lease-2").json()["renewed"] is False   # a new trip opens normally


def test_renew_after_expiry_gets_404_with_the_end_reason(robot):
    client, services, clock = robot
    _open(client, ttl_s=2)
    clock.now += 2.5
    services.trip_lease.expire_due()
    gone = client.delete(f"{URL}/lease-1", headers=FLEET)
    assert gone.status_code == 404
    assert gone.json()["error"]["detail"]["ended"]["reason"] == "expired"


# --- takeover ------------------------------------------------------------------------------


def test_takeover_ends_the_lease_halts_and_then_manual_is_a_separate_request(robot):
    client, services, _ = robot
    _open(client)
    assert _lane(client).status_code == 200
    refused = client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER)
    assert refused.json()["error"]["code"] == "TRIP_LEASED"
    taken = client.post(f"{URL}/takeover", json={"lease_id": "lease-1", "reason": "pilot"}, headers=OTHER)
    assert taken.status_code == 200, taken.text
    assert taken.json()["trip_lease_ended"]["reason"] == "taken_over"
    assert taken.json()["mode"] == "IDLE"
    assert services.modes.mode.value == "IDLE" and not services.line_follow.active
    ended = _state(client)["trip_lease_ended"]
    assert ended["reason"] == "taken_over" and ended["by"]
    assert any(e["type"] == "trip_lease.ended" and e["data"]["reason"] == "taken_over"
               for e in _events(client))
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200
    # Fleet's next renew finds no lease (D-541 7: it ends the trip and does not reopen).
    gone = client.delete(f"{URL}/lease-1", headers=FLEET)
    assert gone.status_code == 404 and gone.json()["error"]["detail"]["ended"]["reason"] == "taken_over"


def test_renew_after_takeover_is_refused_before_the_human_takes_manual(robot):
    """Review MAJOR 1: takeover -> IDLE -> Fleet's renew lands first: it must not re-own the robot."""
    client, services, _ = robot
    _open(client)
    assert client.post(f"{URL}/takeover", json={"lease_id": "lease-1"}, headers=OTHER).status_code == 200
    renew = _open(client)
    assert renew.status_code == 404, renew.text
    assert renew.json()["error"]["detail"]["ended"]["reason"] == "taken_over"
    assert services.trip_lease.current() is None
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200


def test_renew_after_non_owner_cancel_is_refused(robot):
    client, services, _ = robot
    _open(client)
    assert _goal(client).status_code == 200
    assert client.post("/api/v1/navigation/cancel", headers=OTHER).status_code == 200
    assert _open(client).status_code == 404
    assert services.trip_lease.current() is None


def test_ended_lease_ids_stay_refused_after_the_display_window(robot):
    client, services, clock = robot
    _open(client)
    assert client.delete(f"{URL}/lease-1", headers=FLEET).status_code == 200
    clock.now += 3600
    assert "trip_lease_ended" not in _state(client)
    refused = _open(client)
    assert refused.status_code == 404 and refused.json()["error"]["detail"]["ended"]["reason"] == "released"


def test_takeover_rules(robot):
    client, _, _ = robot
    _open(client)
    assert client.post(f"{URL}/takeover", json={"lease_id": "x"}, headers=OTHER).status_code == 404
    assert client.post(f"{URL}/takeover", json={"lease_id": "lease-1"}, headers=FLEET).status_code == 400
    assert client.post(f"{URL}/takeover", json={"lease_id": "lease-1"}, headers=VIEWER).status_code == 403


# --- stuck answers ---------------------------------------------------------------------------


def _stuck_robot(core_client):
    from test_line_follow_stuck_api import _stuck

    client, services, stuck_id = _stuck(core_client)
    made = client.post("/api/v1/system/tokens", headers=OTHER, json={
        "role": "stuck_resolver", "label": "site:fleet-resolver",
        "token": "fleet-stuck-resolver-token-0001"})
    assert made.status_code == 201, made.text
    assert _open(client).status_code == 200
    return client, services, stuck_id


@pytest.mark.parametrize("decision", ["RESUME", "BACK_AND_RETRY", "YIELD"])
def test_resolver_moving_answers_are_trip_leased(core_client, decision):
    client, services, stuck_id = _stuck_robot(core_client)
    body = {"stuck_id": stuck_id, "decision": decision}
    if decision == "YIELD":
        body.update(yield_m=0.1, yield_turn_rad=0.2)
    refused = client.post("/api/v1/line-follow/stuck/decision", json=body, headers=RESOLVER)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "TRIP_LEASED"
    assert services.line_follow.status().stuck is not None     # not consumed


def test_resolver_wait_passes_and_abort_ends_the_lease(core_client):
    client, services, stuck_id = _stuck_robot(core_client)
    wait = client.post("/api/v1/line-follow/stuck/decision",
                       json={"stuck_id": stuck_id, "decision": "WAIT"}, headers=RESOLVER)
    assert wait.status_code == 200, wait.text
    assert services.trip_lease.current() is not None
    stuck_id = services.line_follow.status().stuck.stuck_id
    abort = client.post("/api/v1/line-follow/stuck/decision",
                        json={"stuck_id": stuck_id, "decision": "ABORT"}, headers=RESOLVER)
    assert abort.status_code == 200, abort.text
    assert services.trip_lease.current() is None
    assert services.trip_lease.ended()["reason"] == "mode_left"


def test_owner_moving_answer_passes_the_lease(core_client):
    client, services, stuck_id = _stuck_robot(core_client)
    resumed = client.post("/api/v1/line-follow/stuck/decision",
                          json={"stuck_id": stuck_id, "decision": "RESUME"}, headers=FLEET)
    # Past the lease fence; the stuck itself may still refuse RESUME (object within stop distance).
    assert resumed.status_code == 200 or resumed.json()["error"]["code"] != "TRIP_LEASED", resumed.text
    assert services.trip_lease.current() is not None


# --- calibration exclusivity, shared token, capability -----------------------------------


def test_calibration_lease_and_trip_lease_are_exclusive_both_ways(robot):
    client, services, _ = robot
    assert client.post("/api/v1/calibration/session", json={"kind": "drive"},
                       headers=FLEET).status_code == 201
    refused = _open(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"


def test_owner_token_used_outside_fleet_raises_one_shared_token_warning(robot):
    client, services, _ = robot
    _open(client)
    # A trip never teleops: the owner token driving by hand is someone else holding it.
    for _ in range(3):
        client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=FLEET)
    warnings = [e for e in _events(client) if e["type"] == "trip_lease.shared_token"]
    assert len(warnings) == 1 and warnings[0]["severity"] == "warning"
    # /ws/state from another origin with the owner token.
    services.trip_lease.note_use(services.trip_lease._lease.owner_id, "10.0.0.9", "ws_state")
    services.trip_lease.note_use(services.trip_lease._lease.owner_id, "10.0.0.9", "ws_state")
    # The opening origin itself is Fleet.
    services.trip_lease.note_use(services.trip_lease._lease.owner_id,
                                 services.trip_lease._lease.origin, "ws_state")
    warnings = [e for e in _events(client) if e["type"] == "trip_lease.shared_token"]
    assert len(warnings) == 2


def test_ws_state_from_another_origin_warns(robot):
    client, services, _ = robot
    _open(client)
    services.trip_lease._lease.origin = "10.0.0.1"         # Fleet's address at open
    with client.websocket_connect("/ws/state") as ws:
        ws.send_json({"type": "auth", "token": "rosy-dev-operator"})
        frame = ws.receive_json()
    assert frame["trip_lease"]["lease_id"] == "lease-1"
    assert any(e["type"] == "trip_lease.shared_token" for e in _events(client))


def test_capability_announces_trip_lease(robot):
    client, _, _ = robot
    controls = client.get("/api/v1/system/capabilities", headers=VIEWER).json()["controls"]
    base = next(item for item in controls["items"] if item["kind"] == "base_velocity")
    assert base["trip_lease"] is True


def test_heartbeat_payload_omits_or_carries_the_lease_keys(robot):
    from core_common.protocol.schemas import HeartbeatPayload

    client, services, _ = robot
    beat = HeartbeatPayload(state_snapshot=services.state.snapshot())
    assert "trip_lease" not in beat.model_dump()["state_snapshot"]
    assert '"trip_lease"' not in beat.model_dump_json()
    _open(client)
    beat = HeartbeatPayload(state_snapshot=services.state.snapshot())
    assert beat.model_dump(mode="json")["state_snapshot"]["trip_lease"]["lease_id"] == "lease-1"


def test_open_is_refused_in_docking(core_client):
    client, services = core_client(capabilities={"docking": {"supported": True}})
    services.modes.transition(services.modes.mode.__class__("DOCKING"))
    refused = _open(client)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "MODE_CONFLICT"
    assert services.trip_lease.current() is None


def test_halt_reaches_idle_even_when_the_nav_cancel_fails(robot):
    client, services, clock = robot
    _open(client)
    assert _goal(client).status_code == 200

    def broken_cancel(*args, **kwargs):
        raise RuntimeError("nav down")
    services.nav.cancel = broken_cancel
    clock.now += 5.1
    services.trip_lease.expire_due()
    assert services.trip_lease.current() is None
    assert services.modes.mode.value == "IDLE"


@pytest.mark.parametrize("path,body", [
    ("/api/v1/localization/decision", {"request_id": "req-1", "candidate_index": 0, "source": "candidate",
                                       "cues": ["paint"]}),
    ("/api/v1/localization/suspect", {"reason": "fleet_monitor"}),
])
def test_localization_writes_are_trip_leased_with_423(robot, path, body):
    client, services, _ = robot
    _open(client)
    refused = client.post(path, json=body, headers=OTHER)
    assert refused.status_code == 423, refused.text
    assert refused.json()["error"]["code"] == "TRIP_LEASED"
    assert refused.json()["error"]["detail"]["lease_id"] == "lease-1"


def test_localization_mission_is_trip_leased_for_non_owners(core_client):
    import test_localization_mission as lm

    client, services = core_client()
    services.localization.on_state(lm._state())     # a D-395 robot reporting CANDIDATES
    assert _open(client).status_code == 200
    refused = lm._start(client, headers=OTHER)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "TRIP_LEASED"
    assert services.loc_mission.status()["state"] == "idle"


def test_restart_has_no_lease(core_client):
    _, services = core_client()
    assert services.trip_lease.current() is None


# --- D-760 2: line follow needs a held authority while the lease is open ------------------


def _gated(services, t):
    """The linear speed the authority gate leaves of a moving line decision at line time ``t``."""
    from core_features.line_follow.model import LineFollowDecision, LineFollowMode

    moving = LineFollowDecision(linear=0.05, angular=0.0, generation=0, evidence_revision=0,
                                mode=LineFollowMode.CAMERA_LINE)
    return services.line_follow._authority_gate(t, moving).linear


def _camera_lane(client, headers=FLEET):
    return client.put("/api/v1/line-follow/mode", json={"mode": "CAMERA_LINE"}, headers=headers)


def _line_status(client):
    return client.get("/api/v1/line-follow", headers=VIEWER).json()


def test_lane_following_without_a_lease_needs_no_authority(robot):
    client, services, _ = robot
    assert services.line_follow.config.authority_required is False
    assert _camera_lane(client).status_code == 200
    assert _gated(services, services.line_follow._clock()) == 0.05
    assert "authority" not in _line_status(client)


def test_under_a_lease_lane_following_stands_until_an_authority_and_again_after_a_mode_change(robot):
    client, services, _ = robot
    line = {"t": 10.0}
    lf = services.line_follow
    lf.bind_clock(lambda: line["t"])
    lf._wall = lambda: 1_800_000_000.0 + line["t"]
    _open(client)
    assert _camera_lane(client).status_code == 200
    assert _gated(services, line["t"]) == 0.0
    assert (lf.status().state, lf.status().reason) == ("HOLD", "authority_none")
    assert _line_status(client)["authority"]["state"] == "NONE"
    stamp = round(line["t"] * 1e9)
    lf.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0, yaw=0.0,
                           received_at=line["t"])
    body = {"authority_id": "trip-7:1", "leg_id": "trip-7:0", "pose_stamp": 1_800_000_000.0 + line["t"],
            "until_m": 1.0, "ttl_s": 5.0}
    assert client.post("/api/v1/line-follow/authority", json=body, headers=FLEET).json()["accepted"] is True
    assert _gated(services, line["t"]) == 0.05
    # The owner's lane -> free -> lane keeps the lease and drops the authority: required again.
    assert _goal(client).status_code == 200 and not lf.active
    assert _camera_lane(client).status_code == 200
    assert services.trip_lease.current() is not None
    assert _gated(services, line["t"]) == 0.0 and lf.status().reason == "authority_none"
    assert client.delete(f"{URL}/lease-1", headers=FLEET).status_code == 200
    # The lease ended while line follow is on: latched, so nothing drives without an authority.
    assert _gated(services, line["t"]) == 0.0 and lf.status().reason == "authority_none"
    assert _line_status(client)["authority"]["state"] == "NONE"
    # A mode change ends the session.
    assert client.put("/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=FLEET).status_code == 200
    assert _camera_lane(client).status_code == 200
    assert _gated(services, line["t"]) == 0.05
    assert "authority" not in _line_status(client)


def test_a_lapsed_lease_still_requires_an_authority_until_the_timer_ends_it(robot):
    client, services, clock = robot
    _open(client)
    assert services.line_follow.authority_leased() is True
    clock.now += 5.1
    assert services.line_follow.authority_leased() is True    # lapsed, not yet processed: safe side
    services.trip_lease.expire_due()
    assert services.line_follow.authority_leased() is False


def _gate_when_halted(services):
    """What the authority gate leaves at the moment the ended lease halts the robot."""
    seen, halt = [], services.trip_lease.halt

    def spy(reason):
        seen.append((reason, services.trip_lease.current(), services.line_follow.active,
                     _gated(services, services.line_follow._clock())))
        halt(reason)
    services.trip_lease.halt = spy
    return seen


def test_expiry_before_the_first_authority_never_frees_the_robot(robot):
    client, services, clock = robot
    _open(client)
    assert _camera_lane(client).status_code == 200
    seen = _gate_when_halted(services)
    clock.now += 5.1
    services.trip_lease.expire_due()
    # end() clears the lease, then halts: in between line follow is on, lease-less, and still zeroed.
    assert seen == [("expired", None, True, 0.0)]
    assert not services.line_follow.active and services.modes.mode.value == "IDLE"


def test_takeover_before_the_first_authority_never_frees_the_robot(robot):
    client, services, _ = robot
    _open(client)
    assert _camera_lane(client).status_code == 200
    seen = _gate_when_halted(services)
    taken = client.post(f"{URL}/takeover", json={"lease_id": "lease-1"}, headers=OTHER)
    assert taken.status_code == 200, taken.text
    assert seen == [("taken_over", None, True, 0.0)]
    assert not services.line_follow.active and services.modes.mode.value == "IDLE"


# --- D-763 6: a job's lease survives IDLE between its steps --------------------------------------


def _between_steps(client, services):
    """A job's lease, one lane step, then the owner's IDLE (the gap between two steps)."""
    assert _open(client, job_id="job-3").status_code == 200
    assert _lane(client).status_code == 200
    assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=FLEET).status_code == 200
    assert services.modes.mode.value == "IDLE" and not services.line_follow.active


def test_job_lease_survives_the_owners_idle_and_shows_its_job(robot):
    client, services, _ = robot
    _between_steps(client, services)
    assert services.trip_lease.current()["job_id"] == "job-3"
    assert _state(client)["trip_lease"]["job_id"] == "job-3"
    assert "trip_lease_ended" not in _state(client)
    assert [e["type"] for e in _events(client)] == ["trip_lease.opened"]
    assert _lane(client).status_code == 200            # the next step: the owner drives again


def test_a_plain_trip_lease_still_ends_at_idle(robot):
    client, services, _ = robot
    _open(client)
    assert services.trip_lease.current()["job_id"] is None
    assert _lane(client).status_code == 200
    assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=FLEET).status_code == 200
    assert services.trip_lease.current() is None


@pytest.mark.parametrize("path,body", [
    ("/api/v1/mode", {"mode": "MANUAL"}),
    ("/api/v1/mode", {"mode": "NAVIGATION"}),
    ("/api/v1/teleop", {"linear": 0.05, "angular": 0.0}),
])
def test_between_steps_non_holder_mode_and_teleop_get_409(robot, path, body):
    client, services, _ = robot
    _between_steps(client, services)
    refused = client.post(path, json=body, headers=OTHER)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "TRIP_LEASED", refused.text
    assert services.trip_lease.current() is not None and services.modes.mode.value == "IDLE"


def test_between_steps_handover_passes_and_halts(robot):
    client, services, _ = robot
    _between_steps(client, services)
    taken = client.post(f"{URL}/takeover", json={"lease_id": "lease-1", "reason": "pilot"}, headers=OTHER)
    assert taken.status_code == 200, taken.text
    assert taken.json()["trip_lease_ended"]["reason"] == "taken_over" and taken.json()["mode"] == "IDLE"
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OTHER).status_code == 200
    assert _open(client).status_code == 404            # Fleet's renew of the taken lease: refused


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/v1/safety/stop", None),
    ("post", "/api/v1/mode", {"mode": "IDLE"}),
])
def test_between_steps_stops_pass_and_end_the_jobs_lease(robot, method, path, body):
    client, services, _ = robot
    _between_steps(client, services)
    response = getattr(client, method)(path, json=body, headers=OTHER)
    assert response.status_code == 200, response.text
    assert services.trip_lease.current() is None       # a person's stop: Fleet never drives on (D-763 Q3)
    assert _state(client)["trip_lease_ended"]["reason"] in ("estop", "mode_left")


def test_a_non_owner_idle_during_a_jobs_step_ends_its_lease(robot):
    client, services, _ = robot
    assert _open(client, job_id="job-3").status_code == 200
    assert _lane(client).status_code == 200
    assert client.post("/api/v1/mode", json={"mode": "IDLE"}, headers=OTHER).status_code == 200
    assert services.trip_lease.current() is None and not services.line_follow.active
    assert _state(client)["trip_lease_ended"]["reason"] == "mode_left"


def test_owner_manual_still_ends_a_jobs_lease(robot):
    client, services, _ = robot
    _between_steps(client, services)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=FLEET).status_code == 200
    assert services.trip_lease.current() is None


def test_between_steps_expiry_is_as_today(robot):
    client, services, clock = robot
    _between_steps(client, services)
    clock.now += 5.1
    services.trip_lease.expire_due()
    assert services.trip_lease.current() is None and services.modes.mode.value == "IDLE"
    assert _state(client)["trip_lease_ended"]["reason"] == "expired"
    renew = _open(client, job_id="job-3")
    assert renew.status_code == 404 and renew.json()["error"]["detail"]["ended"]["reason"] == "expired"


def test_a_renew_never_changes_the_job(robot):
    client, services, _ = robot
    _open(client)
    assert _open(client, job_id="job-9").json()["renewed"] is True
    assert services.trip_lease.current()["job_id"] is None     # renewing never turns a trip's lease into a job's


@pytest.mark.parametrize("job_id", ["", "   ", "j" * 129])
def test_job_id_is_validated(robot, job_id):
    client, _, _ = robot
    assert _open(client, job_id=job_id).status_code == 400


def test_capability_announces_trip_lease_job(robot):
    client, _, _ = robot
    controls = client.get("/api/v1/system/capabilities", headers=VIEWER).json()["controls"]
    assert next(item for item in controls["items"] if item["kind"] == "base_velocity")["trip_lease_job"] is True


def test_held_job_lease_never_extends_the_authority(robot):
    """D-763 4 hard rule: renewing the job's lease keeps who holds the robot, not how far it may go."""
    client, services, clock = robot
    line, lf = {"t": 10.0}, services.line_follow
    lf.bind_clock(lambda: line["t"])
    lf._wall = lambda: 1_800_000_000.0 + line["t"]
    assert _open(client, job_id="job-3").status_code == 200
    assert _camera_lane(client).status_code == 200
    stamp = round(line["t"] * 1e9)
    lf.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0, yaw=0.0,
                           received_at=line["t"])
    body = {"authority_id": "s1:1", "leg_id": "s1:0", "pose_stamp": 1_800_000_000.0 + line["t"],
            "until_m": 5.0, "ttl_s": 5.0}
    assert client.post("/api/v1/line-follow/authority", json=body, headers=FLEET).json()["accepted"] is True
    assert _gated(services, line["t"]) == 0.05
    for _ in range(6):                                  # the trip loop stopped; only the lease is renewed
        clock.now += 1.0
        line["t"] += 1.0
        assert _open(client, job_id="job-3").json()["renewed"] is True
        services.trip_lease.expire_due()
    assert services.trip_lease.current() is not None
    assert _gated(services, line["t"]) == 0.0 and lf.status().reason == "authority_expired"


def test_held_job_lease_never_extends_the_goal_lease(robot, monkeypatch):
    client, services, clock = robot
    monkeypatch.setattr("core_api_web.api.v1.navigation.require_kept", lambda *_: None)  # as test_goal_lease
    services.nav.lease_clock = clock
    assert _open(client, job_id="job-3").status_code == 200
    goal = client.post("/api/v1/navigation/goal", json={"x": 1.0, "y": 0.0, "correlation_id": "s2:g",
                                                        "lease_ttl_s": 3.5}, headers=FLEET)
    assert goal.status_code == 200, goal.text
    services.nav.on_goal_accepted()
    expired = False
    for _ in range(4):
        clock.now += 1.0
        assert _open(client, job_id="job-3").json()["renewed"] is True
        services.trip_lease.expire_due()
        expired = services.nav.expire_goal_lease() or expired
    assert expired and services.trip_lease.current() is not None


def test_job_lease_order_lease_mode_first_authority_holds_at_every_step(robot):
    """D-760 2 latch: released by the mode change between steps, armed again at the next line session."""
    client, services, _ = robot
    line, lf = {"t": 10.0}, services.line_follow
    lf.bind_clock(lambda: line["t"])
    lf._wall = lambda: 1_800_000_000.0 + line["t"]
    _between_steps(client, services)                    # step 1 done; the latch went with that line session
    assert _camera_lane(client).status_code == 200      # step 2: lease held, so it latches at once
    assert _gated(services, line["t"]) == 0.0 and lf.status().reason == "authority_none"
    stamp = round(line["t"] * 1e9)
    lf.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=0.0, y=0.0, yaw=0.0,
                           received_at=line["t"])
    body = {"authority_id": "s2:1", "leg_id": "s2:0", "pose_stamp": 1_800_000_000.0 + line["t"],
            "until_m": 1.0, "ttl_s": 5.0}
    assert client.post("/api/v1/line-follow/authority", json=body, headers=FLEET).json()["accepted"] is True
    assert _gated(services, line["t"]) == 0.05          # moves only after its first authority
    assert client.delete(f"{URL}/lease-1", headers=FLEET).status_code == 200   # the job ended
    assert client.put("/api/v1/line-follow/mode", json={"mode": "OFF"}, headers=FLEET).status_code == 200
    assert _camera_lane(client).status_code == 200      # no lease, no config: no authority needed
    assert _gated(services, line["t"]) == 0.05
