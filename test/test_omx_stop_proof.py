"""D-1077: the stop-capability proof replaces a declared person at the switch (cell_stop_proof, cell_job_proof, cell_job_api)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
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
