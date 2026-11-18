"""SLAM fallback wiring: the adapter's measurements, the localization hold, the readiness swap, the state block and the routes."""
import base64
import hashlib
import json
import math
from types import SimpleNamespace

import pytest

from core.slam_fallback_wiring import Evidence, MapOdomJump, build_slam_fallback
from core_common.protocol.localization import LocalizationStatus, LocState, PoseFrame
from core_features.localization.assist import LocalizationAssist
from core_features.localization.slam_fallback import SPOOL_IMAGE, SPOOL_META, SPOOL_NAME, STATE_NAME, STOP_EVIDENCE_NAME
from core_features.navigation.readiness import NavigationReadinessGate
from core_features.state.manager import StateManager


class FakeState:
    def __init__(self, map_pose=(1.0, 2.0, 0.3), odom=(0.5, 0.5, 0.1), map_age=0.1, odom_age=0.1, frame="map"):
        self.map_pose, self.odom, self.map_age, self.odom_age, self.frame = map_pose, odom, map_age, odom_age, frame

    def pose_sample(self):
        return (*self.map_pose, self.frame, self.map_age)

    def odom_sample(self):
        return None if self.odom is None else (*self.odom, self.odom_age)


def test_a_steady_map_to_odom_transform_reports_no_jump_and_a_step_reports_its_size():
    state = FakeState()
    jump = MapOdomJump(state)
    assert jump() is None  # the first sample has nothing to compare with
    assert jump() == pytest.approx(0.0, abs=1e-9)
    state.map_pose = (1.3, 2.0, 0.3)  # SLAM moved the map frame under the robot by 0.3 m
    assert jump() == pytest.approx(0.3, abs=1e-9)


def test_a_stale_or_missing_pose_gives_no_measurement_and_forgets_the_last_one():
    state = FakeState()
    jump = MapOdomJump(state)
    jump()
    state.odom_age = 5.0
    assert jump() is None
    state.odom_age = 0.1
    assert jump() is None  # restarted from nothing, so no jump is invented across the gap
    state.odom = None
    assert jump() is None
    state.frame = "odom"
    assert jump() is None


def test_fleet_fed_evidence_expires():
    now = [0.0]
    evidence = Evidence(clock=lambda: now[0])
    assert evidence.fresh() == {}
    evidence.note(gap_m=0.4, map_verdict="warn")
    assert evidence.fresh()["gap_m"] == 0.4
    now[0] = 11.0
    assert evidence.fresh() == {}


class Events:
    def __init__(self):
        self.items = []

    def publish(self, kind, severity="info", source="", data=None):
        self.items.append((kind, severity))


def assist():
    return LocalizationAssist(Events(), robot_id=lambda: "r1")


def test_a_hold_makes_a_robot_with_no_report_read_unknown_and_refuses_autonomy():
    loc = assist()
    assert loc.status() is None and loc.autonomy_allowed() is True  # a robot that predates D-395
    loc.hold = lambda: "slam_fallback_stopping"
    status = loc.status()
    assert status.state is LocState.UNKNOWN and status.pose_frame is PoseFrame.ODOM and status.reason == "slam_fallback_stopping"
    assert loc.autonomy_allowed() is False and loc.reporting is False
    loc.hold = lambda: None
    assert loc.status() is None and loc.autonomy_allowed() is True


def test_the_halt_runs_when_the_hold_starts():
    halted = []
    loc = LocalizationAssist(Events(), robot_id=lambda: "r1", on_lost=lambda: halted.append(1))
    loc.hold = lambda: "slam_fallback_stopping"
    loc.tick(False)
    assert halted == [1]


def report(loc, state):
    loc.on_state(json.dumps({"status": LocalizationStatus(state=state, pose_frame=PoseFrame.MAP).model_dump(mode="json")}))


def test_the_hold_beats_a_localized_report_but_lets_the_rest_of_the_state_through_to_fleet():
    loc = assist()
    held = [True]
    loc.hold = lambda: "slam_fallback_waiting_pose" if held[0] else None
    report(loc, LocState.LOCALIZED)  # the old SLAM pose, still fresh
    assert loc.status().state is LocState.UNKNOWN and loc.status().reason == "slam_fallback_waiting_pose"
    assert loc.autonomy_allowed() is False
    assert loc.raw_status().state is LocState.LOCALIZED  # what the supervisor's own exit test reads
    report(loc, LocState.CANDIDATES)  # Fleet must still see the open question, or nobody can answer it
    assert loc.status().state is LocState.CANDIDATES and loc.autonomy_allowed() is False
    report(loc, LocState.LOCALIZED)
    held[0] = False  # only the supervisor releases the hold
    assert loc.status().state is LocState.LOCALIZED and loc.autonomy_allowed() is True
    assert loc.reports == 3


def test_the_readiness_profile_can_be_swapped_but_only_to_known_components():
    gate = NavigationReadinessGate(required=True, required_components=["slam_toolbox", "motor_adapter"])
    gate.set_required_components(["amcl", "map_server", "motor_adapter"])
    assert gate.required_components == ("amcl", "map_server", "motor_adapter")
    for bad in ([], ["nope"], "amcl"):
        with pytest.raises(ValueError):
            gate.set_required_components(bad)
    assert gate.required_components == ("amcl", "map_server", "motor_adapter")


def test_the_state_snapshot_carries_the_block_and_null_when_the_supervisor_is_off():
    state = StateManager("r1")
    assert state.snapshot().slam_fallback is None
    state.slam_fallback_provider = lambda: {"phase": "STOPPING", "reason": "map_odom_jump", "since": 1.0}
    assert state.snapshot().slam_fallback.phase == "STOPPING"
    state.slam_fallback_provider = lambda: None
    assert state.snapshot().slam_fallback is None


def test_a_slam_fallback_that_cannot_be_built_leaves_core_running_without_it(monkeypatch):
    import core.slam_fallback_wiring as wiring
    from core.services import _build_slam_fallback

    def broken(config, **parts):
        raise RuntimeError("wiring broke")

    monkeypatch.setattr(wiring, "build_slam_fallback", broken)
    assert _build_slam_fallback({}) is None


class FakeHost:
    def __init__(self):
        self.sent = []

    def request(self, command, *, role, user_id="", confirmed=False, params=None, idempotency_key=None):
        self.sent.append((command, role, params))
        return SimpleNamespace(ok=True, code="OK", data={"phase": "IDLE"}, detail="")


def parts(tmp_path, backend):  # a marker file in tmp_path is a restart after the switch
    state = StateManager("r1")
    events = Events()
    loc = assist()
    nav = SimpleNamespace(nav_state=SimpleNamespace(), cancel=lambda **k: False)
    readiness = NavigationReadinessGate(required=True, required_components=["slam_toolbox", "motor_adapter"])
    host = FakeHost()
    config = {"runtime": {"navigation_backend": backend},
              "navigation": {"readiness": {"profiles": {"localization": ["amcl", "map_server", "motor_adapter"]}}}}
    fallback = build_slam_fallback(
        config, state=state, nav=nav, command=SimpleNamespace(clear_navigation=lambda: None, clear_manual=lambda: None),
        modes=SimpleNamespace(mode=None), line_follow=SimpleNamespace(active=False, stop=lambda: None),
        docking=SimpleNamespace(active=False, cancel=lambda: None), swarm=SimpleNamespace(active=False, cancel=lambda **k: None),
        assist=loc, readiness=readiness, events=events, host_client=host, folder=tmp_path)
    return fallback, state, loc, readiness, host


def test_a_localization_backend_gets_an_inert_supervisor_and_no_block(tmp_path):
    fallback, state, loc, _, host = parts(tmp_path, "localization")
    assert fallback.enabled is False and state.snapshot().slam_fallback is None and loc.hold() is None
    fallback.tick()
    assert host.sent == []


def test_the_slam_supervisor_is_bound_to_the_hold_and_the_state_block(tmp_path):
    fallback, state, loc, readiness, host = parts(tmp_path, "slam")
    assert fallback.enabled and state.snapshot().slam_fallback.phase == "MONITORING"
    fallback._go("STOPPING", "map_odom_jump")
    assert loc.status().reason == "slam_fallback_stopping" and state.snapshot().slam_fallback.reason == "map_odom_jump"


def test_the_host_calls_carry_the_machine_grade_and_the_swap_follows_the_profile(tmp_path):
    fallback, _, _, readiness, host = parts(tmp_path, "slam")
    fallback.stage()
    assert host.sent[0] == ("navigation_fallback.stage", "machine", None)
    fallback._p.after_switch()
    assert readiness.required_components == ("amcl", "map_server", "motor_adapter")


def test_the_stop_evidence_is_written_atomically_for_the_host_half(tmp_path):
    fallback, *_ = parts(tmp_path, "slam")
    fallback._p.write_evidence({"written_at": 1.0, "zero_since": None, "goal_active": False})
    written = json.loads((tmp_path / STOP_EVIDENCE_NAME).read_text(encoding="utf-8"))
    assert written["goal_active"] is False and "boot_id" in written  # the host compares the boot, not a wall clock
    assert not list(tmp_path.glob("*.tmp"))


def test_the_wait_for_a_pose_survives_a_core_restart_on_the_localization_backend(tmp_path):
    fallback, state, loc, *_ = parts(tmp_path, "slam")
    fallback._p.after_switch()
    fallback._enter_waiting()  # the supervisor has just seen SWITCHED
    assert json.loads((tmp_path / STATE_NAME).read_text(encoding="utf-8"))["since"] is not None
    again, state2, loc2, *_ = parts(tmp_path, "localization")  # CORE restarted: runtime.env now says localization
    assert again.phase == "WAITING_LOCALIZATION" and state2.snapshot().slam_fallback.fallback_active is True
    report(loc2, LocState.LOCALIZED)  # a pose claim from the new navigation is still held until the supervisor confirms it
    assert loc2.status().state is LocState.UNKNOWN and loc2.autonomy_allowed() is False
    assert parts(tmp_path / "other", "localization")[0].enabled is False  # no marker, no supervisor


def pgm(width=4, height=3):
    return f"P5\n{width} {height}\n255\n".encode() + bytes([254]) * (width * height)


def route_body(pgm_bytes=None, sha=None):
    from core_api_web.api.v1.slam_fallback import WallMapBody
    content = pgm() if pgm_bytes is None else pgm_bytes
    return WallMapBody(map_id="site-a", version=2, sha256=sha or hashlib.sha256(content).hexdigest(), resolution=0.025,
                       origin=[0.0, 0.0, 0.0], pgm_base64=base64.b64encode(content).decode())


def test_the_wall_map_route_checks_the_sha_spools_atomically_and_asks_the_host_to_stage(tmp_path, monkeypatch):
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1 import slam_fallback as route
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    fallback, *_ = parts(tmp_path, "slam")
    svc = SimpleNamespace(slam_fallback=fallback)
    with pytest.raises(ApiError) as bad:
        route.wall_map(route_body(sha="0" * 64), None, svc)
    assert bad.value.code == "SHA256_MISMATCH" and not (tmp_path / SPOOL_NAME).exists()
    assert route.wall_map(route_body(), None, svc)["staged"] is True
    meta = json.loads((tmp_path / "wall-map-spool" / "meta.json").read_text(encoding="utf-8"))
    assert meta["version"] == 2 and "pgm_base64" not in meta and (tmp_path / SPOOL_NAME / SPOOL_IMAGE).read_bytes() == pgm()
    assert (tmp_path / SPOOL_NAME / SPOOL_META).is_file()


def test_the_wall_map_route_refuses_while_a_switch_runs_and_a_non_finite_origin_never_gets_in(tmp_path, monkeypatch):
    from pydantic import ValidationError
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1 import slam_fallback as route
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    fallback, *_ = parts(tmp_path, "slam")
    fallback._go("SWITCHING")
    with pytest.raises(ApiError) as running:
        route.wall_map(route_body(), None, SimpleNamespace(slam_fallback=fallback))
    assert running.value.code == "SWITCH_RUNNING" and not (tmp_path / SPOOL_NAME).exists()
    body = route_body().model_dump()
    for bad in ([math.inf, 0.0, 0.0], [math.nan, 0.0, 0.0], [5000.0, 0.0, 0.0]):
        with pytest.raises(ValidationError):
            route.WallMapBody(**{**body, "origin": bad})
    for resolution in (0.0, 0.005, 0.5, math.inf):
        with pytest.raises(ValidationError):
            route.WallMapBody(**{**body, "resolution": resolution})


def test_the_routes_refuse_on_a_localization_backend_and_reset_needs_confirm(tmp_path):
    from core_api_web.api.errors import ApiError
    from core_api_web.api.v1 import slam_fallback as route
    inert = SimpleNamespace(slam_fallback=parts(tmp_path, "localization")[0])
    with pytest.raises(ApiError) as refused:
        route.wall_map(route_body(), None, inert)
    assert refused.value.code == "NOT_SLAM_BACKEND"
    live = SimpleNamespace(slam_fallback=parts(tmp_path, "slam")[0])
    with pytest.raises(ApiError) as unconfirmed:
        route.reset(None, live, confirm=False)
    assert unconfirmed.value.code == "CONFIRM_REQUIRED"
    assert route.reset(None, live, confirm=True) == {"reset": False}  # nothing failed: nothing to reset


def test_a_failing_builder_with_a_marker_present_refuses_goals_and_without_one_changes_nothing(tmp_path, monkeypatch):
    import core.slam_fallback_wiring as wiring
    from core.services import _build_slam_fallback
    monkeypatch.setenv("STATE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(wiring, "build_slam_fallback", lambda config, **parts: 1 / 0)
    loc = assist()
    assert _build_slam_fallback({}, assist=loc) is None and loc.hold is None and loc.autonomy_allowed() is True
    (tmp_path / STATE_NAME).write_text("{not json", encoding="utf-8")
    assert _build_slam_fallback({}, assist=loc) is None
    assert loc.status().reason == "slam_fallback_unavailable" and loc.autonomy_allowed() is False


def test_a_corrupt_marker_file_makes_the_supervisor_hold(tmp_path):
    (tmp_path / STATE_NAME).write_text("{not json", encoding="utf-8")
    fallback, _, loc, *_ = parts(tmp_path, "localization")
    assert fallback.phase == "WAITING_LOCALIZATION" and loc.autonomy_allowed() is False


def test_a_fleet_pose_answer_does_not_resume_line_follow_while_the_hold_is_on():
    loc = assist()
    resumed = []
    loc.on_pose_answered = lambda: resumed.append(1)
    loc.publish_decision = lambda payload: None
    request = loc.pose_requests.open("fleet_required", {})["request_id"]
    from core_common.protocol.localization import DecisionSource, LocalizationDecision, MapPose
    loc.decide(LocalizationDecision(request_id=request, pose=MapPose(x=1, y=2, yaw=0), source=DecisionSource.OVERHEAD))
    loc.hold = lambda: "slam_fallback_waiting_pose"
    loc.on_result(json.dumps({"request_id": request, "accepted": True, "state": "LOCALIZED"}))
    assert resumed == [] and loc.pose_requests.current() is not None
    loc.hold = lambda: None
    loc.on_result(json.dumps({"request_id": request, "accepted": True, "state": "LOCALIZED"}))
    assert resumed == [1]
