"""D-1077: the stop-capability proof replaces a declared person at the switch (cell_stop_proof, cell_job_proof, cell_job_api)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))
import cell_job_api as api  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_job_proof as jproof  # noqa: E402
import cell_stop_proof as sp  # noqa: E402

NOW = 1_000.0
FOLDED = {"t": NOW, "folded": True, "chunk": None, "fault": None, "human_hold_latched": False}
ONLINE = {"online": True, "blocked": False, "reason": None}


def _obs(live=FOLDED, session=False, cold=False, fleet=ONLINE):
    return lambda _arm: {"live": live, "session": session, "cold_folded": cold, "fleet": fleet}


def _measure(**kw):
    recovery = kw.pop("recovery", False)
    return sp.measure("job-1", ("arm_s",), _obs(**kw), now=NOW, recovery=recovery)


def test_a_fresh_folded_clean_arm_passes_and_binds_job_arm_and_time():
    proof = _measure()
    assert proof["ok"] and proof["code"] is None and proof["job_id"] == "job-1" and proof["arms"] == ["arm_s"]
    assert sp.verify(proof, job_id="job-1", arms=("arm_s",), now=NOW + 1)
    assert not sp.verify(proof, job_id="job-2", now=NOW) and not sp.verify(proof, arms=("arm_a",), now=NOW)
    assert not sp.verify(proof, now=NOW + sp.MAX_AGE_S + 1)  # never reused later
    assert not sp.verify({**proof, "ok": False}, now=NOW) and not sp.verify({"ok": True}, now=NOW) and not sp.verify(None)


@pytest.mark.parametrize(("kw", "code"), [
    ({"live": {**FOLDED, "fault": "motor error"}}, "STOP_PROOF_FAULT"),
    ({"live": {**FOLDED, "human_hold_latched": True}}, "STOP_PROOF_LATCH"),
    ({"live": {**FOLDED, "contact": True}}, "STOP_PROOF_CONTACT"),
    ({"live": {**FOLDED, "fault": "contact: overload"}}, "STOP_PROOF_CONTACT"),
    ({"live": {**FOLDED, "chunk": "policy"}}, "STOP_PROOF_NOT_SETTLED"),
    ({"live": {**FOLDED, "settled": False}}, "STOP_PROOF_NOT_SETTLED"),
    ({"live": {"t": NOW, "folded": False, "chunk": None}}, "STOP_PROOF_NOT_FOLDED"),
    ({"live": {**FOLDED, "t": NOW - 60}, "session": True}, "STOP_PROOF_LIVE_STALE"),
    ({"live": None}, "STOP_PROOF_ARM_STATE_UNKNOWN"),
    ({"live": None, "cold": True, "fleet": {"online": False, "blocked": False}}, "STOP_PROOF_NO_REMOTE_STOP"),
    ({"fleet": {"online": True, "blocked": True, "reason": "Fleet active_estop is asserted"}}, "STOP_PROOF_FLEET_BLOCKED"),
])
def test_each_failed_item_refuses_with_its_reason_code(kw, code):
    proof = _measure(**kw)
    assert proof["ok"] is False and proof["code"] == code and code in sp.CODES and proof["reason"].startswith("arm_s: ")


def test_a_verified_home_counts_and_a_cold_folded_arm_passes_with_fleet():
    assert _measure(live={**FOLDED, "folded": None, "at_home": True})["ok"]
    cold = _measure(live=None, cold=True)
    assert cold["ok"] and cold["basis"] == {"arm_s": "motor_health_folded"}


def test_recovery_proof_accepts_the_latch_it_clears_but_not_contact_a_hardware_fault_or_a_running_chunk():
    latched = {**FOLDED, "folded": False, "human_hold_latched": True, "fault": "human hold"}
    assert _measure(live=latched, recovery=True)["ok"]
    assert _measure(live={**latched, "contact": True}, recovery=True)["code"] == "STOP_PROOF_CONTACT"
    assert _measure(live={**latched, "fault": "contact: overload-hold"}, recovery=True)["code"] == "STOP_PROOF_CONTACT"
    assert _measure(live={**latched, "fault": "motor hardware error"}, recovery=True)["code"] == "STOP_PROOF_FAULT"
    assert _measure(live={**latched, "chunk": "x"}, recovery=True)["code"] == "STOP_PROOF_NOT_SETTLED"


def test_a_proof_dict_that_this_process_did_not_measure_is_not_a_proof_locally():
    forged = {"schema": sp.SCHEMA, "ok": True, "job_id": "j", "arms": ["arm_s"], "at": time.time()}
    assert sp.verify(forged) and not sp.verify(forged, local=True)  # shape alone passes; only a measured one passes locally
    real = sp.session_proof(Mock(policy_state=Mock(return_value={**FOLDED, "t": time.time()})), "run-9", "arm_s")
    assert sp.verify(real, local=True) and not sp.verify({**real, "job_id": "other"}, local=True)


def test_session_proof_reads_the_runners_own_live_state():
    live = {**FOLDED, "t": time.time()}
    cell = Mock(policy_state=Mock(return_value=live))
    assert sp.session_proof(cell, "run-1", "arm_s")["ok"]
    assert sp.session_proof(cell, "run-1", "arm_s")["basis"] == {"arm_s": "live"}
    cell.policy_state.return_value = {**live, "human_hold_latched": True}
    assert sp.session_proof(cell, "run-1", "arm_s")["code"] == "STOP_PROOF_LATCH"
    assert sp.session_proof(object(), "run-1", "arm_s")["code"] == "STOP_PROOF_LIVE_STALE"  # a session with nothing fresh to show


def test_torque_off_folded_gets_the_arms_own_library_and_a_peer_fold_uses_it(tmp_path, monkeypatch):
    job = api.JOBS["torque_off_folded"]
    assert "--library" not in api.build_argv(job, {"arm": "arm_b", "config": "cell-b.json"}, tmp_path)  # none: omitted
    (tmp_path / "chunks-arm-b-x.json").write_text(json.dumps({"chunks": {"park": [[0, -90, 60, 60, 0, 40]]}}), encoding="utf-8")
    argv = api.build_argv(job, {"arm": "arm_b", "config": "cell-b.json"}, tmp_path)
    assert argv[argv.index("--library") + 1] == "chunks-arm-b-x.json"
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    # lift/elbow pass the coarse rule but wrist_flex is far from this arm's own park pose
    state = [0, -90, 60, -30, 0, 40]
    (io / "live.json").write_text(json.dumps({"t": time.time(), "state": state, "chunk": None}), encoding="utf-8")
    kw = dict(session_lock_held_fn=lambda *_: False, read_json_fn=guards.read_json_dict, live_max_age_s=15.0,
              incident_check_fn=lambda _a: None, motor_health_dir=tmp_path / "h")
    assert "not folded" in guards.check_peer_ab_folded("arm_a", tmp_path, tmp_path / "l", None, **kw)
    (tmp_path / "chunks-arm-b-x.json").unlink()  # no library: the coarse rule only, which this pose passes
    assert guards.check_peer_ab_folded("arm_a", tmp_path, tmp_path / "l", None, **kw) is None


def _runner(tmp_path, monkeypatch, *, live=None, fleet=ONLINE, popen=None):
    for name in ("cell-a.json", "cell-b.json", "cell-s.json", "chunks-s.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc1234/deploy/robot/omx\n", encoding="utf-8")
    if live is not None:
        io = tmp_path / "chunk-io-s"
        io.mkdir()
        (io / "live.json").write_text(json.dumps({**live, "t": time.time()}), encoding="utf-8")
    popen = popen or Mock(return_value=Mock(poll=Mock(return_value=0)))
    monkeypatch.setattr(api.subprocess, "Popen", popen)
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: False)
    runner = api.Runner(tmp_path, lease_dir=tmp_path / "leases", motor_health_dir=tmp_path / "health",
                        incident_check_fn=lambda _arm: None, fleet_safety_check_fn=lambda _arm: fleet)
    return runner, popen


def _audit(runner):
    return [json.loads(line) for line in (runner.out / "audit.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_moving_job_starts_on_a_passing_proof_and_the_request_person_is_ignored_and_recorded(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live=FOLDED)
    res = runner.start("remap", {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True})
    assert res["code"] == 202 and popen.called
    row = next(r for r in _audit(runner) if r.get("event") == "stop_proof")
    assert row["id"] == res["id"] and row["ok"] is True and row["person_at_switch_ignored"] is True and row["job"] == "remap"
    assert runner.runs[res["id"]]["stop_proof"]["job_id"] == res["id"]
    assert "person_at_switch" not in runner.runs[res["id"]]["params"]


def test_no_person_in_the_request_is_needed(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live=FOLDED)
    assert runner.start("remap", {"arm": "arm_s", "config": "cell-s.json"})["code"] == 202
    argv = popen.call_args.args[0]
    assert "--commissioning" in argv and "--person-at-switch" in argv  # script flags kept; set by the runner after the proof


@pytest.mark.parametrize(("live", "code"), [
    ({**FOLDED, "human_hold_latched": True}, "STOP_PROOF_LATCH"),
    ({**FOLDED, "fault": "motor error"}, "STOP_PROOF_FAULT"),
    ({**FOLDED, "folded": False}, "STOP_PROOF_NOT_FOLDED"),
    (None, "STOP_PROOF_ARM_STATE_UNKNOWN"),
])
def test_a_failed_proof_refuses_before_any_process_and_says_why(tmp_path, monkeypatch, live, code):
    runner, popen = _runner(tmp_path, monkeypatch, live=live)
    res = runner.start("remap", {"arm": "arm_s", "config": "cell-s.json", "person_at_switch": True})  # the claim does not help
    assert res["code"] == 409 and res["error_code"] == code and res["stop_proof"]["ok"] is False
    popen.assert_not_called()
    assert [r["event"] for r in _audit(runner)] == ["stop_proof_refused"] and _audit(runner)[0]["person_at_switch_ignored"] is True


def test_fleet_estop_refuses_through_the_existing_safety_gate_and_dry_runs_need_no_proof(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live=FOLDED, fleet={"online": True, "blocked": True, "reason": "Fleet active_estop is asserted"})
    assert runner.start("remap", {"arm": "arm_s", "config": "cell-s.json"})["error_code"] == "FLEET_SAFETY_STOP"
    assert not jproof.needs_proof(api.JOBS["remap"], {}, False)
    assert jproof.needs_proof(api.JOBS["remap"], {}, True)
    assert not jproof.needs_proof(api.JOBS["recover_hold"], {}, True)


def test_a_machine_token_claiming_a_person_is_not_a_403_for_that_claim(tmp_path):
    job = api.JOBS["cell_policy_drive"]
    eff, err = guards.authorize_principal("cell_policy_drive", job, {"person_at_switch": True, "reviewed_auto": True},
                                          guards.Principal(guards.ROLE_MACHINE, "bot"), moves_arm_fn=api.moves_arm)
    assert err is None or err["error_code"] != "MACHINE_COMMISSIONING_FORBIDDEN" or "person_at_switch" not in err["error"]


def _finished_run(runner, tmp_path, result, *, arm="arm_s", job="cell_policy_drive", params=None):
    log = tmp_path / "x.log"
    result = {"reason_code": "START_POSE_OFF_HOME", "hold_kept": True, **result} if "next" in result else result
    log.write_text("starting\n" + json.dumps(result) + "\n", encoding="utf-8")
    run = {"job": job, "moving": True, "arm": arm, "log": log,
           "params": {"arm": arm, "config": "cell-s.json", "library": "chunks-s.json", **(params or {})}}
    return run


def test_a_no_move_refusal_with_next_recover_hold_runs_recover_hold_once(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live={**FOLDED, "folded": False, "human_hold_latched": True, "fault": "human hold"})
    (runner.out / jproof.DEFAULTS_FILE).write_text(json.dumps({"arm_s": {"site": "belt", "roi": [1, 2, 3, 4]}}), encoding="utf-8")
    monkeypatch.setattr(api, "live_hold_attach_err", lambda *a, **k: None)
    run = _finished_run(runner, tmp_path, {"result": "refused", "next": "recover_hold", "hold_kept": True})
    out = jproof.auto_recover_once(runner, "jid1", run, live_max_age_s=15.0, session_held_fn=lambda *_: False)
    assert out["started"] is True and out["http_code"] == 202
    started = runner.runs[out["recover_job_id"]]
    assert started["job"] == "recover_hold" and started["params"]["site"] == "belt" and started["params"]["roi"] == [1, 2, 3, 4]
    assert jproof.auto_recover_once(runner, "jid1", run, live_max_age_s=15.0, session_held_fn=lambda *_: False) is None  # once per run
    assert sum(r.get("event") == "auto_recover" for r in _audit(runner)) == 1


def test_auto_recover_needs_the_jobs_own_kept_hold_and_a_fresh_exit(tmp_path, monkeypatch):
    import os

    runner, popen = _runner(tmp_path, monkeypatch, live={**FOLDED, "folded": False, "human_hold_latched": True, "fault": "human hold"})
    call = lambda run: jproof.auto_recover_once(runner, "j", run, live_max_age_s=15.0, session_held_fn=lambda *_: False)  # noqa: E731
    no_hold = _finished_run(runner, tmp_path, {"next": "recover_hold", "hold_kept": False})
    assert call(no_hold) is None
    old = _finished_run(runner, tmp_path, {"next": "recover_hold"})
    os.utime(old["log"], (time.time() - 60, time.time() - 60))  # a hold someone asked for long after the job ended is not ours to clear
    assert call(old) is None
    popen.assert_not_called()


def test_auto_recover_is_skipped_without_next_with_unsafe_arm_or_without_params(tmp_path, monkeypatch):
    runner, popen = _runner(tmp_path, monkeypatch, live={**FOLDED, "folded": False, "human_hold_latched": True, "contact": True})
    call = lambda run: jproof.auto_recover_once(runner, "j", run, live_max_age_s=15.0, session_held_fn=lambda *_: False)  # noqa: E731
    assert call(_finished_run(runner, tmp_path, {"result": "chunks_done"})) is None
    assert call(_finished_run(runner, tmp_path, {"next": "recover_hold"}, job="recover_hold")) is None  # never chains itself
    machine = _finished_run(runner, tmp_path, {"next": "recover_hold"})
    machine["principal_role"] = guards.ROLE_MACHINE
    assert call(machine)["reason"] == "machine_principal"  # a machine token never gains recover_hold this way
    assert call(_finished_run(runner, tmp_path, {"next": "recover_hold"}))["reason"] == "no_recover_params"
    (runner.out / jproof.DEFAULTS_FILE).write_text(json.dumps({"arm_s": {"site": "belt", "roi": [1, 2, 3, 4]}}), encoding="utf-8")
    out = call(_finished_run(runner, tmp_path, {"next": "recover_hold"}))
    assert out["started"] is False and out["reason"] == "STOP_PROOF_CONTACT"
    popen.assert_not_called()


def test_session_proof_reconciles_lagging_live_chunk_and_merges_state_faults():
    now = time.time()
    lagging_live = {**FOLDED, "t": now - 0.05, "chunk": "policy"}
    idle_state = {"ok": True, "command": "state", "chunk": None, "t": now, "holding": False, "fault": None, "human_hold_latched": False}
    cell = Mock(policy_state=Mock(return_value=lagging_live))
    assert sp.session_proof(cell, "r1", "arm_b", state=idle_state)["ok"] is True
    assert sp.session_proof(cell, "r1", "arm_b", state={**idle_state, "t": now - 0.1})["code"] == "STOP_PROOF_NOT_SETTLED"
    assert sp.session_proof(cell, "r1", "arm_b")["code"] == "STOP_PROOF_NOT_SETTLED"
    for bad_chunk in ("park-slow", "fold-from-hold"):
        c_rec = Mock(policy_state=Mock(return_value={**lagging_live, "chunk": bad_chunk}))
        assert sp.session_proof(c_rec, "r1", "arm_b", state=idle_state)["code"] == "STOP_PROOF_NOT_SETTLED"
    assert sp.session_proof(Mock(policy_state=Mock(return_value={**lagging_live, "t": now - 30})), "r1", "arm_b", state=idle_state)["code"] == "STOP_PROOF_LIVE_STALE"
    clean_cell = Mock(policy_state=Mock(return_value={**FOLDED, "t": now}))
    assert sp.session_proof(clean_cell, "r1", "arm_b", state={**idle_state, "human_hold_latched": True})["code"] == "STOP_PROOF_LATCH"
    assert sp.session_proof(clean_cell, "r1", "arm_b", state={**idle_state, "contact": True})["code"] == "STOP_PROOF_CONTACT"
    assert sp.session_proof(clean_cell, "r1", "arm_b", state={**idle_state, "settled": False})["code"] == "STOP_PROOF_NOT_SETTLED"
    int_cell = Mock(policy_state=Mock(return_value={**FOLDED, "t": now, "interrupt": "sigterm"}))
    assert sp.session_proof(int_cell, "r1", "arm_b", state=idle_state)["code"] == "STOP_PROOF_FAULT"
    assert sp.session_proof(clean_cell, "r1", "arm_b", state={**idle_state, "ok": False, "error": "boom"})["code"] == "STOP_PROOF_FAULT"
    assert sp.session_proof(clean_cell, "r1", "arm_b", state={**idle_state, "fault": "motor err"})["code"] == "STOP_PROOF_FAULT"
    assert sp.session_proof(Mock(policy_state=Mock(return_value={**FOLDED, "t": now, "fault": "motor err"})), "r1", "arm_b",
                            state={**idle_state, "fault": "contact in policy"})["code"] == "STOP_PROOF_CONTACT"


def _assess_fixture(tmp_path, *, arm="arm_b", instance="arm_b_follower"):
    from cell_robot_profile import load

    cal = {k: {"id": i + 11, "drive_mode": 0, "homing_offset": 0, "range_min": 0, "range_max": 4095}
           for i, k in enumerate(["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"])}
    cal_path, prof_path, env_path = tmp_path / "cal.json", tmp_path / "prof.json", tmp_path / "env.json"
    cal_path.write_text(json.dumps(cal))
    prof_path.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": arm,
                                     "instance_id": instance, "robot_config_sha256": "a" * 64,
                                     "operating_envelope_path": str(env_path), "work_dir": str(tmp_path)}))
    binding = load(prof_path)["binding"]
    env_path.write_text(json.dumps({"schema": "rosy.omx-operating-envelope.v1", "device_id": arm, "instance_id": instance,
                                    "profile_sha256": binding["profile_sha256"],
                                    "attempts_path": str(tmp_path / "att.jsonl"), "reviews": []}))
    names = ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"]
    cond = {"installation_revision": "inst-1", "object_revision": "obj-1", "payload_max_kg": 0.25,
            "object_dimensions_m": [0.03, 0.03, 0.03], "environment_revision": "scene-1"}
    old_proof = {**FOLDED, "schema": sp.SCHEMA, "ok": True, "job_id": "r0", "arms": [arm], "at": time.time() - sp.MAX_AGE_S - 5}
    cfg = {"arm_id": arm, "calibration_path": str(cal_path), "operating_profile_path": str(prof_path),
           "operating_envelope_path": str(env_path), "work_dir": str(tmp_path), "payload": {"kg": 0.05, "source": "t"},
           "params": {"auto.max_gross_kg": 0.25}, "operating_conditions": cond, "_commissioning": {"stop_proof": old_proof},
           "cameras": {}, "sites": {}, "plan": {}, "profiles": {}}
    return cfg, binding, names, old_proof


def test_authorization_bind_proof_refreshes_past_max_age_with_real_assess_and_fails_closed(tmp_path):
    import cell_policy_handoff as handoff

    cfg, binding, names, old_proof = _assess_fixture(tmp_path)
    lib = {"fps": 30, "names": names, "gripper_closed": 48.8, "chunks": {"home": [[0] * 6], "policy": [[0] * 6]}}
    live = {**FOLDED, "folded": False, "t": time.time()}
    cell = Mock(policy_state=Mock(side_effect=lambda: dict(live, t=time.time())))
    logs = []
    auth = handoff.Authorization(cfg).bind_proof(cell, "run-2", "arm_b", log=logs.append)
    st = {"t": time.time(), "ok": True, "state": [20, 10, 5, 30, -29, 54], "target": [20, 10, 5, 30, -29, 54],
          "operating_context": {"scope": "hardware", "sha256": "c" * 64, "session_id": "s1", "operating_profile": binding}}
    res = auth(lib, st, ("run policy", "park"), check_home=False)
    assert res["allowed"] and res["mode"] == "commissioning"
    assert cfg["_commissioning"]["stop_proof"] is old_proof  # never mutated in place
    assert logs and logs[-1]["stop_proof_refresh"] and logs[-1]["stop_proof"]["job_id"] == "run-2:auth-1"
    with pytest.raises(ValueError, match="session_changed"):
        auth(lib, {**st, "operating_context": {**st["operating_context"], "session_id": "s2"}}, ("run policy", "park"), check_home=False)
    live["human_hold_latched"] = True
    with pytest.raises(ValueError, match="STOP_PROOF_LATCH"):
        auth(lib, st, ("run policy", "park"), check_home=False)


def test_chunk_runner_loop_publishes_live_immediately_when_chunk_clears():
    import chunk_runner_loop as loop

    snapshots = []
    runner = SimpleNamespace(
        chunk="policy", target=[0.0] * 6, fps=30, ticks=1, lag=0.0, fault=None, holding=False, robot=None,
        human_hold_latched=False, torque_hold_commanded=False, policy_playback=None, health=None,
        jitter={"shaking": False}, pending=[], signals=None, last_input=0.0, last_present=[0.0] * 6,
        clock=lambda: 1.0, sleep=lambda _s: None, live=snapshots.append, idle=lambda: len(snapshots) >= 1,
        present=lambda: [0.0] * 6, command=lambda _c: False, report=lambda **_kw: None,
    )

    def _clear_on_tick(r, _tag, _fn):
        if r.chunk == "policy":
            r.chunk = None  # ticks=1 would not fire periodic 3-tick publish without transition check
        return False

    orig = loop.interrupt_tick
    loop.interrupt_tick = _clear_on_tick
    try:
        loop.run(runner, lambda: [])
    finally:
        loop.interrupt_tick = orig
    assert snapshots and snapshots[0]["chunk"] is None


def test_paced_multi_chunk_refreshes_expired_stop_proof_with_real_bind_proof(tmp_path, monkeypatch):
    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    import cell_envelope as ce
    import cell_policy_handoff as handoff
    from cell_robot_profile import load
    from test_omx_policy_drive import Cell, LIB, NAMES as PD_NAMES, SimPolicy, cal, drive, write_lib

    cal_p, prof_p, env_p = tmp_path / "cal.json", tmp_path / "prof.json", tmp_path / "env.json"
    cal_p.write_text(json.dumps(cal()))
    prof_p.write_text(json.dumps({"schema": "rosy.omx-cell-robot-profile.v1", "device_id": "arm_b",
                                  "instance_id": "arm_b_follower", "robot_config_sha256": "a" * 64,
                                  "operating_envelope_path": str(env_p), "work_dir": str(tmp_path)}))
    binding = load(prof_p)["binding"]
    env_p.write_text(json.dumps({"schema": ce.SCHEMA, "device_id": "arm_b", "instance_id": "arm_b_follower",
                                 "profile_sha256": binding["profile_sha256"],
                                 "attempts_path": str(tmp_path / "att.jsonl"), "reviews": []}))
    expired = {"schema": sp.SCHEMA, "ok": True, "job_id": "init", "arms": ["arm_b"], "at": 100.0}
    sp._MINTED.add(("init", 100.0))
    cond = {"installation_revision": "inst-1", "object_revision": "obj-1", "payload_max_kg": 0.25,
            "object_dimensions_m": [0.03, 0.03, 0.03], "environment_revision": "scene-1"}
    cfg = {"arm_id": "arm_b", "calibration_path": str(cal_p), "operating_profile_path": str(prof_p),
           "operating_envelope_path": str(env_p), "work_dir": str(tmp_path), "payload": {"kg": 0.05, "source": "t"},
           "params": {"auto.max_gross_kg": 0.25}, "operating_conditions": cond,
           "_commissioning": {"stop_proof": expired}, "cameras": {}, "sites": {}, "plan": {}, "profiles": {}}
    ctx = {"scope": "hardware", "sha256": "c" * 64, "session_id": "s1", "operating_profile": binding}
    lib_p = write_lib(tmp_path, {**LIB, "names": [f"{n}.pos" for n in PD_NAMES]})

    class _PacedCell(Cell):
        def policy_state(self):
            return {"t": 1000.0, "state": list(self.state), "folded": False, "chunk": None, "fault": None, "human_hold_latched": False}

        def act(self, cmd):
            r = super().act(cmd)
            return {**r, "operating_context": ctx, "t": 1000.0, "health": {"current_ma": [0] * 6}, "health_t": 1000.0}

    monkeypatch.setattr(sp.time, "time", lambda: 1000.0)
    monkeypatch.setattr(ce.time, "time", lambda: 1000.0)
    cell, logs = _PacedCell(expected_chunks={"home", "reach", "policy"}), []
    auth = handoff.Authorization(cfg).bind_proof(cell, "run-7", "arm_b", log=logs.append)
    res = drive.run_episode(cell, SimPolicy([[[0, -58, 51, 50, -5, 49]] * 16] * 3), lib_p, tmp_path,
                            offset=[0] * 6, max_chunks=3, dry_run=False, log=logs.append, authorize=auth, paced_chunks=True, n_action=4)
    assert res["result"] == "chunks_done" and sum(1 for r in logs if r.get("stop_proof_refresh")) == 3
