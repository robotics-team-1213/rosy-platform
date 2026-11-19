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


def test_camera_invariant_top_belt_and_occlusion_gate():
    import cv2
    import cell_camera_invariant as cci
    import cell_grasp_judges as cgj

    # 1. Arm occlusion gate: rejects belt discovery when arm is extended over belt if require_arm_clear=True
    assert cci.is_arm_clear_of_belt([0.0, -27.0, 18.0, 46.0, -5.0, 58.1]) is True
    assert cci.is_arm_clear_of_belt([0.0, -58.0, 50.0, 50.0, -5.0, 58.1]) is True
    assert cci.is_arm_clear_of_belt([-8.9, -14.7, 22.8, 42.0, 38.3, 54.1]) is False

    # 2. Synthetic top frame with tilted conveyor belt (12 deg tilt) + glare-shifted red-orange container (H=175)
    #    + yellow table glare (H=26, low Lab a*) + off-belt floor container
    top = np.full((480, 640, 3), (150, 150, 145), dtype=np.uint8)
    # Yellow worktable region (BGR ~ (90, 210, 220) -> Hue ~ 26, low redness)
    top[220:470, 220:550] = (95, 210, 220)

    # Draw tilted dark conveyor belt strip centered at (430, 100), length=340, width=110, angle=12 deg
    belt_rect = ((430.0, 100.0), (340.0, 110.0), 12.0)
    belt_pts = np.int32(cv2.boxPoints(belt_rect))
    cv2.fillConvexPoly(top, belt_pts, (42, 42, 40))

    # Draw glare-shifted red-orange container on the belt at (360, 85), size (75, 26), angle=12 deg
    # BGR=(35, 45, 235) has HSV Hue ~ 178 (wraparound red-orange) and high Lab a*
    c_rect = ((360.0, 85.0), (75.0, 26.0), 12.0)
    c_pts = np.int32(cv2.boxPoints(c_rect))
    cv2.fillConvexPoly(top, c_pts, (35, 45, 235))

    # Draw a knocked-off container on the floor at (140, 310)
    f_rect = ((140.0, 310.0), (80.0, 28.0), -35.0)
    cv2.fillConvexPoly(top, np.int32(cv2.boxPoints(f_rect)), (25, 95, 240))

    blocked = cci.detect_top_containers_invariant(
        top,
        joint_state_norm=[-8.9, -14.7, 22.8, 42.0, 38.3, 54.1],
        require_arm_clear=True,
    )
    assert blocked["found"] is False and blocked["verdict"] == "arm_occluding_belt"

    inv = cci.detect_top_containers_invariant(
        top,
        joint_state_norm=[0.0, -27.0, 18.0, 46.0, -5.0, 58.1],
        require_arm_clear=True,
    )
    assert inv["found"] is True
    assert inv["belt_frame"]["found"] is True
    assert abs(inv["belt_frame"]["angle_deg"] - 12.0) <= 4.0
    assert len(inv["containers"]) == 1
    assert len(inv["floor_containers"]) == 1
    c0 = inv["containers"][0]
    assert 0.15 <= c0["u_along_belt"] <= 0.45
    assert 0.25 <= c0["v_across_belt"] <= 0.75
    assert abs(c0["yaw_rel_belt_deg"]) <= 6.0

    # Verify pre_grasp_scene_judge with camera_invariant=True recovers even when fixed slot_rois miss completely!
    broken_rois = {"b_far": (520, 200, 620, 260), "b_shifted": (280, 200, 380, 260)}
    scene_res = cgj.pre_grasp_scene_judge(
        top,
        broken_rois,
        "b_far",
        camera_invariant=True,
    )
    assert scene_res["verdict"] in ("retarget_slot", "proceed")
    assert scene_res["centroid_px"] is not None
    assert abs(scene_res["centroid_px"][0] - 360.0) <= 6.0


def test_wrist_fingers_anchor_pca_continuity_and_border_clip_gate():
    import cv2
    import cell_camera_invariant as cci

    # 1. Verify PCA major-axis angle continuity across -90, 0, +90 deg without minAreaRect 90-deg axis-swap jumps
    for true_deg in (-75.0, -30.0, 0.0, 35.0, 80.0):
        canvas = np.zeros((300, 300), dtype=np.uint8)
        rect = ((150.0, 150.0), (140.0, 42.0), true_deg)
        cv2.fillConvexPoly(canvas, np.int32(cv2.boxPoints(rect)), 255)
        ys, xs = np.where(canvas > 0)
        est_deg, _, _, aspect = cci.pca_major_axis_angle_deg(np.column_stack([xs, ys]))
        expected_deg = true_deg if true_deg >= 0 else true_deg + 180.0
        err = cci.wrap_half_turn_deg(est_deg - expected_deg)
        assert abs(err) <= 3.0
        assert aspect >= 2.5

    # 2. Synthetic wrist frame with white 3D-printed fingers tilted by +8 deg + unclipped skewed container
    wrist = np.full((480, 640, 3), (60, 60, 60), dtype=np.uint8)
    # Left white finger at (170, 390), right white finger at (470, 432) -> finger closing angle ~ +8 deg
    cv2.fillConvexPoly(wrist, np.array([[90, 340], [210, 340], [215, 479], [85, 479]], np.int32), (235, 235, 235))
    cv2.fillConvexPoly(wrist, np.array([[430, 382], [550, 382], [555, 479], [425, 479]], np.int32), (235, 235, 235))

    anchor = cci.detect_wrist_fingers_anchor(wrist, finger_color="white")
    assert anchor["found"] is True
    assert 310.0 <= anchor["finger_mid_x"] <= 330.0
    assert 4.0 <= anchor["finger_angle_deg"] <= 12.0

    # Add unclipped orange container centered at (355, 220), major=280px, minor=110px, tilted 28 deg from vertical
    # (major axis at 90 + 28 = 118 deg)
    c_rect = ((355.0, 220.0), (280.0, 110.0), 118.0)
    cv2.fillConvexPoly(wrist, np.int32(cv2.boxPoints(c_rect)), (25, 95, 240))
    obb = cci.detect_wrist_container_obb(wrist, anchor)
    assert obb["found"] is True
    assert obb["clipped_border"] is False
    assert obb["roll_reliable"] is True
    assert abs(obb["delta_wrist_roll_deg"]) >= 12.0
    assert 0.22 <= obb["mm_per_px"] <= 0.25

    # 3. Border-clipped container (x_max >= 638) -> freezes delta_wrist_roll_deg == 0.0 (translate first!)
    wrist_clipped = np.full((480, 640, 3), (60, 60, 60), dtype=np.uint8)
    cv2.rectangle(wrist_clipped, (520, 140), (639, 340), (25, 95, 240), thickness=-1)
    obb_clip = cci.detect_wrist_container_obb(wrist_clipped, anchor)
    assert obb_clip["found"] is True
    assert obb_clip["clipped_border"] is True
    assert obb_clip["roll_reliable"] is False
    assert obb_clip["delta_wrist_roll_deg"] == 0.0
    assert obb_clip["along_mm"] > 10.0


def test_broyden_ibvs_camera_rotation_convergence_and_strain_safe_roll():
    import math
    import cell_camera_invariant as cci

    # Suppose the physical wrist camera is twisted by +25 deg relative to nominal kinematic closing_rad=0
    state = cci.init_wrist_jacobian(minor_axis_px=250.0, shoulder_pan_rad=0.0, wrist_roll_rad=0.0)
    true_rot = math.radians(25.0)
    c, s = math.cos(true_rot), math.sin(true_rot)
    j_true = 1.15 * (np.array([[c, -s], [s, c]]) @ state.j_0)

    # 1. Sub-threshold step (< 3.0 mm) and outlier contact kick (> 40.0 mm) are rejected
    j_before = state.j_hat.copy()
    cci.update_broyden_jacobian(state, [1.2, 0.5], [10.0, 5.0])
    assert state.last_update_status == "rejected_step_norm"
    assert np.allclose(state.j_hat, j_before)

    cci.update_broyden_jacobian(state, [45.0, 20.0], [300.0, 100.0])
    assert state.last_update_status == "rejected_step_norm"

    # 2. Adversarial observation trying to rotate by 75 deg and scale by 3.0x is clamped to <= 35 deg and <= 1.6x
    adv_rot = math.radians(75.0)
    ca, sa = math.cos(adv_rot), math.sin(adv_rot)
    dp_valid = np.array([8.0, 0.0])
    de_adv = 3.0 * (np.array([[ca, -sa], [sa, ca]]) @ (state.j_0 @ dp_valid))
    cci.update_broyden_jacobian(state, dp_valid, de_adv)
    rel = state.j_hat @ np.linalg.inv(state.j_0)
    u_svd, s_svd, vt_svd = np.linalg.svd(rel)
    r_pol = u_svd @ vt_svd
    phi_est = abs(math.degrees(math.atan2(r_pol[1, 0], r_pol[0, 0])))
    assert phi_est <= 35.01
    assert float(np.mean(s_svd)) <= 1.601

    # 3. Closed-loop IBVS simulation under +25 deg camera mount rotation: converges within 3 steps
    #    and never exceeds MAX_WRIST_ROLL_STEP_RAD (0.045 rad)
    state2 = cci.init_wrist_jacobian(minor_axis_px=250.0, shoulder_pan_rad=0.0, wrist_roll_rad=0.0)
    e_px = np.array([65.0, -40.0], dtype=np.float64)
    ang_deg = 125.0  # 35 deg error from 90 deg vertical
    for _ in range(4):
        cmd = cci.compute_ibvs_step(state2, e_px, ang_deg, max_step_mm=12.0)
        assert abs(cmd["dq5_rad"]) <= cci.MAX_WRIST_ROLL_STEP_RAD + 1e-6
        dp = np.array([cmd["dx_mm"], cmd["dy_mm"]])
        e_px = e_px + j_true @ dp
        ang_deg = ang_deg - math.degrees(cmd["dq5_rad"])
    assert float(np.hypot(e_px[0], e_px[1])) < 12.0

    # 4. Online Eye-to-Hand top extrinsic calibrator updates datum offset and rejects >45mm outliers
    cal = cci.TopExtrinsicCalibrator(
        affine_2x2=np.array([[0.0, -0.0007], [-0.00095, 0.0]]),
        offset_xy=np.array([0.175, 0.373]),
    )
    r_out = cci.update_top_extrinsic_offset(cal, [400.0, 75.0], [0.250, -0.007])
    assert r_out["updated"] is False and r_out["reason"] == "outlier_rejected"
    r_in = cci.update_top_extrinsic_offset(cal, [400.0, 75.0], [0.132, -0.015])
    assert r_in["updated"] is True


def test_multi_arm_a_b_s_camera_invariant_depth_and_remount_self_healing():
    import math
    import cv2
    import cell_camera_invariant as cci
    import cell_fingers
    import cell_realignment_pipeline as crp

    # 1. Per-arm wrist camera & finger configuration for arm_a, arm_b, and arm_s
    cfg_a = cci.resolve_wrist_camera_mount_config("arm_a")
    cfg_b = cci.resolve_wrist_camera_mount_config("arm_b")
    cfg_s = cci.resolve_wrist_camera_mount_config("arm_s")
    assert cfg_a["finger_color"] == "white" and cfg_a["gap_mm"] == 44.0 and cfg_a["sign_along"] == -1.0
    assert cfg_b["finger_color"] == "white" and cfg_b["gap_mm"] == 44.0 and cfg_b["sign_along"] == -1.0
    assert cfg_s["finger_color"] == "dark" and cfg_s["gap_mm"] == 36.0 and cfg_s["sign_along"] == 1.0

    # 2. Monocular container depth & pick-Z estimator distinguishes floor/worktable vs elevated conveyor belt
    z_floor = cci.estimate_container_z_from_wrist_obb(
        {"found": True, "minor_axis_px": 240.0, "eff_minor_axis_px": 240.0},
        z_hover_m=0.086,
        x_cur_m=0.110,
    )
    assert z_floor["valid"] is True
    assert z_floor["surface_class"] == "floor_or_worktable"
    assert 0.005 <= z_floor["z_pick_m"] <= 0.018
    assert z_floor["recommended_x_m"] == 0.116  # prevents elbow_flex saturation at low z near base

    z_belt = cci.estimate_container_z_from_wrist_obb(
        {"found": True, "minor_axis_px": 310.0, "eff_minor_axis_px": 310.0},
        z_hover_m=0.088,
        x_cur_m=0.130,
    )
    assert z_belt["valid"] is True
    assert z_belt["surface_class"] == "conveyor_belt_or_tier1"
    assert 0.040 <= z_belt["z_pick_m"] <= 0.056

    # 3. Online 180-deg remounted camera self-healing (allow_remount_snap=True on divergence)
    state_ab = cci.init_wrist_jacobian(minor_axis_px=260.0, shoulder_pan_rad=0.0, wrist_roll_rad=0.0, arm_id="arm_a")
    # Simulate a wrist camera mounted 180 deg upside-down relative to nominal J_0
    j_flipped = -1.0 * state_ab.j_0
    e_px = np.array([50.0, -30.0], dtype=np.float64)
    # Step 0 moves in the wrong direction because camera is 180-deg flipped; Step 1 detects divergence and snaps SO(2)!
    for _ in range(5):
        cmd = cci.compute_ibvs_step(state_ab, e_px, 90.0, max_step_mm=10.0, allow_remount_snap=True)
        dp = np.array([cmd["dx_mm"], cmd["dy_mm"]])
        e_px = e_px + j_flipped @ dp
    assert float(np.hypot(e_px[0], e_px[1])) < 12.0

    # 4. Unified cell_fingers.resolve_wrist_servo_offset and cell_realignment_pipeline.estimate_wrist_object_pose_2d
    wrist_img = np.full((480, 640, 3), (45, 45, 45), dtype=np.uint8)
    # White v2.1 fingers for arm_a / arm_b
    cv2.fillConvexPoly(wrist_img, np.array([[95, 340], [215, 340], [215, 479], [95, 479]], np.int32), (235, 235, 235))
    cv2.fillConvexPoly(wrist_img, np.array([[425, 340], [545, 340], [545, 479], [425, 479]], np.int32), (235, 235, 235))
    # Orange container on dark belt (no bright neutral surface around it!) tilted by 15 deg
    c_rect = ((345.0, 225.0), (260.0, 115.0), 105.0)
    cv2.fillConvexPoly(wrist_img, np.int32(cv2.boxPoints(c_rect)), (25, 95, 240))

    f_res = cell_fingers.resolve_wrist_servo_offset(wrist_img, {"finger_color": "white"}, structural_fallback=False)
    assert f_res["found"] is True
    assert "delta_wrist_roll_deg" in f_res
    assert abs(f_res["delta_wrist_roll_deg"] - 15.0) <= 5.0

    r2s_pkt = cci.compute_r2s_s2r_sync_packet(
        arm_id="arm_a",
        top_img=None,
        wrist_img=wrist_img,
        q_real_norm=[0.0, -27.0, 18.0, 46.0, -5.0, 58.0],
        q_sim_norm=[0.2, -26.8, 18.1, 45.9, -5.0, 58.0],
    )
    assert r2s_pkt["r2s_synced"] is True
    assert r2s_pkt["wrist_obb"]["found"] is True
    assert r2s_pkt["ibvs_cmd"] is not None



