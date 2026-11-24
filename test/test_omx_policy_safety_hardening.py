"""Safety hardening regressions covering owner fault gates, HOLD ack verification, pre-settle trajectories, and final cleanup."""
import errno
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np
import pytest

OMX = Path(__file__).resolve().parents[1] / "deploy/robot/omx"
if str(OMX) not in sys.path:
    sys.path.insert(0, str(OMX))

import cell_pipeline_io as cpio  # noqa: E402
import cell_policy_drive as drive  # noqa: E402
import cell_policy_paced as paced  # noqa: E402
import cell_policy_timing as timing  # noqa: E402
from cell_policy_timing import best_effort_hold, hold_ack_ok, retreat_ack_ok, run_timed, send_hold  # noqa: E402
from chunk_runner_run import Runner  # noqa: E402
from omx_adapter.chunk_library import NAMES, SCHEMA  # noqa: E402


class _FakeRobot:
    def __init__(self, pos):
        self.pos, self.sent = list(pos), []

    def send_action(self, action):
        self.sent.append(dict(action))
        self.pos = [action[n] for n in NAMES]

    def get_observation(self):
        return dict(zip(NAMES, self.pos))


def test_owner_rejects_checked_policy_and_overload_park_while_preserving_soft_and_bare_recovery(tmp_path):
    from cell_envelope import digest

    home = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "approach": [home]}}
    policy_lib = {**base_lib, "chunks": {**base_lib["chunks"], "policy": [home]}}
    base_p, pol_p = tmp_path / "base.json", tmp_path / "policy.json"
    base_p.write_text(json.dumps(base_lib), encoding="utf-8")
    pol_p.write_text(json.dumps(policy_lib), encoding="utf-8")
    overload_msg = "contact (overload-hold on wrist_flex by the guard): lift and elbow shed its load"

    for fault in ("pushing at rest: elbow_flex pwm 290", "temperature 70 C", "stalled: shoulder_lift", overload_msg):
        reports = []
        r = Runner(_FakeRobot(home), base_lib, fps=30, status=reports.append, operating_context={"session_id": "s1"})
        r.target = list(home)
        sha = digest(base_lib)
        assert r.command(f"checked s1 {sha} load {base_p}") and reports[-1]["ok"] is True
        r.fault = fault
        assert r.command(f"checked s1 {sha} park") and reports[-1]["ok"] is False
        assert "only state or stop" in reports[-1]["error"] and not r.queue and r.chunk is None

    # Policy-library bare park also refuses overload-hold once held clears, while bare non-policy thermal/overload and soft contact recover.
    r_pol_ol = Runner(_FakeRobot(home), policy_lib, fps=30, status=(rep_po := []).append)
    r_pol_ol.target, r_pol_ol.fault = list(home), overload_msg
    r_pol_ol.command("park")
    assert rep_po[-1]["ok"] is False and "only state or stop" in rep_po[-1]["error"] and not r_pol_ol.queue

    r_bare_push = Runner(_FakeRobot(home), base_lib, fps=30, status=(rep_bp := []).append)
    r_bare_push.target, r_bare_push.fault = list(home), "pushing at rest: elbow_flex"
    r_bare_push.command("park")
    assert rep_bp[-1]["ok"] is False and "only state or stop" in rep_bp[-1]["error"] and not r_bare_push.queue

    for fault_ok in ("temperature 66 C", overload_msg):
        r_ok = Runner(_FakeRobot(home), base_lib, fps=30, status=(rep_ok := []).append)
        r_ok.target, r_ok.fault = list(home), fault_ok
        r_ok.command("park")
        assert r_ok.chunk == "park" and r_ok.queue and not rep_ok

    r_contact = Runner(_FakeRobot(home), policy_lib, fps=30, status=(rep_ct := []).append, operating_context={"session_id": "s1"})
    r_contact.target = list(home)
    pol_sha = digest(policy_lib)
    r_contact.command(f"checked s1 {pol_sha} load {pol_p}")
    r_contact.fault = "contact in policy: lag"
    r_contact.command(f"checked s1 {pol_sha} park")
    assert r_contact.chunk == "park" and r_contact.queue and rep_ct[-1]["command"].endswith("load " + str(pol_p))


def test_hold_ack_ok_rejects_overload_and_no_runner_while_preserving_latch_evidence(tmp_path, monkeypatch):
    real_open, real_close, sink_fd, opens, sink = os.open, os.close, [None], [0], tmp_path / "fifo-sink"
    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    io_dir = tmp_path / "io"
    io_dir.mkdir()
    fifo = cpio.FifoCell(io_dir, cameras={}, timeout_s=0.05)

    def fail_open(path, flags):
        opens[0] += 1
        raise OSError(errno.ENXIO, "no reader")

    monkeypatch.setattr(cpio.os, "open", fail_open)
    with pytest.raises(OSError):
        send_hold(fifo, attempts=3, delay_s=0.0)
    assert opens[0] == 3
    opens[0] = 0
    assert best_effort_hold(fifo, attempts=3, delay_s=0.0) is None and opens[0] == 3

    def recover_second(path, flags):
        opens[0] += 1
        if opens[0] == 1:
            raise OSError(errno.ENXIO, "no reader")
        sink_fd[0] = real_open(sink, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        return sink_fd[0]

    def close_second(fd):
        real_close(fd)
        if fd == sink_fd[0]:
            req = sink.read_text(encoding="utf-8").strip().split()[1]
            (io_dir / "chunk-status.jsonl").write_text(json.dumps({"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req, "t": time.time() + 0.01}) + "\n", encoding="utf-8")

    opens[0] = 0
    with monkeypatch.context() as mp:
        mp.setattr(cpio.os, "open", recover_second)
        mp.setattr(cpio.os, "close", close_second)
        assert send_hold(fifo, attempts=3, delay_s=0.0)["torque_hold_commanded"] is True and opens[0] == 2

    overload_ack = {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False,
                    "error": "guard overload during human hold; person needed"}
    assert hold_ack_ok(overload_ack) is False
    assert hold_ack_ok({"ok": True}) is False
    assert hold_ack_ok({"command": "human-hold", "ok": True, "human_hold_latched": False, "torque_hold_commanded": True}) is False
    assert hold_ack_ok({"command": "human-hold", "ok": True, "human_hold_latched": True}) is False
    assert hold_ack_ok({"ok": True, "human_hold_latched": True, "torque_hold_commanded": True}) is False
    assert hold_ack_ok({"command": "human-hold", "ok": True, "released": True, "human_hold_latched": True, "torque_hold_commanded": True}) is False
    assert hold_ack_ok({"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}) is True

    ol_calls, ol_logs = [], []
    ol_cell = SimpleNamespace(act=lambda cmd: (ol_calls.append(cmd), dict(overload_ack))[1])
    with pytest.raises(OSError, match="human_hold_latched=True"):
        send_hold(ol_cell, attempts=3, delay_s=0.0, log=ol_logs.append)
    assert len(ol_calls) == 3 and ol_logs[-1]["unconfirmed"] is True
    assert ol_logs[-1]["human_hold_latched"] is True and ol_logs[-1]["torque_hold_commanded"] is False
    assert best_effort_hold(ol_cell, attempts=3, delay_s=0.0) is None
    assert retreat_ack_ok({"ok": True, "settled": True}) is False
    assert retreat_ack_ok({"command": "retreat", "ok": True, "settled": True}) is True


def test_final_paced_park_and_timed_cleanup_retry_hold_without_bypass(tmp_path, monkeypatch):
    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 51.0, 50.0, -5.0, 49.0]
    (lib_p := tmp_path / "lib.json").write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": [home, [20, -20, 30, 40, -5, 60]]}}))
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # Settled ACT chunk -> unsettled final park -> 3 failed HOLD writes -> fallback retries 4th attempt before raising.
    final_cmds, holds = [], [0]

    class FinalParkHoldRetryCell:
        def act(self, cmd):
            final_cmds.append(cmd)
            if cmd == "human-hold":
                holds[0] += 1
                if holds[0] <= 3:
                    raise BlockingIOError("busy")
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            if cmd == "park":
                return {"command": "park", "ok": True, "settled": False, "state": list(home)}
            return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home)}

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    with pytest.raises(BlockingIOError):
        drive.run_episode(FinalParkHoldRetryCell(), pol, lib_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert final_cmds.count("run policy") == 1 and final_cmds.count("park") == 1 and final_cmds.count("human-hold") == 4

    # No-runner HOLD refusal retries cleanly across both run_paced_chunks and run_timed without parking.
    shadow = SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16)
    for timed_mode in (False, True):
        cmds = []

        class NoRunnerCell:
            def act(self, cmd):
                cmds.append(cmd)
                if cmd == "human-hold":
                    return {"ok": False, "error": "chunk_runner is not running", "fault": "no runner"}
                if cmd == "run policy":
                    return {"command": "run policy", "ok": True, "settled": False, "state": list(home)}
                return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home)}

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        with pytest.raises(OSError):
            if timed_mode:
                run_timed(NoRunnerCell(), shadow, {"fps": 30, "chunks": {}, "gripper_closed": 46.6}, tmp_path,
                          infer=lambda *_: (np.zeros((16, 6)), {}), shape=lambda a, *_: a.tolist(), max_step=0.1, n_action=8, max_obs_age_s=0.6, max_chunks=1, dry_run=False, log=[].append, clock=lambda: 1.0)
            else:
                drive.run_episode(NoRunnerCell(), pol, lib_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert cmds.count("human-hold") >= 6 and not any(c.endswith("park") for c in cmds)

    # Soft contact missing command, overload contact (no snapshot), malformed timing, and KeyboardInterrupt all fail safe.
    ol_err = "contact (overload-hold on wrist_flex by the guard): lift and elbow shed its load"
    for fail_kind in ("bad_retreat", "overload", "bad_timing", "ki_run"):
        fc_cmds, frames_n = [], [0]

        class FailCell:
            def act(self, cmd):
                fc_cmds.append(cmd)
                if fail_kind == "ki_run" and cmd == "run policy":
                    raise KeyboardInterrupt()
                if fail_kind == "bad_retreat" and cmd == "run policy":
                    return {"command": "run policy", "ok": False, "contact": True, "error": "lag", "state": list(home)}
                if fail_kind == "bad_retreat" and cmd == "retreat":
                    return {"ok": True, "settled": True, "state": list(home)}  # missing command label
                if fail_kind == "overload" and cmd == "run policy":
                    return {"command": "run policy", "ok": False, "contact": True, "fault": ol_err, "error": ol_err, "state": list(home)}
                if fail_kind == "bad_timing" and cmd == "run policy":
                    return {"command": "run policy", "ok": True, "settled": False, "timing": "bad", "state": list(home)}
                extra = {"human_hold_latched": True, "torque_hold_commanded": True} if cmd == "human-hold" else {}
                return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home), **extra}

            def frame(self, _v):
                frames_n[0] += 1
                if fail_kind == "overload" and frames_n[0] > 2:
                    raise AssertionError("camera snapshot must not run before overload human-hold")
                return np.zeros((4, 4, 3), np.uint8)

        if fail_kind == "ki_run":
            with pytest.raises(KeyboardInterrupt):
                drive.run_episode(FailCell(), pol, lib_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        else:
            res_f = drive.run_episode(FailCell(), pol, lib_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
            assert res_f["parked"] is False
        assert fc_cmds[-1] == "human-hold" and "park" not in fc_cmds


def test_off_home_refusal_latches_hold_and_blocks_owner_idle_park_and_retry(tmp_path, monkeypatch):
    import chunk_runner_settle as crs

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    sag = [0.0, -58.0, 55.0, 50.0, -5.0, 49.0]
    sag_pre = [list(sag), [0.0, -58.0, 52.5, 50.0, -5.0, 49.0], list(home)]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6,
                "chunks": {"home": [home], "reach": [home, [20, -20, 30, 40, -5, 60]]}}
    pre_lib = {**base_lib, "chunks": {**base_lib["chunks"], "presettle": sag_pre}}
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # 1: Off-home stationary fault-free Runner (with and without `presettle`) latches confirmed HOLD and blocks idle auto-park forever.
    for idx, lib_doc in enumerate((base_lib, pre_lib)):
        (lp := tmp_path / f"idle-{idx}.json").write_text(json.dumps(lib_doc), encoding="utf-8")
        clk, reports, cmds = [10.0], [], []
        r = Runner(_FakeRobot(sag), lib_doc, fps=30, status=reports.append, clock=lambda c=clk: c[0])
        r.target, r.last_input, r.idle_parks, r.home_since = list(sag), 10.0, 0, None
        r.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [35] * 6}

        class RunnerCell:
            def act(self, cmd):
                cmds.append(cmd)
                r.command(cmd)
                if cmd == "human-hold":
                    r.tick()
                return reports[-1]

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        res = drive.run_episode(RunnerCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert res["result"] == "refused" and res["parked"] is False and "run home stage first" in res["reason"]
        assert cmds == ["state", "human-hold"]
        assert r.human_hold_latched is True and r.torque_hold_commanded is True and not r.queue and r.chunk is None
        clk[0] = 10.0 + crs.IDLE_PARK_S + 100.0
        assert r.idle() is False and crs.check_runner_idle(r, lambda _k, d: d) is False
        assert not r.queue and r.chunk is None

    # 2: Off-home BlockingIOError HOLD retries succeed on 4th attempt; all 6 failing raise OSError.
    (ev_p := tmp_path / "retry-lib.json").write_text(json.dumps(base_lib), encoding="utf-8")

    class RetryPreHoldCell:
        def __init__(self, fail_n: int):
            self.fail_n, self.holds, self.cmds = fail_n, 0, []

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd == "human-hold":
                self.holds += 1
                if self.holds <= self.fail_n:
                    raise BlockingIOError("busy")
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(sag)}

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    logs_ok = []
    c_ok = RetryPreHoldCell(fail_n=3)
    res_ok = drive.run_episode(c_ok, pol, ev_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=logs_ok.append, paced_chunks=True)
    assert res_ok["result"] == "refused" and res_ok["reason"] == "START_POSE_OFF_HOME"
    assert c_ok.cmds.count("human-hold") == 4 and any(row.get("command") == "human-hold" and row.get("ok") is True for row in logs_ok)

    c_fail = RetryPreHoldCell(fail_n=99)
    with pytest.raises(OSError):
        drive.run_episode(c_fail, pol, ev_p, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert c_fail.cmds.count("human-hold") == 6


def test_r11_owner_overload_gates_across_presettle_handoff_and_taught_carry_transitions(tmp_path, monkeypatch):
    import chunk_runner_interrupt as cri
    import chunk_runner_settle as crs
    import cell_policy_handoff as cph_mod

    home = [0.0, -58.0, 50.0, 50.0, -5.0, 46.6]
    off_home = [0.0, -58.0, 56.0, 50.0, -5.0, 46.6]
    overload = "contact (overload-hold on wrist_flex by the guard): lift and elbow shed its load"

    def _runner(lib):
        rep = []
        r = Runner(_FakeRobot(off_home), lib, fps=30, status=rep.append)
        r.target, r.fault = list(off_home), overload
        r.robot.motion = SimpleNamespace(held=None)
        r.clock = lambda: 100.0
        r.last_input, r.idle_parks, r.home_since = 0.0, 0, None
        r.hold_file = tmp_path / "hold.json"
        r.signals = []
        r.hold = lambda _p, reason, **_kw: (setattr(r, "human_hold_latched", True), setattr(r, "fault", reason))
        return r, rep

    # 1: `stop fold` and interrupt `_fold` refuse overload-hold while preserving ordinary soft contact recovery.
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "approach": [off_home]}}
    r_stop, rep_stop = _runner(base_lib)
    assert r_stop.command("stop fold") is True and r_stop.human_hold_latched is True and not r_stop.queue and rep_stop[-1]["hold"] is True

    r_int, rep_int = _runner(base_lib)
    r_int._interrupt = {"may_move": True, "phase": "verify", "deadline": 0.0}
    assert cri._fold(r_int, list(off_home)) is False and r_int.human_hold_latched is True and not r_int.queue

    r_soft, _ = _runner(base_lib)
    r_soft.fault = "contact in policy: lag"
    assert r_soft.command("stop fold") is True and r_soft.chunk == "park" and r_soft.queue

    # 2: Bare `park` and `check_runner_idle` reject overload-hold for `presettle` and `lift_pick_policy_handoff` AND persist across later taught carry loads.
    for chunk_name in ("presettle", "lift_pick_policy_handoff"):
        pol_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], chunk_name: [off_home, home]}}
        r_ov, rep_ov = _runner(pol_lib)
        assert r_ov.command("park") is True and rep_ov[-1]["ok"] is False and "only state or stop" in rep_ov[-1]["error"] and not r_ov.queue
        assert crs.check_runner_idle(r_ov, lambda _k, d: d) is False and not r_ov.queue

    taught_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "lift_pick": [home]}}
    (tl_p := tmp_path / "taught.json").write_text(json.dumps(taught_lib), encoding="utf-8")
    r_trans, rep_tr = _runner({"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6,
                               "chunks": {"home": [home], "lift_pick_policy_handoff": [off_home, home]}})
    r_trans.fault = None
    assert r_trans.command(f"load {tl_p}") and rep_tr[-1]["ok"] is True and r_trans._policy_session is True
    r_trans.fault = overload
    assert r_trans.command("park") is True and rep_tr[-1]["ok"] is False and "only state or stop" in rep_tr[-1]["error"] and not r_trans.queue
    assert crs.check_runner_idle(r_trans, lambda _k, d: d) is False and not r_trans.queue

    # 3: CellHandoff.carry routes returned unresolved overload/unsettled carry through retrying confirmed send_hold (never returning without HOLD).
    import grasp_planner

    class StubPlanner:
        kin = SimpleNamespace(fk=lambda _: SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0))

        def __init__(self, _p):
            pass

        def line(self, *_a):
            return [home], 0

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(grasp_planner, "Planner", StubPlanner)
    lib_h = {"fps": 30, "gripper_closed": 49, "chunks": {"home": [home]}, "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}}}
    (lib_hp := tmp_path / "h.json").write_text(json.dumps(lib_h))
    cfg_h = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}
    shadow = SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16)
    monkeypatch.setattr(cph_mod, "_carry", lambda *_a, **_kw: {
        "result": "contact", "error": overload,
        "steps": [{"command": "park", "ok": False, "settled": False, "error": overload}],
    })

    for persistent in (False, True):
        cmds, logs, holds = [], [], [0]

        class CarryOverloadCell:
            def act(self, cmd):
                cmds.append(cmd)
                if cmd == "human-hold":
                    holds[0] += 1
                    if not persistent and holds[0] >= 2:
                        return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                    return {"command": "human-hold", "ok": False, "human_hold_latched": True, "torque_hold_commanded": False}
                if cmd == "run policy":
                    return {"command": "run policy", "ok": True, "settled": True, "holding": True, "state": [0] * 5 + [53],
                            "target": [0] * 5 + [50], "handoff": {"triggered": True, "holding_frames": 8, "jaw": 53}}
                return {"command": cmd, "ok": True, "settled": True, "holding": True, "state": [0] * 5 + [53], "target": [0] * 5 + [50]}

        handoff = cph_mod.CellHandoff(cfg_h, "belt", lib_hp, lib_h, 51, tmp_path)
        if persistent:
            with pytest.raises(OSError):
                run_timed(CarryOverloadCell(), shadow, lib_h, tmp_path, infer=lambda *_: (np.zeros((16, 6)), {}),
                          shape=lambda a, *_: a.tolist(), max_step=0.1, n_action=8, max_obs_age_s=0.6, max_chunks=1,
                          dry_run=False, log=logs.append, handoff=handoff, clock=lambda: 1.0)
            assert cmds.count("human-hold") == 6
        else:
            res = run_timed(CarryOverloadCell(), shadow, lib_h, tmp_path, infer=lambda *_: (np.zeros((16, 6)), {}),
                            shape=lambda a, *_: a.tolist(), max_step=0.1, n_action=8, max_obs_age_s=0.6, max_chunks=1,
                            dry_run=False, log=logs.append, handoff=handoff, clock=lambda: 1.0)
            assert res["result"] == "refused" and cmds.count("human-hold") == 2 and logs[-1]["ok"] is True


def test_r13_hardware_jaw_telemetry_and_chunk0_post_inference_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    sag = [0.0, -58.0, 55.0, 50.0, -5.0, 49.0]
    ctx = {"scope": "hardware", "sha256": "b" * 64, "operating_profile": {"profile_sha256": "c" * 64}}
    base_chunks = {"home": [home], "reach": [home, [20, -20, 30, 40, -5, 60]]}
    ev_lib = tmp_path / "ev-lib.json"
    ev_lib.write_text(json.dumps({"fps": 30, "gripper_closed": 46.6, "chunks": base_chunks}), encoding="utf-8")
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # 1: Real hardware Runner `state` refreshes health + `health_t`; read failure clears stale `health` and omits `health_t`.
    clk = [100.0]
    monkeypatch.setattr(timing.time, "time", lambda: clk[0])
    rep_hw = []
    r_hw = Runner(_FakeRobot(home), {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": base_chunks},
                  fps=30, status=rep_hw.append, operating_context={**ctx, "session_id": "s1"})
    r_hw.target = list(home)
    r_hw.health = {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [35] * 6}  # stale cached sample before state
    assert timing.empty_gripper_ok({**r_hw.__dict__, "holding": False, "t": 100.0}, now=100.0) is False
    r_hw.read_health = lambda: {"pwm": [0] * 6, "current_ma": [0] * 5 + [12], "temp_c": [35] * 6}
    assert r_hw.command("state") and isinstance(rep_hw[-1].get("health_t"), float)
    assert timing.empty_gripper_ok({**rep_hw[-1], "t": 100.0, "health_t": 100.0}, now=100.0) is True
    r_hw.read_health = lambda: (_ for _ in ()).throw(OSError("bus down"))
    assert r_hw.command("state") and rep_hw[-1]["health"] is None and "health_t" not in rep_hw[-1]
    assert timing.empty_gripper_ok(rep_hw[-1], now=clk[0]) is False
    assert timing.empty_gripper_ok({**rep_hw[-1], "health": {"current_ma": [0] * 6}, "health_t": clk[0] - 2.0, "t": clk[0]}, now=clk[0]) is False

    # 2: Hardware initial/sample-2 `state` lacking fresh `health`/`health_t` OR high jaw current refuses with confirmed HOLD before ACT.
    bad_hw_cases = (
        {"holding": False, "operating_context": ctx},  # health=None
        {"holding": False, "operating_context": ctx, "health": {"current_ma": [0] * 6}},  # cached, no health_t
        {"holding": False, "operating_context": ctx, "health": {"current_ma": [0] * 6}, "t": 100.0, "health_t": 98.0},  # stale health_t
        {"holding": False, "operating_context": ctx, "health": {"current_ma": [0] * 5 + [150]}, "t": 100.0, "health_t": 100.0},
    )
    for bad_patch in bad_hw_cases:
        cmds_b = []
        monkeypatch.setattr(paced.time, "time", lambda: 100.0)

        class BadHwCell:
            def act(self, cmd):
                cmds_b.append(cmd)
                if cmd == "human-hold":
                    return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                return {"command": "state", "ok": True, "state": list(home), "t": 100.0, **bad_patch}

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        res_b = drive.run_episode(BadHwCell(), pol, ev_lib, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert res_b["result"] == "refused" and cmds_b == ["state", "human-hold"]

    # 3: Chunk-0 post-inference `auth_status` recheck catches holding=True, 150 mA, missing hardware health, AND off-home drift BEFORE load/authorize (with and without authorize).
    good_hw = {"holding": False, "operating_context": ctx, "t": 100.0, "health_t": 100.0, "health": {"current_ma": [0] * 5 + [10]}}
    third_patches = (
        {**good_hw, "holding": True},
        {**good_hw, "health": {"current_ma": [0] * 5 + [150]}},
        {"holding": False, "operating_context": ctx, "t": 100.0, "health": None},
        {**good_hw, "state": list(sag)},
    )
    monkeypatch.setattr(paced.time, "time", lambda: 100.0)
    for use_auth in (False, True):
        for third in third_patches:
            seq, cmds_3 = [dict(good_hw), dict(good_hw), third], []

            class ThirdStateCell:
                def act(self, cmd):
                    cmds_3.append(cmd)
                    if cmd == "state":
                        return {"command": "state", "ok": True, "state": list(home), **seq.pop(0)}
                    if cmd == "human-hold":
                        return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                    return {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home)}

                def frame(self, _v):
                    return np.zeros((4, 4, 3), np.uint8)

            auth_fn = (lambda *_a: pytest.fail("authorize must not run when chunk-0 recheck fails")) if use_auth else None
            res_3 = drive.run_episode(ThirdStateCell(), pol, ev_lib, tmp_path, offset=[0] * 6,
                                      max_chunks=1, dry_run=False, log=[].append, authorize=auth_fn, paced_chunks=True)
            assert res_3["result"] == "refused" and res_3["parked"] is False
            assert cmds_3 == ["state", "state", "state", "human-hold"] and not any("load " in c or "run policy" in c for c in cmds_3)

    # 4: Clean hardware session with fresh `health_t` on all 3 state checks completes chunk 0 and parks.
    ok_cmds = []

    class CleanHwCell:
        def act(self, cmd):
            ok_cmds.append(cmd)
            return {"command": cmd, "ok": True, "settled": True, "state": list(home), **good_hw}

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    res_hw_ok = drive.run_episode(
        CleanHwCell(), pol, ev_lib, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append,
        authorize=lambda *_a: {"session_id": "s1", "library_sha256": "h1"}, paced_chunks=True,
    )
    assert res_hw_ok["result"] == "chunks_done" and res_hw_ok["parked"] is True and ok_cmds.count("state") == 3
    assert "checked s1 h1 run policy" in ok_cmds and "checked s1 h1 park" in ok_cmds


def test_r14_chunk0_post_inference_io_error_and_shaking_latch_hold(tmp_path, monkeypatch):
    import chunk_runner_settle as crs

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    lib_doc = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6,
               "chunks": {"home": [home], "reach": [home, [20, -20, 30, 40, -5, 60]]}}
    (lp := tmp_path / "r14-lib.json").write_text(json.dumps(lib_doc), encoding="utf-8")
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # 1: Real Runner chunk-0 post-inference `state` OSError latches confirmed HOLD and blocks idle auto-park.
    clk1, rep1, cmds1 = [10.0], [], []
    r1 = Runner(_FakeRobot(home), lib_doc, fps=30, status=rep1.append, clock=lambda: clk1[0])
    r1.target, r1.last_input, r1.idle_parks, r1.home_since = list(home), 10.0, 0, None

    class IoFailCell:
        def act(self, cmd):
            cmds1.append(cmd)
            if cmd == "state" and cmds1.count("state") == 3:
                raise OSError("fifo timeout")
            r1.command(cmd)
            if cmd == "human-hold":
                r1.tick()
            return rep1[-1]

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    res1 = drive.run_episode(IoFailCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert res1["result"] == "refused" and res1["parked"] is False
    assert cmds1 == ["state", "state", "state", "human-hold"]
    assert r1.human_hold_latched is True and r1.torque_hold_commanded is True and not r1.queue
    clk1[0] = 10.0 + crs.IDLE_PARK_S + 100.0
    assert r1.idle() is False and crs.check_runner_idle(r1, lambda _k, d: d) is False and not r1.queue

    # 2: Real Runner reporting `jitter.shaking=True` at chunk-0 post-inference recheck refuses with confirmed HOLD BEFORE `load`/`run policy`.
    clk2, rep2, cmds2 = [10.0], [], []
    r2 = Runner(_FakeRobot(home), lib_doc, fps=30, status=rep2.append, clock=lambda: clk2[0])
    r2.target, r2.last_input, r2.idle_parks, r2.home_since = list(home), 10.0, 0, None

    class ShakingCell:
        def act(self, cmd):
            cmds2.append(cmd)
            if cmd == "state" and cmds2.count("state") == 3:
                r2.jitter = {"shaking": True, "flagged": ["elbow_flex"], "max_std": 1.0}
            r2.command(cmd)
            if cmd == "human-hold":
                r2.tick()
            return rep2[-1]

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    res2 = drive.run_episode(
        ShakingCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append,
        authorize=lambda *_a: pytest.fail("authorize must not run when owner reports shaking"), paced_chunks=True,
    )
    assert res2["result"] == "refused" and res2["parked"] is False and cmds2 == ["state", "state", "state", "human-hold"]
    assert r2.human_hold_latched is True and r2.torque_hold_commanded is True and not r2.queue
    clk2[0] = 10.0 + crs.IDLE_PARK_S + 100.0
    assert r2.idle() is False and crs.check_runner_idle(r2, lambda _k, d: d) is False and not r2.queue

    # 3: `policy_state()` raising OSError during chunk-0 post-inference recheck also latches confirmed HOLD before dispatch.
    cmds3 = []

    class PolicyStateFailCell:
        def act(self, cmd):
            cmds3.append(cmd)
            if cmd == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            return {"command": cmd, "ok": True, "state": list(home), "holding": False}

        def policy_state(self):
            if cmds3.count("state") >= 3:
                raise OSError("live.json unreadable")
            return {"t": time.time(), "state": list(home), "target": list(home), "jitter": {"shaking": False}}

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    res3 = drive.run_episode(PolicyStateFailCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
    assert res3["result"] == "refused" and res3["parked"] is False and cmds3 == ["state", "state", "state", "human-hold"]


def test_r15_fifo_hold_bypasses_broken_status_file_and_load_or_chunk1_state_failures_latch_hold(tmp_path, monkeypatch):
    import chunk_runner_settle as crs

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    tgt = [10.0, -40.0, 40.0, 45.0, -5.0, 60.0]
    reach = [[round(home[i] + (tgt[i] - home[i]) * k / 250, 4) for i in range(6)] for k in range(251)]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": reach}}
    (lp := tmp_path / "r15-lib.json").write_text(json.dumps(base_lib), encoding="utf-8")
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # 1: FifoCell status-file stat OSError triggers HOLD on `state` and STILL opens `chunk-cmd` to write `human-hold`.
    io_dir = tmp_path / "broken_status_io"
    io_dir.mkdir()
    (io_dir / "chunk-cmd").write_bytes(b"")
    (io_dir / "chunk-status.jsonl").write_text("", encoding="utf-8")
    fifo = cpio.FifoCell(io_dir, {}, timeout_s=0.01)
    real_stat, real_exists, real_open, real_close = Path.stat, Path.exists, os.open, os.close
    opened, write_live, sink_fd = [], [True], [None]

    def _bad_exists(self):
        return True if self == io_dir / "chunk-status.jsonl" else real_exists(self)

    def _bad_stat(self, *a, **kw):
        if self == io_dir / "chunk-status.jsonl":
            raise OSError("status I/O error")
        return real_stat(self, *a, **kw)

    def _open_fifo(path, flags):
        if Path(path) == io_dir / "chunk-cmd":
            opened.append(str(path))
            sink_fd[0] = real_open(tmp_path / "cmd-sink", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            return sink_fd[0]
        return real_open(path, flags)

    def _close_fifo(fd):
        real_close(fd)
        if write_live[0] and fd == sink_fd[0]:
            req = (tmp_path / "cmd-sink").read_text(encoding="utf-8").strip().split()[1]
            (io_dir / "live.json").write_text(json.dumps({"t": time.time() + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": req, "state": home}), encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setattr(Path, "exists", _bad_exists)
        mp.setattr(Path, "stat", _bad_stat)
        mp.setattr(cpio.os, "open", _open_fifo)
        mp.setattr(cpio.os, "close", _close_fifo)
        res_fifo = drive.run_episode(fifo, pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert res_fifo["result"] == "refused" and len(opened) == 1
        assert (tmp_path / "cmd-sink").read_text(encoding="utf-8").startswith("human-hold ")

        opened.clear()
        write_live[0] = False
        (io_dir / "live.json").unlink()
        with pytest.raises(OSError):
            drive.run_episode(fifo, pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert len(opened) == 6

    # 2: Lost 1st `load` acknowledgement (raised OSError OR timeout row) latches confirmed HOLD and blocks owner idle auto-park.
    for timeout_reply in (False, True):
        clk_l, rep_l, cmds_l = [10.0], [], []
        r_l = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_l.append, clock=lambda c=clk_l: c[0])
        r_l.target, r_l.last_input, r_l.idle_parks, r_l.home_since = list(home), 10.0, 0, None

        class LoadLostCell:
            def act(self, cmd):
                cmds_l.append(cmd)
                if "load " in cmd:
                    r_l.command(cmd)
                    if timeout_reply:
                        return {"ok": False, "error": "no status within 300 s"}
                    raise OSError("load reply lost")
                r_l.command(cmd)
                if cmd == "human-hold":
                    r_l.tick()
                return rep_l[-1]

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        if timeout_reply:
            res_l = drive.run_episode(LoadLostCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
            assert res_l["result"] == "fault" and res_l["parked"] is False
        else:
            with pytest.raises(OSError, match="load reply lost"):
                drive.run_episode(LoadLostCell(), pol, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert "policy" in r_l.library["chunks"] and cmds_l[-1] == "human-hold" and not any("park" in c for c in cmds_l)
        assert r_l.human_hold_latched is True and r_l.torque_hold_commanded is True and not r_l.queue
        clk_l[0] = 10.0 + crs.IDLE_PARK_S + 100.0
        assert r_l.idle() is False and crs.check_runner_idle(r_l, lambda _k, d: d) is False and not r_l.queue

    # 3: State-read failure on chunk 1 after chunk 0 moved latches confirmed HOLD and never queues `park` without a fresh pose.
    for fail_mode in ("raise", "timeout"):
        clk_c, rep_c, cmds_c, state_n = [10.0], [], [], [0]
        r_c = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_c.append, clock=lambda c=clk_c: c[0])
        r_c.target, r_c.last_input, r_c.idle_parks, r_c.home_since = list(home), 10.0, 0, None

        class Chunk1StateFailCell:
            def act(self, cmd):
                cmds_c.append(cmd)
                if cmd == "state":
                    state_n[0] += 1
                    if state_n[0] == 4:  # first state read of chunk 1
                        if fail_mode == "raise":
                            raise OSError("state fifo read failed")
                        return {"ok": False, "error": "no status within 300 s"}
                r_c.command(cmd)
                if cmd.endswith("run policy"):
                    while r_c.queue or r_c.chunk is not None:
                        clk_c[0] += 1 / 30
                        r_c.tick()
                elif cmd == "human-hold":
                    clk_c[0] += 1 / 30
                    r_c.tick()
                return rep_c[-1]

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        pol2 = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                               inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))
        res_c = drive.run_episode(Chunk1StateFailCell(), pol2, lp, tmp_path, offset=[0] * 6, max_chunks=2, dry_run=False, log=[].append, paced_chunks=True)
        assert res_c["result"] == "refused" and res_c["at"] == 1 and res_c["parked"] is False
        assert cmds_c.count("run policy") == 1 and cmds_c[-1] == "human-hold" and not any("park" in c for c in cmds_c)
        assert r_c.human_hold_latched is True and r_c.torque_hold_commanded is True and not r_c.queue
        clk_c[0] = 10.0 + crs.IDLE_PARK_S + 100.0
        assert r_c.idle() is False and crs.check_runner_idle(r_c, lambda _k, d: d) is False and not r_c.queue


def test_r16_post_load_abort_fifo_timeout_before_idle_park_and_null_status_hold(tmp_path, monkeypatch):
    import chunk_runner_settle as crs
    from cell_envelope import digest

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    tgt = [10.0, -40.0, 40.0, 45.0, -5.0, 60.0]
    reach = [[round(home[i] + (tgt[i] - home[i]) * k / 250, 4) for i in range(6)] for k in range(251)]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": reach}}
    (lp := tmp_path / "r16-lib.json").write_text(json.dumps(base_lib), encoding="utf-8")
    pol = SimpleNamespace(image_views={"top": (4, 4), "wrist": (4, 4)}, goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))

    # 1A: Stale observation immediately after chunk-0 `load` in an authorized `run_paced_chunks` session still latches HOLD and blocks idle park.
    wall, rep_s, cmds_s = [1000.0], [], []
    r_s = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_s.append, clock=lambda w=wall: w[0], operating_context={"session_id": "s1"})
    r_s.target, r_s.last_input, r_s.idle_parks, r_s.home_since = list(home), 1000.0, 0, None

    class _PostLoadWrapper:
        def __init__(self, runner, rep, cmds, clk_ref, bump_on_load: bool):
            self.runner, self.rep, self.cmds, self.clk_ref, self.bump = runner, rep, cmds, clk_ref, bump_on_load

        def act(self, cmd):
            self.cmds.append(cmd)
            self.runner.command(cmd)
            if "load " in cmd and self.bump:
                self.clk_ref[0] += 1.0
            if cmd == "human-hold":
                self.clk_ref[0] += 1 / 30
                self.runner.tick()
            res = dict(self.rep[-1])
            if cmd == "state":
                res.setdefault("health_t", self.clk_ref[0])
                res.setdefault("gripper_ma", 0.0)
            return res

        def frame(self, _v):
            return np.zeros((4, 4, 3), np.uint8)

    with monkeypatch.context() as mp:
        mp.setattr(paced.time, "time", lambda w=wall: w[0])
        auth_fn = lambda lib, _st, _seq: {"session_id": "s1", "library_sha256": digest(lib)}
        res_s = drive.run_episode(_PostLoadWrapper(r_s, rep_s, cmds_s, wall, True), pol, lp, tmp_path, offset=[0] * 6,
                                  max_chunks=1, dry_run=False, log=[].append, authorize=auth_fn, paced_chunks=True)
    assert res_s["result"] == "refused" and res_s["reason"] == "stale policy observation" and res_s["parked"] is False
    assert cmds_s[-1] == "human-hold" and "run policy" not in cmds_s and "policy" in r_s.library["chunks"]
    assert r_s.human_hold_latched is True and r_s.torque_hold_commanded is True and not r_s.queue
    wall[0] = 1000.0 + crs.IDLE_PARK_S + 100.0
    assert r_s.idle() is False and crs.check_runner_idle(r_s, lambda _k, d: d) is False and not r_s.queue

    # 1B: Exception in `log(load_row)` after chunk-0 `load` in `run_paced_chunks` enters `except BaseException`, latches HOLD, and blocks idle park.
    wall_b, rep_b, cmds_b = [1000.0], [], []
    r_b = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_b.append, clock=lambda w=wall_b: w[0], operating_context={"session_id": "s1"})
    r_b.target, r_b.last_input, r_b.idle_parks, r_b.home_since = list(home), 1000.0, 0, None

    def _boom_on_load(entry):
        if entry.get("command") == "load":
            raise RuntimeError("disk full")

    with monkeypatch.context() as mp:
        mp.setattr(paced.time, "time", lambda w=wall_b: w[0])
        with pytest.raises(RuntimeError, match="disk full"):
            drive.run_episode(_PostLoadWrapper(r_b, rep_b, cmds_b, wall_b, False), pol, lp, tmp_path, offset=[0] * 6,
                              max_chunks=1, dry_run=False, log=_boom_on_load,
                              authorize=lambda lib, _st, _seq: {"session_id": "s1", "library_sha256": digest(lib)}, paced_chunks=True)
    assert cmds_b[-1] == "human-hold" and "policy" in r_b.library["chunks"]
    assert r_b.human_hold_latched is True and r_b.torque_hold_commanded is True and not r_b.queue
    wall_b[0] = 1000.0 + crs.IDLE_PARK_S + 100.0
    assert r_b.idle() is False and crs.check_runner_idle(r_b, lambda _k, d: d) is False and not r_b.queue

    # 1C: BaseException immediately after chunk-0 `load` in `run_timed` still invokes `best_effort_hold` (`hold_needed` stays True) and blocks idle park.
    clk_t, rep_t, cmds_t, load_done = [10.0], [], [], [False]
    r_t = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_t.append, clock=lambda: clk_t[0])
    r_t.target, r_t.last_input, r_t.idle_parks, r_t.home_since = list(home), 10.0, 0, None

    class _TimedAbort(BaseException):
        pass

    class _TimedLoadWrap(_PostLoadWrapper):
        def act(self, cmd):
            out = super().act(cmd)
            if "load " in cmd:
                load_done[0] = True
            return out

    sh_t = SimpleNamespace(image_views=(), sim_rule=None, chunk_size=8)
    pol_act = [[round(home[i] + 0.02 * (k + 1) if i == 0 else home[i], 4) for i in range(6)] for k in range(8)]
    with monkeypatch.context() as mp:
        mp.setattr(timing.time, "time", lambda c=clk_t: c[0])
        with pytest.raises(_TimedAbort):
            run_timed(_TimedLoadWrap(r_t, rep_t, cmds_t, clk_t, False), sh_t, base_lib, tmp_path,
                      infer=lambda *_: (np.asarray(pol_act, dtype=float), {}),
                      shape=lambda actions, *_a: np.asarray(actions, dtype=float).tolist(), max_step=10.0, n_action=8, max_obs_age_s=0.6,
                      max_chunks=1, dry_run=False, log=[].append,
                      clock=lambda: (_ for _ in ()).throw(_TimedAbort("abort after load")) if load_done[0] else clk_t[0],
                      sleep=lambda _dt: None)
    assert load_done[0] is True and cmds_t[-1] == "human-hold" and "policy" in r_t.library["chunks"]
    assert r_t.human_hold_latched is True and r_t.torque_hold_commanded is True and not r_t.queue
    clk_t[0] = 10.0 + crs.IDLE_PARK_S + 100.0
    assert r_t.idle() is False and crs.check_runner_idle(r_t, lambda _k, d: d) is False and not r_t.queue

    # 2 & 3: Default `FifoCell` caps `state`/`load`/`human-hold` timeouts strictly below `runner.idle_park_s` min (5s), beats idle park E2E, and skips non-dict JSON rows.
    io2 = tmp_path / "r16_fifo_io"
    io2.mkdir()
    (io2 / "chunk-cmd").write_bytes(b"")
    status2 = io2 / "chunk-status.jsonl"
    status2.write_text("", encoding="utf-8")
    fifo_def = cpio.FifoCell(io2, {})
    assert fifo_def.timeout_s == 300
    fifo_10 = cpio.FifoCell(io2, {}, timeout_s=10.0)
    mono, written_cmds, mode = [0.0], [], ["timeout"]
    rep_e2e = []
    r_e2e = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_e2e.append, clock=lambda: 2000.0 + mono[0])
    r_e2e.target, r_e2e.last_input, r_e2e.idle_parks, r_e2e.home_since = list(home), 2000.0, 0, None
    real_open2, real_close2 = os.open, os.close

    def _open2(path, flags):
        if Path(path) == io2 / "chunk-cmd":
            return real_open2(tmp_path / "r16-cmd-sink", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        return real_open2(path, flags)

    def _close2(fd):
        real_close2(fd)
        cmd_txt = (tmp_path / "r16-cmd-sink").read_text(encoding="utf-8").strip()
        written_cmds.append(cmd_txt)
        if mode[0] == "null_state":
            with status2.open("a", encoding="utf-8") as s:
                s.write("null\n[1]\n" + json.dumps({"command": "state", "ok": True, "state": home}) + "\n")
        elif mode[0] == "null_hold":
            with status2.open("a", encoding="utf-8") as s:
                s.write("null\n[1]\n")
            (io2 / "live.json").write_text(
                json.dumps({"t": 2000.0 + mono[0] + 0.01, "human_hold_latched": True, "torque_hold_commanded": True, "hold_req": cmd_txt.split()[1], "state": home}),
                encoding="utf-8",
            )
        elif mode[0] == "e2e_lost_load":
            before = len(rep_e2e)
            if cmd_txt.startswith("human-hold"):
                mono[0] += 1 / 30
            r_e2e.command(cmd_txt)
            if cmd_txt.startswith("human-hold"):
                r_e2e.tick()
            if "load " not in cmd_txt:
                with status2.open("a", encoding="utf-8") as s:
                    for row in rep_e2e[before:]:
                        s.write(json.dumps(row) + "\n")
            live_doc = {"t": 2000.0 + mono[0] + 0.01, "state": home, "target": home, "jitter": {"shaking": False}}
            if r_e2e.human_hold_latched:
                live_doc.update(human_hold_latched=True, torque_hold_commanded=True, **({"hold_req": r_e2e._human_hold_acked_req} if getattr(r_e2e, "_human_hold_acked_req", None) else {}))
            (io2 / "live.json").write_text(json.dumps(live_doc), encoding="utf-8")

    import chunk_runner_run as crr

    with monkeypatch.context() as mp:
        mp.setattr(cpio.time, "monotonic", lambda: mono[0])
        mp.setattr(cpio.time, "sleep", lambda dt: mono.__setitem__(0, mono[0] + dt))
        mp.setattr(cpio.time, "time", lambda: 2000.0 + mono[0])
        mp.setattr(crr.time, "time", lambda: 2000.0 + mono[0])
        mp.setattr(cpio.os, "open", _open2)
        mp.setattr(cpio.os, "close", _close2)

        for cmd_str, exp_err in (
            ("state", "no status within 3.0 s"),
            ("checked s1 deadbeef load /tmp/lib.json", "no status within 3.0 s"),
            ("human-hold", "no status within 1.0 s"),
        ):
            mono[0] = 0.0
            rep_to = fifo_def.act(cmd_str)
            assert rep_to["ok"] is False and rep_to["error"] == exp_err and mono[0] < 5.0

        mono[0] = 0.0
        rep_park = fifo_10.act("park")
        assert rep_park["ok"] is False and rep_park["error"] == "no status within 10.0 s" and mono[0] >= 10.0

        mode[0] = "null_state"
        rep_ns = fifo_def.act("state")
        assert rep_ns["ok"] is True and rep_ns["command"] == "state" and rep_ns["state"] == home

        mode[0] = "null_hold"
        rep_nh = fifo_def.act("human-hold")
        assert hold_ack_ok(rep_nh) is True and rep_nh["state"] == home

        status2.write_text("", encoding="utf-8")
        (io2 / "live.json").write_text(
            json.dumps({"t": 2000.0, "state": home, "target": home, "jitter": {"shaking": False}}),
            encoding="utf-8",
        )
        written_cmds.clear()
        mono[0], mode[0] = 0.0, "e2e_lost_load"
        pol_e2e = SimpleNamespace(image_views=(), goal_size=None, sim_rule=None,
                                  inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[5, -50, 45, 48, -5, 49.0]]))
        res_e2e = drive.run_episode(fifo_def, pol_e2e, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
        assert res_e2e["result"] == "fault" and res_e2e["parked"] is False and "policy" in r_e2e.library["chunks"]
        assert written_cmds[-1].startswith("human-hold ") and mono[0] < crs.IDLE_PARK_S and mono[0] < 5.0
        assert r_e2e.human_hold_latched is True and r_e2e.torque_hold_commanded is True and not r_e2e.queue
        mono[0] = crs.IDLE_PARK_S + 100.0
        assert r_e2e.idle() is False and crs.check_runner_idle(r_e2e, lambda _k, d: d) is False and not r_e2e.queue


def test_r17_lost_motion_reply_blocks_idle_park_and_state_interrupt_latches_hold(tmp_path, monkeypatch):
    import chunk_runner_run as crr
    import chunk_runner_settle as crs

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    tgt = [10.0, -40.0, 40.0, 45.0, -5.0, 60.0]
    reach = [[round(home[i] + (tgt[i] - home[i]) * k / 250, 4) for i in range(6)] for k in range(251)]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": reach}}
    (lp := tmp_path / "r17-lib.json").write_text(json.dumps(base_lib), encoding="utf-8")

    # 1: Lost `run policy` status reply (withheld while FifoCell waits 300s) never triggers idle park on an off-home policy owner, then latches HOLD.
    pol_p = SimpleNamespace(image_views=(), goal_size=None, sim_rule=None,
                          inputs=lambda st, _fr: ({"s": st}, {}), infer=lambda _o: SimpleNamespace(chunk=[[2.0, -56.0, 49.0, 50.0, -5.0, 49.0]]))
    pol_act = [[round(home[i] + 0.02 * (k + 1) if i == 0 else home[i], 4) for i in range(6)] for k in range(8)]
    sh_t = SimpleNamespace(image_views=(), sim_rule=None, chunk_size=8)
    real_open, real_close = os.open, os.close

    for mode in ("paced", "timed"):
        io_m = tmp_path / f"r17_motion_{mode}"
        io_m.mkdir()
        (io_m / "chunk-cmd").write_bytes(b"")
        status_m = io_m / "chunk-status.jsonl"
        status_m.write_text("", encoding="utf-8")
        (io_m / "live.json").write_text(
            json.dumps({"t": 2000.0, "state": home, "target": home, "jitter": {"shaking": False}}),
            encoding="utf-8",
        )
        fifo_m = cpio.FifoCell(io_m, {})
        mono, rep_m, cmds_m, waiting_motion = [0.0], [], [], [False]
        r_m = Runner(_FakeRobot(home), base_lib, fps=30, status=rep_m.append, clock=lambda: mono[0], params={"runner.idle_park_s": 5.0})
        r_m.target, r_m.last_input, r_m.idle_parks, r_m.home_since = list(home), 0.0, 0, None

        def _open_m(path, flags, *, _io=io_m, _p=tmp_path / f"r17-sink-{mode}"):
            if Path(path) == _io / "chunk-cmd":
                return real_open(_p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            return real_open(path, flags)

        def _close_m(fd, *, _io=io_m, _st=status_m, _p=tmp_path / f"r17-sink-{mode}", _r=r_m, _rep=rep_m, _cmds=cmds_m, _mono=mono, _wm=waiting_motion):
            real_close(fd)
            cmd_txt = _p.read_text(encoding="utf-8").strip()
            _cmds.append(cmd_txt)
            before = len(_rep)
            if cmd_txt.startswith("human-hold"):
                _wm[0] = False
                _mono[0] += 1 / 30
            _r.command(cmd_txt)
            if cmd_txt.endswith("run policy"):
                while _r.queue or _r.chunk is not None:
                    _mono[0] += 1 / 30
                    _r.tick()
                _r.last_input = _mono[0]
                _wm[0] = True
            else:
                if cmd_txt.startswith("human-hold"):
                    _r.tick()
                with _st.open("a", encoding="utf-8") as s:
                    for row in _rep[before:]:
                        s.write(json.dumps(row) + "\n")
            live_doc = {"t": 2000.0 + _mono[0] + 0.01, "state": list(_r.robot.pos), "target": list(_r.target), "jitter": {"shaking": False}}
            if _r.human_hold_latched:
                live_doc.update(human_hold_latched=True, torque_hold_commanded=True, **({"hold_req": _r._human_hold_acked_req} if getattr(_r, "_human_hold_acked_req", None) else {}))
            (_io / "live.json").write_text(json.dumps(live_doc), encoding="utf-8")

        def _sleep_m(dt, *, _r=r_m, _mono=mono, _wm=waiting_motion):
            _mono[0] += 1.0 if (_wm[0] and dt <= 0.05) else dt
            if _wm[0]:
                assert _r.idle() is False and crs.check_runner_idle(_r, lambda _k, d: d) is False
                assert _r.idle_parks == 0 and not _r.queue

        with monkeypatch.context() as mp:
            mp.setattr(cpio.time, "monotonic", lambda _m=mono: _m[0])
            mp.setattr(cpio.time, "sleep", _sleep_m)
            mp.setattr(cpio.time, "time", lambda _m=mono: 2000.0 + _m[0])
            mp.setattr(crr.time, "time", lambda _m=mono: 2000.0 + _m[0])
            mp.setattr(cpio.os, "open", _open_m)
            mp.setattr(cpio.os, "close", _close_m)
            if mode == "paced":
                res_m = drive.run_episode(fifo_m, pol_p, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
                assert res_m["result"] == "fault" and res_m["parked"] is False
            else:
                res_m = run_timed(fifo_m, sh_t, base_lib, tmp_path,
                                  infer=lambda *_: (np.asarray(pol_act, dtype=float), {}),
                                  shape=lambda actions, *_a: np.asarray(actions, dtype=float).tolist(),
                                  max_step=5.0 / 30, n_action=8, max_obs_age_s=0.6,
                                  max_chunks=1, dry_run=False, log=[].append,
                                  clock=lambda _m=mono: _m[0], sleep=lambda _dt: None)
                assert res_m["result"] == "refused"
        assert cmds_m[-1].startswith("human-hold ") and r_m.home_since is None and r_m.idle_parks == 0
        assert r_m.human_hold_latched is True and r_m.torque_hold_commanded is True and not r_m.queue
        mono[0] += 100.0
        assert r_m.idle() is False and crs.check_runner_idle(r_m, lambda _k, d: d) is False and not r_m.queue

    # 2: KeyboardInterrupt during the first live `state` read on an off-home non-policy owner still latches HOLD (never leaves idle fold armed).
    off_home = [5.0, -50.0, 45.0, 48.0, -5.0, 49.0]
    for kind in ("paced_drive", "paced_pre_home", "timed"):
        clk_k, rep_k, cmds_k = [10.0], [], []
        r_k = Runner(_FakeRobot(off_home), base_lib, fps=30, status=rep_k.append, clock=lambda _c=clk_k: _c[0], params={"runner.idle_park_s": 5.0})
        r_k.target, r_k.last_input, r_k.idle_parks, r_k.home_since = list(off_home), 10.0, 0, None

        class InterruptFirstStateCell:
            def act(self, cmd):
                cmds_k.append(cmd)
                if cmd == "state":
                    raise KeyboardInterrupt("operator ctrl-c during initial state read")
                r_k.command(cmd)
                if cmd == "human-hold":
                    clk_k[0] += 1 / 30
                    r_k.tick()
                return rep_k[-1]

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        with pytest.raises(KeyboardInterrupt):
            if kind == "paced_drive":
                drive.run_episode(InterruptFirstStateCell(), pol_p, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False, log=[].append, paced_chunks=True)
            elif kind == "paced_pre_home":
                paced.run_paced_chunks(InterruptFirstStateCell(), pol_p, base_lib, tmp_path, off=np.zeros(6), max_chunks=1, dry_run=False,
                                       log=[].append, goal={}, sim_units=True, open_g=80.0, model_closed=46.6, closed=46.6,
                                       low=np.full(6, -100.0), high=np.full(6, 100.0), fastest=5.0, kin=None, jaw_spec=None,
                                       resolved_tcp=0.0, authorize=None, pre_home=True)
            else:
                run_timed(InterruptFirstStateCell(), sh_t, base_lib, tmp_path,
                          infer=lambda *_: (np.asarray(pol_act, dtype=float), {}),
                          shape=lambda actions, *_a: np.asarray(actions, dtype=float).tolist(),
                          max_step=5.0 / 30, n_action=8, max_obs_age_s=0.6,
                          max_chunks=1, dry_run=False, log=[].append, clock=lambda _c=clk_k: _c[0], sleep=lambda _dt: None)
        assert cmds_k == ["state", "human-hold"] and r_k.human_hold_latched is True and r_k.torque_hold_commanded is True and not r_k.queue
        clk_k[0] = 10.0 + 100.0
        assert r_k.idle() is False and crs.check_runner_idle(r_k, lambda _k, d: d) is False and not r_k.queue


def test_r18_post_state_interrupt_holds_and_handoff_lost_motion_reply_holds_without_park(tmp_path, monkeypatch):
    import cell_policy_handoff as cph_mod
    import chunk_runner_settle as crs
    import grasp_planner
    from cell_envelope import digest

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    off_home = [5.0, -50.0, 45.0, 48.0, -5.0, 49.0]
    tgt = [10.0, -40.0, 40.0, 45.0, -5.0, 60.0]
    reach = [[round(home[i] + (tgt[i] - home[i]) * k / 250, 4) for i in range(6)] for k in range(251)]
    base_lib = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 46.6, "chunks": {"home": [home], "reach": reach}}
    (lp := tmp_path / "r18-lib.json").write_text(json.dumps(base_lib), encoding="utf-8")

    # 1: KeyboardInterrupt AFTER a valid first `state` reply (during infer/shape before `load`) still latches HOLD on off-home non-policy owners.
    pol_ki = SimpleNamespace(image_views=(), goal_size=None, sim_rule=None, inputs=lambda st, _fr: ({"s": st}, {}),
                             infer=lambda _o: (_ for _ in ()).throw(KeyboardInterrupt("ctrl-c during inference")))
    pol_act = [[round(off_home[i] + 0.02 * (k + 1) if i == 0 else off_home[i], 4) for i in range(6)] for k in range(8)]
    sh_t = SimpleNamespace(image_views=(), sim_rule=None, chunk_size=8)

    for kind in ("paced_legacy", "paced_drive", "timed"):
        start_pose = home if kind == "paced_drive" else off_home
        clk1, rep1, cmds1 = [10.0], [], []
        r1 = Runner(_FakeRobot(start_pose), base_lib, fps=30, status=rep1.append, clock=lambda _c=clk1: _c[0], params={"runner.idle_park_s": 5.0})
        r1.target, r1.last_input, r1.idle_parks, r1.home_since = list(start_pose), 10.0, 0, None

        class PostStateInterruptCell:
            def act(self, cmd):
                cmds1.append(cmd)
                r1.command(cmd)
                if cmd == "human-hold":
                    clk1[0] += 1 / 30
                    r1.tick()
                res = dict(rep1[-1])
                if cmd == "state":
                    res.setdefault("health_t", clk1[0])
                    res.setdefault("gripper_ma", 0.0)
                return res

            def frame(self, _v):
                return np.zeros((4, 4, 3), np.uint8)

        with monkeypatch.context() as mp:
            mp.setattr(timing.time, "time", lambda _c=clk1: _c[0])
            with pytest.raises(KeyboardInterrupt):
                if kind == "paced_legacy":
                    paced.run_paced_chunks(PostStateInterruptCell(), pol_ki, base_lib, tmp_path, off=np.zeros(6), max_chunks=1, dry_run=False,
                                           log=[].append, goal={}, sim_units=True, open_g=80.0, model_closed=46.6, closed=46.6,
                                           low=np.full(6, -100.0), high=np.full(6, 100.0), fastest=5.0, kin=None, jaw_spec=None,
                                           resolved_tcp=0.0, authorize=None, pre_home=False)
                elif kind == "paced_drive":
                    drive.run_episode(PostStateInterruptCell(), pol_ki, lp, tmp_path, offset=[0] * 6, max_chunks=1, dry_run=False,
                                      log=[].append, paced_chunks=True)
                else:
                    run_timed(PostStateInterruptCell(), sh_t, base_lib, tmp_path,
                              infer=lambda *_: (np.asarray(pol_act, dtype=float), {}),
                              shape=lambda *_a: (_ for _ in ()).throw(KeyboardInterrupt("ctrl-c during shaping")),
                              max_step=5.0 / 30, n_action=8, max_obs_age_s=0.6, max_chunks=1, dry_run=False,
                              log=[].append, clock=lambda _c=clk1: _c[0], sleep=lambda _dt: None)
        assert "state" in cmds1 and cmds1[-1] == "human-hold" and not any("load " in c or "park" in c for c in cmds1)
        assert r1.human_hold_latched is True and r1.torque_hold_commanded is True and not r1.queue
        clk1[0] = 10.0 + 10.0
        assert r1.idle() is False and crs.check_runner_idle(r1, lambda _k, d: d) is False and not r1.queue

    # 2: Lost `goto above_place` status reply during real CellHandoff.carry -> Gate -> transfer_folded triggers HOLD directly with zero recovery `park`.
    class StubPlanner:
        kin = SimpleNamespace(fk=lambda _: SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0))

        def __init__(self, _p):
            pass

        def line(self, *_a):
            return [home], 0

    monkeypatch.setattr(grasp_planner, "Planner", StubPlanner)
    lib_h = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49,
        "chunks": {"home": [home], "park": [home], "goto above_place": [home], "descend_place": [home], "release_place": [home], "lift_place": [home]},
        "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}, "place": {"x": 0.1, "y": 0.2, "z": 0.05}},
    }
    (lib_hp := tmp_path / "r18-handoff.json").write_text(json.dumps(lib_h), encoding="utf-8")
    cfg_h = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}

    class _AuthStub:
        config = cfg_h
        calibration = {}

        def __call__(self, lib, _st, seq, **_kw):
            return {
                "scope": "hardware", "runtime_sha256": "b" * 64, "operating_profile": None,
                "session_id": "s1", "library_sha256": digest(lib), "allowed": True, "mode": "automatic", "sequence": list(seq),
            }

    cmds2, logs2 = [], []

    class HandoffLostMotionCell:
        def act(self, cmd):
            cmds2.append(cmd)
            if cmd == "state":
                return {
                    "command": "state", "ok": True, "settled": True, "holding": True, "fault": None,
                    "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time(),
                    "operating_context": {"scope": "hardware", "session_id": "s1", "sha256": "b" * 64, "operating_profile": None},
                }
            if cmd == "human-hold":
                return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
            if cmd.endswith("goto above_place"):
                return {"ok": False, "error": "no status within 300 s"}
            base_cmd = cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd
            return {
                "command": base_cmd, "ok": True, "settled": True, "holding": True,
                "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time(),
            }

    handoff2 = cph_mod.CellHandoff(cfg_h, "belt", lib_hp, lib_h, 51, tmp_path)
    init_ran = {"command": "run policy", "ok": True, "settled": True, "holding": True,
                "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0],
                "handoff": {"triggered": True, "holding_frames": 8, "jaw": 53}}
    res2 = handoff2.carry(HandoffLostMotionCell(), init_ran, _AuthStub(), logs2.append)
    assert res2["result"] == "refused" and "no status within 300 s" in res2["reason"]
    got_idx = next(i for i, c in enumerate(cmds2) if c.endswith("goto above_place"))
    assert len([c for c in cmds2 if c.endswith("park")]) == 1
    assert cmds2[got_idx + 1:] == ["human-hold"] and logs2[-1]["command"] == "human-hold" and logs2[-1]["ok"] is True


def test_r19_handoff_unsettled_descent_and_unconfirmed_retreat_hold_without_release_or_park(tmp_path, monkeypatch):
    import cell_policy_handoff as cph_mod
    import grasp_planner
    from cell_envelope import digest

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]

    class StubPlanner:
        kin = SimpleNamespace(fk=lambda _: SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0))

        def __init__(self, _p):
            pass

        def line(self, *_a):
            return [home], 0

    monkeypatch.setattr(grasp_planner, "Planner", StubPlanner)
    lib_h = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49,
        "chunks": {"home": [home], "park": [home], "goto above_place": [home], "descend_place": [home], "release_place": [home], "lift_place": [home]},
        "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}, "place": {"x": 0.1, "y": 0.2, "z": 0.05}},
    }
    (lib_hp := tmp_path / "r19-handoff.json").write_text(json.dumps(lib_h), encoding="utf-8")
    cfg_h = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}

    class _AuthStub:
        config = cfg_h
        calibration = {}

        def __call__(self, lib, _st, seq, **_kw):
            return {
                "scope": "hardware", "runtime_sha256": "b" * 64, "operating_profile": None,
                "session_id": "s1", "library_sha256": digest(lib), "allowed": True, "mode": "automatic", "sequence": list(seq),
            }

    init_ran = {"command": "run policy", "ok": True, "settled": True, "holding": True,
                "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0],
                "handoff": {"triggered": True, "holding_frames": 8, "jaw": 53}}

    def _run_case(descend_reply: dict, retreat_reply: dict | None = None):
        cmds, logs = [], []

        class CaseCell:
            def act(self, cmd):
                cmds.append(cmd)
                if cmd == "state":
                    return {
                        "command": "state", "ok": True, "settled": True, "holding": True, "fault": None,
                        "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time(),
                        "operating_context": {"scope": "hardware", "session_id": "s1", "sha256": "b" * 64, "operating_profile": None},
                    }
                if cmd == "human-hold":
                    return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                if cmd.endswith("run descend_place"):
                    return dict(descend_reply)
                if retreat_reply is not None and cmd.endswith("retreat"):
                    return dict(retreat_reply)
                base_cmd = cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd
                return {
                    "command": base_cmd, "ok": True, "settled": True, "holding": True,
                    "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time(),
                }

        handoff = cph_mod.CellHandoff(cfg_h, "belt", lib_hp, lib_h, 51, tmp_path)
        res = handoff.carry(CaseCell(), init_ran, _AuthStub(), logs.append)
        return res, cmds, logs

    # 1: Unsettled or unconfirmed `run descend_place` never advances to `run release_place` and holds directly without recovery `park`.
    for desc_reply in (
        {"command": "run descend_place", "ok": True, "settled": False, "holding": True, "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0]},
        {"command": "run descend_place", "ok": True, "holding": True, "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0]},
    ):
        res1, cmds1, logs1 = _run_case(desc_reply)
        assert res1["result"] == "refused" and not any(c.endswith("run release_place") for c in cmds1)
        desc_idx = next(i for i, c in enumerate(cmds1) if c.endswith("run descend_place"))
        assert len([c for c in cmds1 if c.endswith("park")]) == 1
        assert cmds1[desc_idx + 1:] == ["human-hold"] and logs1[-1]["command"] == "human-hold" and logs1[-1]["ok"] is True

    # 2: Soft contact during `run descend_place` followed by timeout, unsettled, or unlabeled `retreat` holds directly with zero recovery `park`.
    contact_desc = {"command": "run descend_place", "ok": False, "contact": True, "error": "strain"}
    for bad_retreat in (
        {"ok": False, "error": "no status within 300 s"},
        {"command": "retreat", "ok": True, "settled": False},
        {"ok": True, "settled": True},
    ):
        res2, cmds2, logs2 = _run_case(contact_desc, bad_retreat)
        assert res2["result"] == "refused" and len([c for c in cmds2 if c.endswith("park")]) == 1
        ret_idx = next(i for i, c in enumerate(cmds2) if c.endswith("retreat"))
        assert cmds2[ret_idx + 1:] == ["human-hold"] and logs2[-1]["command"] == "human-hold" and logs2[-1]["ok"] is True

    # 3: Positive soft-contact control: matching settled `retreat` + settled recovery `park` completes clean contact recovery without spurious HOLD.
    res3, cmds3, _logs3 = _run_case(contact_desc, {"command": "retreat", "ok": True, "settled": True})
    assert res3["result"] == "contact" and len([c for c in cmds3 if c.endswith("park")]) == 2 and "human-hold" not in cmds3


def test_r20_aerial_timeout_unconfirmed_release_lift_place_contact_taught_hold_and_unlabeled_strict_ack(tmp_path, monkeypatch):
    import cell_policy_handoff as cph_mod
    import chunk_runner_settle as crs
    import grasp_planner
    from cell_envelope import digest

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    above_place = [0.5, -58.0, 50.0, 50.0, -5.0, 49.0]

    class StubPlanner:
        kin = SimpleNamespace(fk=lambda _: SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0))

        def __init__(self, _p):
            pass

        def line(self, *_a):
            return [home], 0

    monkeypatch.setattr(grasp_planner, "Planner", StubPlanner)
    lib_h = {
        "schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49,
        "chunks": {"home": [home], "park": [home], "above_place": [above_place],
                   "above_pick": [above_place], "descend_pick": [home], "grasp_pick": [home], "lift_pick": [home],
                   "descend_place": [home], "release_place": [home], "lift_place": [home]},
        "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}, "place": {"x": 0.1, "y": 0.2, "z": 0.05}},
    }
    (lib_hp := tmp_path / "r20-handoff.json").write_text(json.dumps(lib_h), encoding="utf-8")
    cfg_h = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}

    class _AuthStub:
        config = cfg_h
        calibration = {}

        def __call__(self, lib, _st, seq, **_kw):
            return {
                "scope": "hardware", "runtime_sha256": "b" * 64, "operating_profile": None,
                "session_id": "s1", "library_sha256": digest(lib), "allowed": True, "mode": "automatic", "sequence": list(seq),
            }

    init_ran = {"command": "run policy", "ok": True, "settled": True, "holding": True,
                "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0],
                "handoff": {"triggered": True, "holding_frames": 8, "jaw": 53}}

    # 1: Real Runner aerial `goto above_place` timing out at SETTLE_S with 4-unit encoder error emits settled=False; strict carry holds without `run descend_place` or recovery `park`.
    clk_a, rep_a = [1.0], []

    class AerialLagRobot(_FakeRobot):
        def send_action(self, action):
            super().send_action(action)
            self.pos[0] = action[NAMES[0]] - 4.0

    r_aer = Runner(AerialLagRobot(home), lib_h, fps=30, status=rep_a.append, clock=lambda: clk_a[0], params={"runner.contact_lag": 99.0})
    r_aer.target = list(home)
    assert r_aer.command("goto above_place") is True
    for _ in range(900):
        clk_a[0] += 1 / 30
        r_aer.tick()
        if r_aer.chunk is None:
            break
    aerial_receipt = next(r for r in rep_a if r.get("command") == "run goto above_place")
    assert aerial_receipt["ok"] is True and aerial_receipt["settled"] is False

    def _run_handoff(overrides: dict[str, dict], *, auth=_AuthStub()):
        cmds, logs = [], []

        class CaseCell:
            def act(self, cmd):
                cmds.append(cmd)
                if cmd == "state":
                    return {
                        "command": "state", "ok": True, "settled": True, "holding": True, "fault": None,
                        "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time(),
                        "operating_context": {"scope": "hardware", "session_id": "s1", "sha256": "b" * 64, "operating_profile": None},
                    }
                if cmd == "human-hold":
                    return {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                base_cmd = cmd.split(" ", 3)[-1] if cmd.startswith("checked ") else cmd
                if base_cmd in overrides:
                    return dict(overrides[base_cmd])
                return {"command": base_cmd, "ok": True, "settled": True, "holding": base_cmd != "run release_place",
                        "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0], "t": time.time()}

        res = cph_mod.CellHandoff(cfg_h, "belt", lib_hp, lib_h, 51, tmp_path).carry(CaseCell(), init_ran, auth, logs.append)
        return res, cmds, logs

    res1, cmds1, logs1 = _run_handoff({"goto above_place": aerial_receipt})
    assert res1["result"] == "refused" and not any(c.endswith("run descend_place") for c in cmds1)
    assert len([c for c in cmds1 if c.endswith("park")]) == 1
    assert cmds1[-1] == "human-hold" and logs1[-1]["command"] == "human-hold" and logs1[-1]["ok"] is True

    # 2: Unconfirmed release (`ok=False, holding=True` or spoofed `ok=True, holding=True`) skips recovery `park` and holds directly.
    for rel_reply in (
        {"command": "run release_place", "ok": False, "settled": True, "holding": True, "error": "release not confirmed by jaw feedback"},
        {"command": "run release_place", "ok": True, "settled": True, "holding": True},
    ):
        res2, cmds2, logs2 = _run_handoff({"run release_place": rel_reply})
        rel_idx = next(i for i, c in enumerate(cmds2) if c.endswith("run release_place"))
        assert res2["result"] == "refused" and cmds2[rel_idx + 1:] == ["human-hold"]
        assert logs2[-1]["command"] == "human-hold" and logs2[-1]["ok"] is True

    # 3: Soft contact during `run lift_place` holds directly with zero `park` and never reports `placed`.
    res3, cmds3, logs3 = _run_handoff({"run lift_place": {"command": "run lift_place", "ok": False, "contact": True, "error": "contact in lift_place"}})
    lift_idx = next(i for i, c in enumerate(cmds3) if c.endswith("run lift_place"))
    assert res3["result"] == "refused" and cmds3[lift_idx + 1:] == ["human-hold"]
    assert logs3[-1]["command"] == "human-hold" and logs3[-1]["ok"] is True

    # 4: Unlabeled strict acks (`run descend_place` and soft-contact recovery `park`) fail closed to `human-hold`.
    res4a, cmds4a, _ = _run_handoff({"run descend_place": {"ok": True, "settled": True, "holding": True}})
    assert res4a["result"] == "refused" and not any(c.endswith("run release_place") for c in cmds4a) and cmds4a[-1] == "human-hold"
    res4b, cmds4b, _ = _run_handoff({
        "run descend_place": {"command": "run descend_place", "ok": False, "contact": True, "error": "strain"},
        "retreat": {"command": "retreat", "ok": True, "settled": True},
        "park": {"ok": True, "settled": True},
    }, auth=None)
    assert res4b["result"] == "refused" and cmds4b[-1] == "human-hold"

    # 5: `run_taught` on an off-home taught-only Runner latches confirmed HOLD on strict fault and keeps idle watchdog blocked past idle_park_s.
    off_home = [5.0, -50.0, 45.0, 48.0, -5.0, 49.0]
    clk_t, rep_t, cmds_t, logs_t = [10.0], [], [], []
    r_taught = Runner(_FakeRobot(off_home), lib_h, fps=30, status=rep_t.append, clock=lambda: clk_t[0], params={"runner.idle_park_s": 5.0})
    r_taught.target, r_taught.last_input, r_taught.idle_parks, r_taught.home_since = list(off_home), 10.0, 0, None

    class TaughtCell:
        def act(self, cmd):
            cmds_t.append(cmd)
            if cmd == "human-hold":
                r_taught.command("human-hold")
                clk_t[0] += 1 / 30
                r_taught.tick()
                return dict(rep_t[-1])
            if cmd == "run descend_place":
                return {"command": cmd, "ok": True, "settled": False, "holding": True, "state": [0.0] * 5 + [53.0]}
            return {"command": cmd, "ok": True, "settled": True, "holding": True, "state": [0.0] * 5 + [53.0]}

    res5 = cph_mod.run_taught(TaughtCell(), lib_hp, dry_run=False, authorize=None, log=logs_t.append)
    assert res5["result"] == "refused" and res5["mode"] == "taught" and res5["parked"] is False
    assert cmds_t[-1] == "human-hold" and logs_t[-1]["command"] == "human-hold" and logs_t[-1]["ok"] is True
    assert r_taught.human_hold_latched is True and r_taught.torque_hold_commanded is True and not r_taught.queue
    clk_t[0] = 70.0
    assert r_taught.idle() is False and crs.check_runner_idle(r_taught, lambda _k, d: d) is False and not r_taught.queue

    ki_cmds, ki_logs = [], []
    with pytest.raises(KeyboardInterrupt):
        cph_mod.run_taught(
            SimpleNamespace(act=lambda cmd: ki_cmds.append(cmd) or (
                {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}
                if cmd == "human-hold" else (_ for _ in ()).throw(KeyboardInterrupt()))),
            lib_hp, dry_run=False, authorize=None, log=ki_logs.append)
    assert ki_cmds[-1] == "human-hold" and ki_logs[-1]["command"] == "human-hold" and ki_logs[-1]["ok"] is True


def test_r21_release_contact_empty_lift_recovery_park_and_strict_policy_labels(tmp_path, monkeypatch):
    import cell_policy_handoff as cph_mod
    import grasp_planner

    monkeypatch.setattr(timing.time, "sleep", lambda _s: None)
    monkeypatch.setattr(paced.time, "sleep", lambda _s: None)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 49.0]
    monkeypatch.setattr(grasp_planner, "Planner", type("P", (), {
        "kin": SimpleNamespace(fk=lambda _j: SimpleNamespace(x=0.2, y=0.1, z=0.12, yaw=0, tool_down_error_rad=0)),
        "__init__": lambda _s, _p: None, "line": lambda _s, *_a: ([home], 0)}))
    lib_h = {"schema": SCHEMA, "names": NAMES, "fps": 30, "gripper_closed": 49, "chunks": {"home": [home], "reach": [home, home]},
             "source": {"pick": {"x": 0.2, "y": 0.1, "z": 0.08, "yaw_deg": 0}}}
    (lib_hp := tmp_path / "r21.json").write_text(json.dumps(lib_h), encoding="utf-8")
    cfg_h = {"plan": {}, "sites": {"belt": {"surface_z": 0.05, "rim_z": 0.09}}}
    init_ran = {"command": "run policy", "ok": True, "settled": True, "holding": True, "state": [0.0] * 5 + [53.0],
                "target": [0.0] * 5 + [50.0], "handoff": {"triggered": True, "holding_frames": 8, "jaw": 53}}
    hold_ack = {"command": "human-hold", "ok": True, "human_hold_latched": True, "torque_hold_commanded": True}

    def _run_handoff(overrides: dict[str, dict | list[dict]]):
        cmds, ov = [], {k: (list(v) if isinstance(v, list) else [v]) for k, v in overrides.items()}
        class Cell:
            def act(self, cmd):
                cmds.append(cmd)
                return (dict(ov[cmd].pop(0)) if cmd in ov and ov[cmd] else dict(hold_ack) if cmd == "human-hold"
                        else {"command": cmd, "ok": True, "settled": True, "holding": cmd != "run release_place",
                              "state": [0.0] * 5 + [53.0], "target": [0.0] * 5 + [50.0]})
        return cph_mod.CellHandoff(cfg_h, "belt", lib_hp, lib_h, 51, tmp_path).carry(Cell(), init_ran, None, lambda _: None), cmds

    r1, c1 = _run_handoff({"run release_place": {"command": "run release_place", "ok": False, "contact": True, "holding": True, "error": "contact"}})
    assert r1["result"] == "refused" and c1[c1.index("run release_place") + 1:] == ["human-hold"]
    t_cmds = []
    rt = cph_mod.run_taught(SimpleNamespace(act=lambda cmd: t_cmds.append(cmd) or (
        {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home)} if cmd == "run grasp_pick"
        else {"ok": False, "error": "no status within 300 s"} if cmd == "run lift_pick" else dict(hold_ack) if cmd == "human-hold"
        else {"command": cmd, "ok": True, "settled": True, "holding": True, "state": list(home)})),
        lib_hp, dry_run=False, authorize=None, log=lambda _: None)
    assert rt["result"] == "refused" and t_cmds[t_cmds.index("run lift_pick") + 1:] == ["human-hold"]
    r3a, c3a = _run_handoff({"goto above_place": {"command": "goto above_place", "ok": False, "error": "must park before recovery"},
                             "park": [{"command": "park", "ok": True, "settled": True, "holding": True, "state": list(home)},
                                      {"ok": False, "error": "no status within 300 s"}]})
    r3b, c3b = _run_handoff({"park": [{"command": "park", "ok": False, "contact": True, "error": "strain"},
                                      {"command": "park", "ok": False, "contact": True, "error": "strain2"}],
                             "retreat": {"command": "retreat", "ok": True, "settled": True}})
    assert r3a["result"] == "refused" and c3a.count("park") == 2 and c3a[-1] == "human-hold"
    assert r3b["result"] == "refused" and c3b.count("retreat") == 1 and c3b.count("park") == 2 and c3b[-1] == "human-hold"
    r4a, c4a = _run_handoff({"run lift_pick_policy_handoff": {"ok": True, "settled": True, "holding": True, "state": [0.0] * 5 + [53.0]}})
    assert r4a["result"] == "refused" and "park" not in c4a and c4a[-1] == "human-hold"
    bad_park_cell = SimpleNamespace(act=lambda cmd: {"ok": True, "settled": True, "state": list(home)} if cmd == "park" else (
        dict(hold_ack) if cmd == "human-hold" else {"command": cmd, "ok": True, "settled": True, "holding": False, "state": list(home)}))
    rt_bad = run_timed(bad_park_cell, SimpleNamespace(image_views=(), sim_rule={}, chunk_size=16), lib_h, tmp_path,
                       infer=lambda *_: (np.zeros((16, 6)), {}), shape=lambda a, *_: a.tolist(), max_step=0.1,
                       n_action=8, max_obs_age_s=0.6, max_chunks=1, dry_run=False, log=lambda _: None, clock=lambda: 1.0)
    pol = SimpleNamespace(image_views=(), goal_size=None, sim_rule=None, inputs=lambda st, _fr: ({"s": st}, {}),
                          infer=lambda _o: SimpleNamespace(chunk=[[round(v + 0.01, 4) for v in home]] * 8))
    kw = dict(off=np.zeros(6), max_chunks=1, dry_run=False, log=lambda _: None, goal={}, sim_units=True, open_g=80.0,
              model_closed=46.6, closed=46.6, low=np.full(6, -100.0), high=np.full(6, 100.0), fastest=5.0, kin=None, jaw_spec=None, resolved_tcp=0.0, authorize=None)
    rp_bad = paced.run_paced_chunks(bad_park_cell, pol, lib_h, tmp_path, **kw)
    rp_ok = paced.run_paced_chunks(SimpleNamespace(act=lambda cmd: {"command": "run park" if cmd == "park" else cmd, "ok": True, "settled": True, "holding": False, "state": list(home)}), pol, lib_h, tmp_path, **kw)
    assert rt_bad["parked"] is False and rp_bad["parked"] is False and rp_ok["parked"] is True and rp_ok["park"]["command"] == "run park"
