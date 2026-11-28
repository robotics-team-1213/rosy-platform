"""D-1078 stage 2: typed Fleet cell-task motions (free-position pick, push): validation, admission, claim and measured completion."""
from __future__ import annotations

from pathlib import Path

import pytest

from test_autonomous_cell_dispatch import ALICE, OBS, SVC, _build_env

SHA = "ab" * 32
FREE = {"kind": "free_pick", "anchor_site": "belt", "at_px": [320, 240], "dst_site": "yard:r1-s1-t1",
        "frame_seq": 41, "frame_sha256": SHA, "object": "box"}
PUSH = {"kind": "push", "site": "belt", "px": [300, 200], "dir": [1, 0], "mm": 10, "frame_seq": 41, "frame_sha256": SHA}
URL = "/api/fleet/pipeline/cell-tasks"


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH", "1")  # the site-wide switch is ON for every test here
    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service;cell_ab=service")
    return _build_env(tmp_path)


def _post(client, headers, motion, **extra):
    return client.post(URL, headers=headers, json={"cell_id": "cell_ab", "arm_id": "arm_a", "tier": 1, "motion": motion, **extra})


def test_service_free_pick_with_the_switch_on_is_queued_by_policy_without_a_human(env):
    """Owner decision 2026-11-27 (amends D-911 section 2): no per-task approval; the cell re-measures at execution."""
    _app, client = env
    res = _post(client, SVC, FREE, task_id="t-free")
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert task["status"] == "QUEUED" and task["approved_by"] == "autonomous_policy" and task["approval_mode"] == "autonomous_policy"
    assert "motion_admission" not in task
    assert task["src_site"] == "belt" and task["motion"]["at_px"] == [320, 240] and task["motion"]["frame_sha256"] == SHA
    assert task["motion"]["object"] == "box"


def test_the_free_pick_waits_for_a_human_when_the_switch_is_off_or_propose_is_set(env, monkeypatch):
    _app, client = env
    assert _post(client, SVC, FREE, task_id="t-prop", propose=True).json()["task"]["status"] == "PROPOSED"
    monkeypatch.delenv("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH")
    off = _post(client, SVC, FREE, task_id="t-off").json()["task"]
    assert off["status"] == "PROPOSED" and off["approved_by"] is None and "approval_mode" not in off


def test_a_motion_is_handed_only_to_a_worker_that_declares_motions(env):
    """Rollout gate: an old worker would ignore the motion and pick from the anchor."""
    app, client = env
    assert _post(client, SVC, FREE, task_id="t-gate").json()["task"]["status"] == "QUEUED"
    claim = "/api/fleet/pipeline/cell-tasks/claim"
    for body in ({}, {"capabilities": []}, {"capabilities": "motion"}, {"capabilities": ["other"]}):
        res = client.post(claim, headers=SVC, json={"cell_id": "cell_ab", "task_id": "t-gate", **body}).json()
        assert res["claimed"] is False and res["reason"] == "WORKER_LACKS_MOTION_CAPABILITY"
    task = app.state.omx_cell_tasks["t-gate"]
    assert task["status"] == "QUEUED" and "handoff_lease_id" not in task and "claimed_at" not in task
    res = client.post(claim, headers=SVC, json={"cell_id": "cell_ab", "task_id": "t-gate", "capabilities": ["motion"]}).json()
    assert res.get("reason") != "WORKER_LACKS_MOTION_CAPABILITY"  # past this gate the usual claim gates decide


def test_a_plain_task_needs_no_capability_to_be_claimed(env):
    from fleet.pipeline.cell_motion import claim_refusal

    assert claim_refusal({"task_id": "t"}, {}) is None and claim_refusal({"motion": FREE}, {"capabilities": ["motion"]}) is None


def test_the_ai_observer_role_still_cannot_post_a_motion(env):
    _app, client = env
    assert _post(client, OBS, FREE, task_id="t-obs").status_code == 403


def test_a_plain_task_from_the_same_principal_still_rides_the_switch(env):
    _app, client = env
    res = client.post(URL, headers=SVC, json={"task_id": "t-plain", "cell_id": "cell_s"})
    assert res.json()["task"]["status"] == "QUEUED" and res.json()["task"]["approval_mode"] == "autonomous_policy"


def test_an_operator_who_creates_a_motion_never_approves_it_themselves(env):
    _app, client = env
    for tid, extra in (("t-alice", {}), ("t-alice-p", {"propose": True})):
        task = _post(client, ALICE, FREE, task_id=tid, **extra).json()["task"]
        assert task["status"] == "PROPOSED" and task["approved_by"] is None and task["proposer"] == "alice"
        assert task["motion"]["kind"] == "free_pick"
    assert _post(client, ALICE, FREE, task_id="t-alice").status_code == 409  # id exists: nothing replaced it


def test_a_service_push_with_the_switch_on_is_queued_by_policy_like_the_free_pick(env):
    """Owner decision 2026-11-28 (amends D-1077 section 7 and D-1081): same condition as the free pick; the cell re-measures at run time."""
    _app, client = env
    res = _post(client, SVC, PUSH, task_id="t-push")  # src = dst = one site; the cell_ab pair rule makes an exception for push
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert task["status"] == "QUEUED" and task["approved_by"] == "autonomous_policy" and task["approval_mode"] == "autonomous_policy"
    assert "motion_admission" not in task and task["motion"]["mm"] == 10 and task["motion"]["dir"] == [1, 0]


def test_a_push_waits_for_a_human_unless_the_switch_is_on_and_a_service_created_it_without_propose(env, monkeypatch):
    _app, client = env
    prop = _post(client, SVC, PUSH, task_id="t-push-p", propose=True).json()["task"]
    assert prop["status"] == "PROPOSED" and prop["approved_by"] is None
    for tid, extra in (("t-push-a", {}), ("t-push-ap", {"propose": True})):
        mine = _post(client, ALICE, PUSH, task_id=tid, **extra).json()["task"]  # an operator never approves their own motion
        assert mine["status"] == "PROPOSED" and mine["approved_by"] is None and mine["proposer"] == "alice"
    monkeypatch.delenv("ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH")
    off = _post(client, SVC, PUSH, task_id="t-push-off").json()["task"]
    assert off["status"] == "PROPOSED" and off["approved_by"] is None and "approval_mode" not in off


def test_a_proposed_push_is_admitted_exactly_like_a_proposed_free_pick(env):
    _app, client = env
    for tid, motion in (("t-adm-push", PUSH), ("t-adm-free", FREE)):
        assert _post(client, SVC, motion, task_id=tid, propose=True).json()["task"]["status"] == "PROPOSED"
    push = client.post(f"{URL}/t-adm-push/admit", headers=ALICE, json={})
    free = client.post(f"{URL}/t-adm-free/admit", headers=ALICE, json={})
    assert push.status_code == free.status_code
    assert (push.json().get("detail") or {}).get("code") == (free.json().get("detail") or {}).get("code") != "PUSH_NOT_EXECUTABLE"
    assert "PUSH_NOT_EXECUTABLE" not in push.text


def test_a_push_is_handed_only_to_a_worker_that_declares_push_and_nothing_is_consumed(env):
    """A worker with only "motion" would run nothing for a push (or an old one a pick from the anchor): the task stays QUEUED."""
    app, client = env
    assert _post(client, SVC, PUSH, task_id="t-pgate").json()["task"]["status"] == "QUEUED"
    claim = f"{URL}/claim"
    for body, code in (({}, "WORKER_LACKS_MOTION_CAPABILITY"), ({"capabilities": ["push"]}, "WORKER_LACKS_MOTION_CAPABILITY"),
                       ({"capabilities": ["motion"]}, "WORKER_LACKS_PUSH_CAPABILITY"), ({"capabilities": "motion,push"}, "WORKER_LACKS_MOTION_CAPABILITY")):
        res = client.post(claim, headers=SVC, json={"cell_id": "cell_ab", "task_id": "t-pgate", **body}).json()
        assert res["claimed"] is False and res["reason"] == code, body
    task = app.state.omx_cell_tasks["t-pgate"]
    assert task["status"] == "QUEUED" and "handoff_lease_id" not in task and "claimed_at" not in task
    res = client.post(claim, headers=SVC, json={"cell_id": "cell_ab", "task_id": "t-pgate", "capabilities": ["motion", "push"]}).json()
    assert res.get("reason") not in ("WORKER_LACKS_MOTION_CAPABILITY", "WORKER_LACKS_PUSH_CAPABILITY")


def test_the_push_capability_gate_does_not_change_the_free_pick_or_plain_tasks():
    from fleet.pipeline.cell_motion import claim_refusal

    assert claim_refusal({"motion": FREE}, {"capabilities": ["motion"]}) is None and claim_refusal({"task_id": "t"}, {}) is None
    assert claim_refusal({"motion": PUSH}, {"capabilities": ["motion", "push"]}) is None
    assert claim_refusal({"motion": PUSH}, {"capabilities": ["motion"]}) == "WORKER_LACKS_PUSH_CAPABILITY"


@pytest.mark.parametrize("key", ["object_ref", "identity", "identity_observation_ref", "emit_release_permit"])
def test_a_push_carries_no_cargo_identity_so_it_can_never_emit_a_stored_event(env, key):
    app, client = env
    res = _post(client, SVC, PUSH, task_id="t-ident", **{key: "x"})
    assert res.status_code == 422 and "t-ident" not in app.state.omx_cell_tasks


# --- measured completion: Fleet checks the push evidence itself, not a boolean ---
EV = {"result": "pushed", "site": "belt", "measured": True, "commanded_mm": 10, "moved_mm": 9.5, "along_dir_mm": 9.0, "lateral_mm": 3.0}
TASK_PUSH = {"task_id": "t", "motion": PUSH, "src_site": "belt"}


@pytest.mark.parametrize("push,ok", [
    (EV, True), ({**EV, "site": "belt"}, True), (None, False), ("pushed", False), ({}, False),
    ({k: v for k, v in EV.items() if k != "measured"}, False),  # exit 0 and a "pushed" result without measured displacement
    ({**EV, "measured": False}, False), ({**EV, "measured": "yes"}, False), ({**EV, "result": "contact"}, False),
    ({**EV, "along_dir_mm": 0.0, "moved_mm": 3.0}, False),  # no displacement along the push
    ({**EV, "along_dir_mm": 4.9, "moved_mm": 5.75}, False), ({**EV, "along_dir_mm": 18.1, "moved_mm": 18.35}, False),
    ({**EV, "lateral_mm": 6.1, "moved_mm": 10.88}, False), ({**EV, "lateral_mm": 12.0, "moved_mm": 15.0}, False),  # large lateral error
    ({**EV, "moved_mm": 25.0}, False), ({**EV, "commanded_mm": 12}, False), ({**EV, "site": "yard"}, False),
    ({**EV, "along_dir_mm": True}, False), ({**EV, "lateral_mm": float("nan")}, False), ({**EV, "extra": 1}, False),
])
def test_push_completion_needs_the_measured_displacement_in_exact_shape(push, ok):
    from fleet.pipeline.cell_motion import push_completion_verified, release_verified

    stage = {"task_verified": True, **({} if push is None else {"push": push})}
    assert push_completion_verified(TASK_PUSH, stage) is ok
    assert release_verified(TASK_PUSH, stage, "cell_ab") is ok


def test_the_push_thresholds_are_pinned_to_the_numbers_the_worker_pins_too():
    """The worker side (test/test_omx_cell_task_motion.py) pins the same literals; the two packages cannot import each other."""
    from fleet.pipeline import cell_motion as fm

    assert (fm.PUSH_ALONG_MIN_FRAC, fm.PUSH_ALONG_MAX_EXTRA_MM, fm.PUSH_LATERAL_MAX_MM) == (0.5, 3.0, 6.0)
    assert fm.PUSH_EVIDENCE_KEYS == {"result", "site", "measured", "commanded_mm", "moved_mm", "along_dir_mm", "lateral_mm"}


def test_a_non_push_task_still_needs_its_zone_verification_and_a_push_never_passes_on_one():
    from fleet.pipeline.cell_motion import release_verified

    zone = {"verification": {"verified": True, "basis": "predefined_side_and_top_target_zones"}}
    assert release_verified({"task_id": "p"}, zone, "cell_ab") is True and release_verified({"task_id": "p"}, {"push": EV}, "cell_ab") is False
    assert release_verified({"task_id": "p"}, {"verification": {"verified": True, "basis": "top_camera_only_target_zone"}}, "cell_ab") is False
    assert release_verified({"task_id": "p"}, {"verification": {"verified": True, "basis": "top_camera_only_target_zone"}}, "cell_s") is True
    assert release_verified(TASK_PUSH, zone, "cell_ab") is False  # a zone verification cannot complete a push


def _push_parts(lease, push, *, folded=True):
    import hashlib
    import json
    import time

    stage = {"handoff_lease_id": lease, "directive_id": "evidence-task", "arm_id": "arm_a", "task_verified": True, **({} if push is None else {"push": push})}
    hardware = {"measured_at": time.time() + 0.05, "stop_event": {"command": "stop", "ok": folded, "folded": folded, "state": [0.0] * 6}}
    digest = "sha256:" + hashlib.sha256(json.dumps({"task_id": "evidence-task", "lease": lease, "stage_result": stage,
                                                    "hardware_telemetry": hardware}, sort_keys=True, default=str).encode()).hexdigest()
    receipt = {"handoff_lease_id": lease, "cell_id": "cell_ab", "stage_id": "evidence-task", "phase": "RELEASED",
               "goal_evidence_digest": digest, "physical_completion": True, "simulated_success": False}
    return {"receipt": receipt, "stage_result": stage, "hardware_telemetry": hardware}, digest


@pytest.mark.parametrize("push,folded,code", [
    (EV, True, None), (None, True, "UNVERIFIED_CELL_COMPLETION"), ({**EV, "along_dir_mm": 0.0, "moved_mm": 3.0}, True, "UNVERIFIED_CELL_COMPLETION"),
    ({**EV, "lateral_mm": 12.0, "moved_mm": 15.0}, True, "UNVERIFIED_CELL_COMPLETION"), (EV, False, "UNVERIFIED_CELL_COMPLETION"),
])
def test_complete_releases_a_push_only_on_measured_evidence_and_a_folded_arm(monkeypatch, push, folded, code):
    """The real /complete route: no place, no zone verification; the displacement and the fold decide."""
    from test_pipeline_evidence import Env, _claimed, _complete, _post_owner

    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service,other;cell_ab=service")
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    env = Env(cell="cell_ab")
    lease = _claimed(env, "cell_ab")
    env.app.state.omx_cell_tasks["evidence-task"]["motion"] = PUSH  # claimed by a worker that declared "push"
    parts, digest = _push_parts(lease, push, folded=folded)
    assert _post_owner(env, lease, parts).status_code == 200
    res = _complete(env, parts, digest)
    if code is None:
        assert res.status_code == 200 and res.json()["task"]["status"] == "COMPLETED"
    else:
        assert res.status_code == 422 and res.json()["detail"]["code"] == code
        assert env.app.state.omx_cell_tasks["evidence-task"]["status"] == "RUNNING"


def test_a_plain_task_cannot_complete_on_push_evidence(monkeypatch):
    from test_pipeline_evidence import Env, _claimed, _complete, _post_owner

    monkeypatch.setenv("ROSY_FLEET_CELL_OWNERS", "cell_s=service,other;cell_ab=service")
    monkeypatch.setenv("ROSY_FLEET_CELL_AB_RELEASE_ENABLED", "1")
    env = Env(cell="cell_ab")
    lease = _claimed(env, "cell_ab")  # no motion on this task: the zone verification and place are still required
    parts, digest = _push_parts(lease, EV)
    assert _post_owner(env, lease, parts).status_code == 200
    res = _complete(env, parts, digest)
    assert res.status_code == 422 and res.json()["detail"]["code"] == "UNVERIFIED_CELL_COMPLETION"


def _with(base, **kw):
    return {**base, **kw}


@pytest.mark.parametrize("motion", [
    _with(FREE, operator="alice"), _with(FREE, reviewed_auto=True), _with(FREE, person_at_switch=True), _with(FREE, x=0.1, y=0.2),
    _with(FREE, at_px=[1281, 0]), _with(FREE, at_px=[1.5, 2]), _with(FREE, at_px=[True, 2]), _with(FREE, at_px=[1]),
    _with(FREE, frame_seq=True), _with(FREE, frame_seq=-1), _with(FREE, frame_sha256="xyz"), _with(FREE, frame_sha256=SHA.upper()),
    _with(FREE, object="Box; rm"), _with(FREE, anchor_site="nowhere"), _with(FREE, dst_site="nowhere"), _with(FREE, anchor_site=3),
    {k: v for k, v in FREE.items() if k != "at_px"}, {k: v for k, v in FREE.items() if k != "frame_sha256"},
    _with(PUSH, mm=4.9), _with(PUSH, mm=20.1), _with(PUSH, mm=True), _with(PUSH, dir=[0, 0]), _with(PUSH, dir=[0.01, 0]), _with(PUSH, dir=[101, 0]),
    _with(PUSH, site="nowhere"), _with(PUSH, dst_site="belt"), {"kind": "drive"}, "free_pick",
])
def test_malformed_motions_are_refused_before_a_task_exists(env, motion):
    app, client = env
    res = _post(client, SVC, motion, task_id="t-bad")
    assert res.status_code == 422, res.text
    assert "t-bad" not in app.state.omx_cell_tasks


@pytest.mark.parametrize("extra,code", [
    ({"preset": "s3_shuttle"}, ("INVALID_CELL_TASK_INPUT", "MOTION_CONFLICTS_WITH_TASK_FIELDS")), ({"tiers": [1, 2]}, "INVALID_CELL_TASK_INPUT"),  # routes that rebuild specs would drop the motion
    ({"execution_mode": "act_policy"}, "MOTION_CONFLICTS_WITH_TASK_FIELDS"), ({"dst_site": "belt"}, "MOTION_SITE_CONFLICT"),
    ({"src_site": "pinky"}, "MOTION_SITE_CONFLICT"), ({"directive": {"schema": "x"}}, "MOTION_CONFLICTS_WITH_TASK_FIELDS"),
])
def test_a_motion_cannot_share_a_task_with_what_it_replaces(env, extra, code):
    _app, client = env
    res = _post(client, SVC, FREE, task_id="t-conflict", **extra)
    assert res.status_code == 422 and res.json()["detail"]["code"] in (code if isinstance(code, tuple) else (code,))


def test_the_free_pick_is_for_the_ab_arms(env):
    _app, client = env
    res = client.post(URL, headers=SVC, json={"cell_id": "cell_s", "motion": FREE})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "MOTION_CELL_NOT_SUPPORTED"


def test_a_retry_never_rebuilds_a_motion_as_a_fixed_site_pick(env):
    app, client = env
    assert _post(client, ALICE, FREE, task_id="t-orig").status_code == 200
    app.state.omx_cell_tasks["t-orig"]["status"] = "ABORTED"
    res = client.post(f"{URL}/t-orig/retry", headers=ALICE)
    assert res.status_code == 409 and len([t for t in app.state.omx_cell_tasks.values() if "retry" in t["task_id"]]) == 0


def test_repark_never_opens_for_or_rebuilds_a_motion_task():
    from types import SimpleNamespace
    from fleet.server.sitemap import pipeline_repark as rp

    task = {"task_id": "m1", "cell_id": "cell_ab", "arm_id": "arm_a", "robot_id": None, "src_site": "belt", "dst_site": "pallet", "motion": FREE}
    state = SimpleNamespace(omx_cell_tasks={"m1": task}, repark_requests={}, repark_done=[], auto_events=[])
    assert rp.on_abort(state, task, {"reach_fix": {"need_arm_dxdy_m": [0.01, 0.0]}}, 1.0) is None and not state.repark_requests
    state.repark_requests["r"] = {"request_id": "r1", "state": "REQUESTED", "task_id": "m1", "root": "m1", "attempt": 1}
    enqueued = []
    with pytest.raises(ValueError, match="MOTION_NOT_REPARKED"):
        rp.close(state, "r1", {"state": "DONE"}, enqueued.append, 2.0)
    assert enqueued == [] and state.repark_requests["r"]["state"] == "REQUESTED"


def test_a_free_pick_is_never_retried_automatically_with_the_same_pixel(env):
    """Failure paths that rebuild a task from an old one all refuse a motion; a new motion needs a new request."""
    app, client = env
    assert _post(client, SVC, FREE, task_id="t-fail").status_code == 200
    app.state.omx_cell_tasks["t-fail"]["status"] = "ABORTED"
    assert client.post(f"{URL}/t-fail/retry", headers=ALICE).status_code == 409
