"""D-395 Phase 2 lane B: snapshot, routes, capability and gating (contract §1, §2).

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md. The bridge is not
here (rclpy); `services.localization` is fed the same JSON the bridge relays,
and its decision/suspect publishers are captured.
"""

from __future__ import annotations

import json

import pytest

VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
ADMIN = {"Authorization": "Bearer rosy-dev-admin"}


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _state(state="UNKNOWN", frame="map", request_id=None) -> str:
    return json.dumps({"status": {"state": state, "pose_frame": frame, "request_id": request_id},
                       "pose": None, "stamp": 1.0})


def _report(request_id="req-1") -> str:
    return json.dumps({"request_id": request_id, "stamp": 5.0,
                       "candidates": [{"x": 1.0, "y": 2.0, "yaw": 0.0, "scan_fit": 0.9}]})


@pytest.fixture
def core(core_client):
    client, services = core_client()
    loc = services.localization
    sent = {"decision": [], "suspect": []}
    loc.publish_decision = sent["decision"].append
    loc.publish_suspect = sent["suspect"].append
    loc.clock = lambda: 777.25
    services.sent = sent
    return client, services


def _types(services, prefix="localization."):
    return [event for event in services.events.history() if event.type.startswith(prefix)]


# --- P2-1: snapshot -------------------------------------------------------------


def test_snapshot_localization_is_null_before_any_state(core):
    client, _ = core
    body = client.get("/api/v1/robot/state", headers=VIEWER).json()
    assert "localization" in body and body["localization"] is None


def test_snapshot_carries_the_robot_state(core):
    client, services = core
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["state"] == "CANDIDATES" and loc["pose_frame"] == "map"
    assert loc["request_id"] == "req-1"


def test_snapshot_frame_is_odom_while_core_uses_odom(core):
    client, services = core
    services.localization.on_state(_state("LOCALIZED", frame="map"))
    services.localization.tick(odom_owns_pose=True)
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["pose_frame"] == "odom"


def test_snapshot_goes_unknown_when_the_state_topic_stops(core):
    client, services = core
    clock = _Clock()
    services.localization._monotonic = clock
    services.localization.on_state(_state("LOCALIZED"))
    clock.now += 3.5
    loc = client.get("/api/v1/robot/state", headers=VIEWER).json()["localization"]
    assert loc["state"] == "UNKNOWN" and loc["reason"] == "state_stale"


def test_localized_cancels_navigation_through_the_manager(core):
    _client, services = core
    cancels = []
    services.nav.cancel = lambda source="api", **_: cancels.append(source)
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    services.localization.on_state(_state("LOCALIZED"))
    assert cancels == ["localization"]
    assert [e.data["state"] for e in _types(services, "localization.state")] == [
        "CANDIDATES", "LOCALIZED"]


# --- P2-5: capability matrix --------------------------------------------------------


def _fleet_token(client) -> dict:
    """Fleet's robot token: an operator token (robots.yaml or D-361 enrollment)."""
    made = client.post("/api/v1/system/tokens", headers=ADMIN, json={
        "role": "operator", "label": "site:fleet", "token": "fleet-site-operator-token-0001"})
    assert made.status_code == 201
    return {"Authorization": "Bearer fleet-site-operator-token-0001"}


def _headers(client, who: str) -> dict:
    return {"viewer": VIEWER, "operator": OPERATOR}.get(who) or _fleet_token(client)


def _candidate(request_id="req-1", **extra) -> dict:
    return {"request_id": request_id, "candidate_index": 0, "source": "candidate",
            "cues": ["paint"], **extra}


def _human(request_id="req-1") -> dict:
    return {"request_id": request_id, "pose": {"x": 1.0, "y": 2.0, "yaw": 0.5}, "source": "human"}


def _open_candidates(services, request_id="req-1"):
    services.localization.on_state(_state("CANDIDATES", request_id=request_id))
    services.localization.on_candidates(_report(request_id))


@pytest.mark.parametrize("who,expected", [("viewer", 403), ("operator", 200), ("fleet", 200)])
def test_candidates_need_localize_assist(core, who, expected):
    client, services = core
    _open_candidates(services)
    response = client.get("/api/v1/localization/candidates", headers=_headers(client, who))
    assert response.status_code == expected
    if expected == 403:
        assert response.json()["error"]["detail"] == {"capability": "LOCALIZE_ASSIST"}
    else:
        assert response.json()["robot_id"] == services.identity.robot_id
        assert response.json()["request_id"] == "req-1"


@pytest.mark.parametrize("who,expected", [("viewer", 403), ("operator", 202), ("fleet", 202)])
def test_decision_and_suspect_need_localize_assist(core, who, expected):
    client, services = core
    _open_candidates(services)
    headers = _headers(client, who)
    decided = client.post("/api/v1/localization/decision", headers=headers, json=_candidate())
    suspected = client.post("/api/v1/localization/suspect", headers=headers,
                            json={"reason": "fleet_monitor"})
    assert (decided.status_code, suspected.status_code) == (expected, expected)
    if expected == 202:
        assert decided.json() == {"request_id": "req-1"}
        assert services.sent["suspect"] == [{"reason": "fleet_monitor"}]


def test_a_human_decision_also_needs_navigate(core, monkeypatch):
    from core_api_web.api import grants
    client, services = core
    _open_candidates(services)
    monkeypatch.setitem(grants.ROLE_GRANTS, "operator", frozenset({grants.LOCALIZE_ASSIST}))
    human = client.post("/api/v1/localization/decision", headers=OPERATOR, json=_human())
    assert human.status_code == 403
    assert human.json()["error"]["detail"] == {"capability": "NAVIGATE"}
    assert client.post("/api/v1/localization/decision", headers=OPERATOR,
                       json=_candidate()).status_code == 202


# --- P2-4: routes ----------------------------------------------------------------


def test_candidates_404_when_not_in_candidates(core):
    client, services = core
    missing = client.get("/api/v1/localization/candidates", headers=OPERATOR)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "NO_CANDIDATES"
    services.localization.on_state(_state("LOCALIZED"))
    services.localization.on_candidates(_report("req-1"))
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 404


def test_a_report_the_robot_dropped_is_not_served_again(core):
    """S1 re-run R5: a mission start drops the robot's open request (`request_id: null`);
    CORE drops its cached report with it, so Fleet cannot decide on it (stale_request)."""
    client, services = core
    _open_candidates(services, "req-1")
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 200
    services.localization.on_state(_state("CANDIDATES", request_id=None))
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 404
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 404


def test_a_report_for_another_request_is_dropped(core):
    client, services = core
    _open_candidates(services, "req-1")
    services.localization.on_state(_state("CANDIDATES", request_id="req-2"))
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 404


def test_a_report_that_arrives_before_its_state_is_served_once_the_state_catches_up(core):
    client, services = core
    _open_candidates(services, "req-1")
    services.localization.on_candidates(_report("req-2"))       # the new search, state not yet
    assert client.get("/api/v1/localization/candidates", headers=OPERATOR).status_code == 404
    services.localization.on_state(_state("CANDIDATES", request_id="req-2"))
    served = client.get("/api/v1/localization/candidates", headers=OPERATOR)
    assert served.status_code == 200 and served.json()["request_id"] == "req-2"


def test_decision_is_published_with_core_receipt_time(core):
    client, services = core
    _open_candidates(services)
    client.post("/api/v1/localization/decision", headers=OPERATOR, json=_candidate(ttl_s=4.0))
    [sent] = services.sent["decision"]
    assert sent["received_s"] == 777.25
    assert sent["decision"]["candidate_index"] == 0 and sent["decision"]["ttl_s"] == 4.0


def test_a_decision_for_another_request_is_409_stale(core):
    client, services = core
    _open_candidates(services, "req-2")
    stale = client.post("/api/v1/localization/decision", headers=OPERATOR, json=_candidate("req-1"))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_REQUEST"
    assert services.sent["decision"] == []


def test_an_invalid_decision_is_400(core):
    client, services = core
    _open_candidates(services)
    both = client.post("/api/v1/localization/decision", headers=OPERATOR,
                       json={**_candidate(), "pose": {"x": 0, "y": 0, "yaw": 0}})
    assert both.status_code == 400 and both.json()["error"]["code"] == "VALIDATION_ERROR"
    long_reason = client.post("/api/v1/localization/suspect", headers=OPERATOR,
                              json={"reason": "x" * 65})
    assert long_reason.status_code == 400


def test_a_pre_d395_robot_answers_501(core):
    client, services = core
    decided = client.post("/api/v1/localization/decision", headers=OPERATOR, json=_candidate())
    suspected = client.post("/api/v1/localization/suspect", headers=OPERATOR, json={"reason": "x"})
    assert decided.status_code == suspected.status_code == 501
    assert services.sent == {"decision": [], "suspect": []}


def _open_lease(client, headers=ADMIN):
    opened = client.post("/api/v1/calibration/session", headers=headers,
                         json={"kind": "drive", "label": "drive", "ttl_s": 30})
    assert opened.status_code in (200, 201), opened.json()


def test_a_calibration_lease_blocks_localization_writes_with_423(core):
    client, services = core
    _open_candidates(services)
    _open_lease(client)
    for path, body in (("/api/v1/localization/decision", _candidate()),
                       ("/api/v1/localization/suspect", {"reason": "fleet_monitor"})):
        refused = client.post(path, headers=OPERATOR, json=body)
        assert refused.status_code == 423, path
        assert refused.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    legacy = client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                         json={"x": 0.0, "y": 0.0, "yaw": 0.0})
    assert legacy.status_code == 409 and legacy.json()["error"]["code"] == "CALIBRATION_ACTIVE"
    assert services.sent == {"decision": [], "suspect": []}
    # The lease owner itself is not fenced.
    assert client.post("/api/v1/localization/decision", headers=ADMIN,
                       json=_candidate()).status_code == 202


def test_an_expired_lease_no_longer_blocks(core):
    client, services = core
    clock = _Clock()
    services.calibration._monotonic = clock
    _open_candidates(services)
    _open_lease(client)
    clock.now += 31.0
    assert client.post("/api/v1/localization/decision", headers=OPERATOR,
                       json=_candidate()).status_code == 202


class _Executor:
    def __init__(self) -> None:
        self.poses, self.goals = [], []

    def send_goal(self, spec, **_):
        self.goals.append(spec)

    def cancel_goal(self):
        pass

    def send_initial_pose(self, x, y, yaw):
        self.poses.append((x, y, yaw))


def test_legacy_initialpose_becomes_a_human_decision_on_a_d395_robot(core):
    client, services = core
    services.nav.executor = executor = _Executor()
    _open_candidates(services, "req-5")
    response = client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                           json={"x": 0.4, "y": -1.2, "yaw": 1.57})
    assert response.status_code == 200 and response.json() == {"accepted": True}
    assert executor.poses == []          # /initialpose is the sensing node's now
    [sent] = services.sent["decision"]
    assert sent["decision"]["source"] == "human"
    assert sent["decision"]["request_id"] == "req-5"
    assert sent["decision"]["pose"] == {"x": 0.4, "y": -1.2, "yaw": 1.57}
    [event] = _types(services, "localization.initialpose")
    assert event.data == {"x": 0.4, "y": -1.2, "yaw": 1.57, "source": "human"}


def test_legacy_initialpose_on_a_pre_d395_robot_still_writes_initialpose(core):
    client, services = core
    services.nav.executor = executor = _Executor()
    response = client.post("/api/v1/localization/initialpose", headers=OPERATOR,
                           json={"x": 0.4, "y": -1.2, "yaw": 1.57})
    assert response.status_code == 200
    assert executor.poses == [(0.4, -1.2, 1.57)]
    assert services.sent["decision"] == []
    assert _types(services, "localization.initialpose")[0].data["source"] == "human"


def test_human_decision_route_emits_initialpose_with_source(core):
    client, services = core
    _open_candidates(services)
    assert client.post("/api/v1/localization/decision", headers=OPERATOR,
                       json=_human()).status_code == 202
    [event] = _types(services, "localization.initialpose")
    assert event.data["source"] == "human"


def test_result_and_candidate_events_are_emitted(core):
    client, services = core
    _open_candidates(services)
    client.post("/api/v1/localization/decision", headers=OPERATOR,
                json=_candidate(cues=["peers", "slot"]))
    services.localization.on_result(json.dumps(
        {"request_id": "req-1", "accepted": False, "reason": "no_asymmetric_cue",
         "state": "CANDIDATES"}))
    assert [e.data["request_id"] for e in _types(services, "localization.candidates")] == ["req-1"]
    [result] = _types(services, "localization.result")
    assert result.data["source"] == "candidate" and result.data["cues"] == ["peers", "slot"]
    assert result.data["accepted"] is False


# --- P2-4: navigation and lane keep refuse unless LOCALIZED ------------------------


def _ready_for_goal(services):
    services.state.set_velocity(0.0, 0.0)
    services.nav.executor = _Executor()


@pytest.mark.parametrize("state", ["UNKNOWN", "CANDIDATES", "SUSPECT"])
def test_navigation_is_refused_unless_localized(core, state):
    client, services = core
    _ready_for_goal(services)
    services.localization.on_state(
        _state(state, request_id="req-1" if state == "CANDIDATES" else None))
    for path, body in (("/api/v1/navigation/goal", {"x": 1.0, "y": 2.0, "yaw": 0.0}),
                       ("/api/v1/navigation/home", None)):
        refused = client.post(path, headers=OPERATOR, json=body)
        assert refused.status_code == 409, path
        assert refused.json()["error"]["code"] == "NOT_LOCALIZED"
        assert refused.json()["error"]["detail"]["state"] == state
    assert services.nav.executor.goals == []


def test_navigation_goal_is_allowed_when_localized(core):
    client, services = core
    _ready_for_goal(services)
    services.localization.on_state(_state("LOCALIZED"))
    goal = client.post("/api/v1/navigation/goal", headers=OPERATOR,
                       json={"x": 1.0, "y": 2.0, "yaw": 0.0})
    assert goal.status_code == 200, goal.json()


def test_navigation_goal_is_allowed_on_a_pre_d395_robot(core):
    client, services = core
    _ready_for_goal(services)
    goal = client.post("/api/v1/navigation/goal", headers=OPERATOR,
                       json={"x": 1.0, "y": 2.0, "yaw": 0.0})
    assert goal.status_code == 200, goal.json()


def test_lane_keep_start_is_refused_unless_localized(core):
    client, services = core
    services.localization.on_state(_state("SUSPECT"))
    refused = client.put("/api/v1/line-follow/mode", headers=OPERATOR, json={"mode": "CAMERA_LINE"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "NOT_LOCALIZED"
    # Turning it OFF only stops motion and stays open.
    assert client.put("/api/v1/line-follow/mode", headers=OPERATOR,
                      json={"mode": "OFF"}).status_code == 200


def test_lane_keep_start_is_not_gated_on_a_pre_d395_robot(core):
    client, _services = core
    response = client.put("/api/v1/line-follow/mode", headers=OPERATOR, json={"mode": "CAMERA_LINE"})
    assert response.status_code != 409 or response.json()["error"]["code"] != "NOT_LOCALIZED"


# --- gap 6: leaving LOCALIZED stops autonomous motion -----------------------------


def test_leaving_localized_cancels_navigation_and_leaves_navigation_mode(core):
    client, services = core
    _ready_for_goal(services)
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post("/api/v1/navigation/goal", headers=OPERATOR,
                       json={"x": 1.0, "y": 2.0, "yaw": 0.0}).status_code == 200
    services.localization.on_state(_state("SUSPECT"))
    assert services.nav.nav_state.value == "CANCELED"
    assert services.modes.mode.value == "IDLE"
    [event] = [e for e in _types(services, "localization.state") if e.data["state"] == "SUSPECT"]
    assert event.data["previous"] == "LOCALIZED"


def test_leaving_localized_stops_line_follow(core):
    _client, services = core
    from core_api_web.api.deps import LineFollowMode
    services.localization.on_state(_state("LOCALIZED"))
    services.line_follow.set_mode(LineFollowMode.CAMERA_LINE)
    assert services.line_follow.active
    services.localization.on_state(_state("CANDIDATES", request_id="req-1"))
    assert not services.line_follow.active
    assert services.line_follow.mode is LineFollowMode.OFF


def test_leaving_localized_stops_swarm_and_docking(core):
    _client, services = core
    calls = []
    services.swarm.cancel = lambda source="api", reason="canceled": calls.append(("swarm", reason))
    services.docking.cancel = lambda: calls.append(("docking", None))
    services.localization.on_state(_state("LOCALIZED"))
    services.localization.on_state(_state("UNKNOWN"))
    assert ("swarm", "localization") in calls and ("docking", None) in calls


def test_a_stale_state_topic_stops_autonomy(core):
    _client, services = core
    clock = _Clock()
    services.localization._monotonic = clock
    cancels = []
    services.nav.cancel = lambda source="api", **_: cancels.append(source)
    services.localization.on_state(_state("LOCALIZED"))
    cancels.clear()                       # entering LOCALIZED cancels too; not this test
    clock.now += 3.5
    services.localization.tick(odom_owns_pose=False)
    assert cancels == ["localization"]


def test_manual_teleop_survives_leaving_localized(core):
    client, services = core
    services.state.set_velocity(0.0, 0.0)
    services.localization.on_state(_state("LOCALIZED"))
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    services.localization.on_state(_state("SUSPECT"))
    assert services.modes.mode.value == "MANUAL"
    drive = client.post("/api/v1/teleop", json={"linear": 0.1, "angular": 0.0}, headers=OPERATOR)
    assert drive.status_code == 200, drive.json()


def test_docking_and_swarm_follow_start_are_refused_unless_localized(core_client):
    client, services = core_client(capabilities={"docking": {"supported": True}})
    services.localization.on_state(_state("SUSPECT"))
    follow = {"target_robot_id": "rosy_02"}
    for path, body in (("/api/v1/docking/dock", {"dock": None}), ("/api/v1/swarm/follow", follow)):
        refused = client.post(path, headers=OPERATOR, json=body)
        assert refused.status_code == 409, (path, refused.json())
        assert refused.json()["error"]["code"] == "NOT_LOCALIZED", path


def test_a_pre_d395_robot_is_unaffected(core):
    client, services = core
    _ready_for_goal(services)
    assert client.post("/api/v1/navigation/goal", headers=OPERATOR,
                       json={"x": 1.0, "y": 2.0, "yaw": 0.0}).status_code == 200
    for _ in range(3):
        services.localization.tick(odom_owns_pose=True)
    assert services.nav.nav_state.value != "CANCELED"
    assert services.modes.mode.value == "NAVIGATION"
    for path in ("/api/v1/docking/dock", "/api/v1/swarm/follow"):
        response = client.post(path, headers=OPERATOR, json={})
        assert response.status_code != 409 or response.json()["error"]["code"] != "NOT_LOCALIZED"


# --- review item 4: an odom pose is not a trusted LOCALIZED pose --------------------


def test_localized_in_the_odom_frame_is_refused(core):
    client, services = core
    _ready_for_goal(services)
    services.localization.on_state(_state("LOCALIZED", frame="map"))
    services.localization.tick(odom_owns_pose=True)
    refused = client.post("/api/v1/navigation/goal", headers=OPERATOR,
                          json={"x": 1.0, "y": 2.0, "yaw": 0.0})
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "NOT_LOCALIZED"
    assert refused.json()["error"]["detail"]["pose_frame"] == "odom"
    assert refused.json()["error"]["detail"]["state"] == "LOCALIZED"


# --- review item 2: the halt and a start are ordered, not interleaved -------------


def test_a_halt_arriving_between_the_check_and_the_start_cancels_the_start(core):
    """The state drops to SUSPECT after `require_localized` passed but before the
    goal is sent. The halt must wait for the start and then fold it, never run
    first and let the goal through afterwards."""
    import threading

    client, services = core
    _ready_for_goal(services)
    services.localization.on_state(_state("LOCALIZED"))
    original = services.nav.resolve_goal
    halt_thread: dict = {}

    def resolve_then_lose_localization(**kwargs):
        worker = threading.Thread(
            target=services.localization.on_state, args=(_state("SUSPECT"),), daemon=True)
        worker.start()
        worker.join(timeout=0.3)
        halt_thread["finished_before_start"] = not worker.is_alive()
        halt_thread["worker"] = worker
        return original(**kwargs)

    services.nav.resolve_goal = resolve_then_lose_localization
    response = client.post("/api/v1/navigation/goal", headers=OPERATOR,
                           json={"x": 1.0, "y": 2.0, "yaw": 0.0})
    halt_thread["worker"].join(timeout=5.0)

    assert response.status_code == 200
    assert halt_thread["finished_before_start"] is False   # the halt waited for the start
    assert services.nav.nav_state.value == "CANCELED"       # and then folded it
    assert services.modes.mode.value == "IDLE"
