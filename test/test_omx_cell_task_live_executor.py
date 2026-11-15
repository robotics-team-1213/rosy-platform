"""A supervised AreaXYZ trial cannot invent a Fleet completion or lose its D-911 intent."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import stat
import sys
import time

import numpy as np
import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
live = importlib.import_module("cell_task_live_executor")
attempts = importlib.import_module("cell_attempts")


def _fixture(tmp_path, monkeypatch, *, fail_command=None, unsettled_command=None):
    work = tmp_path / "work"
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    trace_path = tmp_path / "trace-arm_b.jsonl"
    trace_path.write_bytes(b"")
    config = {"_commissioning": {"person_at_switch": True}, "arm_id": "arm_b", "work_dir": str(work),
              "io": str(io),
              "cameras": {"top": {}, "side": {}}, "plan": {"lift_m": 0.04},
              "sites": {"beltend": {}, "pallet": {}},
              "_operating_profile_binding": {"device_id": "arm_b", "instance_id": "arm_b_follower"}}
    calibration_path = tmp_path / "map.json"
    calibration_path.write_text(json.dumps({"sites": {"beltend": {"points": []}}}))
    handoff = {"task_id": "tier-1", "handoff_lease_id": "lease-1", "arm_id": "arm_b",
               "src_site": "beltend", "dst_site": "pallet", "tier": 1,
               "directive": {"directive_id": "tier-1", "arm_id": "arm_b",
                             "pick": {"area": "beltend", "tier": 1},
                             "place": {"area": "pallet", "tier": 1}}}
    commands = []
    trace_position, trace_sequence, trace_tick = [0], [0], [0]

    def trace_receipt(command, sent):
        trace_sequence[0] += 1
        trace_tick[0] += 1
        data = (json.dumps({"t": trace_tick[0], "present": [0] * 6, "sent": sent,
                            "pwm": {"shoulder": 1}, "owner_session_id": "s",
                            "library_sha256": "lib"}) + "\n").encode()
        with trace_path.open("ab") as stream:
            stream.write(data)
        start = trace_position[0]
        trace_position[0] += len(data)
        reported_at = time.time()
        return {"status": "ok", "source": trace_path.name, "start": start,
                "end": trace_position[0], "sha256": hashlib.sha256(data).hexdigest(),
                "sequence": trace_sequence[0], "session_id": "s", "library_sha256": "lib",
                "command": command, "reported_at": reported_at}

    class Cell:
        def act(self, command):
            assert command == "state"
            return {"ok": True, "t": time.time(), "operating_context": {
                "scope": "hardware", "session_id": "s", "sha256": "a" * 64,
                "operating_profile": {"device_id": "arm_b", "instance_id": "arm_b_follower"}}}

        def frame_receipt(self, camera, *, previous=None):
            raw = b"\xff\xd8" + camera.encode() + (b"after" if previous else b"before")
            seq = 2 if previous else 1
            return {"camera": camera, "image": np.zeros((4, 4, 3), dtype=np.uint8),
                    "jpeg_bytes": raw, "jpeg_sha256": hashlib.sha256(raw).hexdigest(),
                    "source_seq": seq, "source_stamp": time.time()}

    class Gate:
        def __init__(self, cell, config, calibration, *, sequence):
            assert sequence == live.FOLDED
            self.assessment = {"library_sha256": "lib", "task_sha256": "task", "mode": "commissioning",
                               "scope": "hardware", "runtime_sha256": "a" * 64, "session_id": "s",
                               "operating_profile": {"device_id": "d"}}

        def open(self, library, before_motion):
            before_motion(self.assessment)
            return None

        def act(self, command):
            commands.append(command)
            pre = None if command.startswith("load ") else trace_receipt("state", None)
            receipt = trace_receipt(command, [0] * 6)
            return {"ok": command != fail_command, "settled": command != unsettled_command,
                    "holding": command in ("run grasp_pick", "run lift_pick"), "state": [0] * 6,
                    "target": [0] * 6,
                    "health": {"pwm": [1] * 6, "current_ma": [2] * 6, "temp_c": [30] * 6},
                    "fault": None, "t": receipt["reported_at"], "trace_receipt": receipt,
                    "pre_state_trace": ({"t": pre["reported_at"], "trace_receipt": pre} if pre else None),
                    "operating_context": {
                        "scope": "hardware", "sha256": "a" * 64, "session_id": "s",
                        "operating_profile": {"device_id": "d"}}}

        def _settled_home(self, status, assessment):
            return status.get("settled") is True

    monkeypatch.setattr(live, "Gate", Gate)
    def bound_pose_check(cell, config, calibration, path, work, dry_run, out):
        assert calibration["sites"]["beltend"]["points"] == []
        assert path == calibration_path and work == Path(config["work_dir"]) and dry_run is False
        return None

    monkeypatch.setattr(live, "map_pose_preflight", bound_pose_check)
    monkeypatch.setattr(live, "plan_library_from_directive", lambda *args, **kwargs: (
        {"chunks": {"home": [[0] * 6]}}, {}, {}))
    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", lambda *args, **kwargs: None)
    monkeypatch.setattr(attempts, "RUN", dict(attempts.RUN))
    return handoff, config, calibration_path, Cell(), commands


def test_static_carry_journals_unknown_without_bound_depth(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "unverified_place" and result["task_verified"] is False
    assert result["verification"]["verified"] is False
    assert result["verification"]["z_gate"]["verdict"] == "UNKNOWN"
    assert result["verification"]["post_release_gate"]["ok"] is False
    assert "post-placement Z16" in result["verification"]["reason"]
    assert "place_slot" not in result["verification"]
    assert "recovery_mode" not in result["verification"]
    assert "stop_event" not in result and commands[1:] == list(live.FOLDED)
    ledger = Path(config["work_dir"]) / "attempts.jsonl"
    row = json.loads(ledger.read_text())
    assert row["outcome"] == "unverified" and row["task_binding"] == {
        "task_id": "tier-1", "handoff_lease_id": "lease-1"}
    assert row["verify"] == result["verification"]
    assert row["envelope"]["library_sha256"] == "lib"
    assert row["simulation"]["basis"] == "model_only"
    assert row["simulation"]["prediction"] is None
    assert row["simulation"]["comparison"]["verdict"] == "UNKNOWN"
    assert Path(row["frames"]["during"]["manifest"]).exists()
    joints = row["frames"]["joints"]
    assert joints["coverage"] == "command_boundaries_only"
    assert joints["continuous_trace"] == "captured" and joints["torque_nm"] == "UNKNOWN"
    assert joints["pwm_proxy_rows"] > 0 and Path(joints["owner_trace_path"]).exists()
    lines = [json.loads(line) for line in Path(joints["path"]).read_text().splitlines()]
    assert lines[0]["task_id"] == "tier-1" and lines[0]["handoff_lease_id"] == "lease-1"
    assert len(lines) == len(live.FOLDED) + 2  # bound header, load, each arm command
    assert all(line["state"] == [0] * 6 and line["pwm_raw"] == [1] * 6 for line in lines[1:])
    assert not ledger.with_suffix(".pending.json").exists()
    assert attempts.summary([row])["placed"] == 0


def test_post_place_depth_is_bound_to_trial_but_does_not_verify_height(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "_boot_id", lambda: "same-boot")

    def capture(dev, raw_path):
        assert dev == "/dev/v4l/by-id/rosy-realsense-d435-depth"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"z16")
        receipt_path = raw_path.with_suffix(raw_path.suffix + ".receipt.json")
        receipt = {
            "raw_path": str(raw_path), "raw_sha256": hashlib.sha256(b"z16").hexdigest(),
            "boot_id": "same-boot", "exposure_monotonic_s": time.monotonic() + 0.01,
            "exposure_wall_estimate_s": time.time(), "wall_bridge_uncertainty_s": 0.01,
            "clock_semantics": "v4l2_monotonic_start_of_exposure", "source_seq": 12,
        }
        receipt_path.write_text(json.dumps(receipt))
        return np.zeros((480, 640), dtype=np.uint16), receipt

    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", capture)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    row = json.loads((Path(config["work_dir"]) / "attempts.jsonl").read_text())
    depth = row["frames"]["post_place_depth"]
    assert depth["task_id"] == "tier-1" and depth["handoff_lease_id"] == "lease-1"
    assert depth["run_id"] and depth["site_id"] == "pallet-l0" and depth["tier"] == 1
    assert depth["receipt_sha256"] == hashlib.sha256(Path(depth["receipt_path"]).read_bytes()).hexdigest()
    assert result["verification"]["z_gate"]["verdict"] == "UNKNOWN"
    assert result["task_verified"] is False and row["outcome"] == "unverified"


def test_pre_park_depth_exposure_cannot_bind_to_place(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "_boot_id", lambda: "same-boot")

    def stale_capture(dev, raw_path):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"z16")
        raw_path.with_suffix(raw_path.suffix + ".receipt.json").write_bytes(b"{}")
        return np.zeros((480, 640), dtype=np.uint16), {
            "raw_path": str(raw_path), "raw_sha256": hashlib.sha256(b"z16").hexdigest(),
            "boot_id": "same-boot", "exposure_monotonic_s": 0,
            "clock_semantics": "v4l2_monotonic_start_of_exposure", "source_seq": 12,
        }

    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", stale_capture)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["frames"]["post_place_depth"]["status"] == "rejected"
    assert result["verification"]["z_gate"]["verdict"] == "UNKNOWN"


def test_pre_park_camera_frame_holds_trial_before_depth_capture(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    frame_receipt = cell.frame_receipt
    capture_calls = []

    def old_frame(camera, *, previous=None):
        receipt = frame_receipt(camera, previous=previous)
        if previous is not None and camera == "side":
            receipt["source_stamp"] = previous["source_stamp"] + 0.001
        return receipt

    monkeypatch.setattr(cell, "frame_receipt", old_frame)

    def capture(dev, raw_path):
        capture_calls.append(raw_path)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"z16")
        raw_path.with_suffix(raw_path.suffix + ".receipt.json").write_bytes(b"receipt")
        return None, {}

    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", capture)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "ValueError" in result["reason"]
    assert len(capture_calls) == 1
    assert "after" not in result["frames"]
    depth = result["frames"]["post_place_depth"]
    assert depth["status"] == "rejected" and depth["task_id"] == "tier-1"
    assert depth["raw_sha256"] == hashlib.sha256(b"z16").hexdigest()
    assert depth["receipt_sha256"] == hashlib.sha256(b"receipt").hexdigest()
    row = json.loads((Path(config["work_dir"]) / "attempts.jsonl").read_text())
    assert row["frames"]["post_place_depth"] == depth and row["outcome"] == "held"


def test_depth_receipt_sidecar_mismatch_is_rejected(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "_boot_id", lambda: "same-boot")

    def mismatched_capture(dev, raw_path):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"z16")
        raw_path.with_suffix(raw_path.suffix + ".receipt.json").write_text('{"source_seq":99}')
        return None, {"raw_path": str(raw_path), "raw_sha256": hashlib.sha256(b"z16").hexdigest(),
                      "boot_id": "same-boot", "exposure_monotonic_s": time.monotonic() + 0.01,
                      "exposure_wall_estimate_s": time.time(), "wall_bridge_uncertainty_s": 0.01,
                      "clock_semantics": "v4l2_monotonic_start_of_exposure", "source_seq": 12}

    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", mismatched_capture)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "unverified_place"
    assert result["frames"]["post_place_depth"]["status"] == "rejected"
    assert result["task_verified"] is False


def test_depth_far_from_post_park_rgb_is_rejected(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "_boot_id", lambda: "same-boot")

    def late_capture(dev, raw_path):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(b"z16")
        receipt = {"raw_path": str(raw_path), "raw_sha256": hashlib.sha256(b"z16").hexdigest(),
                   "boot_id": "same-boot", "exposure_monotonic_s": time.monotonic() + 0.01,
                   "exposure_wall_estimate_s": time.time() - 2,
                   "wall_bridge_uncertainty_s": 0.01,
                   "clock_semantics": "v4l2_monotonic_start_of_exposure", "source_seq": 12}
        raw_path.with_suffix(raw_path.suffix + ".receipt.json").write_text(json.dumps(receipt))
        return None, receipt

    monkeypatch.setattr(live, "capture_top_depth_z16_receipt", late_capture)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["frames"]["post_place_depth"]["status"] == "rejected"
    assert result["verification"]["z_gate"]["verdict"] == "UNKNOWN"


def test_missing_joint_state_stops_before_next_arm_command(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    original = live.Gate.act

    def no_state(self, command):
        status = original(self, command)
        status.pop("state")
        return status

    monkeypatch.setattr(live.Gate, "act", no_state)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "joint state" in result["reason"]
    assert len(commands) == 1 and result["frames"]["joints"]["rows"] == 1


def test_old_owner_without_trace_receipt_holds_before_arm_motion(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    original = live.Gate.act

    def old_owner(self, command):
        status = original(self, command)
        status.pop("trace_receipt")
        return status

    monkeypatch.setattr(live.Gate, "act", old_owner)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "ValueError" in result["reason"]
    assert len(commands) == 1 and result["frames"]["joints"]["continuous_trace"] == "UNKNOWN"


def test_owner_trace_sequence_gap_holds_before_following_arm_command(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    original = live.Gate.act

    def skipped_status(self, command):
        status = original(self, command)
        if not command.startswith("load "):
            status["pre_state_trace"]["trace_receipt"]["sequence"] += 1
        return status

    monkeypatch.setattr(live.Gate, "act", skipped_status)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "ValueError" in result["reason"]
    assert len(commands) == 2 and result["frames"]["joints"]["continuous_trace"] == "UNKNOWN"


def test_joint_evidence_write_failure_stops_before_next_arm_command(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    original = live.AttemptJointEvidence

    class Broken(original):
        def record(self, command, status):
            raise OSError("evidence disk unavailable")

    monkeypatch.setattr(live, "AttemptJointEvidence", Broken)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "OSError" in result["reason"]
    assert len(commands) == 1 and result["frames"]["joints"]["rows"] == 0


def test_simulation_prediction_stays_distinct_from_real_verification(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    prediction = {"twin": {"samples": 0}, "place_compensated": {"terminal_error_mm": 2.0}}
    monkeypatch.setattr(live, "plan_library_from_directive", lambda *args, **kwargs: (
        {"chunks": {"home": [[0] * 6]}}, {"sim_real_prediction": prediction}, {}))
    result = live.run_supervised_static(handoff, config, calibration, cell)
    row = json.loads((Path(config["work_dir"]) / "attempts.jsonl").read_text())
    assert result["simulation"]["prediction"] == row["simulation"]["prediction"] == prediction
    assert row["simulation"]["library_sha256"] == row["envelope"]["library_sha256"]
    assert row["simulation"]["comparison"]["verdict"] == "UNKNOWN"
    assert row["simulation"]["basis"] == "model_only" and result["task_verified"] is False


def test_incomplete_video_coverage_holds_trial(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)

    class NoFrames:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return self

        def stop(self):
            return {"manifest": "no-frames", "status": "no_frames"}

    monkeypatch.setattr(live, "AttemptVideo", NoFrames)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    row = json.loads((Path(config["work_dir"]) / "attempts.jsonl").read_text())
    assert result["result"] == row["outcome"] == "held"
    assert "video" in result["reason"]
    assert commands[1:] == list(live.FOLDED)


def test_video_limit_stops_before_next_arm_command(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)

    class FullVideo:
        status = "limit_reached"

        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return self

        def stop(self):
            return {"manifest": "limit", "status": self.status}

    monkeypatch.setattr(live, "AttemptVideo", FullVideo)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and result["pending_recovery"] is True
    assert commands == []


def test_fleet_tier_site_matches_canonical_area_without_releasing(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    handoff["tier"] = 2
    handoff["dst_site"] = "pallet-l1"
    handoff["directive"]["place"]["tier"] = 2
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "unverified_place" and result["task_verified"] is False
    assert commands[1:] == list(live.FOLDED)
    handoff["dst_site"] = "pallet-l2"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"


def test_static_carry_rejects_unknown_site_and_shifted_coordinates(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    handoff["src_site"] = ""
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["src_site"] = "beltend"
    handoff["dst_site"] = ""
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["dst_site"] = "pallet-l3"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["dst_site"] = "pallet-l1"
    handoff["directive"]["place"]["area"] = "pallet-l1"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["dst_site"] = "tmp-b-1-l1"
    handoff["directive"]["place"]["area"] = "tmp-b-1-l1"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["directive"]["place"]["area"] = "pallet"
    handoff["dst_site"] = "pallet-l0"
    handoff["directive"]["place"]["x"] = 0.20
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["directive"]["place"]["y"] = -0.013
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    del handoff["directive"]["place"]["x"]
    del handoff["directive"]["place"]["y"]
    handoff["directive"]["place"].update({"schema": "rosy.omx-area-xyz.v1",
                                             "effective_xyz_m": [0.20, -0.013, 0.0074],
                                             "effective_xyz_mm": [200.0, -13.0, 7.4]})
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    assert commands == []


def test_same_second_supervised_trials_have_distinct_attempt_rows(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(live.time, "strftime", lambda *args: "20261113T093000Z")
    first = live.run_supervised_static(handoff, config, calibration, cell)
    second = live.run_supervised_static(handoff, config, calibration, cell)
    rows = [json.loads(line) for line in (Path(config["work_dir"]) / "attempts.jsonl").read_text().splitlines()]
    assert first["result"] == second["result"] == "unverified_place"
    assert first["attempt_id"] != second["attempt_id"]
    assert [row["attempt_id"] for row in rows] == [first["attempt_id"], second["attempt_id"]]
    assert all(row["outcome"] == "unverified" for row in rows)


def test_frame_directory_is_synced_before_trial_ledger(tmp_path, monkeypatch):
    handoff, config, calibration, cell, _ = _fixture(tmp_path, monkeypatch)
    synced = []
    original = attempts._fsync_directory

    def sync(path):
        synced.append(Path(path))
        original(path)

    monkeypatch.setattr(attempts, "_fsync_directory", sync)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "unverified_place"
    assert synced.count(Path(config["work_dir"]) / "frames") == 2


def test_refused_motion_keeps_pending_and_never_sends_next_command(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(
        tmp_path, monkeypatch, fail_command="run descend_pick")
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and commands[-1] == "run descend_pick"
    assert "run grasp_pick" not in commands and "park" not in commands
    ledger = Path(config["work_dir"]) / "attempts.jsonl"
    row = json.loads(ledger.read_text())
    assert row["outcome"] == "held"
    assert set(row["frames"]["failure"]) == {"top", "side"}
    for camera in ("top", "side"):
        failure = row["frames"]["failure"][camera]
        assert failure["source_seq"] > row["frames"]["before"][camera]["source_seq"]
        assert Path(failure["path"]).read_bytes().startswith(b"\xff\xd8")
    assert ledger.with_suffix(".pending.json").exists()


def test_failure_camera_error_preserves_held_attempt(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(
        tmp_path, monkeypatch, fail_command="run descend_pick")
    original = cell.frame_receipt

    def frame_receipt(camera, *, previous=None):
        if camera == "side" and previous is not None:
            raise TimeoutError("camera unavailable")
        return original(camera, previous=previous)

    monkeypatch.setattr(cell, "frame_receipt", frame_receipt)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    row = json.loads((Path(config["work_dir"]) / "attempts.jsonl").read_text())
    assert result["result"] == row["outcome"] == "held"
    assert commands[-1] == "run descend_pick"
    assert set(row["frames"]["failure"]) == {"top"}
    assert row["frames"]["failure_errors"] == {"side": "TimeoutError"}
    assert (Path(config["work_dir"]) / "attempts.pending.json").exists()


def test_refused_motion_after_interim_park_keeps_pending(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(
        tmp_path, monkeypatch, fail_command="goto above_place")
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and result["pending_recovery"] is True
    assert commands[-1] == "goto above_place" and "run descend_place" not in commands
    ledger = Path(config["work_dir"]) / "attempts.jsonl"
    assert len(ledger.read_text().splitlines()) == 1 and ledger.with_suffix(".pending.json").exists()


def test_timeout_with_ok_but_unsettled_holds_before_next_chunk(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(
        tmp_path, monkeypatch, unsettled_command="run descend_pick")
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and commands[-1] == "run descend_pick"
    assert "run grasp_pick" not in commands
    assert (Path(config["work_dir"]) / "attempts.pending.json").exists()


def test_unbound_or_adaptive_directive_never_opens_gate(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    handoff["directive"]["execution"] = {"vision_refine": True}
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    handoff["directive"]["execution"] = {}
    handoff["directive"]["directive_id"] = "another-task"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    assert commands == [] and not (Path(config["work_dir"]) / "attempts.jsonl").exists()


def test_direct_caller_profile_mismatch_holds_before_receipts_or_gate(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    config["_operating_profile_binding"] = {"device_id": "different"}
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "bound arm operating profile" in result["reason"]
    assert commands == [] and not Path(config["work_dir"]).exists()
    config["_operating_profile_binding"] = {"device_id": "arm_b", "instance_id": "omx_follower_arm"}
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    config["_operating_profile_binding"] = {"device_id": "arm_b", "instance_id": "arm_b_follower"}
    config["arm_id"] = "arm_a"
    assert live.run_supervised_static(handoff, config, calibration, cell)["result"] == "held"
    assert commands == []


def test_cli_requires_explicit_supervision_and_matching_handoff(tmp_path, monkeypatch, capsys):
    import cell_auto_setup
    import cell_pipeline_io
    import cell_robot_profile

    handoff, config, calibration, _, _ = _fixture(tmp_path, monkeypatch)
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(json.dumps(handoff))
    config_path = tmp_path / "config.json"
    config_path.write_text("{}")
    raw = {**config, "calibration_path": str(calibration), "io": str(tmp_path / "io"),
           "operating_profile_path": str(tmp_path / "profile.json"),
           "_commissioning": {"person_at_switch": False},
           "_operating_profile_binding": {"device_id": "forged"}}
    seen = []
    monkeypatch.setattr(cell_auto_setup, "load_config", lambda path: dict(raw))

    def bind(document):
        assert "_commissioning" not in document and "_operating_profile_binding" not in document
        return {**document, "_operating_profile_binding": {"device_id": "arm_b", "instance_id": "arm_b_follower"}}

    monkeypatch.setattr(cell_robot_profile, "bind_pipeline", bind)
    monkeypatch.setattr(cell_pipeline_io, "FifoCell", lambda io, cameras, *, operating_profile:
                        seen.append(operating_profile) or object())
    monkeypatch.setattr(live, "run_supervised_static", lambda h, c, p, cell: (
        seen.append(c["_commissioning"]) or {"result": "unverified_place", "task_verified": False}))
    base = ["--config", str(config_path), "--handoff-json", str(handoff_path),
            "--task-id", "tier-1", "--handoff-lease-id", "lease-1"]
    with pytest.raises(SystemExit):
        live.main(base)
    with pytest.raises(SystemExit):
        live.main([*base[:-1], "wrong", "--commissioning", "--person-at-switch"])
    raw.pop("operating_profile_path")
    with pytest.raises(SystemExit):
        live.main([*base, "--commissioning", "--person-at-switch"])
    raw["operating_profile_path"] = str(tmp_path / "profile.json")
    assert seen == []
    assert live.main([*base, "--commissioning", "--person-at-switch"]) == 1
    assert seen == [{"device_id": "arm_b", "instance_id": "arm_b_follower"}, {"person_at_switch": True}]
    assert json.loads(capsys.readouterr().out)["task_verified"] is False


def test_area_terminal_mismatch_and_duplicate_keep_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "RUN", dict(attempts.RUN))
    path = tmp_path / "attempts.jsonl"
    attempts.start(path, "trial", arm_id="arm_b", task_id="t", handoff_lease_id="lease")
    config = {"work_dir": str(tmp_path), "plan": {}}
    assessment = {"library_sha256": "lib", "task_sha256": "task", "mode": "commissioning"}
    directive = {"directive_id": "t", "arm_id": "arm_b", "pick": {"area": "beltend"},
                 "place": {"area": "pallet"}}
    attempts.begin(config, assessment)
    with pytest.raises(OSError, match="differs"):
        attempts.finish_area_xyz(config, {}, directive, {**assessment, "library_sha256": "changed"},
                                 {"result": "held"}, [], {}, folded_home=True, home=[0] * 6, t_start=time.time())
    assert not path.exists() and path.with_suffix(".pending.json").exists()
    attempts.finish_area_xyz(config, {}, directive, assessment, {"result": "held"}, [], {},
                             folded_home=False, home=[0] * 6, t_start=time.time())
    with pytest.raises(OSError, match="already appended"):
        attempts.finish_area_xyz(config, {}, directive, assessment, {"result": "held"}, [], {},
                                 folded_home=True, home=[0] * 6, t_start=time.time())
    assert len(path.read_text().splitlines()) == 1 and path.with_suffix(".pending.json").exists()


def test_area_terminal_sync_failure_keeps_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "RUN", dict(attempts.RUN))
    path = tmp_path / "attempts.jsonl"
    attempts.start(path, "trial", arm_id="arm_b", task_id="t", handoff_lease_id="lease")
    config = {"work_dir": str(tmp_path), "plan": {}}
    assessment = {"library_sha256": "lib", "task_sha256": "task", "mode": "commissioning"}
    attempts.begin(config, assessment)
    directive = {"directive_id": "t", "arm_id": "arm_b", "pick": {"area": "beltend"},
                 "place": {"area": "pallet"}}
    monkeypatch.setattr(attempts.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        attempts.finish_area_xyz(config, {}, directive, assessment, {"result": "held"}, [], {},
                                 folded_home=False, home=[0] * 6, t_start=time.time())
    assert path.with_suffix(".pending.json").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="directory fsync is a Linux durability gate")
def test_pending_directory_sync_precedes_motion_and_failure_holds(tmp_path, monkeypatch):
    handoff, config, calibration, cell, commands = _fixture(tmp_path, monkeypatch)
    original_fsync = attempts.os.fsync
    synced_directory = []
    pending = Path(config["work_dir"]) / "attempts.pending.json"

    def fsync(fd):
        if pending.exists() and stat.S_ISDIR(attempts.os.fstat(fd).st_mode):
            synced_directory.append(True)
            raise OSError("directory sync failed")
        return original_fsync(fd)

    monkeypatch.setattr(attempts.os, "fsync", fsync)
    result = live.run_supervised_static(handoff, config, calibration, cell)
    assert result["result"] == "held" and "review unavailable" in result["reason"]
    assert synced_directory and commands == []
    assert (Path(config["work_dir"]) / "attempts.pending.json").exists()
    assert attempts.RUN["pending"] is None
