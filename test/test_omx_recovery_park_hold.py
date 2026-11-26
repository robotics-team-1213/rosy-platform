"""Tests for RECOVERY_PARKS (`park-slow`, `fold-from-hold`), space-reservation retention, and FifoCell recovery I/O."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "deploy" / "robot" / "omx", ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_auto_fold as af  # noqa: E402
import cell_pipeline_io as cpio  # noqa: E402
import cell_recovery_advisor as cra  # noqa: E402
import chunk_runner as m  # noqa: E402
import chunk_runner_interrupt as cri  # noqa: E402
import judge_seat  # noqa: E402
from cell_envelope import digest  # noqa: E402
from omx_adapter.chunk_library import park_path, too_fast, transit_path  # noqa: E402

HOME = [0.8, -62.2, 53.1, 51.6, 45.2, 49.0]
REACH = [30.0, -20.0, 20.0, 45.0, -5.0, 49.0]
MOTORS = [n.split(".")[0] for n in m.NAMES]


class _Bus:
    def __init__(self, *, temp_c: int = 35):
        self.model_ctrl_table, self.temp_c = True, temp_c

    def sync_read(self, reg, _motors=None, normalize=False, num_retry=0):
        del normalize, num_retry
        val = {"Hardware_Error_Status": 0, "Torque_Enable": 1, "Present_PWM": 10,
               "Present_Current": 20, "Present_Temperature": self.temp_c}.get(reg)
        return {n: val for n in MOTORS} if val is not None else {}


class _Robot:
    def __init__(self, pos=None, *, freeze: bool = False):
        self.pos, self.freeze, self.bus, self.sent, self.checked_calls = list(pos or REACH), freeze, _Bus(), [], []
        self.motion = SimpleNamespace(failed=False, held={}, tracking=True, command=dict(zip(MOTORS, HOME)),
                                      stop_calls=0, stop_streaming=lambda: None, _check_hardware_errors=lambda: None,
                                      pwm_limits=None)

    def get_observation(self):
        return dict(zip(m.NAMES, self.pos))

    def send_action(self, action):
        self.sent.append(dict(action))
        if not self.freeze:
            for i, name in enumerate(m.NAMES):
                self.pos[i] = float(action[name])
        return dict(action)

    def send_action_checked(self, action, _check=None, *, hold_on_read_error=False, allow_stale_hold=False):
        self.checked_calls.append((dict(action), hold_on_read_error, allow_stale_hold))
        return self.send_action(action)


def _lib():
    return {"schema": m.SCHEMA, "names": list(m.NAMES), "fps": 30, "gripper_closed": HOME[5],
            "transit_speed": 0.85, "chunks": {"home": [HOME]}}


def test_fold_from_hold_and_park_slow_admission_and_lockout():
    robot, rows, clock = _Robot(REACH), [], [0.0]
    ctx = {"scope": "simulation", "sha256": "a" * 64, "session_id": "sid-fh"}
    r = m.Runner(robot, _lib(), fps=30, status=rows.append, clock=lambda: clock[0], operating_context=ctx)
    r.target = list(REACH)
    dig = r._library_digest()
    rounded = [round(v, 2) for v in REACH]
    checked_fh = f"checked sid-fh {dig} fold-from-hold " + " ".join(map(str, rounded))

    r.command("fold-from-hold " + " ".join(map(str, rounded)))
    assert rows[-1]["ok"] is False and "checked command" in rows[-1]["error"]
    r.command(checked_fh)
    assert rows[-1]["ok"] is False

    r.command("human-hold")
    r.command(checked_fh)
    assert rows[-1]["ok"] is False and "acknowledged" in rows[-1]["error"]
    r.tick()
    assert r.human_hold_latched is True and r.torque_hold_commanded is True

    # Bad syntax / reserved / pose drift / hard fault / occupied gripper all fail closed while keeping latch
    for bad in (
        f"fold-from-hold {' '.join(map(str, rounded))}",
        f"checked sid-fh {dig} fold-from-hold 1.0 2.0",
        f"checked sid-fh {dig} fold-from-hold {' '.join(map(str, [rounded[0] + 1.0, *rounded[1:]]))}",
    ):
        r.command(bad)
        assert rows[-1]["ok"] is False and r.human_hold_latched is True

    r.fault = "hardware error"
    r.command(checked_fh)
    assert rows[-1]["ok"] is False and r.human_hold_latched is True
    r.fault = "human hold"

    # Occupied gripper refused on BOTH fold-from-hold and park-slow
    robot.pos[5] = HOME[5] + 4.0
    r.command(f"checked sid-fh {dig} fold-from-hold " + " ".join(map(str, [round(v, 2) for v in robot.pos])))
    assert rows[-1]["ok"] is False and "occupied gripper" in rows[-1]["error"] and r.human_hold_latched is True
    robot.pos[5] = HOME[5]

    rp = m.Runner(_Robot([*REACH[:5], HOME[5] + 4.0]), _lib(), fps=30, status=rows.append)
    rp.target, rp.fault = list(REACH), "contact in park"
    rp.command("park-slow")
    assert rows[-1]["ok"] is False and "occupied gripper" in rows[-1]["error"] and rp.fault == "contact in park"

    # Admission clears latch, uses <= 0.3 slow path, locks out stop/park/run/goto/splice while active
    r.command(checked_fh)
    assert r.human_hold_latched is False and r.chunk == "fold-from-hold" and r.queue
    assert not too_fast([REACH, *r.queue], 30)
    for blocked in ("stop", "stop now", "park", "state" if False else "run home", "splice home"):
        r.command(blocked)
        assert rows[-1]["ok"] is False and "still running" in rows[-1]["error"]
    r.command("state")
    assert rows[-1]["ok"] is True

    # Run to settled home (human-hold allowed mid-run)
    for _ in range(len(r.queue) + 5):
        clock[0] += 1 / 30
        r.tick()
    assert r.chunk is None and r.home_since is not None
    assert rows[-1]["command"] == "run fold-from-hold" and rows[-1]["ok"] is True and rows[-1]["settled"] is True

    # Reserved recovery command names cannot be invoked via run/splice/goto
    for res_cmd in ("run fold-from-hold", "run park-slow", "splice fold-from-hold", "goto park-slow"):
        r.command(res_cmd)
        assert rows[-1]["ok"] is False and "reserved recovery command" in rows[-1]["error"]


@pytest.mark.parametrize("mode", ["follow", "thermal", "unsettled", "human_hold"])
def test_recovery_park_relatches_with_torque_on_across_failures(mode, monkeypatch):
    clock, rows = [0.0], []
    robot = _Robot(REACH, freeze=(mode == "follow"))
    r = m.Runner(robot, _lib(), fps=30, status=rows.append, clock=lambda: clock[0])
    r.target, r.fault = list(REACH), "contact in park"
    r.command("park-slow")
    assert r.chunk == "park-slow" and r.queue

    if mode == "follow":
        r.queue = [[REACH[0] + 26.0, *REACH[1:]]] * 4
        r.target = [REACH[0] + 26.0, *REACH[1:]]
        monkeypatch.setattr(r, "strained", lambda *_a, **_k: None)
        for _ in range(4):
            clock[0] += 0.5
            r.tick()
            if r.human_hold_latched:
                break
        assert r.human_hold_latched is True and "following error" in r.fault
    elif mode == "thermal":
        robot.bus.temp_c = 68
        for _ in range(35):
            clock[0] += 1 / 30
            r.tick()
            if r.human_hold_latched:
                break
        assert r.human_hold_latched is True and "temperature 68 C" in r.fault
    elif mode == "unsettled":
        r.queue = []
        r.settle_since = 0.0
        monkeypatch.setattr(robot, "get_observation", lambda: dict(zip(m.NAMES, [REACH[0] + 6.0, *HOME[1:]])))
        clock[0] = 5.0
        r.tick()
        assert r.human_hold_latched is True and r.fault == "park-slow did not settle at home"
    else:
        r.command("human-hold")
        assert r.human_hold_latched is True and r.chunk is None
    assert rows[-1]["command"] == "run park-slow" and rows[-1]["ok"] is False and rows[-1]["person_needed"] is True


def test_fifo_cell_matches_recovery_verbs_and_ignores_unrelated_faults(tmp_path):
    io_dir = tmp_path / "io"
    io_dir.mkdir()
    status_path = io_dir / "chunk-status.jsonl"
    status_path.write_text("", encoding="utf-8")
    (io_dir / "chunk-cmd").write_text("", encoding="utf-8")
    cell = cpio.FifoCell(io_dir, {}, timeout_s=0.5)
    orig_open, orig_close, orig_write = cpio.os.open, cpio.os.close, cpio.os.write
    try:
        cpio.os.open = lambda *_a, **_k: 123
        cpio.os.close = lambda _fd: None

        def _fake_write(_fd, _data):
            lines = [
                json.dumps({"command": "tick", "fault": "stale unrelated"}),
                json.dumps({"command": "run fold-from-hold", "ok": True, "settled": True, "state": HOME}),
            ]
            status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return len(_data)

        cpio.os.write = _fake_write
        reply = cell.checked("fold-from-hold " + " ".join(map(str, HOME)), {"session_id": "s1", "library_sha256": "d1"})
        assert cpio.park_succeeded(reply) is True and reply["command"] == "run fold-from-hold"
    finally:
        cpio.os.open, cpio.os.close, cpio.os.write = orig_open, orig_close, orig_write


def test_auto_fold_direct_fold_from_hold_detour_park_slow_and_reservation_retention():
    class _FoldCell:
        def __init__(self, state, *, park_ok=True, lib_sha="lib-sha"):
            self.state, self.target, self.park_ok, self.lib_sha = list(state), list(state), park_ok, lib_sha
            self.latched, self.cmds = True, []

        def act(self, cmd):
            self.cmds.append(cmd)
            if cmd == "state":
                return {"ok": True, "state": list(self.state), "target": list(self.target), "holding": False,
                        "human_hold_latched": self.latched, "torque_hold_commanded": self.latched,
                        "library_sha256": self.lib_sha, "operating_context": {"session_id": "sid-1"}}
            if cmd == "recover-unlatch":
                self.latched = False
                return {"ok": True, "human_hold_latched": False, "state": list(self.state), "target": list(self.target)}
            if cmd == "human-hold":
                self.latched = True
                return {"ok": True, "human_hold_latched": True, "state": list(self.state)}
            if cmd.startswith("jog "):
                _, j, d = cmd.split()
                idx = m.NAMES.index(j)
                self.state[idx] += float(d)
                self.target[idx] += float(d)
                return {"ok": True, "state": list(self.state), "target": list(self.target)}
            if cmd == "park-slow":
                if not self.park_ok:
                    return {"ok": False, "settled": False, "error": "contact in park-slow", "state": list(self.state)}
                self.state, self.target = list(HOME), list(HOME)
                return {"ok": True, "settled": True, "state": list(HOME), "target": list(HOME)}
            return {"ok": True, "state": list(self.state), "target": list(self.target)}

        def checked(self, cmd, _ctx):
            self.cmds.append(f"checked:{cmd}")
            if not self.park_ok:
                return {"ok": False, "settled": False, "error": "fold-from-hold did not settle at home",
                        "human_hold_latched": True, "state": list(self.state)}
            self.latched = False
            self.state, self.target = list(HOME), list(HOME)
            return {"ok": True, "settled": True, "state": list(HOME), "target": list(HOME)}

    # 1. Clear direct path uses atomic fold-from-hold without recover-unlatch and releases space
    rel1, c1 = [], _FoldCell(REACH)
    res1 = af.recover(c1, HOME, HOME[5], plan=lambda s: [s, HOME], held_plan=lambda s: [s, HOME], library_sha256="lib-sha",
                      look=lambda _: {"clear": True, "low": [], "high": []}, reserve=lambda _: {"ok": True},
                      release=lambda: rel1.append(1), release_and_rise=lambda _: {"result": "risen"}, low=lambda _: False,
                      allow_live_unlatch=True)
    assert res1["result"] == "folded" and res1["candidate"] == "fold-from-hold" and rel1 == [1]
    assert not any("recover-unlatch" in c for c in c1.cmds) and any("fold-from-hold" in c for c in c1.cmds)

    # 2. Failed fold keeps space reservation until TTL (`release()` is NOT called!)
    rel2, c2 = [], _FoldCell(REACH, park_ok=False)
    res2 = af.recover(c2, HOME, HOME[5], plan=lambda s: [s, HOME], held_plan=lambda s: [s, HOME], library_sha256="lib-sha",
                      look=lambda _: {"clear": True, "low": [], "high": []}, reserve=lambda _: {"ok": True},
                      release=lambda: rel2.append(1), release_and_rise=lambda _: {"result": "risen"}, low=lambda _: False,
                      allow_live_unlatch=True)
    assert res2["result"] == "held" and res2["reason"] == "PARK_NOT_HOME" and rel2 == []

    # 3. Direct blocked -> falls through to Tier-1 detour using recover-unlatch + park-slow
    rel3, c3 = [], _FoldCell(REACH)
    res3 = af.recover(c3, HOME, HOME[5], plan=lambda s: [s, HOME], held_plan=lambda s: [s, HOME], library_sha256="lib-sha",
                      look=lambda f: {"clear": any(abs(p[0] - REACH[0]) >= 4.0 and p[:5] != HOME[:5] for p in f), "low": [], "high": []},
                      reserve=lambda _: {"ok": True}, release=lambda: rel3.append(1), release_and_rise=lambda _: {"result": "risen"},
                      low=lambda _: False, allow_live_unlatch=True, sleep=lambda _: None)
    assert res3["result"] == "folded" and rel3 == [1] and "recover-unlatch" in c3.cmds and "park-slow" in c3.cmds


def test_park_from_open_jaws_rises_first_and_closes_at_the_transit_height_never_at_the_hover():
    # 2026-11-19 arm_a: a park closed open jaws at the hover over a tray and lifted the box they caught
    home, start = [0.0, -58.0, 50.0, 50.0, -5.0, 46.6], [35.0, -10.0, 9.0, 41.0, 71.0, 56.0]
    path = park_path(start, home, 46.6, fps=30)
    assert not too_fast([start] + path, 30)
    closed = next(i for i, f in enumerate(path) if f[5] < 56.0 - 1e-6)
    assert path[closed][1] <= -26.0 and path[closed][2] <= 19.0
    assert all(f[5] == pytest.approx(56.0) for f in path[:closed])
    turning = next(i for i, f in enumerate(path) if abs(f[0] - start[0]) > 1e-6)
    assert closed < turning and path[-1][:5] == pytest.approx(home[:5]) and path[-1][5] == pytest.approx(46.6)
    # 2026-11-27 arm_b (closed 48.8) & arm_a (closed 49.0): ANY extended park_path wider than closed rises to transit first
    for closed_g, open_g in ((46.6, 52.0), (48.8, 53.85), (48.8, 54.5), (48.8, 55.68), (49.0, 55.8)):
        pose = [35.0, -10.0, 9.0, 41.0, 71.0, open_g] if closed_g == 46.6 else [20.4, 12.6, 6.6, 30.8, -29.0, open_g]
        h = home if closed_g == 46.6 else [0.8, -62.2, 53.1, 51.6, 45.2, closed_g]
        p_open = park_path(pose, h, closed_g, fps=30)
        c_idx = next(i for i, f in enumerate(p_open) if f[5] < open_g - 1e-6)
        t_idx = next(i for i, f in enumerate(p_open) if abs(f[0] - pose[0]) > 1e-6)
        assert p_open[c_idx][1] <= -26.0 and c_idx < t_idx
        assert all(f[5] == pytest.approx(open_g) for f in p_open[:c_idx])
        assert all(f[5] <= open_g + 1e-6 for f in p_open)
    # Direct transit_path keeps OPEN_JAW_MARGIN behavior for held carry transfers
    held_transit = transit_path([35.0, -10.0, 9.0, 41.0, 71.0, 52.0], home, 46.6, fps=30)
    assert next(i for i, f in enumerate(held_transit) if f[5] < 52.0 - 1e-6) < next(i for i, f in enumerate(held_transit) if f[1] <= -26.0)


def test_unreadable_state_and_holding_margin_guards():
    def _cell(resp):
        cmds = []
        class _C:
            def act(self, cmd):
                cmds.append(cmd)
                return dict(resp) if cmd == "state" else {"ok": True}
        return _C(), cmds

    for allow, rel in ((True, False), (False, True)):
        c, cmds = _cell({"ok": False, "error": "timeout"})
        out = af.recover(c, HOME, HOME[5], plan=lambda s: [s, HOME], look=lambda _: {"clear": True},
                         reserve=lambda _: {"ok": True}, release=lambda: None, release_and_rise=lambda _: {"result": "risen"},
                         low=lambda _: False, allow_live_unlatch=allow, release_unmoved=rel)
        assert out["result"] == "held" and out["reason"] == "STATE_UNREADABLE" and "stop now" not in cmds and "human-hold" in cmds

    c_ah, cmds_ah = _cell({"ok": True, "state": [*HOME[:5], HOME[5] + 3.0], "target": HOME, "holding": False, "human_hold_latched": True})
    assert af.recover(c_ah, HOME, HOME[5], plan=lambda s: [s, HOME], look=lambda _: {"clear": True}, reserve=lambda _: {"ok": True},
                      release=lambda: None, release_and_rise=lambda _: {"result": "risen"}, low=lambda _: False,
                      allow_live_unlatch=True)["reason"] == "HOLDING_AT_HOME" and "recover-unlatch" not in cmds_ah
    c_hl, _ = _cell({"ok": True, "state": REACH, "target": REACH, "holding": True, "human_hold_latched": True})
    assert af.recover(c_hl, HOME, HOME[5], plan=lambda s: [s, HOME], look=lambda _: {"clear": True}, reserve=lambda _: {"ok": True},
                      release=lambda: None, release_and_rise=lambda _: {"result": "risen"}, low=lambda _: False,
                      allow_live_unlatch=True)["reason"] == "HOLDING_HIGH"


def test_post_unlatch_detour_window_protection(monkeypatch):
    clock, rows = [0.0], []
    robot = _Robot(REACH)
    r = m.Runner(robot, _lib(), fps=30, status=rows.append, clock=lambda: clock[0], operating_context={"scope": "simulation"})
    r.target, r.human_hold_latched, r.torque_hold_commanded, r.fault = list(REACH), True, True, "human hold"
    r.command("recover-unlatch")
    assert r._recovery_active is True and r.chunk is None and r.holding is False
    r.tick()
    assert robot.checked_calls and robot.checked_calls[-1][1:] == (True, False)
    r.command("stop now")
    assert rows[-1]["ok"] is False and "refused during recovery" in rows[-1]["error"]
    assert r.idle() is False and cri.gate_allows(r, []) is False

    # FOLLOW_STOP / read_health / encoder errors during post-unlatch window all re-latch with torque ON
    robot.freeze = True
    r.target = [REACH[0] + 26.0, *REACH[1:]]
    clock[0] += 0.5
    r.tick()
    clock[0] += 1.5
    r.tick()
    assert r.human_hold_latched is True and r._recovery_active is False and "following error" in r.fault

    robot.freeze = False
    for bad_kind in ("health", "enc"):
        r.target, r.pos, r.fault, r.torque_hold_commanded = list(REACH), list(REACH), "human hold", True
        r.command("recover-unlatch")
        assert rows[-1]["ok"] is True and r._recovery_active is True
        with monkeypatch.context() as mp:
            if bad_kind == "health":
                mp.setattr(r, "read_health", lambda: (_ for _ in ()).throw(OSError("bus")))
                r.ticks = max(1, round(r.fps * m.HEALTH_PERIOD_S)) - 1
            else:
                mp.setattr(robot, "get_observation", lambda: (_ for _ in ()).throw(OSError("enc")))
            r.tick()
        assert r.human_hold_latched is True and r._recovery_active is False

    # Settled park-slow or clean stop at home clears _recovery_active
    r.target, r.pos, r.fault, r.torque_hold_commanded = list(REACH), list(REACH), "human hold", True
    r.command("recover-unlatch")
    assert rows[-1]["ok"] is True and r._recovery_active is True
    r.command("park-slow")
    assert r.human_hold_latched is False and r.chunk == "park-slow"
    for _ in range(len(r.queue) + 2):
        clock[0] += 1 / 30
        r.tick()
    assert rows[-1]["command"] == "run park-slow" and rows[-1]["settled"] is True
    assert r._recovery_active is False and cri.gate_allows(r, []) is True

    r.command("human-hold")
    r.tick()
    r.command("recover-unlatch")
    assert rows[-1]["ok"] is True and r._recovery_active is True
    assert r.command("stop") is False and r._recovery_active is False and cri.gate_allows(r, []) is True


def test_advisor_str_spec_nested_panel_and_arbiter_model():
    assert cra._str_to_spec("VLLM:qwen3-vl") == {"provider": "vllm", "model": "qwen3-vl"}
    assert cra._str_to_spec("http:endpoint") == {"provider": "http", "model": "endpoint"}
    assert cra._str_to_spec("http://127.0.0.1:11434")["provider"] == "ollama"
    with pytest.raises(ValueError):
        cra.select_recovery_backend({"models": [{"models": []}]})
    arb = lambda *_a: {"decision": "hold", "confidence": 0.9, "reason": "safe"}  # noqa: E731
    arb.__name__ = "arbiter_fn"
    out = judge_seat.cooperate([lambda *_: {"decision": "hold"}, lambda *_: {"decision": "stop"}], arbiter=arb)("p", [], None)
    assert out["decision"] == "hold" and out["model"] == "arbiter_fn"


def test_chunk_runner_async_health_and_live_flush_on_unlatch_and_stop(tmp_path, monkeypatch):
    import bus_watchdog
    import cell_job_guards
    import guarded_native
    import motor_health
    seen, ended, lives = [], [], []
    cfg, lib = tmp_path / "c.json", tmp_path / "l.json"
    cfg.write_text(json.dumps({"robot": {"type": "omx_follower", "port": "/dev/null", "max_relative_target": 5}, "dataset": {"fps": 30}}))
    lib.write_text(json.dumps(_lib()))
    monkeypatch.setitem(sys.modules, "lerobot.robots.omx_follower", SimpleNamespace(OmxFollowerConfig=lambda **k: k, OmxFollower=lambda _c: _Robot(HOME)))
    for mod, attr, val in ((guarded_native, "connect_passive", lambda *_a, **_k: None), (guarded_native, "close_device", lambda *_a: None), (bus_watchdog, "arm", lambda *_a: None), (m, "fifo_lines", lambda *_a: SimpleNamespace(close=lambda: None)), (m, "runtime_context", lambda *_a, **_k: {"scope": "simulation"}), (motor_health, "MotorHealth", lambda *, async_publish=False: seen.append(async_publish) or SimpleNamespace(end=lambda: ended.append(True))), (m, "Runner", type("_R", (m.Runner,), {"run": lambda self, _l: None}))):
        monkeypatch.setattr(mod, attr, val)
    m.main(["--config", str(cfg), "--library", str(lib), "--io", str(tmp_path / "io")])
    assert seen == [True] and ended == [True]
    r = m.Runner(_Robot(HOME), _lib(), fps=30, status=lambda _row: None, live=lives.append)
    r.target = list(HOME)
    r.command("human-hold")
    r.tick()
    assert r.command("recover-unlatch") is True and lives and lives[-1]["human_hold_latched"] is False and lives[-1]["fault"] is None
    assert r.command("stop") is False and len(lives) >= 2 and not (lives[-1]["human_hold_latched"] or lives[-1]["torque_hold_commanded"] or lives[-1]["fault"])
    (tmp_path / "chunk-io-b").mkdir()
    (tmp_path / "chunk-io-b" / "live.json").write_text(json.dumps(lives[-1]), encoding="utf-8")
    assert cell_job_guards.check_peer_ab_folded("arm_a", tmp_path, tmp_path / "leases", tmp_path, session_lock_held_fn=lambda *_: False, read_json_fn=lambda p: json.loads(p.read_text()) if p.is_file() else None, live_max_age_s=15.0, incident_check_fn=lambda _: None) is None


def test_publish_live_always_includes_pid_and_fifo_cell_fast_fails_dead_or_stalled_runner(tmp_path, monkeypatch):
    lives = []
    r = m.Runner(_Robot(HOME), _lib(), fps=30, status=lambda _row: None, live=lives.append)
    r.target = list(HOME)
    r._interrupt = None
    r._crl_publish = True
    from chunk_runner_loop import publish_live
    publish_live(r)
    assert lives and lives[-1]["pid"] == os.getpid() and lives[-1]["holding"] is False and "interrupt" not in lives[-1]
    r.holding = True
    publish_live(r)
    assert lives[-1]["holding"] is True
    r.holding = False

    io_dir = tmp_path / "io_liveness"
    io_dir.mkdir()
    status_path = io_dir / "chunk-status.jsonl"
    status_path.write_text("", encoding="utf-8")
    live_path = io_dir / "live.json"
    (io_dir / "chunk-cmd").write_text("", encoding="utf-8")
    monkeypatch.setattr(cpio.os, "open", lambda *_a, **_k: 123)
    monkeypatch.setattr(cpio.os, "close", lambda _fd: None)
    monkeypatch.setattr(cpio.os, "write", lambda _fd, data: len(data))

    # 1. Dead PID -> runner_dead quickly; final status row written before exit is still drained
    live_path.write_text(json.dumps({"t": 100.0, "pid": 999999}), encoding="utf-8")
    monkeypatch.setattr(cpio.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()) if pid == 999999 else None)
    cell = cpio.FifoCell(io_dir, {}, timeout_s=30.0, stall_timeout_s=0.15)
    t0 = time.monotonic()
    dead_res = cell.act("park")
    assert dead_res["ok"] is False and dead_res["fault"] == "runner_dead" and time.monotonic() - t0 < 1.0

    def kill_after_final_status(pid, sig):
        if pid == 999999:
            status_path.write_text(json.dumps({"command": "park", "ok": True, "settled": True}) + "\n", encoding="utf-8")
            raise ProcessLookupError()

    monkeypatch.setattr(cpio.os, "kill", kill_after_final_status)
    assert cell.act("park")["ok"] is True
    status_path.write_text("", encoding="utf-8")

    # 2. PermissionError is treated as alive, advancing live.json t stays alive, stalled t -> runner_stalled
    monkeypatch.setattr(cpio.os, "kill", lambda _pid, _sig: (_ for _ in ()).throw(PermissionError()))
    live_path.write_text(json.dumps({"t": 100.0, "pid": 4242}), encoding="utf-8")
    stall_res = cell.act("park")
    assert stall_res["ok"] is False and stall_res["fault"] == "runner_stalled"

    ticks = [100.0]
    def advancing_policy_state():
        ticks[0] += 1.0
        return {"t": ticks[0], "pid": 4242}
    adv_cell = cpio.FifoCell(io_dir, {}, timeout_s=0.12, stall_timeout_s=0.05)
    monkeypatch.setattr(adv_cell, "policy_state", advancing_policy_state)
    adv_res = adv_cell.act("park")
    assert adv_res["ok"] is False and "no status within" in adv_res["error"]

    # 3. Missing live.json falls back cleanly to deadline
    live_path.unlink()
    missing_cell = cpio.FifoCell(io_dir, {}, timeout_s=0.05, stall_timeout_s=0.02)
    miss_res = missing_cell.act("park")
    assert miss_res["ok"] is False and "no status within" in miss_res["error"]

    # 4. human-hold path untouched even with dead PID
    monkeypatch.setattr(cpio.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError()) if pid == 999999 else None)
    live_path.write_text(json.dumps({"t": 100.0, "pid": 999999}), encoding="utf-8")
    hold_res = cpio.FifoCell(io_dir, {}, timeout_s=0.05, stall_timeout_s=0.02).act("human-hold")
    assert hold_res["ok"] is False and hold_res.get("command") == "human-hold" and "no status within" in hold_res["error"]


def test_pr2_park_chunk_absorbs_transient_bus_errors() -> None:
    import chunk_policy_playback as cpp

    class _ParkRobot(_Robot):
        def get_observation(self):
            raise ConnectionError("transient sync_read timeout")

        def send_action_checked(self, action, _check=None, *, hold_on_read_error=False, allow_stale_hold=False):
            from guarded_native import GoalRejected

            raise GoalRejected("transient goal readback mismatch")

    rows = []

    def _new_park_runner():
        r_inst = m.Runner(_ParkRobot(REACH), _lib(), fps=30, status=rows.append, clock=lambda: 1.0)
        r_inst.chunk, r_inst.target, r_inst.last_present = "park", list(REACH), list(REACH)
        return r_inst

    r1 = _new_park_runner()
    assert cpp.absorb_telemetry_error(r1, list(REACH), "telemetry read", OSError("bus glitch")) is True
    assert r1.human_hold_latched is True
    assert any("bus glitch" in row.get("policy_stop", "") for row in rows)

    r2 = _new_park_runner()
    pose, fresh = cpp.read_present_or_hold(r2, "present read")
    assert fresh is False and pose == list(REACH) and r2.human_hold_latched is True

    r3 = _new_park_runner()
    sent, ok = cpp.send_with_jaw_gate(r3, dict(zip(m.NAMES, REACH)), None, None, list(REACH))
    assert sent is None and ok is False and r3.human_hold_latched is True
