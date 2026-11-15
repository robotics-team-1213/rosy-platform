"""One supervised, fixed AreaXYZ carry under the exact D-911 operating envelope.

This is a cell owner component, not a Fleet completion provider. It never emits a
physical-completion receipt; measured post-release and stop evidence must be
connected before an AreaXYZ task can be released to Fleet.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

import cell_attempts
from cell_depth import capture_top_depth_z16_receipt
from cell_auto_evidence import map_pose_preflight
from cell_auto_pick_plan import save_frame_receipt
from cell_directive_compiler import plan_library_from_directive
from cell_envelope import _state_current
from cell_spec_recovery_fsm import evaluate_execution_gate
from cell_task_joint_evidence import AttemptJointEvidence
from cell_task_video import AttemptVideo
from cell_transfer import FOLDED, Gate
from omx_adapter.area_xyz import coerce_area_xyz, resolve_area_xyz


def _held(reason: str, *, steps=None, frames=None) -> dict:
    return {"result": "held", "task_verified": False, "reason": reason,
            "steps": steps or [], "frames": frames or {}}


def _site_id(value) -> str:
    if isinstance(value, dict):
        raw = value.get("area") or value.get("site_id")
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("directive site missing")
        expected = resolve_area_xyz(raw, col=value.get("col"), row=value.get("row"), tier=value.get("tier"))
        if value.get("tier") is not None and (type(value["tier"]) is not int or value["tier"] != expected["tier"]):
            raise ValueError("directive tier differs from site suffix")
        if any(key in value and value[key] is not None and float(value[key]) != expected[key]
               for key in ("x", "y", "z", "x_mm", "y_mm", "z_mm")):
            raise ValueError("directive coordinates differ from fixed site")
        actual = coerce_area_xyz(value)
        # shortcut: fixed trials reject XYZ overrides until an owner binds the exact Fleet directive and calibrated site map.
        if (any(actual.get(key) != expected[key] for key in
                ("area", "site_id", "tier", "effective_xyz_m", "effective_xyz_mm"))
                or (value.get("site_id") and str(value["site_id"]).lower() != expected["site_id"])):
            raise ValueError("directive coordinates differ from fixed site")
    else:
        raw = value
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("handoff site missing")
        expected = resolve_area_xyz(raw)
    if str(raw or "").strip().lower().startswith(("pallet-l", "tmp-")) and str(raw).strip().lower() != expected["site_id"]:
        raise ValueError("unknown tier site")
    return expected["site_id"]


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None


def run_supervised_static(handoff: dict, config: dict, calibration_path: Path,
                          cell, *, kinematics_root: Path | None = None) -> dict:
    """Run one exact precompiled arm_b library; stop at the first uncertain command."""
    if not isinstance(handoff, dict) or not isinstance(config, dict):
        return _held("unbound supervised AreaXYZ task")
    directive = handoff.get("directive")
    task_id, lease = handoff.get("task_id"), handoff.get("handoff_lease_id")
    if (config.get("_commissioning") != {"person_at_switch": True}
            or not isinstance(task_id, str) or not task_id or not isinstance(lease, str) or not lease
            or not isinstance(directive, dict) or directive.get("directive_id") != task_id
            or directive.get("arm_id") != handoff.get("arm_id") != "arm_b"
            or not isinstance(directive.get("pick"), dict) or not isinstance(directive.get("place"), dict)
            or directive["place"].get("tier") != handoff.get("tier")
            or not isinstance(config.get("work_dir"), str) or not isinstance(config.get("plan"), dict)
            or type(handoff.get("tier")) is not int or handoff["tier"] not in (1, 2, 3)):
        return _held("unbound supervised AreaXYZ task")
    try:
        if (_site_id(directive["pick"]) != _site_id(handoff.get("src_site"))
                or _site_id(directive["place"]) != _site_id(handoff.get("dst_site"))
                or resolve_area_xyz(handoff["dst_site"], tier=handoff["tier"])["tier"] != handoff["tier"]):
            return _held("unbound supervised AreaXYZ task")
    except (AttributeError, IndexError, KeyError, OverflowError, TypeError, ValueError):
        return _held("unbound supervised AreaXYZ task")
    execution = directive.get("execution") or {}
    if not isinstance(execution, dict) or any(execution.get(key) for key in (
            "vision_refine", "vision_after_grasp", "grasp_debate", "stay_in_hover", "retry_on_unverified_place")):
        return _held("adaptive AreaXYZ directive requires separate reviewed attempts")
    if not {"top", "side"}.issubset(config.get("cameras") or {}):
        return _held("top and side source cameras required")
    profile = config.get("_operating_profile_binding")
    # shortcut: this cell's arm_b is arm_b_follower; use an approved role registry before serving other cells.
    if (not isinstance(profile, dict) or profile.get("device_id") != "arm_b"
            or profile.get("instance_id") != "arm_b_follower"
            or config.get("arm_id") != "arm_b"):
        return _held("bound arm operating profile required")
    work = Path(config["work_dir"]).expanduser()
    calibration_path = Path(calibration_path).expanduser()
    try:
        initial_calibration = calibration_path.read_bytes()
        calibration = json.loads(initial_calibration)
        state = cell.act("state")
        context = state.get("operating_context") or {}
        if (not _state_current(state, time.time()) or context.get("scope") != "hardware"
                or context.get("operating_profile") != profile):
            return _held("hardware owner state unavailable")
        frames = {}
        reason = map_pose_preflight(cell, config, calibration, calibration_path, work, False, frames)
        if reason:
            return _held(reason, frames=frames)
        before = {name: cell.frame_receipt(name) for name in ("top", "side")}
        frames["before"] = {name: save_frame_receipt(
            work / "frames" / f"{uuid.uuid4().hex}-{name}-before.jpg", receipt)
            for name, receipt in before.items()}
        cell_attempts._fsync_directory(work / "frames")
        cell_attempts._fsync_directory(work)
        if calibration_path.read_bytes() != initial_calibration:
            return _held("calibration changed before reviewed motion", frames=frames)
        library, plan, _ = plan_library_from_directive(directive, config["plan"], work_dir=work,
                                                        kinematics_root=kinematics_root)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return _held(f"preflight unavailable: {type(exc).__name__}")
    work.mkdir(parents=True, exist_ok=True)
    library_path = work / f"area-static-{hashlib.sha256(task_id.encode()).hexdigest()[:16]}-{uuid.uuid4().hex}.json"
    video = None
    try:
        with library_path.open("x", encoding="utf-8") as stream:
            json.dump(library, stream)
            stream.flush()
            os.fsync(stream.fileno())
        run_id = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex}"
        video = AttemptVideo(cell, work, task_id, run_id, lease).start()
        cell_attempts.start(work / "attempts.jsonl", run_id=run_id, knowledge=config.get("knowledge"),
                            params=config.get("params_path"), arm_id="arm_b",
                            task_id=task_id, handoff_lease_id=lease)
        gate = Gate(cell, config, calibration, sequence=FOLDED)
        held = gate.open(library_path, lambda assessment: cell_attempts.begin(config, assessment))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if video is not None:
            video.stop()
        return _held(f"review unavailable: {type(exc).__name__}", frames=frames)
    if held is not None:
        video.stop()
        return _held(f"review held: {held.get('reason')}", frames=frames)
    try:
        joints = AttemptJointEvidence(
            work, task_id, run_id, lease, gate.assessment["library_sha256"],
            session_id=gate.assessment["session_id"], owner_io=config.get("io"),
        ).start()
    except (OSError, KeyError, TypeError, ValueError) as exc:
        video.stop()
        return _held(f"joint evidence unavailable: {type(exc).__name__}", frames=frames)

    started = time.time()
    steps: list[dict] = []
    folded_home = False
    released_at = parked_at = parked_wall_at = None
    release_boot_id = None
    result = _held("fixed carry not completed", steps=steps, frames=frames)
    try:
        for command in (f"load {library_path}", *FOLDED):
            if getattr(video, "status", "stopped") != "stopped":
                result = _held("video recording ended during carry", steps=steps, frames=frames)
                break
            if command != "park":
                folded_home = False
            status = gate.act(command)
            steps.append({"command": command, **status})
            if not joints.record(command, status):
                result = _held(f"joint state unavailable: {command}", steps=steps, frames=frames)
                break
            if getattr(video, "status", "stopped") != "stopped":
                result = _held("video recording ended during carry", steps=steps, frames=frames)
                break
            if (status.get("ok") is not True or status.get("contact") or status.get("fault")
                    or (command != f"load {library_path}" and status.get("settled") is not True)
                    or (command in ("run grasp_pick", "run lift_pick") and status.get("holding") is not True)):
                result = _held(f"command held: {command}", steps=steps, frames=frames)
                break
            if command == "run release_place":
                released_at = time.monotonic()
                release_boot_id = _boot_id()
            if command == "park":
                if not gate._settled_home(status, gate.assessment):
                    result = _held("folded home unconfirmed", steps=steps, frames=frames)
                    break
                folded_home = True
                parked_at = time.monotonic()
                parked_wall_at = time.time()
        else:
            depth_dir = work / "depth"
            depth_dir.mkdir(parents=True, exist_ok=True)
            raw_path = depth_dir / f"{run_id}-{uuid.uuid4().hex}-post-place.z16"
            captured = capture_top_depth_z16_receipt(
                "/dev/v4l/by-id/rosy-realsense-d435-depth", raw_path)
            receipt_path = raw_path.with_suffix(raw_path.suffix + ".receipt.json")
            receipt = captured[1] if captured else None
            raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest() if raw_path.is_file() else None
            receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest() if receipt_path.is_file() else None
            frames["post_place_depth"] = {
                "status": "rejected", "reason": "post-placement RGB pairing unavailable",
                "task_id": task_id, "run_id": run_id, "handoff_lease_id": lease,
                "site_id": _site_id(handoff["dst_site"]), "tier": handoff["tier"],
                "raw_path": str(raw_path), "raw_sha256": raw_sha,
                "receipt_path": str(receipt_path), "receipt_sha256": receipt_sha,
            }
            cell_attempts._fsync_directory(depth_dir)
            cell_attempts._fsync_directory(work)
            after = {name: cell.frame_receipt(name, previous=before[name]) for name in ("top", "side")}
            if (not parked_wall_at or any(
                    type(frame.get("source_stamp")) not in (int, float)
                    or not math.isfinite(frame["source_stamp"])
                    or frame["source_stamp"] <= parked_wall_at
                    for frame in after.values())):
                raise ValueError("post-park camera source frame unavailable")
            frames["after"] = {name: save_frame_receipt(
                work / "frames" / f"{uuid.uuid4().hex}-{name}-after.jpg", frame)
                for name, frame in after.items()}
            cell_attempts._fsync_directory(work / "frames")
            cell_attempts._fsync_directory(work)
            if (not isinstance(receipt, dict) or not release_boot_id or not parked_at
                    or not released_at or receipt.get("boot_id") != release_boot_id
                    or receipt.get("clock_semantics") != "v4l2_monotonic_start_of_exposure"
                    or receipt.get("raw_path") != str(raw_path)
                    or not isinstance(receipt.get("exposure_monotonic_s"), (int, float))
                    or not math.isfinite(receipt["exposure_monotonic_s"])
                    or receipt["exposure_monotonic_s"] <= max(released_at, parked_at)
                    or type(receipt.get("exposure_wall_estimate_s")) not in (int, float)
                    or not math.isfinite(receipt["exposure_wall_estimate_s"])
                    or type(receipt.get("wall_bridge_uncertainty_s")) not in (int, float)
                    or not 0 <= receipt["wall_bridge_uncertainty_s"] <= 0.25
                    or any(abs(frame["source_stamp"] - receipt["exposure_wall_estimate_s"])
                           + receipt["wall_bridge_uncertainty_s"] > 0.5 for frame in after.values())
                    or not raw_path.is_file() or not receipt_path.is_file()
                    or raw_sha != receipt.get("raw_sha256")
                    or json.loads(receipt_path.read_text(encoding="utf-8")) != receipt):
                frames["post_place_depth"].update(reason="post-placement Z16 provenance unavailable")
            else:
                frames["post_place_depth"] = {
                    "status": "captured", "task_id": task_id, "run_id": run_id,
                    "handoff_lease_id": lease, "site_id": _site_id(handoff["dst_site"]),
                    "tier": handoff["tier"], "release_monotonic_s": released_at,
                    "park_monotonic_s": parked_at, "boot_id": release_boot_id,
                    "raw_path": str(raw_path), "raw_sha256": receipt["raw_sha256"],
                    "receipt_path": str(receipt_path),
                    "receipt_sha256": receipt_sha,
                    "source_seq": receipt.get("source_seq"),
                    "exposure_monotonic_s": receipt["exposure_monotonic_s"],
                    "rgb_depth_clock_semantics": "host_source_stamp_near_depth_exposure_not_sensor_sync",
                }
            z_gate = {"verdict": "UNKNOWN", "failure_code": "S5_VIEW_OR_GATE_MISMATCH",
                      "reason": "post-placement Z16 frame has no independent calibrated height reference" if
                      frames["post_place_depth"]["status"] == "captured" else
                      "no provenance-bound post-placement Z16 frame"}
            verification = {"verified": False, "z_gate": z_gate,
                            "post_release_gate": evaluate_execution_gate("post_release", z_gate=z_gate),
                            "reason": z_gate["reason"]}
            result = {"result": "unverified_place", "task_verified": False,
                      "reason": "owner stop, torque and tier acceptance unverified",
                      "verification": verification, "steps": steps, "frames": frames}
    except Exception as exc:
        result = _held(f"carry interrupted: {type(exc).__name__}", steps=steps, frames=frames)
    try:
        frames["joints"] = joints.stop()
    except (OSError, ValueError) as exc:
        frames["joints"] = {"status": "incomplete", "reason": type(exc).__name__}
        result = _held("joint evidence incomplete", steps=steps, frames=frames)
    frames["during"] = video.stop()
    if result["result"] == "unverified_place" and frames["during"]["status"] != "stopped":
        result = _held("video evidence incomplete", steps=steps, frames=frames)
    if result["result"] == "held":
        frames["failure"] = {}
        for name in ("top", "side"):
            try:
                receipt = cell.frame_receipt(name, previous=before[name])
                saved = save_frame_receipt(
                    work / "frames" / f"{uuid.uuid4().hex}-{name}-failure.jpg", receipt)
                cell_attempts._fsync_directory(work / "frames")
                cell_attempts._fsync_directory(work)
                frames["failure"][name] = saved
            except Exception as exc:
                frames.setdefault("failure_errors", {})[name] = type(exc).__name__
        result["frames"] = frames
    result["simulation"] = {
        "basis": "model_only", "prediction": plan.get("sim_real_prediction"),
        "library_sha256": gate.assessment["library_sha256"],
        "comparison": {"verdict": "UNKNOWN", "reason": "real post-placement TCP and height unavailable"},
    }
    try:
        attempt_id = cell_attempts.finish_area_xyz(
            config, calibration, directive, gate.assessment, result, steps, frames,
            folded_home=folded_home, home=library["chunks"]["home"][-1], t_start=started)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _held(f"audit unavailable: {type(exc).__name__}", steps=steps, frames=frames)
    return {**result, "attempt_id": attempt_id, "pending_recovery": not folded_home}


def main(argv=None) -> int:
    """Explicitly supervised one-carry trial; never a Fleet completion entrypoint."""
    from cell_auto_setup import load_config
    from cell_pipeline_io import FifoCell
    from cell_robot_profile import bind_pipeline

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--handoff-json", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--handoff-lease-id", required=True)
    parser.add_argument("--commissioning", action="store_true")
    parser.add_argument("--person-at-switch", action="store_true")
    args = parser.parse_args(argv)
    if not args.commissioning or not args.person_at_switch:
        parser.error("one supervised carry requires --commissioning --person-at-switch")
    if not args.task_id.strip() or not args.handoff_lease_id.strip():
        parser.error("task and lease correlation must be explicit")
    try:
        handoff = json.loads(args.handoff_json.read_text(encoding="utf-8"))
        if (not isinstance(handoff, dict) or handoff.get("task_id") != args.task_id
                or handoff.get("handoff_lease_id") != args.handoff_lease_id):
            parser.error("handoff task and lease differ from the explicit command")
        config = load_config(args.config)
        config.pop("_commissioning", None)
        config.pop("_operating_profile_binding", None)
        if not config.get("operating_profile_path"):
            parser.error("a pinned per-device operating profile is required")
        config = bind_pipeline(config)
        if not isinstance(config.get("_operating_profile_binding"), dict):
            parser.error("per-device operating profile could not be bound")
        config["_commissioning"] = {"person_at_switch": True}
        cell = FifoCell(Path(config["io"]).expanduser(), config["cameras"],
                        operating_profile=config["_operating_profile_binding"])
        result = run_supervised_static(handoff, config, Path(config["calibration_path"]), cell)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = _held(f"supervised carry unavailable: {type(exc).__name__}")
    print(json.dumps(result, default=str))
    return 1  # A trial is never a verified task or Fleet release.


if __name__ == "__main__":
    sys.exit(main())
