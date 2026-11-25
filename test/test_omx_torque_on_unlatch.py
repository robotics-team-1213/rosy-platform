"""Tests for Torque-ON guarded recover-unlatch, multi-VLM/LLM recovery panels, and recover_hold job admission."""
from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_fold as af  # noqa: E402
import cell_corridor as cc  # noqa: E402
import cell_job_api as api  # noqa: E402
import cell_job_guards as guards  # noqa: E402
import cell_objects  # noqa: E402
import cell_pipeline as cp  # noqa: E402
import cell_place_fit  # noqa: E402
import cell_recovery_advisor as cra  # noqa: E402
import cell_space  # noqa: E402
import chunk_runner as m  # noqa: E402
from chunk_runner_recover import ensure_live_unlatch  # noqa: E402
import judge_seat  # noqa: E402

HOME = [0.0, -60.0, 50.0, 45.0, 10.0, 46.6]
REACH = [20.0, -20.0, 20.0, 45.0, -5.0, 54.0]
MOTORS = [n.split(".")[0] for n in m.NAMES]


@pytest.mark.parametrize("fields", [{}, {"human_hold_latched": None}, {"human_hold_latched": 0},
                                    {"human_hold_latched": True}, {"human_hold_latched": False}])
def test_unlatch_requires_explicit_release(fields):
    cell = Mock()
    cell.act.return_value = {"ok": True, **fields}
    latched = {"active": True}
    ok, error = ensure_live_unlatch(cell, latched, Mock())
    released = fields.get("human_hold_latched") is False
    assert ok is released
    assert latched["active"] is (not released)
    assert bool(error) is (not released)


@pytest.mark.parametrize("case", ["released", "still_held", "new_session", "old_state", "fault", "state_error",
                                  "ack_error", "ack_fault", "read_failure"])
def test_unlatch_reads_current_session_after_incomplete_ack(case):
    context = {"session_id": "session", "scope": "hardware", "sha256": "a" * 64}
    initial = {"operating_context": context, "library_sha256": "b" * 64}

    def act(command):
        if command == "recover-unlatch":
            if case in ("ack_error", "ack_fault"):
                return {"ok": True, "human_hold_latched": False, case[4:]: "bus fault"}
            return {"ok": True}
        assert command == "state"
        if case == "read_failure":
            raise OSError("bus offline")
        return {**initial, "ok": True, "t": time.time() - (60 if case == "old_state" else 0),
                "error": "bus fault" if case == "state_error" else None,
                "human_hold_latched": case == "still_held", "fault": "held" if case == "fault" else None,
                "operating_context": {**context, "session_id": "other"} if case == "new_session" else context}

    latched = {"active": True, "initial_status": initial}
    ok, _ = ensure_live_unlatch(SimpleNamespace(act=act), latched, Mock())
    assert ok is (case == "released")
    assert latched["active"] is (not ok)


class _FakeBus:
    def __init__(self, *, hw_err: int = 0, torque: int = 1, sync: bool = True):
        self.model_ctrl_table, self.hw_err, self.torque, self._sync = sync, hw_err, torque, sync

    def _val(self, reg):
        return {"Hardware_Error_Status": self.hw_err, "Torque_Enable": self.torque,
                "Present_PWM": 10, "Present_Current": 20, "Present_Temperature": 35}.get(reg)

    def sync_read(self, reg, _motors=None, normalize=False, num_retry=0):
        del normalize, num_retry
        if not self._sync:
            raise AssertionError("unexpected sync_read")
        val = self._val(reg)
        return {name: val for name in MOTORS} if val is not None else {}

    def read(self, reg, _motor=None):
        return self._val(reg)


class _FakeMotion:
    def __init__(self):
        self.failed, self.held, self.tracking, self.command = False, {}, True, dict(zip(MOTORS, HOME))
        self.stop_calls, self.hw_error = 0, None

    def stop_streaming(self):
        self.stop_calls += 1

    def _check_hardware_errors(self):
        if self.hw_error is not None:
            raise self.hw_error


class _RunnerRobot:
    def __init__(self, pos=None, *, with_motion: bool = True):
        self.pos, self.bus = list(pos or REACH), _FakeBus()
        self.motion = _FakeMotion() if with_motion else None
        self.sent, self.checked_calls = [], []

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))

    def send_action(self, action):
        self.sent.append(dict(action))
        for i, name in enumerate(m.NAMES):
            self.pos[i] = float(action[name])
        return dict(action)

    def send_action_checked(self, action, _check=None, *, hold_on_read_error=False, allow_stale_hold=False):
        self.checked_calls.append((dict(action), hold_on_read_error, allow_stale_hold))
        return self.send_action(action)


def _runner_lib(closed: float = 46.6):
    return {"schema": m.SCHEMA, "names": list(m.NAMES), "gripper_closed": closed, "chunks": {"home": [HOME], "jog": [HOME]}}


def test_recover_unlatch_preconditions_checked_context_and_zero_jump_sync():
    robot, status, now = _RunnerRobot(REACH), [], [10.0]
    r = m.Runner(robot, _runner_lib(), fps=30, status=status.append, clock=lambda: now[0])
    r.target = [20.0, -18.0, 20.0, 45.0, -5.0, 48.0]  # lagged body + partially open jaw
    r.command("human-hold")
    r.tick()
    assert r.human_hold_latched is True and r.fault == "human hold"
    stop0, chk0 = robot.motion.stop_calls, len(robot.checked_calls)
    robot.pos[1] = -21.5
    assert r.command("recover-unlatch") is True
    ack = status[-1]
    assert ack["ok"] is True and ack["command"] == "recover-unlatch"
    assert ack["unlatched_from_hold"] is True and ack["previous_fault"] == "human hold"
    assert r.human_hold_latched is False and r.torque_hold_commanded is False and r.fault is None
    assert r.target[:5] == pytest.approx(robot.pos[:5]) and r.target[5] == pytest.approx(robot.pos[5])
    assert robot.motion.stop_calls > stop0 and len(robot.checked_calls) == chk0
    r.command("jog shoulder_lift.pos -2.0")
    assert status[-1]["ok"] is True
    r.fault = "pushing at rest: elbow_flex still 1.2 units short"
    r.command("human-hold")
    r.tick()
    assert r.human_hold_latched is True and r.fault.startswith("pushing at rest")
    assert r.command("recover-unlatch") is True
    assert status[-1]["ok"] is True and r.human_hold_latched is False and r.fault is None
    assert r.target[:5] == pytest.approx(robot.pos[:5])

    r.fault = "contact in jog"
    r.command("human-hold")
    r.tick()
    assert r.human_hold_latched is True and r.fault == "contact in jog"

    # Clamped box preserves target[5] and recomputes holding=True; checked preserves session_id
    robot_h, st_h = _RunnerRobot([*REACH[:5], 56.0]), []
    rh = m.Runner(robot_h, _runner_lib(), fps=30, status=st_h.append,
                  operating_context={"scope": "simulation", "sha256": "a" * 64, "session_id": "sid-1"})
    rh.target, rh.holding, rh.human_hold_latched, rh.torque_hold_commanded, rh.fault = [*REACH[:5], 46.6], False, True, True, "contact in lift"
    dig = rh._library_digest()
    rh.command(f"checked bad-sid {dig} recover-unlatch")
    assert st_h[-1]["ok"] is False and rh.human_hold_latched is True
    rh.command("checked sid-1 bad-dig recover-unlatch")
    assert st_h[-1]["ok"] is False and rh.human_hold_latched is True
    rh.command(f"checked sid-1 {dig} recover-unlatch")
    assert st_h[-1]["ok"] is True and rh.human_hold_latched is False
    assert rh.target[5] == pytest.approx(46.6) and rh.holding is True and rh.operating_context["session_id"] == "sid-1"
    rh.command("human-hold")
    rh.tick()
    rh.command("recover-unlatch")
    assert st_h[-1]["ok"] is True and rh.operating_context["session_id"] != "sid-1"

    # Fail-closed refusal matrix + bus.read fallback pass
    def _set(obj, attr, val):
        setattr(obj, attr, val)

    refusal_muts = {
        "interrupt": lambda rb, rc: _set(rc, "_interrupt", {"phase": "hold"}),
        "signal": lambda rb, rc: _set(rc, "signals", [signal.SIGINT]),
        "fifo_hold": lambda rb, rc: _set(rc, "_fifo_hold_seen", True),
        "chunk": lambda rb, rc: _set(rc, "chunk", "park"),
        "queue": lambda rb, rc: _set(rc, "queue", [HOME]),
        "stop_after_park": lambda rb, rc: _set(rc, "_stop_after_park", "stop fold"),
        "release_until": lambda rb, rc: _set(rc, "_release_until", 999.0),
        "no_home": lambda rb, rc: _set(rc, "library", {"schema": m.SCHEMA, "names": list(m.NAMES), "gripper_closed": 46.6, "chunks": {}}),
        "pose_err": lambda rb, rc: _set(rb, "get_observation", lambda: (_ for _ in ()).throw(OSError("enc"))),
        "motion_failed": lambda rb, rc: _set(rb.motion, "failed", True),
        "not_tracking": lambda rb, rc: _set(rb.motion, "tracking", False),
        "motion_held": lambda rb, rc: _set(rb.motion, "held", {"shoulder_lift": {}}),
        "hw_err_motion": lambda rb, rc: _set(rb.motion, "hw_error", ValueError("wrist_flex: hardware error")),
        "hw_err_bus": lambda rb, rc: _set(rb.bus, "hw_err", 8),
        "hw_err_read": lambda rb, rc: _set(rb.bus, "hw_err", 8),
        "torque_off": lambda rb, rc: _set(rb.bus, "torque", 0),
        "temp_high": lambda rb, rc: _set(rc, "read_health", lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [30, 66, 30, 30, 30, 30]}),
        "temp_extra": lambda rb, rc: _set(rc, "read_health", lambda: {"pwm": [0] * 6, "current_ma": [0] * 6, "temp_c": [30] * 6 + [99]}),
        "temp_fault": lambda rb, rc: _set(rc, "fault", "temperature 67 C"),
        "health_err": lambda rb, rc: _set(rc, "read_health", lambda: (_ for _ in ()).throw(OSError("temp unreadable"))),
        "health_none": lambda rb, rc: _set(rc, "read_health", lambda: None),
    }
    cases = ("unlatched", "unacked", "extra_arg", "status_oserr", *refusal_muts)
    for case in cases:
        rb, logs, fail_status = _RunnerRobot(REACH, with_motion=(case not in ("hw_err_bus", "hw_err_read"))), [], [case == "status_oserr"]
        if case == "hw_err_read":
            delattr(rb.bus, "model_ctrl_table")
        rc = m.Runner(rb, _runner_lib(), fps=30, status=lambda row, _l=logs, _f=fail_status: (_f.__setitem__(0, False), (_ for _ in ()).throw(OSError("disk"))) if _f[0] else _l.append(row))
        rc.target, rc.human_hold_latched, rc.torque_hold_commanded, rc.fault = list(REACH), (case != "unlatched"), (case != "unacked"), "human hold"
        if case in refusal_muts:
            refusal_muts[case](rb, rc)
        rc.command("recover-unlatch now" if case == "extra_arg" else "recover-unlatch")
        assert rc.human_hold_latched is (case != "unlatched"), case
        if case != "status_oserr":
            assert logs[-1]["ok"] is False, case
    rb_ok, st_ok = _RunnerRobot(REACH, with_motion=False), []
    delattr(rb_ok.bus, "model_ctrl_table")
    r_ok = m.Runner(rb_ok, _runner_lib(), fps=30, status=st_ok.append)
    r_ok.target, r_ok.human_hold_latched, r_ok.torque_hold_commanded = list(REACH), True, True
    r_ok.command("recover-unlatch")
    assert st_ok[-1]["ok"] is True and r_ok.human_hold_latched is False


class _HoldCell:
    def __init__(self, state, *, target=None, park_ok=True, unlatch_ok=True, home=HOME, stop_on_crash=False):
        self.state, self.target, self.latched = list(state), list(target or state), True
        self.park_ok, self.unlatch_ok, self.home, self.stop_on_crash = park_ok, unlatch_ok, list(home), stop_on_crash
        self.cmds = []

    def frame(self, _role):
        return np.zeros((16, 16, 3), np.uint8)

    def act(self, cmd: str):
        self.cmds.append(cmd)
        verb = cmd.split()[0]
        if self.latched and verb not in ("state", "human-hold", "recover-unlatch"):
            return {"ok": False, "error": "human hold latched", "human_hold_latched": True,
                    "state": list(self.state), "target": list(self.target)}
        if cmd == "state":
            return {"ok": True, "state": list(self.state), "target": list(self.target), "holding": False,
                    "human_hold_latched": self.latched, "torque_hold_commanded": self.latched}
        if cmd == "recover-unlatch":
            if not self.unlatch_ok:
                return {"ok": False, "error": "hardware fault", "human_hold_latched": True}
            self.latched = False
            return {"ok": True, "human_hold_latched": False, "unlatched_from_hold": True,
                    "previous_fault": "human hold", "state": list(self.state), "target": list(self.target)}
        if cmd == "human-hold":
            self.latched = True
            return {"ok": True, "human_hold_latched": True, "state": list(self.state)}
        if cmd.startswith("jog "):
            _, j, d = cmd.split()
            idx = m.NAMES.index(j)
            self.state[idx] += float(d)
            self.target[idx] += float(d)
        elif cmd in ("park", "park-slow"):
            if not self.park_ok:
                return {"ok": False, "settled": False, "contact": True, "error": f"contact in {cmd}", "state": list(self.state)}
            self.state, self.target = list(self.home), list(self.home)
            return {"ok": True, "settled": True, "state": list(self.state), "target": list(self.target)}
        return {"ok": True, "state": list(self.state), "target": list(self.target)}


def test_auto_fold_live_hold_attach_plans_before_unlatch_and_keeps_torque_on():
    kw = dict(plan=lambda s: [s, HOME], reserve=lambda _: {"ok": True}, release=lambda: None,
              release_and_rise=lambda _: {"result": "risen"}, release_unmoved=True)
    c0 = _HoldCell(REACH)
    r0 = af.recover(c0, HOME, 46.6, look=lambda _: {"clear": True}, low=lambda _: True, **kw)
    assert r0["result"] == "held" and r0["reason"] == "LIVE_HOLD_LATCHED" and "recover-unlatch" not in c0.cmds

    for look_c, low_v, st, tgt, why in ((False, True, REACH, REACH, "ALL_PATHS_BLOCKED"), (True, False, [*REACH[:5], 56.0], [*REACH[:5], 46.6], "HOLDING_HIGH")):
        cb = _HoldCell(st, target=tgt)
        rb = af.recover(cb, HOME, 46.6, look=lambda _: {"clear": look_c}, low=lambda _: low_v, allow_live_unlatch=True, **kw)
        assert rb["result"] == "held" and rb["reason"] == why and "recover-unlatch" not in cb.cmds and "stop now" not in cb.cmds

    events, c1 = [], _HoldCell(REACH)
    res1 = af.recover(
        c1, HOME, 46.6, plan=lambda s: [s, HOME],
        look=lambda _: events.append(("look", list(c1.cmds))) or {"clear": True, "low": [], "high": []},
        reserve=lambda _: events.append(("reserve", list(c1.cmds))) or {"ok": True},
        release=lambda: events.append("release"), release_and_rise=lambda _: {"result": "risen"},
        low=lambda _: False, release_unmoved=True, allow_live_unlatch=True,
    )
    assert res1["result"] == "folded" and res1["unlatched_live_hold"] is True
    assert events[0][0] == "look" and events[1][0] == "reserve" and "recover-unlatch" not in events[1][1]
    assert c1.cmds.index("recover-unlatch") < c1.cmds.index("park-slow") and "release" in events

    rel, c2 = [], _HoldCell(REACH, unlatch_ok=False)
    r2 = af.recover(c2, HOME, 46.6, plan=lambda s: [s, HOME], look=lambda _: {"clear": True}, reserve=lambda _: {"ok": True},
                    release=lambda: rel.append(1), release_and_rise=lambda _: {"result": "risen"}, low=lambda _: False,
                    release_unmoved=True, allow_live_unlatch=True)
    assert r2["reason"] == "UNLATCH_REFUSED" and rel == [1] and "park-slow" not in c2.cmds and "stop now" not in c2.cmds

    # Post-unlatch PARK_NOT_HOME within REST_TOL holds torque ON (never sends stop now)
    c_rest = _HoldCell([HOME[0] + 4.0, *HOME[1:]], park_ok=False)
    r_rest = af.recover(c_rest, HOME, 46.6, look=lambda _: {"clear": True}, low=lambda _: False, allow_live_unlatch=True, **kw)
    assert r_rest["reason"] == "PARK_NOT_HOME" and c_rest.cmds[-1] == "human-hold" and "stop now" not in c_rest.cmds

    c3 = _HoldCell([*REACH[:5], 56.0], target=[*REACH[:5], 46.6], park_ok=False)
    r3 = af.recover(c3, HOME, 46.6, **{**kw, "release_and_rise": lambda c: c.act("jog shoulder_lift.pos -4.0") and {"result": "risen"}},
                    look=lambda _: {"clear": True}, low=lambda _: True, allow_live_unlatch=True)
    assert r3["reason"] == "PARK_NOT_HOME" and c3.cmds[-1] == "human-hold"
    assert c3.cmds.index("recover-unlatch") < c3.cmds.index("jog shoulder_lift.pos -4.0") < c3.cmds.index("park-slow")

    ch_empty = _HoldCell(HOME)
    assert af.recover(ch_empty, HOME, 46.6, look=lambda _: {"clear": True}, low=lambda _: True, allow_live_unlatch=True, **kw)["candidate"] == "already_home"
    assert "recover-unlatch" in ch_empty.cmds
    ch_box = _HoldCell([*HOME[:5], 56.0], target=[*HOME[:5], 46.6])
    assert af.recover(ch_box, HOME, 46.6, look=lambda _: {"clear": True}, low=lambda _: True, allow_live_unlatch=True, **kw)["reason"] == "HOLDING_AT_HOME"


def test_multi_vlm_panel_cooperation_timeout_and_live_hold_e2e(tmp_path, monkeypatch):
    seen = []
    prop_ok = {"strategy": "lift_pan_then_park", "lift_mm": 75.0, "elbow_retract_deg": 0.0,
               "pan_detour_deg": 32.0, "open_jaws": False, "confidence": 0.92, "reason": "lift clear then pan"}
    prop_esc = {"strategy": "escalate_human", "lift_mm": 0.0, "elbow_retract_deg": 0.0,
                "pan_detour_deg": 0.0, "open_jaws": False, "confidence": 0.85, "reason": "ambiguous scene"}
    m_vlm = lambda p, _i, _s: seen.append(p) or dict(prop_ok)  # noqa: E731
    m_agree = lambda p, _i, _s: seen.append(p) or dict(prop_ok)  # noqa: E731
    m_esc = lambda _p, _i, _s: dict(prop_esc)  # noqa: E731

    r_ok = judge_seat.cooperate([m_vlm, m_agree])("prompt", ["img"], cra.PROPOSAL_SCHEMA)
    assert r_ok["strategy"] == "lift_pan_then_park" and r_ok["consensus"] is True and "Deliberation v2" in seen[1]
    assert judge_seat.cooperate([m_vlm, m_esc])("p", ["i"], cra.PROPOSAL_SCHEMA)["strategy"] == "escalate_human"
    assert judge_seat.cooperate([m_vlm, m_esc], arbiter=m_vlm)("p", ["i"], cra.PROPOSAL_SCHEMA)["strategy"] == "lift_pan_then_park"
    with pytest.raises(RuntimeError):
        judge_seat.cooperate([lambda _p, _i, _s: {**prop_ok, "role": "spoof"}, lambda _p, _i, _s: {**prop_ok, "deliberation": []}],
                             )("p", ["i"], cra.PROPOSAL_SCHEMA)

    clamped = cra._clamp_timeout({"models": ["ollama:qwen3-vl:8b-instruct", {"provider": "zai", "timeout_s": 5}], "arbiter": "opencode:zai-coding-plan/glm-5.3"}, 45.0)
    assert clamped["models"][0]["timeout"] == 30.0 and clamped["arbiter"]["timeout_s"] == 30.0
    assert clamped["models"][1]["timeout"] == 5.0 and cra._clamp_timeout("qwen3-vl:8b-instruct", 90.0)["timeout"] == 30.0

    for bad_spec in (["opencode:zai-coding-plan/glm-5.3", {"provider": "zai", "model": "glm-5.3"}],
                     "opencode:zai-coding-plan/glm-5.3", {"models": "bad"}, [judge_seat.rules, "qwen3-vl:8b-instruct"]):
        with pytest.raises(ValueError):
            cra.select_recovery_backend(bad_spec)
    assert callable(cra.select_recovery_backend({"models": [{"provider": "ollama", "model": "qwen3-vl:8b-instruct"}, {"provider": "zai", "model": "glm-5.3"}]}))

    state_reach = [22.2, 8.8, 5.5, 23.9, -24.6, 54.2]
    home_b = [0.8, -62.2, 53.0, 51.9, 44.6, 48.8]
    cell = _HoldCell(state_reach, home=home_b)
    panel_adv = cra.make_advisor([m_vlm, m_agree], cell, home=home_b, plan=lambda s: [s, home_b], tcp_x_m=0.0740)
    out = af.recover(cell, home_b, 48.8, plan=lambda s: [s, home_b],
                     look=lambda frames: {"clear": abs(frames[-2][0] - state_reach[0]) > 16.0 or len(frames) > 8, "low": [], "high": []},
                     reserve=lambda _: {"ok": True}, release=lambda: None, release_and_rise=lambda _: {"result": "risen"},
                     low=lambda _: True, advisor=panel_adv, release_unmoved=True, allow_live_unlatch=True, sleep=lambda _: None)
    assert out["result"] == "folded" and out["candidate"] == "advisor:lift_pan_then_park"
    adv_step = next(s for s in out["steps"] if s.get("step") == "advisor")
    assert adv_step["consensus"] is True and len(adv_step["deliberation"]) == 2
    for junk in ({**prop_ok, "extra_junk": 1}, {**prop_ok, "deliberation": [], "role": "x"}):
        bad_adv = cra.make_advisor([lambda _p, _i, _s, _j=junk: _j], cell, home=home_b, plan=lambda s: [s, home_b], tcp_x_m=0.0740)
        assert bad_adv({"state": state_reach, "target": state_reach, "low": True})["audit"]["veto"] == "SCHEMA_KEYS_MISMATCH"

    cfg, cal, lib, vlm_cfg, out_p = (tmp_path / n for n in ("c.json", "cal.json", "lib.json", "vlm.json", "out.json"))
    cal.write_text("{}")
    cfg.write_text(json.dumps({"io": str(tmp_path / "io"), "cameras": {"top": 0}, "calibration_path": str(cal),
                               "work_dir": str(tmp_path), "space_dir": str(tmp_path / "space"),
                               "sites": {"belt": {"surface_px": [[0, 0], [10, 0], [10, 10], [0, 10]]}}}))
    lib.write_text(json.dumps({"fps": 30, "gripper_closed": 48.8, "chunks": {"home": [home_b]}}))
    vlm_cfg.write_text(json.dumps({"models": [{"provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen3-vl:8b-instruct"},
                                              {"provider": "zai", "model": "glm-5.3"}]}))
    cli_cell = _HoldCell(state_reach, home=home_b)
    monkeypatch.setattr(cell_place_fit, "with_tiers", lambda data: [data])
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **k: SimpleNamespace(act=cli_cell.act, frame=cli_cell.frame))
    monkeypatch.setattr(cell_objects, "foreground", lambda *a, **k: "mask")
    monkeypatch.setattr(cc, "check", lambda *a, **k: {"clear": True, "low": [], "high": [], "off_map": 0, "off_surface": 0})
    monkeypatch.setattr(cc, "runs", lambda pts: (pts, []))
    monkeypatch.setattr(cc, "corridor", lambda *a, **k: "lane")
    monkeypatch.setattr(cell_space, "Space", lambda *a: SimpleNamespace(reserve=lambda *a, **k: {"ok": True}, release=lambda *a: None))
    monkeypatch.setattr(cra, "select_recovery_backend", lambda _spec: lambda _p, _i, _s: dict(prop_ok))
    rc = af.main(["--supervised", "--unlatch-hold", "--arm", "arm_b", "--config", str(cfg), "--library", str(lib),
                  "--site", "belt", "--roi", "0", "0", "10", "10", "--out", str(out_p), "--vlm-config", str(vlm_cfg)])
    assert rc == 0 and json.loads(out_p.read_text())["result"] == "folded" and cli_cell.cmds[-1] == "stop"

    err_cell = _HoldCell(state_reach, home=home_b)
    err_cell.latched = False
    monkeypatch.setattr(cp, "FifoCell", lambda *a, **k: SimpleNamespace(act=err_cell.act, frame=err_cell.frame))
    monkeypatch.setattr(cc, "check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("corridor crash")))
    rc_err = af.main(["--supervised", "--unlatch-hold", "--arm", "arm_b", "--config", str(cfg), "--library", str(lib),
                      "--site", "belt", "--roi", "0", "0", "10", "10", "--out", str(out_p)])
    assert rc_err == 3 and "stop now" not in err_cell.cmds and err_cell.cmds[-1] == "human-hold"


def test_cell_job_api_recover_hold_admission_and_safety_guards(tmp_path, monkeypatch):
    for name in ("cell-a.json", "cell-b.json", "chunks-b.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    (tmp_path / "tools-env-current.sh").write_text("export OMX=~/rosy-test/omx-tools-abc/deploy/robot/omx\n", encoding="utf-8")
    (tmp_path / "chunk-io-b").mkdir()
    (tmp_path / "chunk-io-a").mkdir()

    base = {"arm": "arm_b", "config": "cell-b.json", "library": "chunks-b.json", "site": "belt",
            "roi": [0, 0, 10, 10], "vlm_config": "panel.json", "vlm_timeout": 25.0}
    argv = api.build_argv(api.JOBS["recover_hold"], base, tmp_path)
    assert argv[:2] == ["bash", "-c"] and "./with-session-arm-b-par.sh" not in argv and "--person-at-switch" not in argv
    assert "cell_auto_fold.py" in argv and "--unlatch-hold" in argv and "cell-job-api/recover-hold-arm_b.json" in argv
    assert "--vlm-config" in argv and "--vlm-timeout" in argv
    with pytest.raises(ValueError, match="unknown params"):
        api.build_argv(api.JOBS["recover_hold"], {**base, "out": "/tmp/evil.json"}, tmp_path)
    with pytest.raises(ValueError, match="AMR bed"):
        api.build_argv(api.JOBS["recover_hold"], {**base, "site": "pinky"}, tmp_path)

    monkeypatch.setattr(api, "_check_arm_incident", lambda _arm: None)
    monkeypatch.setattr(api, "_check_depth_lock_held", lambda _ld=None: False)
    monkeypatch.setattr(api, "_session_lock_held", lambda arm, _ld=None: arm == "arm_b")
    procs = []
    monkeypatch.setattr(api.subprocess, "Popen", lambda a, **kw: procs.append(a) or Mock(poll=Mock(return_value=0)))
    r = api.Runner(tmp_path, lock_dir=tmp_path, fleet_safety_check_fn=lambda _: {"online": False, "blocked": False})

    res_mach = r.start("recover_hold", base, principal=guards.Principal(guards.ROLE_MACHINE, "bot"))
    assert res_mach["code"] == 403 and res_mach["error_code"] == "MACHINE_COMMISSIONING_FORBIDDEN"

    for bad_live in (None, {"human_hold_latched": False, "torque_hold_commanded": True, "chunk": None, "t": time.time()},
                     {"human_hold_latched": True, "torque_hold_commanded": False, "chunk": None, "t": time.time()},
                     {"human_hold_latched": True, "torque_hold_commanded": True, "chunk": "park", "t": time.time()},
                     {"human_hold_latched": True, "torque_hold_commanded": True, "chunk": None, "interrupt": "hold", "t": time.time()},
                     {"human_hold_latched": True, "torque_hold_commanded": True, "chunk": None, "t": time.time() - 120.0}):
        p_live = tmp_path / "chunk-io-b" / "live.json"
        p_live.unlink(missing_ok=True) if bad_live is None else p_live.write_text(json.dumps(bad_live), encoding="utf-8")
        bad_res = r.start("recover_hold", base)
        assert bad_res["code"] == 409 and bad_res["error_code"] == "NO_LIVE_HOLD_TO_RECOVER"

    (tmp_path / "chunk-io-b" / "live.json").write_text(json.dumps({"human_hold_latched": True, "torque_hold_commanded": True, "chunk": None, "t": time.time()}), encoding="utf-8")
    (tmp_path / "leases").mkdir()
    (tmp_path / "leases" / "arm_b.json").write_text(json.dumps({"pid": None, "expires_at": time.time() + 60.0}), encoding="utf-8")
    assert api.live_hold_attach_err("arm_b", tmp_path, tmp_path / "leases", tmp_path,
                                    session_lock_held_fn=lambda *_: False,
                                       read_json_fn=lambda p: json.loads(p.read_text()) if p.is_file() else None,
                                       live_max_age_s=15.0, pid_alive_fn=lambda _: True) is not None
    (tmp_path / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": None, "state": [0, 10, 10, 0, 0, 0], "t": time.time()}), encoding="utf-8")
    assert r.start("recover_hold", base)["error_code"] == "PEER_ARM_NOT_FOLDED"

    (tmp_path / "chunk-io-a" / "live.json").write_text(json.dumps({"chunk": None, "state": [0, -60, 50, 0, 0, 0], "t": time.time()}), encoding="utf-8")
    assert r.start("recover_hold", base)["code"] == 202 and len(procs) == 1


def test_fifo_cell_act_allows_recover_unlatch_while_human_hold_latched(tmp_path, monkeypatch):
    import cell_pipeline_io as pio

    prof = {"device_id": "arm_s", "profile_sha256": "p" * 64}
    cell = pio.FifoCell(tmp_path / "io", {}, operating_profile=prof)
    sent_cmds = []

    def fake_send(_self, _sock, *, wire_cmd, command, expected, **_kw):
        sent_cmds.append(command)
        if expected == "state":
            return {
                "ok": True, "t": time.time(), "fault": "contact in park",
                "human_hold_latched": True, "torque_hold_commanded": True,
                "operating_context": {"session_id": "s1", "operating_profile": prof},
                "library_sha256": "lib1",
            }, None
        return {"ok": True, "human_hold_latched": False, "unlatched_from_hold": True}, None

    monkeypatch.setattr(pio, "send_unix_command", fake_send)
    res = cell.act("recover-unlatch")
    assert res["ok"] is True and sent_cmds[-1] == "checked s1 lib1 recover-unlatch"
    bad_jog = cell.act("jog elbow_flex.pos 1.0")
    assert bad_jog["ok"] is False and bad_jog["fault"] == "profile_mismatch"
