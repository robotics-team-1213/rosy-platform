"""D-1079: queued navigation cannot admit after its receive-relative deadline."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace

import pytest

from core_api_web.api.v1 import navigation
from core_features.navigation import goal_contract
from core_features.waypoints.manager import Waypoint
from test_map_snapshots import GRID

OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
LINE_STOP = {"lease_id": "lease-1", "trip_id": "trip-7", "junction_seq": 12, "stop_place_id": "S3_entry"}
STARTS = [
    ("goal", {"x": 1., "y": 0.}),
    ("bound-goal", {"x": 1., "y": 0., "expected_map_grid_id": "grid", "correlation_id": "s3"}),
    ("line-handoff-goal", {"x": 1., "y": 0., "expected_map_grid_id": "grid", "correlation_id": "s3", **LINE_STOP}),
    ("home", {}),
    ("route", {"points": [{"x": 1., "y": 0., "kind": "stop"}]}),
    ("bound-route", {"points": [{"x": 1., "y": 0., "kind": "stop"}], "expected_map_grid_id": "grid"}),
]


def ready(core_client, monkeypatch):
    tc, svc = core_client()
    svc.state.set_velocity(0., 0.)
    monkeypatch.setattr(navigation, "require_kept", lambda *_: None)
    svc.state.set_map_id("map", "grid")
    svc.state.set_pose(0., 0., 0.)
    svc.maps.set_map(GRID, map_id="map")
    svc.waypoints.create(Waypoint(name="__home__", x=0., y=0.))
    sent = []
    pose = SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=0., y=0.)))
    svc.nav.executor = SimpleNamespace(
        send_goal=lambda spec, **kw: sent.append(spec),
        send_native_path=lambda route, run_id, **kw: sent.append((route, str(run_id))),
        compute_navigation_path=lambda *a, **kw: SimpleNamespace(poses=[pose]),
        native_transport_snapshot=lambda: (0, False, False),
        path_controller_ready=lambda: True,
        cancel_goal=lambda: None,
    )
    now = [10.]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(navigation, "time", clock)
    monkeypatch.setattr(goal_contract, "time", clock)
    return tc, svc, now, sent


def prepare_start(tc, svc, path, body):
    payload = dict(body)
    if path not in {"bound-goal", "line-handoff-goal"}:
        return payload
    plan_body = {"x": payload["x"], "y": payload["y"], "expected_map_grid_id": payload["expected_map_grid_id"],
                 "correlation_id": payload["correlation_id"]}
    if path == "line-handoff-goal":
        assert tc.put("/api/v1/trip-lease", headers=OPERATOR, json={
            "lease_id": "lease-1", "trip_id": "trip-7", "holder": "site-a", "operator_name": "kim", "ttl_s": 5
        }).status_code == 200
        assert tc.put("/api/v1/line-follow/mode", headers=OPERATOR, json={"mode": "CAMERA_LINE"}).status_code == 200
        line = svc.line_follow
        line._junction_seq = 12
        line._junction = {"seq": 12, "place_id": "S3_entry", "action": "stop", "state": "executing", "held": True}
        line._status = line._status.model_copy(update={"state": "HOLD", "reason": "junction_stop"})
        plan_body["line_stop"] = dict(LINE_STOP)
    plan = tc.post("/api/v1/navigation/bound-plan", headers=OPERATOR, json=plan_body)
    assert plan.status_code == 200, plan.text
    owner = tc.get("/api/v1/navigation/state", headers=OPERATOR).json()["owner"]
    payload["plan_id"] = plan.json()["plan_id"]
    if path == "line-handoff-goal":
        payload.update(expected_boot_id=owner["boot_id"], expected_owner_generation=owner["owner_generation"])
    return payload


@pytest.mark.parametrize("path, body", STARTS)
@pytest.mark.parametrize("budget, wait, status", [(3., 3., 200), (3., 3.001, 409), (None, 100., 200)])
def test_deadline_includes_localization_wait(core_client, monkeypatch, path, body, budget, wait, status):
    tc, svc, now, sent = ready(core_client, monkeypatch)
    payload = prepare_start(tc, svc, path, body)
    original = navigation.localized_start

    @contextmanager
    def delayed(service):
        now[0] += wait
        with original(service):
            yield

    monkeypatch.setattr(navigation, "localized_start", delayed)
    if budget is not None:
        payload["admit_within_s"] = budget
    reply = tc.post("/api/v1/navigation/" + path, headers=OPERATOR, json=payload)
    assert reply.status_code == status, reply.text
    assert bool(sent) is (status == 200)
    assert svc.nav._admitting is None
    if status == 409:
        assert reply.json()["error"]["code"] == "MOTION_ADMIT_DEADLINE_EXCEEDED"
        assert svc.nav.native.current is None


@pytest.mark.parametrize("path, body", STARTS)
def test_deadline_includes_nav_lock_wait(core_client, monkeypatch, path, body):
    tc, svc, now, sent = ready(core_client, monkeypatch)
    payload = prepare_start(tc, svc, path, body)
    payload["admit_within_s"] = 3.
    entered = Event()
    original = navigation.localized_start

    @contextmanager
    def notify(service):
        with original(service):
            entered.set()
            yield

    monkeypatch.setattr(navigation, "localized_start", notify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with svc.nav._lock:
            future = pool.submit(tc.post, "/api/v1/navigation/" + path, headers=OPERATOR, json=payload)
            assert entered.wait(5.)
            now[0] += 4.
        reply = future.result(timeout=5.)
    assert reply.status_code == 409 and not sent
    assert reply.json()["error"]["code"] == "MOTION_ADMIT_DEADLINE_EXCEEDED"


def test_receive_time_precedes_sync_dependencies(core_client, monkeypatch):
    tc, svc, now, sent = ready(core_client, monkeypatch)

    # Authenticate normally, then delay the service dependency before the sync handler enters.
    def services():
        now[0] += 4.
        return svc

    tc.app.dependency_overrides[navigation.get_services] = services
    reply = tc.post("/api/v1/navigation/goal", headers=OPERATOR,
                    json={"x": 1., "y": 0., "admit_within_s": 3.})
    assert reply.status_code == 409 and not sent
    assert reply.json()["error"]["code"] == "MOTION_ADMIT_DEADLINE_EXCEEDED"


@pytest.mark.parametrize("model", [navigation.GoalRequest, navigation.BoundGoalRequest,
    navigation.BoundPlanRequest, navigation.LineHandoffGoalRequest, navigation.HomeRequest,
    navigation.RouteRequest, navigation.BoundRouteRequest])
def test_all_navigation_models_declare_bounded_finite_deadline(model):
    field = model.model_json_schema()["properties"]["admit_within_s"]
    number = next(option for option in field["anyOf"] if option.get("type") == "number")
    assert number["exclusiveMinimum"] == 0 and number["maximum"] == 10


@pytest.mark.parametrize("value", [0., -1., 10.001, float("inf"), float("nan")])
def test_deadline_rejects_invalid_values(value):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        navigation.GoalRequest(x=1., y=0., admit_within_s=value)


def test_capabilities_announce_admit_deadline(core_client):
    tc, _svc = core_client()
    reply = tc.get("/api/v1/system/capabilities", headers=OPERATOR)
    assert reply.status_code == 200
    assert reply.json()["navigation"]["admit_deadline"] is True
    assert reply.json()["navigation"]["generation_fence"] is True


@pytest.mark.parametrize("path, body", STARTS)
def test_idle_cancel_generation_fence_causes_no_motion_and_rejects_late_start(core_client, monkeypatch, path, body):
    tc, svc, _now, sent = ready(core_client, monkeypatch)
    payload = prepare_start(tc, svc, path, body)
    cancels = []
    svc.nav.executor.cancel_goal = lambda: cancels.append(True)
    before = tc.get("/api/v1/navigation/state", headers=OPERATOR).json()["owner"]
    events_before = len(svc.events.history(since_seq=None, limit=1000))

    plain = tc.post("/api/v1/navigation/cancel", headers=OPERATOR)
    assert plain.status_code == 200
    assert tc.get("/api/v1/navigation/state", headers=OPERATOR).json()["owner"] == before

    fenced = tc.post("/api/v1/navigation/cancel", headers=OPERATOR, json={"advance_generation": True})
    assert fenced.status_code == 200
    owner = fenced.json()["owner"]
    assert owner["boot_id"] == before["boot_id"]
    assert owner["owner_generation"] == before["owner_generation"] + 1
    assert not sent and not cancels
    assert (svc.modes.mode.value in {"IDLE", "LINE_FOLLOW"}
            or path == "line-handoff-goal" and svc.modes.mode.value == "NAVIGATION"
            and svc.line_follow.status().state == "HOLD") and svc.nav.nav_state.value == "IDLE"
    assert svc.command.select_output().linear == svc.command.select_output().angular == 0.0
    assert len(svc.events.history(since_seq=None, limit=1000)) == events_before

    payload.update(admit_within_s=3., expected_boot_id=before["boot_id"],
                   expected_owner_generation=before["owner_generation"])
    late = tc.post("/api/v1/navigation/" + path, headers=OPERATOR, json=payload)
    assert late.status_code == 409 and not sent
    assert late.json()["error"]["code"] == "OWNER_GENERATION_CHANGED"
    assert (svc.modes.mode.value in {"IDLE", "LINE_FOLLOW"}
            or path == "line-handoff-goal" and svc.modes.mode.value == "NAVIGATION"
            and svc.line_follow.status().state == "HOLD") and svc.nav.nav_state.value == "IDLE"
