"""cell_grasp_debate: multi-model consistency debate and post-grasp put-back (release_pick / reinsert_pick)."""
import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
ROOT = Path(__file__).resolve().parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    import cell_grasp_debate as cgd
    import grasp_planner as gp
finally:
    sys.path.remove(str(OMX))

PLAN = json.loads((OMX / "grasp-plan.example.json").read_text())


def test_planner_generates_release_pick_and_reinsert_pick_with_grip_release():
    plan = dict(PLAN, grip_open=56.58, grip_release=56.10, grip_closed=48.8)
    planner = gp.Planner(plan)
    lib = planner.library()
    assert "release_pick" in lib["chunks"] and "reinsert_pick" in lib["chunks"]
    rel = lib["chunks"]["release_pick"]
    reins = lib["chunks"]["reinsert_pick"]
    # release_pick starts closed at pick.z, opens to grip_release (56.10), and lifts to lifted
    assert rel[0][5] == pytest.approx(48.8, abs=0.2)
    assert rel[-1][5] == pytest.approx(56.10, abs=0.05)
    assert rel[-1][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    # reinsert_pick starts at lifted with grip_closed (48.8), lowers to pick.z, opens to 56.10, and lifts back up
    assert reins[0][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    assert reins[0][5] == pytest.approx(48.8, abs=0.05)
    assert reins[-1][:5] == pytest.approx(lib["chunks"]["lift_pick"][-1][:5], abs=0.05)
    assert reins[-1][5] == pytest.approx(56.10, abs=0.05)


def test_telemetry_judge_distinguishes_shallow_corner_pinch_stable_grasp_and_diagonal_wedge():
    params = {"gripper.held_30mm": 55.7, "grasp.shallow_tol_units": 1.2, "grasp.wedged_tol_units": 0.7}
    # Trial 4 shallow corner pinch (52.4 < 54.5)
    shallow = cgd.telemetry_judge([0, 0, 0, 0, 0, 52.4], True, params)
    assert shallow["verdict"] == "reinsert" and shallow["class"] == "unstable_shallow"
    # Trial 8 centered grasp (55.4 within 54.5..56.4)
    stable = cgd.telemetry_judge([0, 0, 0, 0, 0, 55.4], True, params)
    assert stable["verdict"] == "proceed" and stable["class"] == "stable"
    # Diagonal rim wedge (56.6 > 56.4)
    wedged = cgd.telemetry_judge([0, 0, 0, 0, 0, 56.6], True, params)
    assert wedged["verdict"] == "reinsert" and wedged["class"] == "unstable_wedged"
    # Slipping grasp: jaw within band (55.1) but squeeze current (85 mA) below min_stable_current_ma (140 mA)
    params_cur = dict(params, **{"grasp.min_stable_current_ma": 140})
    slipping = cgd.telemetry_judge([0, 0, 0, 0, 0, 55.1], True, params_cur, current_ma=85.0)
    assert slipping["verdict"] == "reinsert" and slipping["class"] == "unstable_slipping"



def test_multi_model_debate_enforces_safety_invariant_and_chooses_reinsert_pick():
    telemetry = {"verdict": "reinsert", "class": "unstable_shallow", "jaw_units": 52.4, "error_units": -3.3, "reason": "shallow"}
    vision = {"verdict": "reinsert", "class": "unstable_skewed", "found": True, "along_mm": -6.6, "dx_mm": 5.61, "dy_mm": 0.0, "reason": "skewed"}

    # Even if Critic mistakenly says 'proceed', safety invariant overrides to 'reinsert_and_retry', and Arbiter refines dx_mm
    def critic(prompt, images, schema):
        return {"verdict": "proceed", "dx_mm": 5.6, "dy_mm": 0.0, "reason": "critic tried proceed"}

    def arbiter(prompt, images, schema):
        return {"verdict": "reinsert_and_retry", "dx_mm": 5.8, "dy_mm": -0.2, "reason": "arbiter confirmed reinsert + shift"}

    out = cgd.debate_and_decide("run lift_pick", telemetry, vision, reinsert_count=0, max_reinsert=1, models=[critic, arbiter])
    assert out["verdict"] == "reinsert_and_retry"
    assert out["recovery_chunk"] == "run reinsert_pick"
    assert (out["dx_mm"], out["dy_mm"]) == (5.8, -0.2)
    assert len(out["debate"]) == 2 and out["debate"][0]["verdict"] == "reinsert_and_retry"


def test_hook_executes_reinsert_pick_replans_and_retries_on_unstable_lift(tmp_path):
    commands = []
    states = [
        [0, 0, 0, 0, 0, 52.4],  # first lift_pick is shallow (52.4)
        [0, 0, 0, 0, 0, 55.6],  # after reinsert_pick + replan, second lift_pick is stable (55.6)
    ]

    class FakeCell:
        def act(self, cmd):
            commands.append(cmd)
            st = states[-1] if len(commands) >= 4 else states[0]
            return {"ok": True, "holding": True, "state": st}

        def frame(self, cam):
            return None

    cfg = {
        "work_dir": str(tmp_path),
        "arm_id": "arm_b",
        "params": {"gripper.held_30mm": 55.7, "grasp.shallow_tol_units": 1.2, "grasp.wedged_tol_units": 0.7, "grasp.max_reinsert": 1},
        "wrist": {"camera": "wrist", "hsv_min": [0, 60, 120], "hsv_max": [179, 255, 255]},
    }
    target = {"pick": {"x": 0.1650, "y": -0.1020, "z": 0.0074, "yaw_deg": -90.0}, "place": {"x": 0.1280, "y": -0.0120, "z": 0.0398, "yaw_deg": -90.0}}
    chk = cgd.hook(cfg, FakeCell(), target, lambda c, pk, pl, p: p, 34.4)
    res = chk("run lift_pick", {"ok": True, "holding": True, "state": states[0]}, FakeCell().act)
    assert res["schema_version"] == 2
    assert res["verdict"] == "reinsert_and_retry" and res["put_back_ok"] is True
    assert commands[0] == "run reinsert_pick"
    assert commands[1].startswith("load ") and commands[2:] == ["goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick"]
    assert target["pick"]["x"] != 0.1650
    # Default glm_backend points to glm-5.3 via judge_seat.openai_chat
    assert cgd.glm_backend().__name__ == "zai:glm-5.3"


def test_three_agent_council_deliberates_partial_grasp_and_post_lift_slip():
    params = {
        "gripper.held_30mm": 54.3,
        "gripper.closed": 48.8,
        "gripper.open": 57.85,
        "grasp.shallow_tol_units": 1.2,
        "grasp.wedged_tol_units": 0.7,
        "grasp.max_skew_mm": 4.0,
        "grasp.max_across_skew_mm": 7.5,
        "grasp.min_bite_ratio": 0.42,
    }
    # 1. Partial edge bite: static jaw width is 54.2 (nominal 30mm), but wrist vision sees shallow/edge bite
    t_ok = cgd.telemetry_judge([0, 0, 0, 0, 0, 54.2], True, params, current_ma=135.0)
    assert t_ok["verdict"] == "proceed"
    v_partial = {
        "verdict": "reinsert",
        "class": "unstable_partial_bite",
        "found": True,
        "along_mm": 2.0,
        "across_mm": 9.8,
        "bite_ratio": 0.34,
        "dx_mm": -3.2,
        "dy_mm": 5.4,
        "dz_mm": -2.2,
        "reason": "partial edge bite",
    }
    k_ok = cgd.kinesthetic_judge({"ok": True, "holding": True, "state": [0, 0, 0, 0, 0, 54.2], "gripper_current_ma": 135.0}, params=params)
    d_edge = cgd.debate_and_decide("run grasp_pick", t_ok, v_partial, kinesthetic=k_ok, reinsert_count=0, max_reinsert=2)
    assert d_edge["verdict"] == "reinsert_and_retry"
    assert d_edge["recovery_chunk"] == "run release_pick"
    assert (d_edge["dx_mm"], d_edge["dy_mm"], d_edge["dz_mm"]) == (-3.2, 5.4, -2.2)
    assert [r["role"] for r in d_edge["council_debate"]] == ["proposal", "critique", "arbiter"]

    # 2. Post-lift fingertip slip: telemetry and vision looked ok at grasp, but lifting caused dq_lift = -1.35u partial slip
    r_grasp = {"ok": True, "holding": True, "state": [0, 0, 0, 0, 0, 53.35], "gripper_current_ma": 115.0}
    r_lift = {"ok": True, "holding": True, "state": [0, 0, 0, 0, 0, 51.95], "gripper_current_ma": 78.0}
    k_slip = cgd.kinesthetic_judge(r_grasp, r_lift=r_lift, params=params)
    assert k_slip["verdict"] == "reinsert" and k_slip["class"] == "unstable_partial_slip"
    v_skip = {"verdict": "proceed", "class": "no_frame", "found": False, "dx_mm": 0.0, "dy_mm": 0.0, "dz_mm": 0.0, "reason": "no_frame"}
    d_lift = cgd.debate_and_decide("run lift_pick", t_ok, v_skip, kinesthetic=k_slip, reinsert_count=0, max_reinsert=2)
    assert d_lift["verdict"] == "reinsert_and_retry"
    assert d_lift["recovery_chunk"] == "run reinsert_pick"
    assert d_lift["dz_mm"] <= -2.2
    assert "Override static proceed" in d_lift["council_debate"][1]["reason"]

    # 3. Longitudinal end-grab on 1x3 container (across_mm = -18.75mm) permits up to 16.0mm centroid shift in one retry
    v_end_grab = {
        "verdict": "reinsert",
        "class": "unstable_partial_bite",
        "found": True,
        "along_mm": 4.5,
        "across_mm": -18.75,
        "bite_ratio": 0.36,
        "dx_mm": -13.4,
        "dy_mm": 4.2,
        "dz_mm": -2.2,
        "reason": "longitudinal end grab",
    }
    d_end = cgd.debate_and_decide("run grasp_pick", t_ok, v_end_grab, kinesthetic=k_ok, reinsert_count=0, max_reinsert=2)
    assert d_end["verdict"] == "reinsert_and_retry"
    assert d_end["dx_mm"] == -13.4 and d_end["dy_mm"] == 4.2

    # 4. Fast release_pick and reinsert_pick execution speed check (down from >650 / >900 frames at 0.18x guard)
    plan = dict(PLAN, grip_open=56.58, grip_release=56.10, grip_closed=48.8, grip_s=0.50, settle_s=0.25)
    lib = gp.Planner(plan).library()
    assert len(lib["chunks"]["release_pick"]) <= 240
    assert len(lib["chunks"]["reinsert_pick"]) <= 380


def test_empty_air_grasp_unclosed_jaw_and_pre_grasp_scene_retargeting():
    import cv2

    params = {
        "gripper.held_30mm": 52.3,
        "gripper.closed": 48.8,
        "gripper.open": 57.2,
        "grasp.shallow_tol_units": 1.2,
        "grasp.wedged_tol_units": 0.7,
    }
    # 1. Empty air grasp (jaw = 48.82 on arm_s when Pinky/belt slot was empty) -> verdict="empty", class="empty_air_grasp"
    air = cgd.telemetry_judge([39.0, -4.13, 13.16, 40.71, -13.89, 48.82], True, params, current_ma=14.0)
    assert air["verdict"] == "empty" and air["class"] == "empty_air_grasp"
    d_air = cgd.debate_and_decide("run grasp_pick", air, {"verdict": "proceed", "class": "unseen", "found": False})
    assert d_air["verdict"] == "empty" and d_air["recovery_chunk"] is None

    # 2. Unclosed open jaw (jaw = 58.1 with low current when runner did not execute grasp) -> verdict="empty", class="unclosed_open_jaw"
    unclosed = cgd.telemetry_judge([-9.1, -16.7, 13.8, 39.2, -16.4, 58.1], True, params, current_ma=12.0)
    assert unclosed["verdict"] == "empty" and unclosed["class"] == "unclosed_open_jaw"

    # 3. Vision judge rejects grey belt + yellow housing edge texture when no orange container is in view
    belt_img = np.full((480, 640, 3), (125, 128, 128), dtype=np.uint8)
    cv2.rectangle(belt_img, (210, 30), (430, 380), (40, 215, 235), -1)  # yellow housing/sticker (B=40, G=215, R=235 -> yellow, not orange)
    v_belt = cgd.vision_judge(belt_img, ([5, 110, 110], [22, 255, 255]), 36.0, 0.0, params=params)
    assert v_belt["found"] is False and v_belt["class"] == "unseen"

    # 4. Pre-grasp scene judge detects empty requested slot and retargets to occupied belt_far slot or flags knocked-off floor stack
    top_img = np.full((480, 640, 3), (110, 110, 110), dtype=np.uint8)
    slot_rois = {
        "pinky": (140, 210, 260, 390),
        "belt_mid": (270, 120, 420, 280),
        "belt_far": (460, 120, 610, 280),
    }
    floor_roi = (10, 280, 130, 470)
    # Put an orange container at belt_far (BGR=(20, 110, 240) -> HSV=(14, 234, 240))
    cv2.rectangle(top_img, (500, 160), (570, 230), (20, 110, 240), -1)
    retarget = cgd.pre_grasp_scene_judge(top_img, slot_rois, "belt_mid", floor_roi=floor_roi)
    assert retarget["verdict"] == "retarget_slot" and retarget["retarget_slot"] == "belt_far"

    # When belt_far is also empty and containers are knocked onto the floor beside Pinky -> abort_empty_scene (knocked_off_to_floor)
    top_knocked = np.full((480, 640, 3), (110, 110, 110), dtype=np.uint8)
    cv2.rectangle(top_knocked, (30, 320), (110, 430), (20, 110, 240), -1)
    aborted = cgd.pre_grasp_scene_judge(top_knocked, slot_rois, "pinky", floor_roi=floor_roi)
    assert aborted["verdict"] == "abort_empty_scene" and aborted["class"] == "knocked_off_to_floor" and aborted["person_needed"] is True


def test_usb_recovery_pipeline_camera_symlinks_and_12v_hardfault_diagnosis(tmp_path):
    import cell_usb_recovery as cur

    v4l_dir = tmp_path / "v4l"
    v4l_dir.mkdir()
    jieli_target = v4l_dir / "usb-Jieli_Technology_USB_Composite_Device-video-index0"
    wrist_target = v4l_dir / "usb-Innomaker_Innomaker-U20CAM-720P_SN0001-video-index0"
    jieli_target.write_text("video4")
    wrist_target.write_text("video2")

    cam_res = cur.restore_camera_symlinks(v4l_dir)
    assert cam_res["ok"] is True
    assert set(cam_res["restored"]) == {"rosy-arm_s_jieli", "rosy-arm_s_wrist"}

    decoded = cur.decode_port_status(0x0103, 0x0010)
    assert decoded["connected"] is True and decoded["enabled"] is True and decoded["powered"] is True and decoded["c_reset"] is True

    # Tier 4 last-resort host reboot safety checks: blocked by policy or by active session-arm_a.lock
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    r_disabled = cur.schedule_last_resort_host_reboot(allow_host_reboot=False, lock_dir=lock_dir)
    assert r_disabled["ok"] is False and r_disabled["verdict"] == "reboot_skipped_policy_disabled"

    (lock_dir / "session-arm_a.lock").write_text("111676")
    r_blocked = cur.schedule_last_resort_host_reboot(allow_host_reboot=True, lock_dir=lock_dir)
    assert r_blocked["ok"] is False and r_blocked["verdict"] == "reboot_blocked_by_active_arm"
    assert "session-arm_a.lock" in r_blocked["active_other_locks"]

    (lock_dir / "session-arm_a.lock").unlink()
    called = []

    class _DummyRes:
        returncode = 0
        stderr = ""

    def _fake_run(cmd, **_kw):
        called.append(cmd)
        return _DummyRes()

    r_ok = cur.schedule_last_resort_host_reboot(allow_host_reboot=True, lock_dir=lock_dir, run_fn=_fake_run)
    assert r_ok["ok"] is True and r_ok["verdict"] == "host_reboot_initiated"
    assert called == [["sudo", "-n", "systemctl", "reboot"]]

    # Emergency torque OFF helper: handles offline serial gracefully and confirms torque=0 via injected bus_factory
    r_offline = cur.emergency_torque_off_arm(tmp_path / "missing-serial")
    assert r_offline["ok"] is False and r_offline["verdict"] == "port_unavailable_torque_already_unpowered_or_dropped"

    fake_serial = tmp_path / "fake-serial"
    target_tty = tmp_path / "ttyACM1"
    target_tty.write_text("tty")
    try:
        fake_serial.symlink_to(target_tty.name)
        r_tq = cur.emergency_torque_off_arm(
            fake_serial,
            bus_factory=lambda path, mids, baud: {
                "ok": True,
                "verdict": "torque_off_confirmed",
                "serial_path": path,
                "torques": {m: 0 for m in mids},
                "reason": "all follower motors confirmed torque OFF",
            },
        )
        assert r_tq["ok"] is True and r_tq["verdict"] == "torque_off_confirmed"
    except OSError:
        pass
