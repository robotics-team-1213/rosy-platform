"""D-1079: held arms' automatic recovery is retried with backoff, never blindly after a load failure (2026-11-27 arm_a facts)."""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))
import cell_hold_retry as hr  # noqa: E402
from cell_job_guards import ROLE_MACHINE, Principal, authorize_principal  # noqa: E402
from cell_job_spec import JOBS  # noqa: E402

PARAMS = {"config": "cell-arm-a.json", "library": "lib.json", "site": "belt", "roi": [1, 2, 3, 4]}
HELD = {"arm_a": {"session": True, "live": {"human_hold_latched": True, "torque_hold_commanded": True}}}
# rosy-arm-cell incidents 20261127T151516-arm_a and T153023-arm_a (OMX A/B review of D-1079)
OVERLOAD_1515 = {"latched": {"12": {"hw_error": 32, "bits": ["overload"], "packet_alert": True}},
                 "flagged": [{"command": "human-hold", "fault": "contact (overload-hold on shoulder_lift by the guard): lift and elbow shed its load"}]}
PUSHING_1530 = {"latched": {}, "flagged": [
    {"command": "fault", "fault": "pushing at rest: shoulder_lift still 1.7 units short, PWM winding up 192 -> 455 of 600: pushing against something"},
    {"command": "tick", "fault": "session ended: ValueError: shoulder_lift: following error >5 motor degrees; command=2336, current=2405"}]}


class Proc:
    def __init__(self, done):
        self.done = done

    def poll(self):
        return 0 if self.done else None


class Runner:
    def __init__(self, tmp):
        self.out, self.lock, self.runs, self.started = tmp / "api", threading.Lock(), {}, []
        self.out.mkdir()
        (self.out / hr.DEFAULTS_FILE).write_text(json.dumps({"arm_a": PARAMS}))

    def start(self, name, params, *, principal):
        self.started.append((name, params, principal))
        jid = f"j{len(self.started)}"
        self.runs[jid] = {"moving": True, "arm": params["arm"], "arms": (params["arm"],), "proc": Proc(done=True)}
        return {"code": 202, "id": jid}


def _dirs(tmp):
    (tmp / "inc").mkdir(exist_ok=True)
    (tmp / "health").mkdir(exist_ok=True)
    return tmp / "inc", tmp / "health"


def _incident(tmp, facts, stamp="20261127T151516"):
    folder = tmp / "inc" / f"{stamp}-arm_a"
    folder.mkdir(parents=True)
    (folder / "incident.json").write_text(json.dumps({"facts": facts}))


def _health(tmp, now, temps=(36, 33, 32, 22, 22, 22), hw=0, raw=2048, status="active", torque=True):
    motors = [{"id": 11 + i, "temperature_c": t, "hardware_error": hw if i == 1 else 0, "fault": False,
               "present_raw": raw, "torque_enabled": torque} for i, t in enumerate(temps)]
    (tmp / "health" / "arm_a.json").write_text(json.dumps({"observed_at": now, "status": status, "motors": motors}))


def _tick(runner, state, now, live, tmp, incident=None, folds=None):
    inc, hd = _dirs(tmp)
    return hr.tick(runner, state, now, arms=("arm_a",), observe=lambda arm: live.get(arm, {"session": False}),
                   incident_status=lambda arm: (incident or {}).get(arm, {}),
                   launch_fold=lambda arm: (folds.append(arm) if folds is not None else None) or {"started": True},
                   incidents=inc, health_dir=hd)


def test_a_live_hold_is_retried_by_recover_hold_with_backoff_and_never_handed_to_a_person(tmp_path):
    runner, state = Runner(tmp_path), {}
    _tick(runner, state, 1000.0, HELD, tmp_path)
    assert [(n, p["arm"], pr.role, pr.principal_id) for n, p, pr in runner.started] == [("recover_hold", "arm_a", ROLE_MACHINE, "hold-retry")]
    _tick(runner, state, 1000.0 + hr.RETRY_S[0] - 1, HELD, tmp_path)
    assert len(runner.started) == 1
    _tick(runner, state, 1000.0 + hr.RETRY_S[0], HELD, tmp_path)
    for k in range(10):
        _tick(runner, state, 1e6 + k * hr.RETRY_S[-1], HELD, tmp_path)
    assert len(runner.started) == 12


def test_overload_latch_of_1515_starts_no_motion(tmp_path):
    runner, state = Runner(tmp_path), {}
    _dirs(tmp_path)
    _incident(tmp_path, OVERLOAD_1515)
    rows = _tick(runner, state, 1000.0, HELD, tmp_path)
    assert runner.started == [] and rows[0]["reason"] == "NO_FRESH_MOTOR_HEALTH"
    _health(tmp_path, 2000.0, hw=32)
    rows = _tick(runner, state, 2000.0, HELD, tmp_path)
    assert runner.started == [] and rows[0]["reason"] == "HARDWARE_ERROR_LATCHED"
    _health(tmp_path, 3000.0, temps=(50, 33, 32, 22, 22, 22))
    rows = _tick(runner, state, 3000.0, HELD, tmp_path)
    assert runner.started == [] and rows[0]["reason"] == "MOTORS_NOT_COOL"
    _health(tmp_path, 4000.0)  # latch cleared (rebooted) and cool: one checked try
    _tick(runner, state, 4000.0, HELD, tmp_path)
    assert len(runner.started) == 1


def test_pushing_then_following_error_of_1530_waits_for_a_pose_change_after_a_second_load_failure(tmp_path):
    runner, state, folds = Runner(tmp_path), {}, []
    _dirs(tmp_path)
    _incident(tmp_path, PUSHING_1530, "20261127T153023")
    held = {"arm_a": {"local_held": True}}
    _health(tmp_path, 1000.0)
    _tick(runner, state, 1000.0, {}, tmp_path, held, folds)
    assert folds == ["arm_a"]  # the incident's own fault is load failure 1; cool and fault-free: one try
    marker = tmp_path / "inc" / "auto-fold-inc1.json"
    marker.write_text(json.dumps({"incident_id": "inc1", "arm": "arm_a", "stage": "full", "at": 1000.0}))
    _health(tmp_path, 1030.0)
    _tick(runner, state, 1061.0, {}, tmp_path, held, folds)
    assert folds == ["arm_a"]  # its try still runs
    (tmp_path / "inc" / "auto-fold-inc1.result.json").write_text(json.dumps({"result": "held", "why": "pushing at rest: PWM 200 -> 450"}))
    _health(tmp_path, 1100.0)
    rows = _tick(runner, state, 1100.0, {}, tmp_path, held, folds)
    assert folds == ["arm_a"] and rows[0]["reason"] == "LOAD_FAILED_WAIT_POSE" and not marker.exists()
    for k in range(5):  # keeps auditing, never moves, never latches a person
        _health(tmp_path, 2000.0 + k * 600)
        assert _tick(runner, state, 2000.0 + k * 600, {}, tmp_path, held, folds)[0]["reason"] == "LOAD_FAILED_WAIT_POSE"
    _health(tmp_path, 9000.0, raw=2048 + 80)  # someone moved the arm: a fresh situation
    _tick(runner, state, 9000.0, {}, tmp_path, held, folds)
    assert folds == ["arm_a", "arm_a"]


def test_an_ended_torque_off_session_counts_as_cooled_after_ten_minutes(tmp_path):
    _dirs(tmp_path)
    _health(tmp_path, 1000.0, temps=(60, 60, 60, 60, 60, 60), status="ended", torque=False)
    assert hr.health(tmp_path / "health", "arm_a", 1100.0) is None
    assert hr.health(tmp_path / "health", "arm_a", 1000.0 + hr.COOLED_S)["cool"] is True


def test_a_dead_fold_try_does_not_stop_the_retries(tmp_path):
    runner, state, folds = Runner(tmp_path), {}, []
    inc, _ = _dirs(tmp_path)
    (inc / "auto-fold-inc1.json").write_text(json.dumps({"incident_id": "inc1", "arm": "arm_a", "stage": "full", "at": 0.0}))
    _tick(runner, state, hr.STALE_S + 1, {}, tmp_path, {"arm_a": {"local_held": True}}, folds)
    assert folds == ["arm_a"] and list(inc.glob("auto-fold-inc1.try*.json"))


def test_skips_pause_files_peer_jobs_running_folds_and_home_recovery(tmp_path):
    runner, state, folds = Runner(tmp_path), {}, []
    (runner.out / "hold-retry-off-arm_a").write_text("")
    assert _tick(runner, state, 1000.0, HELD, tmp_path)[0]["reason"] == "PAUSED" and runner.started == []
    (runner.out / "hold-retry-off-arm_a").unlink()
    state.clear()
    runner.runs["peer"] = {"moving": True, "arm": "arm_b", "arms": ("arm_b",), "proc": Proc(done=False)}
    assert _tick(runner, state, 1000.0, HELD, tmp_path) == [] and runner.started == []
    runner.runs.clear()
    inc, _ = _dirs(tmp_path)
    (inc / "auto-fold-x.json").write_text(json.dumps({"arm": "arm_a", "stage": "full", "at": 999.0}))
    assert _tick(runner, state, 1000.0, HELD, tmp_path) == []  # a D-1048 fold of this arm still runs
    (inc / "auto-fold-x.json").unlink()
    assert hr.needs({"session": False}, {"local_held": True, "fleet_reason": "home_recovery"}) is None
    assert hr.needs({"session": False}, {"fleet_held": True}) is None  # only a local arm incident


def test_only_the_hold_retry_machine_principal_may_start_recover_hold():
    def auth(pid):
        return authorize_principal("recover_hold", JOBS["recover_hold"], {"arm": "arm_a", **PARAMS}, Principal(ROLE_MACHINE, pid),
                                   moves_arm_fn=lambda job, params: True)[1]
    assert auth("hold-retry") is None
    assert auth("cell-job-machine")["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"


def test_a_short_unseen_gap_keeps_the_load_failure_count(tmp_path):
    runner, state, folds = Runner(tmp_path), {}, []
    _dirs(tmp_path)
    _incident(tmp_path, PUSHING_1530, "20261127T153023")
    state["arm_a"] = {"tries": 2, "next": 0.0, "load_fails": 2, "pending": None, "stuck_pose": [180.0] * 5, "hold": "incident"}
    _tick(runner, state, 1000.0, {}, tmp_path, {}, folds)  # stale live.json / session end before the incident: unseen
    _health(tmp_path, 1100.0)
    rows = _tick(runner, state, 1100.0, {}, tmp_path, {"arm_a": {"local_held": True}}, folds)
    assert folds == [] and rows[0]["reason"] == "LOAD_FAILED_WAIT_POSE"
    _tick(runner, state, 1200.0, {}, tmp_path, {}, folds)
    _tick(runner, state, 1200.0 + hr.CLEAR_GRACE_S, {}, tmp_path, {}, folds)
    assert state["arm_a"]["load_fails"] == 0  # gone for good: a later hold starts fresh


def test_an_automatic_recovery_refuses_an_unchecked_load(monkeypatch):
    import cell_recovery_plan

    monkeypatch.delenv("ROSY_JOB_PRINCIPAL", raising=False)
    assert cell_recovery_plan.make_load_checker({}, {})([[0] * 6])["ok"] is False
    monkeypatch.setenv("ROSY_JOB_PRINCIPAL", "human:operator")
    assert cell_recovery_plan.make_load_checker({}, {}) is None
