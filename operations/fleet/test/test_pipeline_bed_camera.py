"""D-1057 2-9: cell S's bed_ready from the top camera (bed-observation), with the operator bed-confirm as the UNKNOWN fallback."""
import time

import pytest

from fleet.server.sitemap import pipeline_evidence as ev
from test_pipeline_evidence import (  # noqa: F401  (_cell_owners is an autouse fixture)
    OP, OTHER, SVC, TASK, TOP_ONLY, Env, _cell_owners, _complete, _owner_parts, _post_owner, _snapshot,
)

URL = f"/api/fleet/pipeline/cell-tasks/{TASK}/bed-observation"
STILL_S = 2.4  # Env.beat feeds one earlier still sample; over STILL_MAX_GAP_S (2.5 s) the run would restart


def _frames(first_age=1.5, span=1.2, n=3):
    t0 = time.time() - first_age
    return [{"source_seq": 10 + i, "source_stamp": t0 + span * i / (n - 1), "jpeg_sha256": "ab" * 32} for i in range(n)]


def _observe(env, verdict="READY", headers=SVC, frames=None, **over):
    body = {"robot_id": "pinky_1", "verdict": verdict, "reasons": [] if verdict == "READY" else ["BED_EMPTY"],
            "frames": _frames() if frames is None else frames, "bed": {"score": 0.9, "offset_px": [0, 0], "tol_px": 20.0},
            "objects": 1, "site": "pinky", "roi": [49, 139, 295, 305], "config_sha256": "cd" * 32, **over}
    return env.client.post(URL, headers=headers, json=body)


def _claim(env, cell="cell_s", **extra):
    return env.client.post("/api/fleet/pipeline/cell-tasks/claim", headers=SVC, json={"cell_id": cell, **extra}).json()


def _code(res):
    return res.json()["detail"]["code"]


@pytest.fixture
def env():
    e = Env()
    e.beat(still_s=STILL_S)
    return e


def test_ready_is_recorded_and_the_claim_binds_it_as_the_camera_with_no_operator(env):
    res = _observe(env)
    assert res.status_code == 200 and res.json()["recorded"] is True
    rec = env.app.state.cell_bed_confirmations[TASK]
    assert rec["source"] == "cell_top_camera" and rec["principal_id"] == "service" and rec["ttl_s"] == ev.BED_CAMERA_TTL_S
    assert _claim(env)["claimed"] is True
    bound = env.app.state.omx_cell_tasks[TASK]["bed_confirmation"]
    assert bound["source"] == "cell_top_camera" and bound["operator"] is None and bound["principal"] == "service"
    assert len(bound["camera"]["frames"]) == 3


def test_unknown_makes_no_record_and_the_named_operator_is_the_fallback(env):
    assert _observe(env, "UNKNOWN").json()["recorded"] is False
    assert TASK not in env.app.state.cell_bed_confirmations
    res = _claim(env)
    assert res["claimed"] is False and res["reason"] == "AMR_BRAKE_BED_VELOCITY_UNMEASURED"
    assert env.confirm_bed().status_code == 200
    assert _claim(env)["claimed"] is True
    assert env.app.state.omx_cell_tasks[TASK]["bed_confirmation"]["operator"] == "operator"


def test_a_measured_not_ready_blocks_the_operator_for_10_s(env):
    assert _observe(env, "NOT_READY").json()["recorded"] is False
    refused = env.confirm_bed()
    assert refused.status_code == 409 and _code(refused) == "BED_CAMERA_NOT_READY"
    env.app.state.cell_bed_camera[TASK]["at"] -= ev.BED_CAMERA_VERDICT_S + 0.1
    assert env.confirm_bed().status_code == 200


def test_cell_ab_takes_no_camera_record_and_its_bed_confirm_is_unchanged():
    env = Env(cell="cell_ab")
    res = _observe(env)
    assert res.status_code == 409 and _code(res) == "BED_CAMERA_CELL_NOT_SUPPORTED"
    ok = env.confirm_bed()
    assert ok.status_code == 200 and ok.json()["confirmation"]["principal_id"] == "operator"
    assert "source" not in ok.json()["confirmation"]


@pytest.mark.parametrize("headers", [OTHER, OP], ids=["other_service_of_cell_ab", "person"])
def test_only_a_registered_cell_s_owner_service_may_post(env, monkeypatch, headers):
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service;cell_ab=other")
    res = _observe(env, headers=headers)
    assert res.status_code == 403 and TASK not in env.app.state.cell_bed_confirmations


@pytest.mark.parametrize("frames", [  # built at run time: the ages are relative to now
    lambda: _frames(n=2),
    lambda: [{**f, "source_seq": 10} for f in _frames()],
    lambda: _frames(span=0.9),
    lambda: _frames(first_age=1.2 + 2.1),
    lambda: _frames(first_age=-0.65 + 1.2),
], ids=["two_frames", "seq_not_advancing", "span_0.9_s", "last_2.1_s_old", "last_0.6_s_in_future"])
def test_invalid_frames_are_refused_and_nothing_is_stored(env, frames):
    res = _observe(env, frames=frames())
    assert res.status_code == 422 and _code(res) == "BED_OBSERVATION_INVALID"
    assert TASK not in env.app.state.cell_bed_confirmations and TASK not in env.app.state.cell_bed_camera


def test_fleet_stillness_must_cover_the_first_camera_frame(env):
    env.beat(still_s=1.2)  # held still (>= 1 s), but only since after the first frame minus the clock margin
    res = _observe(env)
    assert res.status_code == 409 and _code(res) == "BED_OBSERVATION_ROBOT_NOT_STILL"
    assert TASK not in env.app.state.cell_bed_confirmations
    env.beat(_snapshot(v=0.3), still_s=STILL_S)
    assert _code(_observe(env)) == "BED_OBSERVATION_ROBOT_NOT_STILL"


@pytest.mark.parametrize("age, claimed", [(9.9, True), (10.1, False)])
def test_the_camera_record_waits_10_s_for_the_claim(env, age, claimed):
    assert _observe(env).json()["recorded"] is True
    rec = env.app.state.cell_bed_confirmations[TASK]
    task = env.app.state.omx_cell_tasks[TASK]
    assert ev.bind_bed(env.app, task, "lease-x", now=rec["confirmed_at"] + age) is claimed
    if not claimed:
        assert "bed_confirmation" not in task and "lease" not in rec and task["status"] == "QUEUED"
        rec["confirmed_at"] -= age
        res = _claim(env)
        assert res["claimed"] is False and task["status"] == "QUEUED"


def _released_by_camera(env):
    assert _observe(env).json()["recorded"] is True
    res = _claim(env)
    assert res["claimed"] is True
    lease = res["handoff"]["handoff_lease_id"]
    parts, digest = _owner_parts(lease, basis=TOP_ONLY)
    assert _post_owner(env, lease, parts).status_code == 200
    return parts, digest


def test_a_bound_camera_record_dies_on_a_2_1_cm_move_and_only_a_person_confirms_again(env):
    parts, digest = _released_by_camera(env)
    env.pose.x += 0.021
    ev.check_beds(env.app)
    refused = _complete(env, parts, digest)
    assert refused.status_code == 422 and _code(refused) == "BED_CONFIRMATION_INVALID"
    assert _code(_observe(env)) == "CELL_TASK_NOT_QUEUED"
    env.beat()
    again = env.confirm_bed()
    assert again.status_code == 200 and env.app.state.omx_cell_tasks[TASK]["bed_confirmation"]["operator"] == "operator"


def test_a_map_version_change_voids_a_bound_camera_record(env):
    parts, digest = _released_by_camera(env)
    real = env.app.state.site_maps.active
    env.app.state.site_maps.active = lambda: (2, *real()[1:])
    ev.check_beds(env.app)
    refused = _complete(env, parts, digest)
    assert refused.status_code == 422 and _code(refused) == "BED_CONFIRMATION_INVALID"


@pytest.mark.parametrize("value", ["off", "OFF", "0", "false"])
def test_the_kill_switch_refuses_camera_records(env, monkeypatch, value):
    monkeypatch.setenv("ROSY_FLEET_CELL_S_BED_CAMERA", value)
    res = _observe(env)
    assert res.status_code == 409 and _code(res) == "BED_CAMERA_DISABLED"


def test_a_valid_operator_confirmation_is_never_replaced(env):
    assert env.confirm_bed().status_code == 200
    before = dict(env.app.state.cell_bed_confirmations[TASK])
    res = _observe(env)
    assert res.status_code == 200 and res.json()["recorded"] is False
    assert env.app.state.cell_bed_confirmations[TASK] == before and "source" not in before


def _task_owner(task_id, lease, cell="cell_s", arm="arm_s", basis=TOP_ONLY, place=None, verification=None, **stage_extra):
    import hashlib
    import json

    ver = {"verified": True, "basis": basis, **(verification or {})}
    stage = {"handoff_lease_id": lease, "directive_id": task_id, "arm_id": arm, "task_verified": True,
             "verification": ver, "place": place or {"area": "belt", "tier": 1}, **stage_extra}
    hw = {"measured_at": time.time() + 0.05, "stop_event": {"command": "stop", "ok": True, "folded": True, "state": [0.0] * 6}}
    digest = "sha256:" + hashlib.sha256(
        json.dumps({"task_id": task_id, "lease": lease, "stage_result": stage, "hardware_telemetry": hw},
                   sort_keys=True, default=str).encode()).hexdigest()
    receipt = {"handoff_lease_id": lease, "cell_id": cell, "stage_id": task_id, "phase": "RELEASED",
               "goal_evidence_digest": digest, "physical_completion": True, "simulated_success": False}
    return {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hw}, digest


def test_tier_hint_validation_and_two_tier_unload_batch_reclaim_gate(env):
    env.app.state.omx_cell_tasks.clear()
    bad_hint = env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "bad-h", "cell_id": "cell_s", "robot_id": "pinky_1", "tier": 1, "tier_hint": "upper"})
    assert bad_hint.status_code == 422 and _code(bad_hint) == "INVALID_TIER_HINT"

    for tid, extra in [
        ("u-1", {"unload_batch_id": "batch-2t", "unload_index": 0, "tier_hint": {"layers_below": 1}}),
        ("u-2", {"unload_batch_id": "batch-2t", "unload_index": 1, "depends_on": "u-1"}),
        ("u-other", {"unload_batch_id": "batch-other", "unload_index": 0}),
    ]:
        res = env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
            "task_id": tid, "cell_id": "cell_s", "robot_id": "pinky_1", "src_site": "pinky", "dst_site": "belt",
            "tier": 1, **extra})
        assert res.status_code == 200

    assert env.client.post("/api/fleet/pipeline/cell-tasks/u-1/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c1 = _claim(env, task_id="u-1")
    assert c1["claimed"] is True and c1["handoff"]["tier_hint"] == {"layers_below": 1}
    lease1 = c1["handoff"]["handoff_lease_id"]

    # Null objects in source_clearance refuses completion (tested in isolated Env so u-1 posts owner-evidence once)
    e_null = Env()
    e_null.beat(still_s=STILL_S)
    e_null.app.state.omx_cell_tasks.clear()
    assert e_null.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "u-null", "cell_id": "cell_s", "robot_id": "pinky_1", "src_site": "pinky", "dst_site": "belt",
        "tier": 1, "unload_batch_id": "batch-null", "unload_index": 0}).status_code == 200
    assert e_null.client.post("/api/fleet/pipeline/cell-tasks/u-null/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c_null = _claim(e_null, task_id="u-null")
    assert c_null["claimed"] is True
    l_null = c_null["handoff"]["handoff_lease_id"]
    null_parts, null_digest = _task_owner("u-null", l_null, source_clearance={"objects": None})
    assert e_null.client.post("/api/fleet/pipeline/cell-tasks/u-null/owner-evidence", headers=SVC,
                              json={"handoff_lease_id": l_null, "measured_at": null_parts["hardware_telemetry"]["measured_at"], **null_parts}).status_code == 200
    e_null.beat()
    refused = e_null.client.post("/api/fleet/pipeline/cell-tasks/u-null/complete", headers=SVC,
                                 json={"phase": "RELEASED", "goal_evidence_digest": null_digest, **null_parts})
    assert refused.status_code == 422 and _code(refused) == "UNVERIFIED_CELL_COMPLETION"

    # objects > 0 keeps cell_s CLAIMED + amr_motion_inhibited=True for the same batch
    rem_parts, rem_digest = _task_owner("u-1", lease1, source_clearance={"objects": 1})
    assert env.client.post("/api/fleet/pipeline/cell-tasks/u-1/owner-evidence", headers=SVC,
                           json={"handoff_lease_id": lease1, "measured_at": rem_parts["hardware_telemetry"]["measured_at"], **rem_parts}).status_code == 200
    env.beat()
    done1 = env.client.post("/api/fleet/pipeline/cell-tasks/u-1/complete", headers=SVC,
                            json={"phase": "RELEASED", "goal_evidence_digest": rem_digest, **rem_parts})
    assert done1.status_code == 200
    cs = env.app.state.omx_cell_states["cell_s"]
    assert cs["phase"] == "CLAIMED" and cs["amr_motion_inhibited"] is True and cs["unload_batch_id"] == "batch-2t"

    # Unrelated batch stays blocked while same-batch continuation reclaims and releases on objects == 0
    assert env.client.post("/api/fleet/pipeline/cell-tasks/u-other/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    assert _claim(env, task_id="u-other")["reason"] == "CELL_BUSY_OR_HELD"
    assert env.client.post("/api/fleet/pipeline/cell-tasks/u-2/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c2 = _claim(env, task_id="u-2")
    assert c2["claimed"] is True
    lease2 = c2["handoff"]["handoff_lease_id"]
    zero_parts, zero_digest = _task_owner("u-2", lease2, source_clearance={"objects": 0})
    assert env.client.post("/api/fleet/pipeline/cell-tasks/u-2/owner-evidence", headers=SVC,
                           json={"handoff_lease_id": lease2, "measured_at": zero_parts["hardware_telemetry"]["measured_at"], **zero_parts}).status_code == 200
    env.beat()
    done2 = env.client.post("/api/fleet/pipeline/cell-tasks/u-2/complete", headers=SVC,
                            json={"phase": "RELEASED", "goal_evidence_digest": zero_digest, **zero_parts})
    assert done2.status_code == 200
    assert env.app.state.omx_cell_states["cell_s"]["phase"] == "RELEASED"
    assert env.app.state.omx_cell_states["cell_s"]["amr_motion_inhibited"] is False


def test_cell_ab_multisite_arm_affinity_optional_tier_and_completion_gate(monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    env = Env(cell="cell_ab")
    env.app.state.omx_cell_tasks.clear()

    # Pallet / omitted dst_site still require explicit tier
    assert env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "ab-no-tier", "cell_id": "cell_ab", "robot_id": "pinky_1"}).status_code == 422
    assert env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "ab-pal-no-tier", "cell_id": "cell_ab", "robot_id": "pinky_1", "dst_site": "pallet"}).status_code == 422
    bad_arm = env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "ab-bad-arm", "cell_id": "cell_ab", "robot_id": "pinky_1", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1", "arm_id": "arm_b"})
    assert bad_arm.status_code == 422 and _code(bad_arm) == "INVALID_CELL_SITE_ARM"

    # Canonical tier-encoded cell_ab sites carry tier=1 and infer arm affinity
    for tid, dst, exp_arm, exp_area in [
        ("ab-ta", "temp_a:r1-s1-t1", "arm_a", "temp_a"),
        ("ab-tb", "temp_b:r1-s1-t1", "arm_b", "temp_b"),
        ("ab-stand", "stand:r1-s1-t1", "arm_a", "stand"),
    ]:
        r = env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
            "task_id": tid, "cell_id": "cell_ab", "robot_id": "pinky_1", "src_site": "belt", "dst_site": dst})
        assert r.status_code == 200 and r.json()["task"]["arm_id"] == exp_arm and r.json()["task"]["tier"] == 1
        assert r.json()["task"]["dst_area"] == exp_area

    # Stand completes without z_gate PASS when canonical place and target match
    env.beat(still_s=STILL_S)
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-stand/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c_st = _claim(env, cell="cell_ab", task_id="ab-stand")
    assert c_st["claimed"] is True
    l_st = c_st["handoff"]["handoff_lease_id"]
    st_place = {"area": "stand", "site": "stand", "site_id": "stand:r1-s1-t1", "col": 1, "row": 1, "tier": 1}
    ok_st, ok_st_digest = _task_owner("ab-stand", l_st, cell="cell_ab", arm="arm_a",
                                      basis="predefined_side_and_top_target_zones", place=st_place,
                                      verification={"target": dict(st_place)})
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-stand/owner-evidence", headers=SVC,
                           json={"handoff_lease_id": l_st, "measured_at": ok_st["hardware_telemetry"]["measured_at"], **ok_st}).status_code == 200
    env.beat()
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-stand/complete", headers=SVC,
                           json={"phase": "RELEASED", "goal_evidence_digest": ok_st_digest, **ok_st}).status_code == 200

    # Pallet destination requires z_gate PASS + matching tier
    r_pal = env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "ab-pal", "cell_id": "cell_ab", "robot_id": "pinky_1", "src_site": "belt", "dst_site": "pallet", "tier": 2})
    assert r_pal.status_code == 200 and r_pal.json()["task"]["arm_id"] == "arm_b"
    env.beat(still_s=STILL_S)
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-pal/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c_pal = _claim(env, cell="cell_ab", task_id="ab-pal")
    assert c_pal["claimed"] is True
    l_pal = c_pal["handoff"]["handoff_lease_id"]
    pal_parts, pal_digest = _task_owner("ab-pal", l_pal, cell="cell_ab", arm="arm_b",
                                        basis="predefined_side_and_top_target_zones",
                                        place={"area": "pallet", "tier": 2}, verification={"z_gate": {"verdict": "PASS"}})
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-pal/owner-evidence", headers=SVC,
                           json={"handoff_lease_id": l_pal, "measured_at": pal_parts["hardware_telemetry"]["measured_at"], **pal_parts}).status_code == 200
    env.beat()
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-pal/complete", headers=SVC,
                           json={"phase": "RELEASED", "goal_evidence_digest": pal_digest, **pal_parts}).status_code == 200

    # Mismatched destination area is refused (distinct task because owner-evidence is write-once per RUNNING task)
    assert env.client.post("/api/fleet/pipeline/cell-tasks", headers=OP, json={
        "task_id": "ab-ta-bad", "cell_id": "cell_ab", "robot_id": "pinky_1", "src_site": "belt", "dst_site": "temp_a:r1-s1-t1"}).status_code == 200
    env.beat(still_s=STILL_S)
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-ta-bad/bed-confirm", headers=OP, json={"robot_id": "pinky_1"}).status_code == 200
    c_bad = _claim(env, cell="cell_ab", task_id="ab-ta-bad")
    assert c_bad["claimed"] is True
    l_bad = c_bad["handoff"]["handoff_lease_id"]
    bad_area, bad_digest = _task_owner("ab-ta-bad", l_bad, cell="cell_ab", arm="arm_a",
                                       basis="predefined_side_and_top_target_zones",
                                       place={"area": "stand", "site": "stand", "site_id": "temp_a:r1-s1-t1", "col": 1, "row": 1, "tier": 1},
                                       verification={"z_gate": {"verdict": "PASS"},
                                                     "target": {"area": "temp_a", "site_id": "temp_a:r1-s1-t1", "col": 1, "row": 1, "tier": 1}})
    assert env.client.post("/api/fleet/pipeline/cell-tasks/ab-ta-bad/owner-evidence", headers=SVC,
                           json={"handoff_lease_id": l_bad, "measured_at": bad_area["hardware_telemetry"]["measured_at"], **bad_area}).status_code == 200
    env.beat()
    assert _code(env.client.post("/api/fleet/pipeline/cell-tasks/ab-ta-bad/complete", headers=SVC,
                                 json={"phase": "RELEASED", "goal_evidence_digest": bad_digest, **bad_area})) == "UNVERIFIED_CELL_COMPLETION"
