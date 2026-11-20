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


def _snapshot(v=0.0, w=0.0, mode="IDLE", nav="IDLE", estop=False, fresh=True, vel_at=None):
    stamp = datetime.fromtimestamp(vel_at or time.time(), tz=timezone.utc).isoformat(timespec="milliseconds")
    velocity = ValueEvidence(received_at=stamp, stale_after_s=0.5,
                             evidence=EvidenceState.FRESH if fresh else EvidenceState.DELAYED)
    return StateSnapshot(robot_id="pinky_1", mode=mode, navigation=nav, velocity=Velocity(linear=v, angular=w),
                         safety=SafetySummary(estop=estop), evidence={"velocity": velocity})


class Env:
    def __init__(self, via="direct"):
        from tools.sim.bay_departure_sim import build_world_261026_site_map

        site, graph, _ = build_world_261026_site_map()
        self.station = resolve_omx_cells(site, graph)["cell_s"].station_xy
        principals = {sha256(t.encode()).hexdigest(): SitePrincipal(t, t) for t in ("viewer", "service", "operator")}
        require_viewer, require_operator, _, require_proposer = build_role_guards(
            build_authorize(None, principals, None), principals)
        self.app = app = FastAPI()
        app.state.operator_guard = [Depends(require_operator)]
        app.state.proposer_guard = [Depends(require_proposer)]
        app.state.amr_still_autostart = False  # no sampling thread in tests: the tracker is fed by hand
        self.registry = RobotRegistry()
        app.state.console = SimpleNamespace(hub=SimpleNamespace(registry=self.registry))
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
            "task_id": TASK, "cell_id": "cell_s", "arm_id": "arm_s", "robot_id": "pinky_1",
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


def _owner_parts(lease, **stop):
    stage = {"handoff_lease_id": lease, "directive_id": TASK, "arm_id": "arm_s", "task_verified": True,
             "verification": {"verified": True, "basis": "predefined_side_and_top_target_zones"},
             "place": {"area": "belt", "tier": 1}}
    hardware = {"stop_event": {"command": "stop", "ok": True, "folded": True, "state": [0.0] * 6, **stop}}
    digest = "sha256:" + hashlib.sha256(json.dumps(
        {"task_id": TASK, "lease": lease, "stage_result": stage, "hardware_telemetry": hardware},
        sort_keys=True, default=str).encode()).hexdigest()
    receipt = {"handoff_lease_id": lease, "cell_id": "cell_s", "stage_id": TASK, "phase": "RELEASED",
               "goal_evidence_digest": digest, "physical_completion": True, "simulated_success": False}
    return {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}, digest


def _claimed(env):
    env.confirm_bed()
    claimed = env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": "cell_s"}).json()
    assert claimed["claimed"] is True
    return claimed["handoff"]["handoff_lease_id"]


def _post_owner(env, lease, parts, **over):
    return env.client.post(f"/api/fleet/pipeline/cell-tasks/{TASK}/owner-evidence", headers=SVC, json={
        "handoff_lease_id": lease, "measured_at": time.time() + 0.05, **parts, **over})  # claimed_at is rounded up to 1 ms


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
