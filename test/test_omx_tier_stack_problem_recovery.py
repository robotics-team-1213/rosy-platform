"""Tests for the OMX 1단/2단/3단 tier-stacking problem-recovery simulation suite."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tools/sim", ROOT / "deploy/robot/omx", ROOT / "middleware/devices/omx/adapter"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import cell_problem_pipeline as cpp  # noqa: E402
import judge_seat  # noqa: E402
import omx_tier_stack_recovery_sim as rsim  # noqa: E402


def test_wrist_centering_converges_for_dark_and_white_fingers_with_hazards(tmp_path: Path):
    for arm_id, expected_color, init_mm in (("arm_s", "dark", 6.2), ("arm_a", "white", -5.8), ("arm_b", "white", -6.6)):
        res = rsim.simulate_wrist_centering_loop(arm_id, initial_offset_mm=init_mm, work_dir=tmp_path)
        assert res["finger_color"] == expected_color
        assert res["converged"] is True
        assert abs(res["final_offset_mm"]) <= 1.5
        assert (tmp_path / f"arm-cal-{arm_id}.json").exists()


def test_grasp_debate_reinsert_recovery_and_auto_calibration_across_all_three_tiers(tmp_path: Path):
    res = rsim.run_full_problem_recovery_simulation(tmp_path)
    assert res["completed"] is True
    assert res["tiers_verified"] == [1, 2, 3]
    assert res["arms_verified"] == ["arm_s", "arm_a", "arm_b"]
    for row in res["grasp_debate_reinsert_recovery"]:
        assert row["schema_version"] == 2
        assert row["attempt_1"]["verdict"] == "reinsert_and_retry"
        assert row["attempt_1"]["recovery_chunk"] == "run reinsert_pick"
        assert row["attempt_2"]["verdict"] == "proceed"
        assert row["calibration_after"]["samples"] >= 1


def test_judge_seat_from_config_accepts_shorthand_string_specs():
    fn_glm = judge_seat.from_config("glm-5.1")
    fn_ollama = judge_seat.from_config("ollama:qwen3-vl:8b")
    fn_panel = judge_seat.from_config(["glm-5.1", "ollama:qwen3-vl:8b"])
    assert callable(fn_glm)
    assert callable(fn_ollama)
    assert callable(fn_panel)


def test_real_problem_ledger_capture_and_sim_replay_verification_pipeline(tmp_path: Path):
    cfg = {"_work": tmp_path, "arm_id": "arm_b"}
    captured = cpp.capture_from_attempt(
        cfg,
        {
            "from": "pallet-l1",
            "dest": "pallet-l2",
            "result": "reinserted",
            "fail_stage": "run lift_pick",
            "why": "skewed grasp reinserted",
            "grasp_debate": {"verdict": "reinsert_and_retry", "dx_mm": 6.1, "dy_mm": 0.0},
            "wrist": {"along_mm": -6.1, "across_mm": 0.2, "finger_color": "white"},
        },
    )
    assert captured is not None
    assert captured["category"] == "unstable_grasp_reinsert"
    assert (tmp_path / "problem-cases.jsonl").exists()

    report = rsim.replay_and_verify_ledger(tmp_path)
    assert report["all_verified"] is True
    assert report["total_cases"] >= 5
    assert report["passed_cases"] == report["total_cases"]


def test_online_imitation_and_reinforcement_learning_residual_policy_loop(tmp_path: Path):
    cfg = {"_work": tmp_path, "arm_id": "arm_b"}
    # Episode 1: empty grasp at (0.1100, -0.0250, 0.0085), recovery refined to (0.1130, -0.0240, 0.0055)
    ep1 = {
        "result": "empty",
        "task_verified": False,
        "pick": {"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1100, "y": -0.0250, "z": 0.0085, "yaw_deg": -90.0},
        "place": {"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1430, "y": -0.0200, "z": 0.0390, "yaw_deg": -90.0},
        "recovery": [{"recovered_pick_xyz_m": [0.1130, -0.0240, 0.0055]}],
        "steps": [{"command": "run grasp_pick", "holding": False}],
    }
    r1 = cpp.update_il_rl_from_run(cfg, ep1)
    assert r1["reward"] == -0.5
    assert r1["il_demos"] == 1
    assert r1["bucket"] == "pallet_left"
    assert r1["residual"]["dx_m"] > 0.0
    assert r1["residual"]["dz_m"] < 0.0

    # Episode 2: apply learned IL/RL residual to a new directive in pallet_left, then succeed!
    directive = {
        "directive_id": "next-ep-col1",
        "pick": {"area": "pallet", "col": 1, "row": 1, "tier": 1, "x": 0.1100, "y": -0.0250, "z": 0.0085, "yaw_deg": -90.0},
        "place": {"area": "pallet", "col": 2, "row": 1, "tier": 2, "x": 0.1430, "y": -0.0200, "z": 0.0390, "yaw_deg": -90.0},
    }
    updated = cpp.apply_learned_il_rl_residual(cfg, directive)
    assert updated["pick"]["x"] > 0.1100
    assert updated["pick"]["z"] < 0.0085

    ep2 = {
        "result": "placed",
        "task_verified": True,
        "pick": updated["pick"],
        "place": updated["place"],
        "steps": [
            {"command": "run grasp_pick", "holding": True},
            {"command": "run release_place", "holding": False},
        ],
    }
    r2 = cpp.update_il_rl_from_run(cfg, ep2)
    assert r2["reward"] == 2.0
    assert r2["il_demos"] == 2
    assert r2["rl_episodes"] == 2


def test_cell_reach_multisample_jitter_averaging_and_feel_z_step_search(tmp_path: Path):
    import cell_feel
    import cell_reach

    class ShakyCell:
        def __init__(self):
            self.states = [
                {"ok": True, "state": [0.105, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [0.095, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": True}},
                {"ok": True, "state": [0.100, 0.0, 0.0, 0.0, 0.0, 55.0], "jitter": {"shaking": False}},
            ]

        def act(self, cmd):
            if cmd == "state":
                return self.states.pop(0)
            return {"ok": True}

    res = cell_reach.correct(
        ShakyCell(),
        (0.100, 0.0),
        lambda dx, dy: tmp_path / "r.json",
        fk=lambda s: (s[0], s[1]),
    )
    assert res["verdict"] == "pass"
    assert res["iterations"][0]["samples"] == 3
    assert res["iterations"][0]["error_mm"] == [0.0, 0.0]

    class FeelCell:
        def __init__(self):
            self.calls = []
            self.grasp_try = 0

        def act(self, cmd):
            self.calls.append(cmd)
            if cmd == "run grasp_pick":
                self.grasp_try += 1
                return {"ok": True, "holding": self.grasp_try >= 1, "state": [0, 0, 0, 0, 0, 52.3]}
            return {"ok": True, "state": [0, 0, 0, 0, 0, 55.0]}

    cfg = {
        "work_dir": str(tmp_path),
        "params": {"feel.enabled": 1, "feel.tries": 3, "feel.step_mm": 10.0, "feel.z_step_mm": 8.0, "reach.enabled": 0},
        "sites": {"ship": {"surface_z": -0.025}},
    }
    target = {"pick": {"site": "ship", "x": 0.17, "y": -0.15, "z": 0.008, "yaw_deg": 0.0}, "place": {"x": 0.14, "y": 0.12, "z": 0.02, "yaw_deg": 0.0}}
    planned_zs = []

    def write_lib(_c, pick, _place, path):
        planned_zs.append(pick["z"])
        path.write_text("{}")
        return path

    fc = FeelCell()
    hook = cell_feel.feel_hook(cfg, fc, target, write_lib)
    out = hook(fc.act)
    assert out["holding"] is True
    assert planned_zs == [0.0]  # 0.008 - 0.008 = 0.0 m Z-step tried first!
    assert target["pick"]["z"] == 0.0

    # Contact recovery with explicit contact_z updates pick.z to contact_z + 4 mm and propagates to target["pick"]
    class ContactFeelCell:
        def __init__(self):
            self.desc_count = 0

        def act(self, cmd):
            if cmd == "run descend_pick":
                self.desc_count += 1
                if self.desc_count == 1:
                    return {"ok": False, "contact": True, "contact_z": 0.002}
                return {"ok": True, "state": [0, 0, 0, 0, 0, 55.0]}
            if cmd == "run grasp_pick":
                return {"ok": True, "holding": True, "state": [0, 0, 0, 0, 0, 53.5]}
            return {"ok": True, "state": [0, 0, 0, 0, 0, 55.0]}

    target2 = {"pick": {"site": "ship", "x": 0.17, "y": -0.15, "z": 0.008, "yaw_deg": 0.0}, "place": {"x": 0.14, "y": 0.12, "z": 0.02, "yaw_deg": 0.0}}
    cfc = ContactFeelCell()
    hook2 = cell_feel.feel_hook(cfg, cfc, target2, write_lib)
    target2["pick"] = dict(target2["pick"], x=0.175)  # upstream hover shift before feel runs
    out2 = hook2(cfc.act)
    assert out2["holding"] is True
    assert target2["pick"]["x"] == 0.175
    assert target2["pick"]["z"] == 0.006  # contact_z (0.002) + 0.004 m


def test_cell_s_displaced_container_belt_far_and_floor_front_handoff_recovery(tmp_path: Path) -> None:
    """Verify OMX Cell S (`arm_s`) displaced-container (`belt_far` / `floor_front`) top-camera detection,
    `S9_DISPLACED_CONTAINER_BELT_FAR` / `S10_DISPLACED_CONTAINER_FLOOR_FRONT` classification, crane-lift
    trajectories (`shoulder_lift -> -27.0`, `elbow_flex -> 22.0`, `max_step <= 0.032` before panning),
    and automatic `CellToFleetRReceipt` (`phase: 'RELEASED'`, `reason: 'TRANSFER_CONFIRMED'`) completion."""
    import numpy as np
    import cell_fleet_handoff as cfh
    import cell_fleet_pipeline as cfp
    import cell_spec_recovery_fsm as csrf

    # 1. Top-camera scan detects empty pick (`wrist_occ < 0.14`) and locates container in `belt_far`
    top_belt_far = np.full((480, 640, 3), (40, 40, 40), dtype=np.uint8)
    top_belt_far[150:250, 400:540] = (20, 120, 245)  # Warm orange container inside `belt_far` ROI (320, 110, 620, 290)
    scan_bf_pinky = cfh.scan_cell_s_extended_zones(
        top_belt_far, wrist_occ=0.05, intended_site="pinky", target_site="pinky",
    )
    assert scan_bf_pinky["pick_empty"] is True
    assert scan_bf_pinky["zones_scanned"] == ["belt_far", "floor_front", "pinky_tray", "belt_center"]
    assert scan_bf_pinky["displaced"] is True
    assert scan_bf_pinky["displaced_zone"] == "belt_far"
    assert scan_bf_pinky["failure_code"] == "S9_DISPLACED_CONTAINER_BELT_FAR"
    assert scan_bf_pinky["recovery_trajectory"] == "recover_from_belt_far_to_pinky"
    traj_bf = scan_bf_pinky["trajectory"]
    assert traj_bf["grasp_pose_units"] == [-27.685, 6.725, -2.289, 45.649, 17.882]
    assert traj_bf["crane_shoulder_lift"] == -27.0
    assert traj_bf["crane_elbow_flex"] == 22.0
    assert traj_bf["max_step"] <= 0.032
    assert traj_bf["lift_before_pan"] is True
    lift_wp = next(w for w in traj_bf["waypoints"] if w["phase"] == "crane_lift_vertical")
    assert lift_wp["pose_units"][0] == -27.685 and lift_wp["pose_units"][1] == -27.0 and lift_wp["pose_units"][2] == 22.0

    # 2. `belt_far` -> `belt_center` trajectory selection when target is `belt`
    scan_bf_belt = cfh.scan_cell_s_extended_zones(
        top_belt_far, wrist_occ=0.02, intended_site="belt", target_site="belt",
    )
    assert scan_bf_belt["failure_code"] == "S9_DISPLACED_CONTAINER_BELT_FAR"
    assert scan_bf_belt["recovery_trajectory"] == "recover_from_belt_far_to_belt_center"

    # 3. Top-camera scan locates displaced container on `floor_front` and selects `recover_from_floor_front_to_pinky`
    top_floor = np.full((480, 640, 3), (40, 40, 40), dtype=np.uint8)
    top_floor[220:360, 100:230] = (20, 120, 245)  # Warm orange container inside `floor_front` ROI (60, 180, 280, 420)
    scan_ff = cfh.scan_cell_s_extended_zones(
        top_floor, wrist_occ=0.03, intended_site="pinky", target_site="pinky",
    )
    assert scan_ff["displaced"] is True
    assert scan_ff["displaced_zone"] == "floor_front"
    assert scan_ff["failure_code"] == "S10_DISPLACED_CONTAINER_FLOOR_FRONT"
    assert scan_ff["recovery_trajectory"] == "recover_from_floor_front_to_pinky"
    assert csrf.select_recovery_skill("S10_DISPLACED_CONTAINER_FLOOR_FRONT")["skill"] == "recover_from_floor_front_to_pinky"

    # 4. Fleet-to-Cell handoff automatically recovers `belt_far` and `floor_front` and emits RELEASED receipt
    pipe = cfp.FleetModelPipeline(tmp_path)
    base_handoff = {
        "handoff_lease_id": "cell_s:pinky_1:displaced",
        "cell_id": "cell_s",
        "station_place": "S3",
        "robot_id": "pinky_1",
        "wheel_brake_locked": True,
        "bed_ready": True,
        "v_cmd_mps": 0.0,
    }
    res_bf = pipe.run_contract_handoff_stage(
        {**base_handoff, "wrist_occ": 0.04, "top_frame": top_belt_far, "src_site": "pinky", "dst_site": "belt"},
        stage_id="handoff-s3-recover-belt-far",
    )
    assert res_bf["receipt"]["phase"] == "RELEASED"
    assert res_bf["receipt"]["reason"] == "TRANSFER_CONFIRMED"
    assert res_bf["receipt"]["goal_evidence_digest"].startswith("sha256:")
    assert res_bf["stage_result"]["displaced_recovery"]["failure_code"] == "S9_DISPLACED_CONTAINER_BELT_FAR"
    assert res_bf["stage_result"]["displaced_recovery"]["recovery_trajectory"] == "recover_from_belt_far_to_belt_center"

    res_ff = pipe.run_contract_handoff_stage(
        {**base_handoff, "wrist_occ": 0.01, "top_frame": top_floor, "src_site": "pinky", "dst_site": "pinky"},
        stage_id="handoff-s3-recover-floor-front",
    )
    assert res_ff["receipt"]["phase"] == "RELEASED"
    assert res_ff["receipt"]["reason"] == "TRANSFER_CONFIRMED"
    assert res_ff["stage_result"]["displaced_recovery"]["failure_code"] == "S10_DISPLACED_CONTAINER_FLOOR_FRONT"
    assert res_ff["stage_result"]["displaced_recovery"]["recovery_trajectory"] == "recover_from_floor_front_to_pinky"

    ledger_rows = cpp.load_ledger(tmp_path)
    cats = {r["category"] for r in ledger_rows}
    assert "s9_displaced_container_belt_far" in cats
    assert "s10_displaced_container_floor_front" in cats
    for row in ledger_rows:
        if row["category"] in ("s9_displaced_container_belt_far", "s10_displaced_container_floor_front"):
            assert rsim.replay_and_verify_problem_case(row, tmp_path)["verified"] is True


def test_cell_task_worker_event_driven_hw_and_parallel_handoff(tmp_path: Path, monkeypatch) -> None:
    """Verify `cell_task_worker` replaces blind sleeps in `execute_live_hardware_arm` with event-driven
    status-line acknowledgment (`_wait_cmd`), uploads snapshots from `live-*` directories in parallel,
    and overlaps `run_contract_handoff_stage` with `live_act_fn` in `poll_and_execute_once`."""
    import json
    import time
    import cell_fleet_pipeline as cfp
    import cell_task_worker as ctw

    io_dir = tmp_path / "chunk-io-s"
    io_dir.mkdir(parents=True)
    status_file = io_dir / "chunk-status.jsonl"
    (tmp_path / "chunks-arm-s-inplace-live.json").write_text("{}", encoding="utf-8")

    def _fake_check_output(*a, **k) -> str:
        status_file.write_text(
            "\n".join(
                [
                    json.dumps({"command": "state", "ok": True}),
                    json.dumps({"command": "load chunks-arm-s-inplace-live.json", "ok": True}),
                    json.dumps({"command": "jog shoulder_pan.pos -1.0", "ok": True}),
                    json.dumps({"command": "stop", "ok": True, "folded": True}),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return "session up\n"

    monkeypatch.setattr(ctw.subprocess, "check_output", _fake_check_output)
    t0 = time.monotonic()
    hw_out = ctw.execute_live_hardware_arm("arm_s", prep_dir=tmp_path)
    elapsed_s = time.monotonic() - t0
    assert hw_out["arm"] == "arm_s"
    assert hw_out["events_count"] == 4
    assert hw_out["stop_event"]["folded"] is True
    assert elapsed_s < 0.4

    realign_dir = tmp_path / "live-realignment-pipeline-s-20261113"
    realign_dir.mkdir(parents=True)
    (realign_dir / "top_frame.jpg").write_bytes(b"\xff\xd8" + b"x" * 1500)
    (realign_dir / "wrist_frame.jpg").write_bytes(b"\xff\xd8" + b"y" * 1600)

    class _DummyResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ctw, "urlopen", lambda req, **kw: _DummyResp())
    up = ctw.upload_latest_camera_snapshots("https://fleet.local:8443", "tok", prep_dir=tmp_path)
    assert set(up.keys()) == {"cell_s", "cell_ab", "pinky"}
    assert up["cell_s"] == 1502 and up["cell_ab"] == 1602

    pipe = cfp.FleetModelPipeline(tmp_path / "pipe")

    def _req(method: str, path: str, body):
        if method == "GET":
            return {"tasks": [{"task_id": "t-par-1", "cell_id": "cell_s", "tier": 1}]}
        if path.endswith("/claim"):
            return {
                "claimed": True,
                "gate": {"amr_motion_inhibited": True},
                "handoff": {
                    "handoff_lease_id": "lease-par-1",
                    "cell_id": "cell_s",
                    "wheel_brake_locked": True,
                    "bed_ready": True,
                    "v_cmd_mps": 0.0,
                },
            }
        return {"gate": {"amr_motion_inhibited": False}, "task": {"status": "COMPLETED", "hardware_telemetry": body["hardware_telemetry"]}}

    runs = ctw.poll_and_execute_once(pipe, request_fn=_req, live_act_fn=lambda h: hw_out, prep_dir=tmp_path)
    assert len(runs) == 1 and runs[0]["task"]["status"] == "COMPLETED"






