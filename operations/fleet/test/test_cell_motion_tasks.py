"""D-1078 stage 2: typed Fleet cell-task motions (free-position pick, push): validation and admission limits."""
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


def test_a_push_is_never_queued_by_anyone_and_cannot_be_admitted(env):
    _app, client = env
    res = _post(client, SVC, PUSH, task_id="t-push")  # src = dst = one site; the cell_ab pair rule makes an exception for push
    assert res.status_code == 200, res.text
    task = res.json()["task"]
    assert task["status"] == "PROPOSED" and task["motion_admission"] == "PUSH_NOT_EXECUTABLE"
    assert task["motion"]["mm"] == 10 and task["motion"]["dir"] == [1, 0]
    mine = _post(client, ALICE, PUSH, task_id="t-push-a").json()["task"]
    assert mine["status"] == "PROPOSED" and mine["approved_by"] is None
    res = client.post(f"{URL}/t-push/admit", headers=ALICE, json={})  # a different named operator: it has no run or completion path yet
    assert res.status_code == 409 and res.json()["detail"]["code"] == "PUSH_NOT_EXECUTABLE"


def _with(base, **kw):
    return {**base, **kw}


@pytest.mark.parametrize("motion", [
    _with(FREE, operator="alice"), _with(FREE, reviewed_auto=True), _with(FREE, person_at_switch=True), _with(FREE, x=0.1, y=0.2),
    _with(FREE, at_px=[1281, 0]), _with(FREE, at_px=[1.5, 2]), _with(FREE, at_px=[True, 2]), _with(FREE, at_px=[1]),
    _with(FREE, frame_seq=True), _with(FREE, frame_seq=-1), _with(FREE, frame_sha256="xyz"), _with(FREE, frame_sha256=SHA.upper()),
    _with(FREE, object="Box; rm"), _with(FREE, anchor_site="nowhere"), _with(FREE, dst_site="nowhere"), _with(FREE, anchor_site=3),
    {k: v for k, v in FREE.items() if k != "at_px"}, {k: v for k, v in FREE.items() if k != "frame_sha256"},
    _with(PUSH, mm=4.9), _with(PUSH, mm=20.1), _with(PUSH, mm=True), _with(PUSH, dir=[0, 0]), _with(PUSH, dir=[101, 0]),
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
