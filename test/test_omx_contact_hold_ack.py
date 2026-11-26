"""A contact hold under a guard overload-hold still confirms the torque hold (2026-11-26 arm A and B).

The runner cleared `torque_hold_commanded` every tick while the guard shed load, so recover_hold answered 409 and
safe_home could not attach. The overload shed is now its own `overload_shed` field; the guard itself is unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_job_peer_health as peer  # noqa: E402
import cell_safe_home as safe_home  # noqa: E402
import chunk_runner as m  # noqa: E402
from chunk_runner_loop import publish_live  # noqa: E402

HOME = [0.8, -62.2, 53.1, 51.6, 45.2, 49.0]
REACH = [30.0, -20.0, 20.0, 45.0, -5.0, 49.0]
MOTORS = [n.split(".")[0] for n in m.NAMES]


class _Bus:
    model_ctrl_table = True

    def sync_read(self, reg, _motors=None, normalize=False, num_retry=0):
        val = {"Hardware_Error_Status": 0, "Torque_Enable": 1, "Present_PWM": 10,
               "Present_Current": 20, "Present_Temperature": 35}.get(reg)
        return {n: val for n in MOTORS} if val is not None else {}


class _Robot:
    def __init__(self):
        self.pos, self.bus, self.sent = list(REACH), _Bus(), []
        self.motion = SimpleNamespace(failed=False, held={"shoulder_lift": {"since": 0.0}}, tracking=True,
                                      command=dict(zip(MOTORS, REACH)), stop_streaming=lambda: None,
                                      _check_hardware_errors=lambda: None, pwm_limits=None, last_effort_time=False)

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))

    def send_action(self, action):
        self.sent.append(dict(action))
        return dict(action)

    def send_action_checked(self, action, _check=None, *, hold_on_read_error=False, allow_stale_hold=False):
        return self.send_action(action)


def _held_runner():
    robot, rows, lives = _Robot(), [], []
    lib = {"schema": m.SCHEMA, "names": list(m.NAMES), "fps": 30, "gripper_closed": HOME[5],
           "transit_speed": 0.85, "chunks": {"home": [HOME]}}
    r = m.Runner(robot, lib, fps=30, status=rows.append, clock=lambda: 1.0, live=lives.append)
    r.target = list(REACH)
    r.tick()  # the guard holds shoulder_lift: the runner enters a contact hold (no human latch yet)
    assert r.fault.startswith("contact (overload-hold") and r.human_hold_latched is False
    return robot, r, rows, lives


def test_contact_hold_under_overload_acks_torque_hold_and_reports_shed_separately():
    robot, r, rows, _ = _held_runner()
    assert r.command("human-hold req1") is True
    assert r.torque_hold_commanded is False  # not yet streamed
    r.tick()
    holds = [row for row in rows if row.get("command") == "human-hold"]
    assert r.human_hold_latched is True and r.torque_hold_commanded is True
    assert holds[-1]["ok"] is True and holds[-1]["hold_req"] == "req1" and holds[-1]["torque_hold_commanded"] is True
    assert holds[-1]["overload_shed"] == ["shoulder_lift"]
    for _ in range(10):  # every later tick still sheds: the ack must stand and no failed hold row may follow
        r.tick()
    assert r.torque_hold_commanded is True and robot.motion.held
    assert all(row["ok"] is True for row in rows if row.get("command") == "human-hold")
    assert len([row for row in rows if row.get("command") == "human-hold"]) == len(holds)


def test_overload_starting_after_the_ack_keeps_it_and_reports_the_shed_once():
    robot, r, rows, _ = _held_runner()
    robot.motion.held = {}
    r.command("human-hold req2")
    r.tick()
    assert r.torque_hold_commanded is True and "overload_shed" not in rows[-1]
    robot.motion.held = {"elbow_flex": {"since": 1.0}}
    for _ in range(5):
        r.tick()
    shed = [row for row in rows if row.get("command") == "human-hold" and row.get("overload_shed")]
    assert r.torque_hold_commanded is True and len(shed) == 1
    assert shed[0]["ok"] is True and shed[0]["hold_req"] == "req2" and shed[0]["person_needed"] is True


def test_recover_hold_and_safe_home_accept_the_shedding_hold(tmp_path):
    _, r, rows, lives = _held_runner()
    r.command("recover-unlatch")
    assert rows[-1]["ok"] is False and "human hold" in rows[-1]["error"]
    r.command("human-hold")
    r.command("recover-unlatch")  # latched but not yet streamed: still refused
    assert rows[-1]["ok"] is False and "acknowledged torque hold" in rows[-1]["error"]
    r.tick()
    publish_live(r)
    live = lives[-1]
    assert live["human_hold_latched"] is True and live["torque_hold_commanded"] is True
    assert live["overload_shed"] == ["shoulder_lift"] and live["pid"] == os.getpid()

    io = tmp_path / "chunk-io-a"
    io.mkdir()
    (io / "live.json").write_text(json.dumps({**live, "t": time.time()}), encoding="utf-8")
    err = peer.live_hold_attach_err("arm_a", tmp_path, tmp_path, None, session_lock_held_fn=lambda *_: True,
                                    read_json_fn=lambda p: json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None,
                                    live_max_age_s=15.0, pid_alive_fn=lambda _pid: True)
    assert err is None
    assert safe_home._live_hold_active({"io": str(io)}) is True

    r.command("recover-unlatch")
    assert rows[-1]["ok"] is True and rows[-1]["unlatched_from_hold"] is True
    r.tick()  # the guard still holds shoulder_lift: the runner holds again, the guard is not bypassed
    assert r.fault.startswith("contact (overload-hold") and robot_held(r)


def robot_held(r):
    return bool(r.robot.motion.held)
