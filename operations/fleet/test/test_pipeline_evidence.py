"""D-1057: measured admission evidence for cell tasks (AMR and OMX owner), with the guards left unchanged."""
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from core_common.protocol.evidence import EvidenceState, ValueEvidence
from core_common.protocol.schemas import StateSnapshot
from core_common.protocol.state_components import SafetySummary, Velocity
from fleet.hub.registry import RobotRegistry
from fleet.pipeline import resolve_omx_cells
from fleet.server.auth.site_auth import build_authorize, build_role_guards
from fleet.server.sitemap import pipeline_evidence as ev
from fleet.server.sitemap.pipeline_evidence import amr_evidence, omx_owner_evidence
from fleet.server.sitemap.pipeline_routes import install_pipeline_routes
from rosy_account.principal import SitePrincipal

OP = {"Authorization": "Bearer operator"}
SVC = {"Authorization": "Bearer service"}
VIEW = {"Authorization": "Bearer viewer"}
TASK = "evidence-task"
OTHER = {"Authorization": "Bearer other"}
CONSOLE = {"Authorization": "Bearer console"}


@pytest.fixture(autouse=True)
def _cell_owners(monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service,other;cell_ab=service")


def _snapshot(v=0.0, w=0.0, mode="IDLE", nav="IDLE", estop=False, fresh=True, vel_at=None):
    stamp = datetime.fromtimestamp(vel_at or time.time(), tz=timezone.utc).isoformat(timespec="milliseconds")
    velocity = ValueEvidence(received_at=stamp, stale_after_s=0.5,
                             evidence=EvidenceState.FRESH if fresh else EvidenceState.DELAYED)
    return StateSnapshot(robot_id="pinky_1", mode=mode, navigation=nav, velocity=Velocity(linear=v, angular=w),
                         safety=SafetySummary(estop=estop), evidence={"velocity": velocity})


class Env:
    def __init__(self, via="direct", cell="cell_s"):
        from tools.sim.bay_departure_sim import build_world_261026_site_map

        site, graph, _ = build_world_261026_site_map()
        self.station = resolve_omx_cells(site, graph)[cell].station_xy
        principals = {sha256(t.encode()).hexdigest(): SitePrincipal(t, t) for t in ("viewer", "service", "operator")}
        principals[sha256(b"other").hexdigest()] = SitePrincipal("other", "service")
        principals[sha256(b"console").hexdigest()] = SitePrincipal("site-console", "operator")
        require_viewer, require_operator, _, require_proposer = build_role_guards(
            build_authorize(None, principals, None), principals)
        self.app = app = FastAPI()
        app.state.operator_guard = [Depends(require_operator)]
        app.state.proposer_guard = [Depends(require_proposer)]
        app.state.amr_still_autostart = False  # no sampling thread in tests: the tracker is fed by hand
        self.registry = RobotRegistry()
        self.console = SimpleNamespace(hub=SimpleNamespace(registry=self.registry), _state_sink=None)
        self.console.set_state_sink = lambda sink: setattr(self.console, "_state_sink", sink)
        app.state.console = self.console
        self.pose = SimpleNamespace(state="LOCALIZED", source="sighting", x=self.station[0], y=self.station[1],
                                    yaw=0.1, age_s=0.3, map_id="m1")
        app.state.map_pose = SimpleNamespace(arbitrated_pose=lambda rid: self.pose, active_map_id=lambda: "m1")
        app.state.site_maps = SimpleNamespace(active=lambda: (1, site, graph, None),
                                              rules=SimpleNamespace(active_rules=lambda: None))
        if via == "direct":
            install_pipeline_routes(
                app, site_maps=app.state.site_maps, read_guard=[Depends(require_viewer)],
                amr_evidence_fn=lambda t: amr_evidence(app, t), omx_evidence_fn=lambda t: omx_owner_evidence(app, t))
        elif via == "charge_bay":  # the evidence functions are wired by the production assembly, not passed here
            from fleet.server.charge_bay_routes import install_charge_bay_routes

            async def gathered():
                return {"robots": []}

            install_charge_bay_routes(app, SimpleNamespace(_clock=lambda: 0.0), gathered, [Depends(require_viewer)])
        else:
            from unittest.mock import MagicMock
            from fleet.server.sitemap.site_map_routes import install_site_map_routes

            maps = MagicMock()
            maps.active = app.state.site_maps.active
            maps.rules.active_rules = lambda: None
            install_site_map_routes(app, site_maps=maps, route_active=lambda: None,
                                    read_guard=[Depends(require_viewer)], require_named_operator=require_operator)
        self.client = TestClient(app)
        self.beat()
        self.task = self.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
            "task_id": TASK, "cell_id": cell, "arm_id": "arm_s" if cell == "cell_s" else "arm_a", "robot_id": "pinky_1",
            "src_site": "pinky", "dst_site": "belt", "tier": 1}).json()["task"]

    def beat(self, snapshot=None, age=0.1, still_s=1.5):
        """A heartbeat that arrived `age` s ago; `still_s` of earlier still samples are fed to the tracker."""
        row = self.registry.record("pinky_1")
        row.online, row.snapshot = True, snapshot or _snapshot()
        row.last_heartbeat_monotonic = time.monotonic() - age
        tracker = ev._tracker(self.app)
        tracker._rows.pop("pinky_1", None)
        if still_s:
            tracker.feed("pinky_1", row.last_heartbeat_monotonic - still_s, time.time() - age - still_s, True)

    def amr(self):
        return amr_evidence(self.app, self.app.state.omx_cell_tasks[TASK])

    def confirm_bed(self):
        return self.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/bed-confirm", headers=OP,
                                json={"robot_id": "pinky_1"})


@pytest.fixture
def env():
    return Env()


@pytest.mark.parametrize("via", ["charge_bay", "site_map"])
def test_both_production_assemblies_run_a_task_from_queued_to_completed(via):
    env = Env(via)
    lease = _claimed(env)
    parts, digest = _owner_parts(lease)
    assert _post_owner(env, lease, parts).status_code == 200
    done = _complete(env, parts, digest)
    assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED"


def test_measured_evidence_has_every_field_and_the_guard_accepts_it(env):
    assert env.confirm_bed().status_code == 200
    got = env.amr()
    assert got["wheel_brake_locked"] is True and got["bed_ready"] is True and got["v_cmd_mps"] == 0.0
    assert got["robot_id"] == "pinky_1" and got["cell_id"] == "cell_s"
    assert 0 <= time.time() - got["observed_at"] <= 2.0
    claimed = env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": "cell_s"}).json()
    assert claimed["claimed"] is True


def test_claim_is_refused_without_a_bed_confirmation(env):
    got = env.amr()
    assert got["bed_ready"] is False
    res = env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": "cell_s"}).json()
    assert res["claimed"] is False and res["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"


@pytest.mark.parametrize("change", ["no_heartbeat", "offline", "old_heartbeat", "velocity_delayed", "velocity_missing",
                                    "no_pose", "unknown_pose", "degraded", "bridged", "old_pose", "other_map", "outside_zone"])
def test_missing_or_stale_measurement_returns_none(env, change):
    if change == "no_heartbeat":
        env.registry._robots.clear()
    elif change == "offline":
        env.registry.record("pinky_1").online = False
    elif change == "old_heartbeat":
        env.beat(age=2.5)
    elif change == "velocity_delayed":
        env.beat(_snapshot(fresh=False))
    elif change == "velocity_missing":
        env.beat(_snapshot().model_copy(update={"evidence": {}}))
    elif change == "no_pose":
        env.app.state.map_pose = SimpleNamespace(arbitrated_pose=lambda rid: None, active_map_id=lambda: "m1")
    elif change == "unknown_pose":
        env.pose.state = "UNKNOWN"
    elif change == "degraded":
        env.pose.state = "DEGRADED"
    elif change == "bridged":
        env.pose.source = "bridged"
    elif change == "old_pose":
        env.pose.age_s = 2.5
    elif change == "other_map":
        env.pose.map_id = "m2"
    else:
        env.pose.x += ev.STOP_ZONE_RADIUS_M + 0.05
    assert env.amr() is None


def test_boundaries_are_allowed_and_the_observation_is_never_in_the_future(env):
    env.pose.age_s = ev.POSE_MAX_AGE_S
    env.beat(_snapshot(vel_at=time.time() + 30), age=ev.HEARTBEAT_MAX_AGE_S - 0.2)
    got = env.amr()
    assert got is not None and got["observed_at"] <= time.time()
    env.pose.age_s = 0.1
    env.pose.x = env.station[0] + ev.STOP_ZONE_RADIUS_M - 0.01
    assert env.amr() is not None


@pytest.mark.parametrize("snapshot", [_snapshot(v=0.01), _snapshot(w=0.1), _snapshot(mode="NAVIGATION"),
                                      _snapshot(nav="NAVIGATING"), _snapshot(estop=True)])
def test_a_moving_or_driving_robot_is_not_held_still(env, snapshot):
    env.beat(snapshot)
    got = env.amr()
    assert got is not None and got["wheel_brake_locked"] is False


def test_stillness_needs_a_second_of_samples_without_a_gap(env):
    env.beat(still_s=0.0)
    assert env.amr()["wheel_brake_locked"] is False  # one sample proves nothing
    env.beat(still_s=0.5)
    assert env.amr()["wheel_brake_locked"] is False
    env.beat(still_s=ev.STILL_MIN_S + 0.1)
    assert env.amr()["wheel_brake_locked"] is True
    env.beat(still_s=ev.STILL_MAX_GAP_S + 1.0)  # fed with one sample 3.5 s earlier: the gap voids the run
    tracker = ev._tracker(env.app)
    row = tracker._rows["pinky_1"]
    tracker._rows["pinky_1"] = {**row, "last": row["last"] - 10.0, "mark": -1.0}
    assert env.amr()["wheel_brake_locked"] is False


def test_bed_confirmation_expires_and_dies_when_the_robot_moves(env):
    assert env.confirm_bed().status_code == 200 and env.amr()["bed_ready"] is True
    rec = env.app.state.cell_bed_confirmations[TASK]
    env.pose.x += 0.015
    assert env.amr()["bed_ready"] is True
    env.pose.x += 0.03
    assert env.amr()["bed_ready"] is False
    env.pose.x = env.station[0]
    rec["confirmed_at"] -= ev.BED_CONFIRM_TTL_S + 1
    assert env.amr()["bed_ready"] is False


def test_bed_confirm_endpoint_guards(env):
    url = f"/api/fleet/pipeline/cell-tasks/{TASK}/bed-confirm"
    assert env.client.post(url, headers=SVC, json={"robot_id": "pinky_1"}).status_code == 403
    assert env.client.post(url, headers=VIEW, json={"robot_id": "pinky_1"}).status_code == 403
    assert env.client.post(url, headers=OP, json={"robot_id": "other"}).status_code == 422
    assert env.client.post("/api/fleet/pipeline/cell-tasks/nope/bed-confirm", headers=OP, json={}).status_code == 404
    env.pose.state = "DEGRADED"
    assert env.confirm_bed().json()["detail"]["code"] == "BED_CONFIRM_POSE_UNAVAILABLE"
    env.pose.state = "LOCALIZED"
    ok = env.confirm_bed().json()
    assert ok["confirmation"]["principal_id"] == "operator" and ok["confirmation"]["robot_id"] == "pinky_1"


def _owner_parts(lease, basis="predefined_side_and_top_target_zones", cell="cell_s", **stop):
    stage = {"handoff_lease_id": lease, "directive_id": TASK, "arm_id": "arm_s" if cell == "cell_s" else "arm_a",
             "task_verified": True, "verification": {"verified": True, "basis": basis},
             "place": {"area": "belt", "tier": 1}}
    hardware = {"measured_at": time.time() + 0.05,  # claimed_at is rounded up to 1 ms
                "stop_event": {"command": "stop", "ok": True, "folded": True, "state": [0.0] * 6, **stop}}
    digest = "sha256:" + hashlib.sha256(json.dumps(
        {"task_id": TASK, "lease": lease, "stage_result": stage, "hardware_telemetry": hardware},
        sort_keys=True, default=str).encode()).hexdigest()
    receipt = {"handoff_lease_id": lease, "cell_id": cell, "stage_id": TASK, "phase": "RELEASED",
               "goal_evidence_digest": digest, "physical_completion": True, "simulated_success": False}
    return {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}, digest


def _claimed(env, cell="cell_s"):
    env.confirm_bed()
    claimed = env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": cell}).json()
    assert claimed["claimed"] is True
    return claimed["handoff"]["handoff_lease_id"]


def _post_owner(env, lease, parts, headers=SVC, **over):
    return env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/owner-evidence", headers=headers, json={
        "handoff_lease_id": lease, "measured_at": parts.get("hardware_telemetry", {}).get("measured_at", time.time()), **parts, **over})


def _complete(env, parts, digest):
    env.beat()
    return env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/complete", headers=SVC, json={
        "phase": "RELEASED", "goal_evidence_digest": digest, **parts})


def test_complete_uses_the_stored_owner_evidence(env):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease)
    assert _post_owner(env, lease, parts).json()["recorded"] is True
    done = _complete(env, parts, digest)
    assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED"


def test_complete_without_stored_evidence_is_refused(env):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease)
    res = _complete(env, parts, digest)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE"


def test_a_complete_body_that_differs_from_the_stored_record_is_refused(env):
    lease = _claimed(env)
    stored, digest = _owner_parts(lease)
    assert _post_owner(env, lease, stored).status_code == 200
    forged, forged_digest = _owner_parts(lease, folded=True, extra="body-only")
    res = _complete(env, forged, forged_digest)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_MISMATCH"
    assert env.app.state.omx_cell_tasks[TASK]["status"] == "RUNNING"


def test_measured_unfolded_arm_is_refused_by_the_unchanged_guard(env):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease, folded=False)
    assert _post_owner(env, lease, parts).status_code == 200
    res = _complete(env, parts, digest)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"


def test_stale_stored_evidence_is_not_trusted(env):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease)
    _post_owner(env, lease, parts)
    env.app.state.cell_owner_evidence[TASK]["measured_at"] -= ev.OWNER_EVIDENCE_MAX_AGE_S + 1
    assert _complete(env, parts, digest).json()["detail"]["code"] == "OMX_OWNER_EVIDENCE_UNAVAILABLE"


def test_owner_evidence_post_checks_lease_time_and_state(env):
    url = f"/api/fleet/pipeline/cell-tasks/{TASK}/owner-evidence"
    parts, _ = _owner_parts("x")
    assert env.client.post(url, headers=SVC, json=parts).json()["detail"]["code"] == "CELL_TASK_NOT_RUNNING"
    lease = _claimed(env)
    parts, _ = _owner_parts(lease)
    assert env.client.post(url, headers=VIEW, json=parts).status_code == 403
    assert _post_owner(env, "other-lease", parts).json()["detail"]["code"] == "OWNER_EVIDENCE_LEASE_MISMATCH"
    early = env.app.state.omx_cell_tasks[TASK]["claimed_at"] - 5
    assert _post_owner(env, lease, parts, measured_at=early).json()["detail"]["code"] == "OWNER_EVIDENCE_MEASURED_AT_INVALID"
    assert _post_owner(env, lease, parts, measured_at=time.time() + 60).status_code == 422
    nan_body = json.dumps({"handoff_lease_id": lease, "measured_at": 1.0, **parts}).replace("1.0,", "NaN,", 1)
    assert env.client.post(url, headers=SVC, content=nan_body).json()["detail"]["code"] == "INVALID_OWNER_EVIDENCE"
    assert _post_owner(env, lease, {"receipt": parts["receipt"]}).json()["detail"]["code"] == "INVALID_OWNER_EVIDENCE"
    first = _post_owner(env, lease, parts, measured_at=time.time())
    assert first.json()["recorded"] is True
    stored_at = env.app.state.cell_owner_evidence[TASK]["measured_at"]
    assert _post_owner(env, lease, parts, measured_at=stored_at).json()["recorded"] is False  # same evidence again
    changed, _ = _owner_parts(lease, folded=False)
    assert _post_owner(env, lease, changed).json()["detail"]["code"] == "OWNER_EVIDENCE_ALREADY_RECORDED"


def test_stop_zone_radius_matches_the_charge_bay_claim_radius():
    from fleet.server.charge_bay_routes import CELL_CLAIM_RADIUS_M

    assert ev.STOP_ZONE_RADIUS_M == CELL_CLAIM_RADIUS_M


def test_velocity_must_be_fresh_in_every_sample_and_no_goal_may_be_active(env):
    env.beat(_snapshot(vel_at=time.time() - 5))
    assert env.amr()["wheel_brake_locked"] is False
    env.beat()
    assert env.amr()["wheel_brake_locked"] is True
    env.app.state.console._goals = {"pinky_1": {"goal": 1}}
    assert env.amr()["wheel_brake_locked"] is False
    env.app.state.console._goals = {}
    env.beat(_snapshot(nav="BLOCKED"))
    assert env.amr()["wheel_brake_locked"] is False


def test_only_a_registered_service_principal_may_post_owner_evidence(env, monkeypatch):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease)
    assert _post_owner(env, lease, parts, headers=OP).json()["detail"]["code"] == "OWNER_PRINCIPAL_NOT_REGISTERED"
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_ab=service")
    assert _post_owner(env, lease, parts).status_code == 403  # registered for another cell only
    monkeypatch.delenv("ROSY_FLEET_CELL_OWNERS")
    assert _post_owner(env, lease, parts).status_code == 403  # no setting: nobody
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service,other")
    assert _post_owner(env, lease, parts).status_code == 200
    assert _post_owner(env, lease, parts, headers=OTHER).status_code == 403  # first record is owned by its poster
    env.beat()
    res = env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/complete", headers=OTHER, json={
        "phase": "RELEASED", "goal_evidence_digest": digest, **parts})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "OWNER_PRINCIPAL_NOT_REGISTERED"
    assert env.app.state.omx_cell_tasks[TASK]["status"] == "RUNNING"


def test_zone_needs_an_active_map_id_and_a_real_stop_place(env):
    assert env.amr() is not None
    env.app.state.map_pose.active_map_id = lambda: None
    assert env.amr() is None
    env.app.state.map_pose.active_map_id = lambda: "m1"
    bare = SimpleNamespace(places=[], edges=[])
    env.app.state.site_maps.active = lambda: (1, bare, bare, None)  # resolve_omx_cells then invents default coordinates
    assert env.amr() is None


def test_bed_confirmation_is_named_one_shot_and_dies_for_good(env):
    url = f"/api/fleet/pipeline/cell-tasks/{TASK}/bed-confirm"
    assert env.client.post(url, headers=CONSOLE, json={"robot_id": "pinky_1"}).json()["detail"]["code"] == "NAMED_OPERATOR_REQUIRED"
    first = env.confirm_bed().json()
    assert first["renewed"] is True and first["confirmation"]["map_id"] == "m1"
    rec = env.app.state.cell_bed_confirmations[TASK]
    stamp = rec["confirmed_at"]
    env.pose.x += 0.005
    again = env.confirm_bed().json()
    assert again["renewed"] is False and rec["confirmed_at"] == stamp and rec["pose"]["x"] == env.station[0]
    env.pose.x += 0.05
    assert env.amr()["bed_ready"] is False
    env.pose.x = env.station[0]
    assert env.amr()["bed_ready"] is False  # moving back does not revive it
    assert env.confirm_bed().json()["renewed"] is True  # a new one only after the old one is void
    assert env.amr()["bed_ready"] is True
    env.app.state.map_pose.active_map_id = lambda: "m2"
    env.pose.map_id = "m2"
    assert env.amr()["bed_ready"] is False
    env.app.state.map_pose.active_map_id = lambda: "m1"
    env.pose.map_id = "m1"
    assert env.amr()["bed_ready"] is False  # the map change voided it for good


def test_owner_measured_at_must_be_recent_and_match_the_device_time(env):
    lease = _claimed(env)
    parts, _ = _owner_parts(lease)
    now = time.time()
    code = lambda r: r.json()["detail"]["code"]
    assert code(_post_owner(env, lease, parts, measured_at=now + 5)) == "OWNER_EVIDENCE_MEASURED_AT_INVALID"
    skewed = {**parts, "hardware_telemetry": {**parts["hardware_telemetry"], "measured_at": now - 3}}
    assert code(_post_owner(env, lease, skewed, measured_at=now + 0.05)) == "OWNER_EVIDENCE_MEASURED_AT_INVALID"
    no_device = {**parts, "hardware_telemetry": {"stop_event": {}}}
    assert code(_post_owner(env, lease, no_device, measured_at=now + 0.05)) == "OWNER_EVIDENCE_MEASURED_AT_INVALID"
    env.app.state.omx_cell_tasks[TASK]["claimed_at"] = now - 200
    old = {**parts, "hardware_telemetry": {**parts["hardware_telemetry"], "measured_at": now - 61}}
    assert code(_post_owner(env, lease, old, measured_at=now - 61)) == "OWNER_EVIDENCE_MEASURED_AT_INVALID"
    assert _post_owner(env, lease, parts).status_code == 200


def test_bodies_are_capped_and_finished_or_expired_records_are_removed(env):
    big = {"x": "y" * (ev.MAX_BODY_BYTES + 1)}
    assert env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/bed-confirm", headers=OP, json=big).status_code == 413
    lease = _claimed(env)
    assert env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/owner-evidence", headers=SVC, json=big).status_code == 413
    parts, digest = _owner_parts(lease)
    assert _post_owner(env, lease, parts).status_code == 200
    assert TASK in env.app.state.cell_bed_confirmations and TASK in env.app.state.cell_owner_evidence
    assert _complete(env, parts, digest).status_code == 200
    ev.prune_evidence(env.app)
    assert not env.app.state.cell_bed_confirmations and not env.app.state.cell_owner_evidence


def test_expired_bed_confirmation_is_pruned(env):
    env.confirm_bed()
    env.app.state.cell_bed_confirmations[TASK]["confirmed_at"] -= ev.BED_CONFIRM_TTL_S + 1
    ev.prune_evidence(env.app)
    assert TASK not in env.app.state.cell_bed_confirmations


def test_motion_between_two_requests_voids_the_bed_confirmation_through_the_state_sink(env):
    seen = []
    env.console._state_sink = lambda robot_id, state: seen.append(robot_id)  # the MapPoseService feed, installed earlier
    assert env.confirm_bed().status_code == 200
    rec = env.app.state.cell_bed_confirmations[TASK]
    sink = env.console._state_sink
    sink("pinky_1", {})
    assert not rec.get("invalid") and seen == ["pinky_1"]  # the earlier sink still runs
    env.pose.x += 0.05
    sink("pinky_1", {})  # one state update while it is away
    env.pose.x = env.station[0]  # back home before anyone asks
    assert rec["invalid"] is True and env.amr()["bed_ready"] is False


def test_a_new_version_of_the_same_map_voids_the_bed_confirmation(env):
    assert env.confirm_bed().status_code == 200
    rec = env.app.state.cell_bed_confirmations[TASK]
    real = env.app.state.site_maps.active
    env.app.state.site_maps.active = lambda: (2, *real()[1:])
    env.console._state_sink("pinky_1", {})
    env.app.state.site_maps.active = real  # reverted before the next request
    assert rec["invalid"] is True and env.amr()["bed_ready"] is False


TOP_ONLY = "top_camera_only_target_zone"


def test_cell_s_may_release_on_the_top_camera_only_basis(env):
    lease = _claimed(env)
    parts, digest = _owner_parts(lease, basis=TOP_ONLY)
    assert _post_owner(env, lease, parts).status_code == 200
    done = _complete(env, parts, digest)
    assert done.status_code == 200 and done.json()["task"]["status"] == "COMPLETED"


def test_cell_ab_may_not_release_on_the_top_camera_only_basis(monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    env = Env(cell="cell_ab")
    lease = _claimed(env, "cell_ab")
    parts, digest = _owner_parts(lease, basis=TOP_ONLY, cell="cell_ab")
    assert _post_owner(env, lease, parts).status_code == 200
    res = _complete(env, parts, digest)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"


def test_a_direct_state_read_in_the_pose_service_voids_the_bed_confirmation():
    # The real MapPoseService: its own refresh path feeds observe_state without passing the console sink.
    from fleet.server.pose.map_pose_service import MapPoseService

    env = Env()
    svc = MapPoseService(lambda: ["pinky_1"])
    seen = []
    svc.add_update_listener(lambda robot_id: seen.append(robot_id))
    svc.arbitrated_pose = lambda robot_id: env.pose  # the pose the evidence reads; the feed below is the real path
    env.app.state.map_pose = SimpleNamespace(arbitrated_pose=svc.arbitrated_pose, active_map_id=lambda: "m1",
                                             add_update_listener=svc.add_update_listener)
    assert env.confirm_bed().status_code == 200
    rec = env.app.state.cell_bed_confirmations[TASK]
    env.pose.x += 0.05
    svc.observe_state("pinky_1", {})  # what MapPoseService._fetch does for a direct read
    env.pose.x = env.station[0]
    assert rec["invalid"] is True and seen[0] == "pinky_1"
    svc.observe_state("pinky_1", {"odom_pose": "bad"})  # a bad snapshot is swallowed and the listener still runs
    assert len(seen) == 2


def _ledger(env):
    import copy

    return copy.deepcopy((env.app.state.omx_cell_tasks, env.app.state.omx_cell_states))


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_cell_ab_claim_is_refused_before_the_ledger_changes_unless_enabled(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", raising=False)
    else:
        monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", value)
    env = Env(cell="cell_ab")
    env.confirm_bed()
    before = _ledger(env)
    res = env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": "cell_ab"}).json()
    assert res["claimed"] is False and res["reason"] == "CELL_AB_EVIDENCE_NOT_ENABLED"
    assert _ledger(env) == before  # status, lease and cell state untouched
    task = env.app.state.omx_cell_tasks[TASK]
    assert task["status"] == "QUEUED" and not task.get("handoff_lease_id") and "cell_ab" not in env.app.state.omx_cell_states


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_cell_ab_claim_takes_the_existing_path_when_enabled(monkeypatch, value):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", value)
    env = Env(cell="cell_ab")
    assert _claimed(env, "cell_ab")  # the lease came back: the normal checks ran and passed


def test_cell_s_is_not_affected_by_the_cell_ab_switch(monkeypatch):
    monkeypatch.delenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", raising=False)
    assert _claimed(Env())
