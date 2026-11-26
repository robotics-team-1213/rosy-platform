"""Tests for jaw-zone retreat before paced policy park, human-hold gripper freeze, and arm session wrappers."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy" / "robot" / "omx"
for _p in (OMX, ROOT / "middleware" / "devices" / "omx" / "adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_policy_drive as drive  # noqa: E402
from chunk_runner_guards import hold_runner  # noqa: E402
from grasp_planner import norm_to_rad  # noqa: E402

HOME = [0.0, -58.0, 51.0, 50.0, -14.0, 49.0]
PICK_ZONE = [38.8, -10.0, 2.0, 55.0, -14.0, 54.0]
GRASP_LIB = {
    "fps": 30,
    "gripper_closed": 48.8,
    "chunks": {
        "home": [HOME, HOME],
        "reach": [[0.0, -58.0, 2.0, 40.0, -14.0, 49.0], [40.0, -10.0, 51.0, 55.0, -14.0, 60.0]],
        "grasp_pick": [[38.8, -10.0, 2.0, 55.0, -14.0, 49.0]] * 2,
    },
}


class _FakeKin:
    def fk(self, joints):
        pan = joints[0]
        yaw = pan - joints[4]
        near_pick = abs(pan - norm_to_rad(38.8)) < 0.35
        low_z = joints[1] > norm_to_rad(-30.0)
        return SimpleNamespace(
            x=0.18 if near_pick else 0.02,
            y=0.14 if near_pick else 0.0,
            z=0.04 if low_z else 0.16,
            yaw=yaw,
            tool_down_error_rad=0.05,
        )


class _PacedSeqPolicy:
    image_views = {"top": (4, 4), "wrist": (4, 4)}
    goal_size = None
    sim_rule = None
    chunk_size = 16
    n_action_steps = 4
    files = {}

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def inputs(self, state, frames, **_):
        return {"observation.state": state}, {"model_frame_sha256": {}}

    def infer(self, obs, **_):
        return SimpleNamespace(chunk=self._chunks.pop(0))


class _RetreatCell:
    def __init__(self, *, run_replies=None, retreat_contact=False, drop_state_on_retreat=False):
        self.state = list(HOME)
        self.commands: list[str] = []
        self.loaded_libs: list[dict] = []
        self._run_replies = list(run_replies or [])
        self._retreat_contact = retreat_contact
        self._drop_state_on_retreat = drop_state_on_retreat

    def frame(self, _view):
        import numpy as np

        return np.zeros((4, 4, 3), np.uint8)

    def act(self, command: str):
        self.commands.append(command)
        base = command.split(" ", 3)[-1] if command.startswith("checked ") else command
        if base == "state":
            if self._drop_state_on_retreat and self.commands.count("state") >= 5:
                return {"ok": False, "fault": "bus lost", "error": "bus lost", "state": list(self.state)}
            return {"state": list(self.state), "target": list(self.state), "ok": True,
                    "command": "state", "settled": True, "holding": False, "health": {"current_ma": [0] * 6}}
        if base.startswith("load "):
            lib = json.loads(Path(base[5:]).read_text(encoding="utf-8"))
            self.loaded_libs.append(lib)
            return {"command": command, "ok": True, "settled": True, "holding": False, "state": list(self.state)}
        if base == "run policy":
            if self._run_replies:
                reply = self._run_replies.pop(0)
                if reply.get("state"):
                    self.state = list(reply["state"])
                return {"command": command, "holding": False, **reply}
            pol = self.loaded_libs[-1]["chunks"]["policy"]
            if self._retreat_contact and len(self.loaded_libs) >= 2:
                return {"command": command, "ok": False, "settled": False, "contact": True,
                        "error": "contact during retreat", "state": list(self.state)}
            self.state = list(pol[-1])
            return {"command": command, "ok": True, "settled": True, "holding": False, "state": list(self.state)}
        if base == "park":
            self.state = list(HOME)
            return {"command": command, "ok": True, "settled": True, "holding": False, "state": list(self.state)}
        if base == "human-hold":
            return {"command": "human-hold", "ok": True, "human_hold_latched": True,
                    "torque_hold_commanded": True, "state": list(self.state)}
        raise AssertionError(f"unexpected command: {command}")


def _write_lib(tmp_path: Path) -> Path:
    path = tmp_path / "lib.json"
    path.write_text(json.dumps(GRASP_LIB), encoding="utf-8")
    return path


def _make_auth(calls: list):
    def authorize(_lib, status, seq, *, check_home=True):
        calls.append((seq, list(status["state"]), check_home))
        return {"session_id": f"s{len(calls)}", "library_sha256": f"h{len(calls)}"}

    authorize.supports_check_home = True
    return authorize


def test_paced_refusal_inside_jaw_zone_retreats_then_parks(tmp_path):
    cell = _RetreatCell()
    auth_calls = []
    # Chunk 0 descends into PICK_ZONE; chunk 1 proposes out-of-envelope pan to trigger shape refusal inside zone.
    pol = _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16])
    rows = []
    res = drive.run_episode(
        cell, pol, _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=rows.append, kin=_FakeKin(), authorize=_make_auth(auth_calls),
        paced_chunks=True, n_action=4,
    )
    assert res["result"] == "refused" and res["parked"] is True
    assert len(cell.loaded_libs) == 2
    retreat_frames = cell.loaded_libs[1]["chunks"]["policy"]
    first_open = next(i for i, f in enumerate(retreat_frames) if abs(f[5] - 60.0) < 1e-3)
    assert all(f[1] == pytest.approx(PICK_ZONE[1]) for f in retreat_frames[:first_open + 1])  # opened to library max before lifting
    assert retreat_frames[-1][1] <= -30.0  # cleared FakeKin low_z threshold (-30 -> z=0.16 > z_m+0.025)
    assert auth_calls[-1] == (("run policy", "park"), PICK_ZONE, False)
    assert cell.commands[-1].startswith("checked s2 h2 park")
    assert any(r.get("command") == "retreat_jaw_zone" and r.get("ok") is True for r in rows)


@pytest.mark.parametrize("mode", ["contact", "unreachable", "bad_state"])
def test_paced_refusal_inside_jaw_zone_fails_closed_when_retreat_blocked(tmp_path, mode):
    cell = _RetreatCell(
        retreat_contact=(mode == "contact"),
        drop_state_on_retreat=(mode == "bad_state"),
    )
    low_reach = {
        **GRASP_LIB,
        "chunks": {
            **GRASP_LIB["chunks"],
            "reach": [[38.8, -10.0, 2.0, 55.0, -14.0, 49.0], [38.8, -5.0, 2.0, 55.0, -14.0, 60.0]],
        },
    }
    lib_path = tmp_path / "lib.json"
    lib_path.write_text(json.dumps(low_reach), encoding="utf-8")

    class AlwaysLowKin(_FakeKin):
        def fk(self, joints):
            fk = super().fk(joints)
            if mode == "unreachable":
                return SimpleNamespace(x=fk.x, y=fk.y, z=0.04, yaw=fk.yaw, tool_down_error_rad=fk.tool_down_error_rad)
            return fk

    pol = _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16])
    rows = []
    res = drive.run_episode(
        cell, pol, lib_path, tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=rows.append, kin=AlwaysLowKin(), paced_chunks=True, n_action=4,
    )
    assert res["result"] == "refused" and res["parked"] is False
    assert not any(c.endswith("park") for c in cell.commands)
    assert cell.commands[-1] == "human-hold"
    assert any(r.get("command") == "retreat_jaw_zone" and not r.get("ok") for r in rows)


def test_paced_refusal_outside_jaw_zone_parks_directly(tmp_path):
    high_pose = [0.0, -50.0, 51.0, 50.0, -14.0, 54.0]
    cell = _RetreatCell()
    pol = _PacedSeqPolicy([[high_pose] * 16, [[99.0, -50.0, 51.0, 50.0, -14.0, 54.0]] * 16])
    rows = []
    res = drive.run_episode(
        cell, pol, _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=rows.append, kin=_FakeKin(), paced_chunks=True, n_action=4,
    )
    assert res["result"] == "refused" and res["parked"] is True
    assert len(cell.loaded_libs) == 1  # only chunk 0 loaded; no extra retreat load/run
    assert cell.commands[-1] == "park"
    assert not any(r.get("command") == "retreat_jaw_zone" for r in rows)


def _dummy_runner(*, holding: bool, target_grip: float = 48.8, release_until=None):
    return SimpleNamespace(
        chunk="park", jog_path=[], played=[], queue=[], retreat_frames=[],
        target=[22.2, 8.77, 5.54, 23.91, -24.69, target_grip],
        fault=None, holding=holding, pace_floor=0.0, paced=0, pace_last=None, trend=[],
        pitch_hold=0.0, sway_peak={}, speed_low=1.0, human_hold_latched=False,
        robot=None, policy_playback=None, jaw_gate=None, _trailing_jaw_gate=None,
        pending=[], grip_from=None, _release_until=release_until, _release_floor=None,
        _held_jaw=None, _stop_after_park=None, _stopped=False, home_since=None,
        signals=[], last_input=0.0, clock=lambda: 0.0, report=lambda **_kw: None,
    )


def test_hold_runner_freezes_unheld_obstructed_gripper_target():
    runner = _dummy_runner(holding=False, target_grip=48.8, release_until=None)
    hold_runner(runner, [22.2, 9.21, 5.54, 23.91, -24.64, 53.75], "human hold", human=True, empty_margin=2.0)
    assert runner.target[:5] == [22.2, 9.21, 5.54, 23.91, -24.64]
    assert runner.target[5] == pytest.approx(53.75)
    assert runner.holding is False and runner.human_hold_latched is True


@pytest.mark.parametrize("holding,release_until,human", [
    (True, None, True),
    (False, 75.0, True),
    (False, None, False),
])
def test_hold_runner_preserves_gripper_target_for_payload_release_or_soft_contact(holding, release_until, human):
    runner = _dummy_runner(holding=holding, target_grip=48.8, release_until=release_until)
    hold_runner(runner, [22.2, 9.21, 5.54, 23.91, -24.64, 53.75], "contact", human=human, empty_margin=2.0)
    assert runner.target[5] == pytest.approx(48.8)


def test_session_wrappers_allow_chunk_override_and_have_lf_endings():
    wrappers = OMX / "session-wrappers"
    expectations = {
        "with-session-arm-a-par.sh": (
            'ROSY_SESSION_CHUNKS:-chunks-topdown-guard-arma-closed49-20261103.json',
            "rosy-omx-observer@arm_a.service",
        ),
        "with-session-arm-b-par.sh": (
            'ROSY_SESSION_CHUNKS:-chunks-topdown-guard-armb-v21.json',
            "rosy-omx-observer@arm_b.service",
        ),
    }
    for name, (chunk_expr, observer_unit) in expectations.items():
        raw = (wrappers / name).read_bytes()
        assert b"\r" not in raw, f"{name} must use LF line endings"
        text = raw.decode("utf-8")
        assert chunk_expr in text
        assert f"systemctl --user is-active --quiet {observer_unit}" in text
        assert "sleep 0.2" in text


def test_retreat_refuses_authorize_load_unsettled_command_mismatch_and_post_droop(tmp_path):
    # 1. authorize ValueError fails closed to human-hold without calling park
    cell_auth = _RetreatCell()
    rows_auth = []

    def bad_auth(_lib, status, seq, *, check_home=True):
        if len(rows_auth) > 3 and seq == ("run policy", "park"):
            raise ValueError("retreat not reviewed")
        if any(r.get("command") == "run policy" for r in rows_auth):
            raise ValueError("retreat not reviewed")
        return {"session_id": "s1", "library_sha256": "h1"}

    bad_auth.supports_check_home = True
    res_auth = drive.run_episode(
        cell_auth,
        _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16]),
        _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=rows_auth.append, kin=_FakeKin(), authorize=bad_auth, paced_chunks=True, n_action=4,
    )
    assert res_auth["parked"] is False and cell_auth.commands[-1] == "human-hold"
    assert not any(c.endswith("park") for c in cell_auth.commands)
    assert any(r.get("command") == "retreat_jaw_zone" and r.get("ok") is False for r in rows_auth)

    # 2. run policy returning ok=True, settled=False fails closed AND logs ok=False
    cell_uns = _RetreatCell(run_replies=[
        {"ok": True, "settled": True, "state": list(PICK_ZONE)},
        {"ok": True, "settled": False, "state": list(PICK_ZONE), "error": "did not settle"},
    ])
    rows_uns = []
    res_uns = drive.run_episode(
        cell_uns,
        _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16]),
        _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=rows_uns.append, kin=_FakeKin(), paced_chunks=True, n_action=4,
    )
    assert res_uns["parked"] is False and cell_uns.commands[-1] == "human-hold"
    ret_uns = [r for r in rows_uns if r.get("command") == "retreat_jaw_zone"]
    assert ret_uns and ret_uns[-1]["ok"] is False

    # 3. Mismatched command echo on run policy fails closed
    cell_mis = _RetreatCell(run_replies=[
        {"ok": True, "settled": True, "state": list(PICK_ZONE)},
        {"command": "state", "ok": True, "settled": True, "state": [0.0, -50.0, 2.0, 55.0, -14.0, 60.0]},
    ])
    res_mis = drive.run_episode(
        cell_mis,
        _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16]),
        _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=lambda _r: None, kin=_FakeKin(), paced_chunks=True, n_action=4,
    )
    assert res_mis["parked"] is False and cell_mis.commands[-1] == "human-hold"

    # 4. Post-retreat droop: settled=True with state STILL inside jaw_spec refuses park and holds
    cell_droop = _RetreatCell(run_replies=[
        {"ok": True, "settled": True, "state": list(PICK_ZONE)},
        {"ok": True, "settled": True, "state": list(PICK_ZONE)},
    ])
    res_droop = drive.run_episode(
        cell_droop,
        _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16]),
        _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2,
        dry_run=False, log=lambda _r: None, kin=_FakeKin(), paced_chunks=True, n_action=4,
    )
    assert res_droop["parked"] is False and cell_droop.commands[-1] == "human-hold"
    assert not any(c.endswith("park") for c in cell_droop.commands)


def test_retreat_frames_preserve_pitch_with_real_omx_kinematics_and_strip_playback(tmp_path):
    from cell_policy_retreat import retreat_from_jaw_zone, retreat_from_jaw_zone_frames
    from grasp_planner import load_kinematics
    from omx_adapter.kinematics import TopDownPose, IkLimits

    kin = load_kinematics(None, 0.0740)[0]
    from omx_adapter.contracts.kinematic_types import IK_OK
    lim = IkLimits(
        position_limits={
            "joint1": (-2.6, 2.6), "joint2": (-2.6, 2.6), "joint3": (-2.6, 2.6),
            "joint4": (-2.6, 2.6), "joint5": (-2.6, 2.6),
        },
        workspace_min_m=(-0.4, -0.4, -0.1), workspace_max_m=(0.4, 0.4, 0.5),
        singularity_radius_m=0.02,
    )
    ik = kin.solve_top_down(TopDownPose(0.15, 0.08, 0.02, 0.0), lim)
    assert ik.ok and ik.reason == IK_OK
    from cell_control_core import rad_to_norm

    cur = [rad_to_norm(v) for v in ik.joints] + [54.0]
    low = [min(c, h) - 25.0 for c, h in zip(cur, HOME)]
    high = [max(c, h) + 25.0 for c, h in zip(cur, HOME)]
    jaw_spec = {
        "x": 0.15, "y": 0.08, "z_m": 0.06, "yaw_deg": 0.0,
        "xy_radius_m": 0.08, "tol_deg": 35.0, "max_tilt_rad": 0.45,
    }
    frames = retreat_from_jaw_zone_frames(cur, 60.0, low, high, 0.1667, kin, jaw_spec, home_pose=HOME)
    end_fk = kin.fk([norm_to_rad(v) for v in frames[-1][:5]])
    assert end_fk.z > jaw_spec["z_m"] + 0.015
    assert end_fk.tool_down_error_rad <= 0.15  # wrist pitch compensation kept tool near top-down

    # Stale policy_playback key is stripped before writing retreat_lib
    class _CheckPlaybackCell:
        def __init__(self):
            self.state = list(cur)
            self.libs = []

        def act(self, cmd: str):
            if cmd == "state":
                return {"ok": True, "state": list(self.state), "target": list(self.state), "holding": False}
            if cmd.startswith("load "):
                self.libs.append(json.loads(Path(cmd[5:]).read_text(encoding="utf-8")))
                return {"command": cmd, "ok": True, "settled": True, "state": list(self.state)}
            if cmd == "run policy":
                self.state = list(self.libs[-1]["chunks"]["policy"][-1])
                return {"command": "run policy", "ok": True, "settled": True, "state": list(self.state)}
            raise AssertionError(cmd)

    stale_lib = {**GRASP_LIB, "policy_playback": {"start": 0.0, "observed": 0.0, "max_age": 0.5}}
    ok, _prefix, row = retreat_from_jaw_zone(
        _CheckPlaybackCell(), stale_lib, tmp_path, cmd_prefix="", open_g=60.0, low=low, high=high,
        fastest=0.1667, kin=kin, jaw_spec=jaw_spec, resolved_tcp=0.0740, authorize=None,
    )
    assert ok is True and row is not None and row["ok"] is True


def test_paced_retreat_log_oserror_does_not_corrupt_safety_done(tmp_path):
    cell = _RetreatCell(retreat_contact=True)
    pol = _PacedSeqPolicy([[PICK_ZONE] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 54.0]] * 16])
    seen_logs = []

    def flaky_log(entry):
        seen_logs.append(entry)
        if entry.get("command") == "retreat_jaw_zone" and entry.get("ok") is False:
            raise OSError("disk full")

    low_reach = {**GRASP_LIB, "chunks": {**GRASP_LIB["chunks"], "reach": [[38.8, -10.0, 2.0, 55.0, -14.0, 49.0], [38.8, -5.0, 2.0, 55.0, -14.0, 60.0]]}}
    lib_p = tmp_path / "lib.json"
    lib_p.write_text(json.dumps(low_reach), encoding="utf-8")
    with pytest.raises(OSError):
        drive.run_episode(
            cell, pol, lib_p, tmp_path, offset=[0.0] * 6, max_chunks=2,
            dry_run=False, log=flaky_log, kin=_FakeKin(), paced_chunks=True, n_action=4,
        )
    # _hold_and_log ran AFTER try/except, so best-effort redundant hold should only run once if safety_done wasn't set
    assert "human-hold" in cell.commands and not any(c.endswith("park") for c in cell.commands)


def test_partial_target_act_grasp_sets_holding_and_paced_abort_holds_instead_of_parking(tmp_path):
    from chunk_runner_settle import check_chunk_settled

    runner = _dummy_runner(holding=False, target_grip=52.8)
    runner.chunk, runner.jitter, runner.paced_ticks, runner.peak_lag = "policy", {"shaking": False}, 0, 0.0
    runner.library = {"fps": 30, "gripper_closed": 48.8, "chunks": {"home": [[0.0] * 6]}}
    runner.fps, runner.over_ticks, runner.damped_ticks = 30, 0, 0
    runner.last_grip, runner.last_body, runner.settle_since = 54.04, [20.78, 5.15, 3.0, 43.59, -29.18], 0.0
    runner.read_health = lambda: {"pwm": [15, -258, -168, 20, -23, -101], "current_ma": [0, 0, 0, 0, 0, 110]}
    runner.report = lambda **kw: reported.append(kw)
    reported = []
    check_chunk_settled(runner, [20.78, 5.15, 3.0, 43.59, -29.18, 54.04], 0.5, 1.0, lambda _n, d: d)
    assert runner.holding is True and reported[0]["holding"] is True and reported[0]["gripper_current_ma"] == 110

    cell = _RetreatCell(run_replies=[{"ok": True, "settled": True, "holding": False, "state": [38.8, -10.0, 2.0, 55.0, -14.0, 54.0],
                                      "target": [38.8, -10.0, 2.0, 55.0, -14.0, 52.8], "health": {"pwm": [0, 0, 0, 0, 0, -101], "current_ma": [0, 0, 0, 0, 0, 110]}}])
    # Chunk 1 fails shaping/envelope after Chunk 0 picked with closing PWM -101 and lag -> must human-hold, NEVER retreat/park
    res = drive.run_episode(
        cell, _PacedSeqPolicy([[[38.8, -10.0, 2.0, 55.0, -14.0, 52.8]] * 16, [[99.0, -10.0, 2.0, 55.0, -14.0, 52.8]] * 16]),
        _write_lib(tmp_path), tmp_path, offset=[0.0] * 6, max_chunks=2, dry_run=False, log=lambda _r: None,
        kin=_FakeKin(), paced_chunks=True, n_action=4,
    )
    assert res["result"] == "refused" and res["parked"] is False and cell.commands[-1] == "human-hold"
    assert not any(c.endswith("park") for c in cell.commands)


def test_stop_fold_preserves_partial_target_held_gripper_instead_of_squeezing_closed():
    from chunk_runner_commands import dispatch_runner_command

    runner = _dummy_runner(holding=True, target_grip=52.8)
    runner.chunk, runner.fps = None, 30
    runner.params = {}
    runner.operating_context = {"scope": "hardware"}
    runner.robot = SimpleNamespace(motion=SimpleNamespace(held=set()))
    runner.present = lambda: [20.4, 12.6, 6.6, 30.8, -29.0, 54.0]
    runner.library = {"fps": 30, "gripper_closed": 48.8, "chunks": {"home": [[0.8, -62.2, 53.1, 51.6, 45.2, 48.8]]}}
    assert dispatch_runner_command(runner, "stop fold") is True
    assert runner.queue and all(f[5] == pytest.approx(52.8) for f in runner.queue)

