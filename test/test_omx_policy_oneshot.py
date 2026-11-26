"""One submitted ACT run: one session, one lock, staged and timed (2026-11-26, A/B real runs lost most time to retries)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
import cell_job_api as api  # noqa: E402
import cell_policy_run as prun  # noqa: E402
import cell_policy_timing as timing  # noqa: E402
import session_refusal as refusal  # noqa: E402

HOME = [0.0, -100.0, 90.0, 10.0, 0.0, 30.0]
LIBRARY = {"chunks": {"home": [HOME]}}
CAMERAS = {"top": {"url": "http://x/top.jpg"}, "side": {"url": "http://x/side.jpg"}, "wrist": {"url": "http://x/w.jpg"},
           "spare": {"url": "http://x/s.jpg", "optional": True}}
NOW = 1000.0


class Cell:
    """The arm and cameras as the run sees them: every command and frame request is recorded."""

    def __init__(self, state=HOME, live=None, frame_errors=()):
        self.state, self.calls, self.frames = state, [], []
        self.live = {"t": NOW - 0.1, "state": HOME, "chunk": None, "fault": None} if live is None else live
        self.frame_errors = list(frame_errors)

    def policy_state(self):
        return self.live

    def act(self, command):
        self.calls.append(command)
        return {"ok": True, "state": self.state, "holding": False}

    def frame_receipt(self, name, **_kw):
        self.frames.append(name)
        if self.frame_errors:
            raise ValueError(self.frame_errors.pop(0))
        return {"source_stamp": NOW - 0.05}


@pytest.fixture
def config(monkeypatch):
    import cell_envelope
    import cell_params

    monkeypatch.setattr(cell_params, "load", lambda _p: {"values": {}})
    monkeypatch.setattr(cell_envelope, "_conditions", lambda _c: {})
    monkeypatch.setattr(cell_envelope, "payload_check", lambda c, _k: ({}, None if c.get("payload") else "payload_unknown"))
    return {"cameras": CAMERAS, "payload": {"kg": 0.016}}


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def go(config, cell, *, home=(0, {"result": "home"}), drive=(0, {"result": "chunks_done", "parked": True}), env=None):
    clock, order = Clock(), []

    def home_fn():
        order.append("home")
        clock.t += 7
        return home

    def drive_fn(argv):
        order.append("drive")
        clock.t += 20
        return drive

    code, receipt = prun.run(config, LIBRARY, cell, ["--config", "c"], home_fn=home_fn, drive_fn=drive_fn, env=env or {},
                             clock=clock, wall=lambda: NOW, sleep=clock.sleep)
    return code, receipt, order, clock


def names(receipt):
    return [s["stage"] for s in receipt["stages"]]


def test_stages_run_in_order_in_one_receipt_with_times(config):
    cell = Cell(state=[0, -80, 70, 10, 0, 30])  # off home
    code, receipt, order, _ = go(config, cell, env={"ROSY_SESSION_UP_S": "12", "ROSY_SESSION_ATTEMPTS": "2"})
    assert code == 0 and receipt["result"] == "chunks_done" and order == ["home", "drive"]
    assert names(receipt) == ["session", "precheck", "home_check", "home", "drive"]
    assert receipt["stages"][0] == {"stage": "session", "ok": True, "s": 12.0, "attempts": 2}
    assert receipt["stages"][3]["s"] == 7 and receipt["stages"][4]["s"] == 20 and receipt["total_s"] == 27
    assert receipt["stages"][1]["cameras"].keys() == {"top", "side", "wrist"}  # the optional camera is not required


def test_home_is_skipped_when_the_arm_is_already_home(config):
    code, receipt, order, _ = go(config, Cell())
    assert code == 0 and order == ["drive"] and "home" not in names(receipt)


@pytest.mark.parametrize("break_it,reason", [
    (lambda c, cell: c.pop("payload"), "precheck: operating envelope: payload_unknown"),
    (lambda c, cell: setattr(cell, "live", None), "precheck: no running arm session"),
    (lambda c, cell: setattr(cell, "live", {"t": NOW - 30, "state": HOME}), "precheck: no running arm session"),
    (lambda c, cell: setattr(cell, "live", {"t": NOW, "state": HOME, "fault": "joint at 80 % of its cap"}), "precheck: session is in a safety state (fault)"),
    (lambda c, cell: setattr(cell, "live", {"t": NOW, "state": HOME, "human_hold_latched": True}), "precheck: session is in a safety state (human_hold_latched)"),
    (lambda c, cell: setattr(cell, "frame_errors", ["camera frame HTTP 503; no fresh JPEG"] * 3), "precheck: camera top gave no new frame in 3 tries"),
])
def test_precheck_refusals_say_why_and_move_nothing(config, break_it, reason):
    cell = Cell(state=[0, -80, 70, 10, 0, 30])
    break_it(config, cell)
    code, receipt, order, _ = go(config, cell)
    assert code == 1 and receipt["result"] == "refused" and receipt["reason"].startswith(reason)
    assert receipt["stage"] == "precheck" and receipt["moved"] is False and order == [] and cell.calls == []


def test_a_transient_bad_frame_is_retried_but_a_safety_state_is_not(config):
    cell = Cell(frame_errors=["camera frame source metadata is stale or invalid"])
    code, receipt, order, clock = go(config, cell)
    assert code == 0 and cell.frames.count("top") == 2 and clock.t == prun.CAMERA_WAIT_S + 20  # one 1 s wait, then ok
    held = Cell(live={"t": NOW, "state": HOME, "hold": True})
    go(config, held)
    assert held.frames == []  # refused before touching a camera


def test_home_failure_stops_before_the_drive_and_a_bad_home_state_refuses_unmoved(config):
    code, receipt, order, _ = go(config, Cell(state=[0, -80, 70, 10, 0, 30]), home=(1, {"result": "refused"}))
    assert code == 1 and order == ["home"] and receipt["stage"] == "home" and receipt["reason"] == "home: refused"
    bad = Cell()
    bad.act = lambda command: {"ok": False, "error": "no status within 5 s"}
    code, receipt, order, _ = go(config, bad)
    assert code == 1 and order == [] and receipt["stage"] == "home_check" and "no status within 5 s" in receipt["reason"]


def test_drive_failures_keep_the_drives_own_result_and_exit_code(config):
    held = {"result": "refused", "at": 2, "reason": "stale policy observation", "parked": False}
    code, receipt, order, _ = go(config, Cell(), drive=(1, held))
    assert code == 1 and receipt["result"] == "refused" and receipt["reason"] == "stale policy observation"
    assert receipt["at"] == 2 and receipt["parked"] is False and names(receipt)[-1] == "drive"
    code, receipt, *_ = go(config, Cell(), drive=(0, {"result": "chunks_done", "parked": False}))
    assert code == 1  # done but not parked is still not a success
    code, receipt, *_ = go(config, Cell(), drive=(1, {"result": "error", "reason": "ValueError: x"}))
    assert code == 1 and receipt["reason"] == "ValueError: x"


def test_the_run_sends_the_arm_only_state_reads_and_each_camera_once(config):
    cell = Cell()
    go(config, cell)
    assert cell.calls == ["state"] and sorted(cell.frames) == ["side", "top", "wrist"]  # every motion command is the drive's or home's


def test_main_refuses_without_person_at_switch_and_a_dry_run_flag(capsys):
    for argv in (["--config", "c", "--library", "l", "--operating-profile", "p"],
                 ["--config", "c", "--library", "l", "--operating-profile", "p", "--person-at-switch", "--dry-run"]):
        with pytest.raises(SystemExit) as stop:
            prun.main(argv)
        assert stop.value.code == 2


def test_job_spec_one_session_wrapper_and_the_unchanged_drive_job(tmp_path):
    for name in ("cell-b.json", "chunks-b.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    base = {"arm": "arm_b", "config": "cell-b.json", "library": "chunks-b.json", "max_chunks": 15, "operator": "op_b",
            "operating_profile": "arm-b-robot-profile.json", "person_at_switch": True, "paced_chunks": True, "mode": "act",
            "policy_root": "~/rosy-models/b", "policy_revision": "a" * 64, "cell_calibration": "cell.json",
            "model_calibration": "m.json", "endpoint_url": "http://127.0.0.1:8790", "n_action": 8}
    job = api.JOBS["cell_policy_run"]
    argv = api.build_argv(job, base, tmp_path)
    assert argv[0] == "./with-session-arm-b-par.sh" and "cell_policy_run.py" in argv
    assert argv[argv.index("--operating-profile") + 1] == "arm-b-robot-profile.json"
    assert "--paced-chunks" in argv and argv[argv.index("--arm-id") + 1] == "arm_b" and argv[-1] == "--person-at-switch"
    assert job["moving"] and job["camera"] and "--commissioning" not in argv
    for bad in ({"dry_run": True}, {"proposer": "op_b"}, {"mode": "hybrid"}):
        with pytest.raises(ValueError):
            api.build_argv(job, {**base, **bad}, tmp_path)
    with pytest.raises(ValueError, match="operating_profile"):
        api.build_argv(job, {k: v for k, v in base.items() if k != "operating_profile"}, tmp_path)
    drive = {k: v for k, v in base.items() if k != "operating_profile"}
    assert api.build_argv(api.JOBS["cell_policy_drive"], {**drive, "dry_run": True}, tmp_path)[0] == "bash"  # still no session for a dry run
    assert api.moves_arm(job, base) and not api.moves_arm(api.JOBS["cell_policy_drive"], {**drive, "dry_run": True})


class Live:
    def __init__(self, live):
        self.live, self.acts = live, []

    def policy_state(self):
        return self.live

    def act(self, command):
        self.acts.append(command)
        return {"ok": True, "state": HOME, "t": NOW}


@pytest.mark.parametrize("live,uses_live", [
    ({"t": NOW - 0.1, "state": HOME, "chunk": None}, True),
    ({"t": NOW - 0.5, "state": HOME, "chunk": None}, False),  # older than the live limit: ask the runner
    ({"t": NOW, "state": HOME, "chunk": "policy"}, False),
    ({"t": NOW, "state": HOME, "chunk": None, "fault": "x"}, False),
    ({"t": NOW, "state": HOME, "chunk": None, "human_hold_latched": True}, False),
    ({"t": NOW + 5, "state": HOME, "chunk": None}, False),  # a stamp from the future is not fresh
    ({"state": HOME, "chunk": None}, False), (None, False),
])
def test_first_observation_reads_the_sessions_live_joint_state_when_it_is_fresh(monkeypatch, live, uses_live):
    monkeypatch.setattr(timing.time, "time", lambda: NOW)
    cell = Live(live)
    snap = timing._fresh_snapshot(cell, None, None, None, None, False)
    assert (cell.acts == []) is uses_live and snap["state"] == HOME and snap["ok"] is True
    assert timing.MAX_OBSERVATION_AGE_S == 0.6  # the freshness limit itself is unchanged


# --- why a session did not start, and which causes may be tried again ---

@pytest.mark.parametrize("hint,lines,code,comm", [
    ("start_failed", ["write_caps: read pwm_limit: comm -3001"], "motor_comm", -3001),
    ("start_failed", ["Hardware error on joint 3: overload", "comm -3001"], "safety_state", None),
    ("start_failed", ["torque is ON before start"], "safety_state", None),
    ("start_failed", ["human-hold latched"], "safety_state", None),
    ("start_failed", ["observer handoff failed: lease held"], "observer_handoff", None),
    ("start_failed", ["camera frame HTTP 503"], "camera", None),
    ("lock_held", [], "lock_held", None),
    ("start_failed", ["something odd"], "start_failed", None),
])
def test_refusal_codes(hint, lines, code, comm):
    assert refusal.classify(hint, lines) == (code, comm)
    assert refusal.classify("start_failed", ["comm -3001"], bg_alive=True)[0] == "start_timeout"


def test_retry_limits_by_cause_and_safety_is_never_retried():
    assert refusal.decide("lock_held", 1, 0) == 5.0 and refusal.decide("lock_held", 20, 100) == 5.0  # every try inside the window
    assert refusal.decide("lock_held", 2, refusal.RETRY_WINDOW_S) is None  # a stuck holder, not a transient
    assert refusal.decide("motor_comm", 1, 5) == 3.0 and refusal.decide("motor_comm", 2, 5) is None
    assert refusal.decide("observer_handoff", 2, 5) == 3.0 and refusal.decide("observer_handoff", 3, 5) is None
    assert refusal.decide("camera", 1, 5) == 5.0 and refusal.decide("camera", 2, 5) is None
    for never in ("safety_state", "start_timeout", "unknown", "start_failed"):
        assert refusal.decide(never, 1, 0) is None


def test_refusal_row_carries_reason_comm_code_and_evidence_and_exits_10_only_to_retry(tmp_path, capsys):
    status = tmp_path / "chunk-status.jsonl"
    status.write_text(json.dumps({"command": "start", "ok": True}) + "\n"
                      + json.dumps({"command": "start", "ok": False, "error": "write_caps read pwm_limit: comm -3001"}) + "\n")
    log = tmp_path / "session.log"
    log.write_text("starting\nerror: bus open timeout\n")
    row, wait = refusal.refusal("arm_b", "start_failed", "REFUSED: the arm session did not start", status=str(status), n0=1,
                                log=str(log), attempt=1, t0=100.0, now=130.0)
    assert row["result"] == "retry" and wait == 3.0 and row["code"] == "motor_comm" and row["comm"] == -3001
    assert "comm -3001" in row["reason"] and row["elapsed_s"] == 30.0 and any("pwm_limit" in e for e in row["evidence"])
    slept = []
    args = ["--arm", "arm_b", "--code", "start_failed", "--message", "REFUSED: x", "--status", str(status), "--n0", "1", "--log", str(log)]
    assert refusal.main([*args, "--attempt", "1"], sleep=slept.append) == 10 and slept == [3.0]
    assert json.loads(capsys.readouterr().out)["result"] == "retry"
    assert refusal.main([*args, "--attempt", "2"], sleep=slept.append) == 0 and slept == [3.0]  # second comm failure: refuse
    final = json.loads(capsys.readouterr().out)
    assert final["result"] == "refused" and final["code"] == "motor_comm" and final["stage"] == "session"


def test_a_held_lock_ignores_old_status_rows(tmp_path):
    status = tmp_path / "chunk-status.jsonl"
    status.write_text(json.dumps({"command": "start", "ok": False, "error": "old torque ON fault"}) + "\n")
    row, wait = refusal.refusal("arm_b", "lock_held", "REFUSED: the arm session lock is held", status=str(status), lock_dir=tmp_path)
    assert row["code"] == "lock_held" and wait == 5.0 and row["lock_holder"] is None


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="field wrappers use bash")
@pytest.mark.parametrize("letter", ["a", "b"])
def test_wrapper_keeps_the_refused_line_adds_the_reason_and_retries_only_when_told_to(tmp_path, letter):
    prep = tmp_path / "rosy-test/omx-record-prep-20261019"
    (prep / f"chunk-io-{letter}").mkdir(parents=True)
    (prep / f"chunk-io-{letter}/chunk-status.jsonl").touch()
    env_file = tmp_path / ".config/rosy/omx-observation-bridge.env"
    env_file.parent.mkdir(parents=True)
    env_file.touch()
    bin_dir = tmp_path / "rosy-omx/current-env/bin"
    bin_dir.mkdir(parents=True)
    scripts = {
        "systemctl": 'test "$2" = stop',
        "python": ('case "$1" in\n'
                   '  */record_session.py) exit 1 ;;\n'
                   '  */session_refusal.py) echo "$@" | sed "s/.*--attempt \\([0-9]*\\).*/\\1/" >> "$HOME/attempts"\n'
                   '    if [ "$(wc -l < "$HOME/attempts")" -lt "$TEST_RETRIES" ]; then echo \'{"result": "retry"}\'; exit 10; fi\n'
                   '    echo \'{"result": "refused", "reason": "why"}\'; exit 0 ;;\n'
                   '  *) exit 99 ;;\nesac'),
    }
    for name, script in scripts.items():
        exe = bin_dir / name
        exe.write_text(f"#!/bin/sh\n{script}\n")
        exe.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}", "TEST_RETRIES": "3"}
    # run as the job API does: a relative ./path from the wrappers folder, so the retry must find itself after the wrapper's cd
    result = subprocess.run(["bash", f"./with-session-arm-{letter}-par.sh", "touch", str(tmp_path / "moved")], cwd=OMX / "session-wrappers",
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and not (tmp_path / "moved").exists()
    assert result.stdout.count("REFUSED: the arm session did not start") == 3  # asked to retry twice, then refused
    assert result.stdout.strip().splitlines()[-1] == '{"result": "refused", "reason": "why"}'
    assert (tmp_path / "attempts").read_text().split() == ["1", "2", "3"]  # each try knows its number


def test_state_files_block_a_retry_even_when_the_log_shows_a_transient_cause(tmp_path):
    live = tmp_path / "live.json"
    health = tmp_path / "motor-health-current.json"
    live.write_text(json.dumps({"t": 1, "state": HOME, "fault": None, "hold": False, "human_hold_latched": False}))
    health.write_text(json.dumps({"status": "ok", "motors": [{"joint": "gripper", "torque_enabled": False}]}))
    clean = [str(live), str(health)]
    assert refusal.state_flags(*clean) == [] and refusal.state_flags(str(tmp_path / "missing.json"), "/") == []
    row, wait = refusal.refusal("arm_b", "lock_held", "REFUSED: lock", state_files=clean, lock_dir=tmp_path)
    assert wait == 5.0 and row["result"] == "retry"
    for name, path, body, flag in (
            ("fault", live, {"fault": "joint at 80 % of its cap"}, "live.json:fault"),
            ("hold", live, {"hold": True}, "live.json:hold"),
            ("latched", live, {"human_hold_latched": True}, "live.json:human_hold_latched"),
            ("torque", health, {"motors": [{"joint": "gripper", "torque_enabled": True}]}, "motor-health-current.json:torque_enabled"),
            ("hw", health, {"motors": [{"hardware_error": 4}]}, "motor-health-current.json:hardware_error"),
            ("status", health, {"status": "fault"}, "motor-health-current.json:status=fault")):
        path.write_text(json.dumps(body))
        row, wait = refusal.refusal("arm_b", "lock_held", "REFUSED: x", state_files=clean, lock_dir=tmp_path)  # a cause that would be retried
        assert wait is None and row["result"] == "refused" and row["code"] == "safety_state", name  # no log line needed
        assert flag in row["reason"] or any(flag in e for e in row["evidence"]), name
        path.write_text(json.dumps({}))
    path = tmp_path / "status.jsonl"
    path.write_text(json.dumps({"command": "start", "ok": False, "error": "comm -3001"}) + "\n")
    row, wait = refusal.refusal("arm_b", "start_failed", "REFUSED: x", status=str(path), state_files=clean)
    assert row["code"] == "motor_comm" and wait == 3.0  # comm timeout with clean state files still gets its one retry


@pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="field wrappers use bash")
def test_wrapper_with_the_real_refusal_helper_does_not_retry_on_a_held_arm(tmp_path):
    prep = tmp_path / "rosy-test/omx-record-prep-20261019"
    (prep / "chunk-io-b").mkdir(parents=True)
    (prep / "chunk-io-b/chunk-status.jsonl").write_text("")
    (prep / "chunk-io-b/live.json").write_text(json.dumps({"t": 1, "state": HOME, "human_hold_latched": True}))
    env_file = tmp_path / ".config/rosy/omx-observation-bridge.env"
    env_file.parent.mkdir(parents=True)
    env_file.touch()
    bin_dir = tmp_path / "rosy-omx/current-env/bin"
    bin_dir.mkdir(parents=True)
    fake = {"systemctl": 'test "$2" = stop',
            "python": ('case "$1" in\n  */record_session.py) echo "error: comm -3001" >&2; exit 1 ;;\n'
                       f'  */session_refusal.py) exec {sys.executable} "$@" ;;\n  *) exit 99 ;;\nesac')}
    for name, script in fake.items():
        exe = bin_dir / name
        exe.write_text(f"#!/bin/sh\n{script}\n")
        exe.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    result = subprocess.run(["bash", "./with-session-arm-b-par.sh", "touch", str(tmp_path / "moved")], cwd=OMX / "session-wrappers",
                            env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 2 and not (tmp_path / "moved").exists()
    assert result.stdout.splitlines().count("REFUSED: the arm session did not start") == 1  # one attempt, no second session
    last = json.loads(result.stdout.strip().splitlines()[-1])
    assert last["result"] == "refused" and last["code"] == "safety_state" and "live.json:human_hold_latched" in last["reason"] + " ".join(last["evidence"])


def test_the_run_job_is_judged_like_the_drive_by_the_outcome_fence(monkeypatch):
    import cell_vlm_facts
    import cell_vlm_fence

    monkeypatch.setattr(cell_vlm_facts, "query_incident", lambda *a, **k: {"held": False})
    for job in ("cell_policy_drive", "cell_policy_run"):
        bad = {"exit": 0, "structured_result": {"result": "stopped_x", "parked": True, "took_one": True}}
        _status, detail = cell_vlm_fence.verify_job_outcome(type("C", (), {"readiness": lambda self: {}})(), job, "arm_b", bad, collect_facts=False)
        assert any("policy_drive result" in r for r in detail.get("failure_reasons", [])) or "policy_drive result" in json.dumps(detail), job
