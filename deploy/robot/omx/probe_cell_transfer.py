#!/usr/bin/env python3
"""Rosy Cell C3b: CELL_TRANSFERs in Gazebo through the single OMX owner (ROS-SIM only).

Run inside the container started by run_cell_sim.sh (docker exec). This process IS the one
owner process of the workcell (D-403 §8): it builds ArmCommandOwner from the simulation cell
profile (sim-time owner clock with a wall-clock bound), plans with
AnalyticCellTransferPlanner, executes with PickPlaceRunner through
/arm_controller/follow_joint_trajectory, judges the gripper with gripper_contract, and reads
each block's Gazebo model pose before and after.

C3 probe workarounds are gone: no rebinding port, no feedback filter, no widened arm
tolerance, no grasp-depth flag, no probe-side hold re-check (the owner window, bounded
feedback journaling, profile tolerances, recipe grasp_depth and the runner do it).

What remains, labelled in the evidence:
* SIM AID: the world's DetachableJoint attaches a block to link5 only after the gripper
  readback proved a hold, and detaches it right before release (operator decision: no
  friction-grasp tuning). Repeat transfers spawn the next block at the infeed (sim staging).
* SIM GRIPPER SENSOR: gripper_joint_1 position. Held = the finger stopped at least half the
  squeeze margin above the width-matched close target; open = within 0.05 rad of open.
* C4 scope, not motion: the grant envelope is built locally (FleetActionGrant does not admit
  CELL_TRANSFER yet; RGB-D fields are unread placeholders) and the stop fence is always open.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("ROSY_SIM_REPO", "/repo"))
# Appended, not prepended: every other import would otherwise stat the (slow) bind mount first.
for _part in ("src/contracts/foundation", "src/products/omx/adapter", "src/site/cell"):
    sys.path.append(str(REPO / _part))

WORKCELL_ID, INSTANCE_ID = "omx_cell_sim", "omx_cell_sim_01"
CALIBRATION = "omx-f-gazebo-only-v1"
TRANSFORM = "gz-world-is-link0-v1"
OPEN_TOL_RAD = 0.05
# Acceptance for one placement (C3b brief): upright, xy <= 5 mm, yaw <= 0.05 rad mod pi,
# block top within 2 mm of the expected top.
PLACE_TOL = {"xy_m": 0.005, "yaw_rad": 0.05, "top_z_m": 0.002, "tilt_rad": 0.05}

from cell_sim_tools import (  # noqa: E402
    SimAid, model_pose, refuse_second_owner, sha256_lf, spawn_infeed_block,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cell", default=str(REPO / "src/site/cell/examples/omx_sim/cell.yaml"))
    parser.add_argument("--recipe", default=str(REPO / "src/site/cell/examples/omx_sim/recipe.yaml"))
    parser.add_argument("--profile", default=str(REPO / "deploy/robot/omx/sim/cell_profile.yaml"))
    parser.add_argument("--world", default=str(REPO / "src/sim/gz_sim/worlds/omx_cell_workcell_sim_aid.sdf"))
    parser.add_argument("--transfers", default="3",
                        help="comma-separated Job transfer indices, run in this order")
    parser.add_argument("--journal-dir", default="/tmp/rosy-cell-c3b",
                        help="SQLite phase journal (overlay /tmp: C3 needed tmpfs, C3b must not)")
    parser.add_argument("--out", required=True, help="directory for the JSON evidence")
    args = parser.parse_args()

    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("C3 probe requires localhost-only ROS discovery")
    if Path("/dev/serial/by-id").exists() or list(Path("/dev").glob("video*")):
        raise RuntimeError("C3 probe refuses hardware device grants")
    refuse_second_owner()

    import rclpy
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import JointState

    from core_common.protocol.schemas import FleetActionGrant
    from omx_adapter.action_api import action_grant_digest
    from omx_adapter.action_store import ActionStore
    from omx_adapter.command_owner import TrajectoryCommand
    from omx_adapter.gripper_contract import (
        GripperObservation, GripperReadbackError, verify_held_object, verify_released_object,
    )
    from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose, wrap_angle
    from omx_adapter.local_stop import LocalStopBlocked
    from omx_adapter.manipulation_plan import ExecutionStateSnapshot
    from omx_adapter.phase_recorder import ActionPhaseRecorder
    from omx_adapter.pick_place_runner import PickPlaceRunner
    from omx_adapter.pose_plan import (
        AnalyticCellTransferPlanner, CellPlanningProfile, CellTransferPlanRejected, CellTransferRequest,
    )
    from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort
    from rosy_cell.cell import load_cell
    from rosy_cell.compiler import compile_job
    from rosy_cell.recipe import load_recipe

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    kin = OmxKinematics.load()
    profile = CellPlanningProfile.load(args.profile)
    cell = load_cell(Path(args.cell).read_text(encoding="utf-8"))
    recipe = load_recipe(Path(args.recipe).read_text(encoding="utf-8"))
    job = compile_job(recipe, cell, tol_m=0.001)
    if not (cell.kinematics_revision == profile.kinematics_revision == kin.revision):
        raise RuntimeError("cell, profile and kinematics revisions disagree")
    box = recipe.box
    close_q = profile.gripper_close_for_width(box.width)
    contact_q = profile.gripper_contact_for_width(box.width)
    held_threshold = (contact_q - close_q) / 2
    sensor_revision = (f"omx-sim-gripper-joint-position-v2:held>=close{close_q:.4f}+{held_threshold:.4f}"
                       f":open+-{OPEN_TOL_RAD}")
    evidence: dict = {
        "schema": "rosy.cell-c3b-transfer-probe.v1",
        "labelled": {
            "sim_aid": "gz DetachableJoint parent omx_f::link5 -> child <block>::block, added at runtime "
                       "only after the gripper readback proved a hold, detached right before release; "
                       "repeat blocks spawned at the infeed",
            "sim_gripper_sensor": sensor_revision,
            "c4_scope_not_motion": "local PICK_PLACE-validated grant envelope with action_kind "
                                   "CELL_TRANSFER (RGB-D fields unread placeholders); stop fence open",
        },
        "revisions": {
            "profile_revision": profile.revision, "kinematics_revision": kin.revision,
            "cell_sha256": job.cell_hash, "recipe_sha256": job.recipe_hash,
            "world_sha256_lf": sha256_lf(Path(args.world)), "carry_z": job.carry_z,
            "planner_revision": AnalyticCellTransferPlanner.planner_revision,
        },
        "gripper": {"width_m": box.width, "squeeze_m": profile.gripper_squeeze_m,
                    "close_target": close_q, "contact_model": contact_q, "held_threshold": held_threshold},
        "events": [], "transfers": [],
    }
    log_lock = threading.Lock()

    def log(kind: str, **facts) -> None:
        entry = {"wall": time.time(), "kind": kind, **facts}
        with log_lock:
            evidence["events"].append(entry)
        print(json.dumps(entry, default=str), flush=True)

    def save() -> None:
        (out_dir / "c3b-transfer.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")

    moves = [step for step in job.steps if step.kind != "pallet_done"]
    indices = [int(value) for value in args.transfers.split(",")]
    for index in indices:
        pick, place = moves[2 * index], moves[2 * index + 1]
        if pick.kind != "pick" or place.kind != "place" or pick.item != "box":
            raise RuntimeError(f"transfer {index} is not a box pick/place pair")
        if (pick.target.x, pick.target.y) != (moves[0].target.x, moves[0].target.y):
            raise RuntimeError("box picks must all come from the infeed")

    rclpy.init()
    node = Node("rosy_cell_c3b_probe", parameter_overrides=[Parameter("use_sim_time", value=True)])
    config = profile.arm_command_config(workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID,
                                        calibration_revision=CALIBRATION)
    runtime = RosArmCommandRuntime(
        node, config, joint_state_topic="/joint_states",
        trajectory_action="/arm_controller/follow_joint_trajectory", owner_clock="sim",
        on_goal_event=lambda event: (event.kind == "RUNNING_FEEDBACK") or log(
            "ros_goal_event", event=event.kind, command=event.command_id, phase=event.phase_id,
            status=event.status, result_code=event.result_code),
    )
    clock = runtime.monotonic  # sim time, the owner's clock
    raw: dict = {}
    # Observation only (velocities for settling); the owner has its own subscription.
    node.create_subscription(JointState, "/joint_states", lambda m: raw.update(msg=m),
                             qos_profile_sensor_data, callback_group=ReentrantCallbackGroup())
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    def raw_state() -> dict:
        msg = raw["msg"]
        return {"positions": dict(zip(msg.name, msg.position)), "velocities": dict(zip(msg.name, msg.velocity))}

    def settle(limit_s: float = 20.0) -> dict:
        start, calm = time.monotonic(), 0
        while time.monotonic() - start < limit_s:
            if "msg" in raw and max(abs(v) for v in raw_state()["velocities"].values() or [0.0]) < 0.01:
                calm += 1
                if calm >= 10:
                    break
            else:
                calm = 0
            time.sleep(0.05)
        return raw_state()

    def snapshot() -> ExecutionStateSnapshot:
        js = runtime.latest_joint_state
        return ExecutionStateSnapshot(
            sequence=js.sequence, joint_positions=dict(js.positions), calibration_revision=CALIBRATION,
            transform_revision=TRANSFORM, planning_scene_revision=kin.planning_scene_revision,
            observed_at_monotonic_s=js.received_at,
        )

    def wait_owner_idle(limit_s: float) -> str:
        start = time.monotonic()
        while time.monotonic() - start < limit_s:
            if runtime.owner.state != "active":
                return runtime.owner.state
            time.sleep(0.05)
        return "timeout"

    def gripper_observation(expect: str) -> GripperObservation:
        """SIM GRIPPER SENSOR (labelled): finger position against the width-matched target."""
        js = runtime.latest_joint_state
        q = js.positions[profile.gripper_joint]
        if expect == "held":
            present = q >= close_q + held_threshold
            return GripperObservation(WORKCELL_ID, INSTANCE_ID, sensor_revision, js.sequence, js.received_at,
                                      "CLOSED", present, "box" if present else None, 1)
        is_open = abs(q - profile.gripper_open) <= OPEN_TOL_RAD
        return GripperObservation(WORKCELL_ID, INSTANCE_ID, sensor_revision, js.sequence, js.received_at,
                                  "OPEN" if is_open else "UNKNOWN", False if is_open else None, None, 1)

    class ProbeFence:  # C4 scope: no Fleet stop producer in C3
        def run_if_open(self, *, authority_epoch, dispatch_generation, fleet_fence_current, operation):
            if not fleet_fence_current():
                raise LocalStopBlocked("fleet fence is not current")
            return operation()

        def is_open(self, *, authority_epoch, dispatch_generation):
            return True

    aid = SimAid()

    def sim_rtf(sim_s: float, wall_s: float) -> float | None:
        return round(sim_s / wall_s, 3) if wall_s > 0 else None

    exit_code = 1
    try:
        start = time.monotonic()
        while runtime.latest_joint_state is None or not runtime.action_port.server_is_ready() or "msg" not in raw:
            if time.monotonic() - start > 120:
                raise RuntimeError("no joint states or action server within 120 s")
            time.sleep(0.1)
        evidence["joint_state_initial"] = raw_state()

        # 1. Home with the gripper open: one joint-space goal through the same owner, with the
        #    owner start window (A1) instead of an exact joint-state sequence.
        home = TopDownPose(cell.home.x, cell.home.y, cell.home.z, cell.home.yaw)
        home_q = kin.solve_top_down(home, profile.ik_limits()).joints
        target = dict(zip(ARM_JOINTS, home_q))
        target[profile.gripper_joint] = profile.gripper_open
        current = runtime.latest_joint_state
        delta = max(abs(target[n] - current.positions[n]) for n in config.joint_names)
        duration = max(3.0, 2.0 * delta / (min(profile.velocity_limits.values()) * profile.planning_limit_fraction))
        command = TrajectoryCommand(
            workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID, command_id=f"c3b-home-{int(time.time())}",
            session_id=runtime.owner.session_id, owner="rule_based", positions=target, duration_s=duration,
            source_state_sequence=current.sequence, calibration_revision=CALIBRATION,
            joint_names=config.joint_names,
            start_state_window={n: (current.positions[n], profile.start_state_tolerance_rad)
                                for n in config.joint_names},
        )
        t0, s0 = time.monotonic(), clock()
        decision = runtime.submit(command)
        log("home_submit", decision=decision.reason, duration_s=duration)
        if not decision.accepted:
            raise RuntimeError(f"home goal rejected: {decision.reason}")
        state = wait_owner_idle(config.action_timeout_s * config.wall_clock_bound_factor + 30)
        settled = settle()
        wall_s, sim_s = time.monotonic() - t0, clock() - s0
        evidence["home"] = {"planned_s": duration, "wall_s": wall_s, "sim_s": sim_s, "rtf": sim_rtf(sim_s, wall_s),
                            "owner": state, "readback": settled}
        log("home_done", owner=state, sim_s=sim_s, wall_s=wall_s)
        if state != "ready":
            raise RuntimeError(f"owner after home: {state} {runtime.last_terminal_decision}")

        planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: job.cell_hash, monotonic=clock)
        for run_no, index in enumerate(indices):
            pick, place = moves[2 * index], moves[2 * index + 1]
            block = "infeed_block" if run_no == 0 else f"infeed_block_{run_no}"
            record: dict = {"transfer_index": index, "block_model": block, "place": vars(place.target),
                            "pick": vars(pick.target), "layer": place.layer, "pallet": place.pallet}
            evidence["transfers"].append(record)
            if run_no:
                # Stage the next block at the infeed (sim staging, labelled).
                top = cell.station_pose(recipe.pick_station)
                record["spawn"] = spawn_infeed_block(block, (top[0], top[1], top[2] - box.height / 2), top[3],
                                                     (box.length, box.width, box.height), box.mass_kg)
                time.sleep(2.0)
            aid.watch(block)
            aid._robot_entity_id()  # resolve once, before any motion
            record["block_pose_initial"] = model_pose(block)

            request = CellTransferRequest(
                job_id="c3b-omx-sim", recipe_sha256=job.recipe_hash, cell_sha256=job.cell_hash,
                step_index=index, item=pick.item, home=home,
                pick=TopDownPose(pick.target.x, pick.target.y, pick.target.z, pick.target.yaw),
                place=TopDownPose(place.target.x, place.target.y, place.target.z, place.target.yaw),
                pick_approach_z=pick.approach_z, place_approach_z=place.approach_z, carry_z=job.carry_z,
                grasp_depth_m=box.grasp_depth, grasp_width_m=box.width,
            )
            try:
                plan = planner.plan_transfer(request, profile, snapshot())
            except CellTransferPlanRejected as exc:
                record["plan_rejected"] = {"reason": exc.reason, "detail": exc.detail}
                raise
            record["plan"] = {p.phase_id: {"points": len(p.points), "planned_s": p.points[-1].time_from_start_s}
                              for p in plan.phases}
            log("planned", transfer=index, phases=record["plan"])

            now = datetime.now(timezone.utc)
            placeholder = {
                "object_id": f"c3b:{index}", "observation_id": "c3b-no-observation",
                "frame_sha256": "0" * 64, "camera_identity": "none", "optical_frame_id": "none",
                "calibration_revision": CALIBRATION, "transform_revision": TRANSFORM,
                "capture_time_ns": time.time_ns(), "selector_kind": "point", "image_bbox_xyxy": [0, 0, 1, 1],
            }
            value = {
                "mission_id": "c3b-mission", "step_id": f"c3b-step-{index}",
                "action_id": f"c3b-action-{index}-{int(time.time())}", "attempt_id": "attempt-1",
                "request_digest": "0" * 64, "workcell_id": WORKCELL_ID, "instance_id": INSTANCE_ID,
                "action_kind": "PICK_PLACE", "source_evidence": placeholder,
                "destination_evidence": {**placeholder, "object_id": f"c3b:{index}:place"},
                "capability_revision": "cell-transfer-sim-v1", "config_revision": profile.revision,
                "observation_revision": "c3b-no-observation", "authority_epoch": 1, "dispatch_generation": 1,
                "issued_at": now, "expires_at": now + timedelta(minutes=30),
            }
            value["request_digest"] = action_grant_digest(value)
            grant = FleetActionGrant.model_validate(value).model_copy(update={"action_kind": "CELL_TRANSFER"})
            grant = grant.model_copy(update={"request_digest": action_grant_digest(grant)})
            store = ActionStore(Path(args.journal_dir) / f"{grant.action_id}.sqlite3")
            store.create_action(
                workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID, principal_id="c3b-probe",
                request_key=grant.action_id, action_id=grant.action_id, action_kind=grant.action_kind,
                configuration_revision=grant.config_revision, observation_id=grant.observation_revision,
                owner_generation=grant.dispatch_generation, payload=grant.model_dump(mode="json"),
            )
            store.begin_submission(grant.action_id, expected_generation=grant.dispatch_generation,
                                   attempt_id=grant.attempt_id)
            recorder = ActionPhaseRecorder(store, action_id=grant.action_id, attempt_id=grant.attempt_id)
            runner = PickPlaceRunner(
                recorder, grant, plan,
                command_for_phase=lambda phase, grant=grant: TrajectoryCommand(
                    workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID,
                    command_id=f"{grant.action_id}-{phase.phase_id}", session_id=runtime.owner.session_id,
                    owner="rule_based", positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
                    duration_s=phase.points[-1].time_from_start_s,
                    source_state_sequence=phase.source_state_sequence, calibration_revision=CALIBRATION,
                    joint_names=phase.joint_names, trajectory_points=phase.points, phase_id=phase.phase_id,
                ),
                goal_port=RosArmPhaseGoalPort(runtime), submission_fence=ProbeFence(),
                phase_gate=lambda phase_id: True,
                current_fence=lambda epoch, gen, grant=grant: (epoch, gen) == (grant.authority_epoch,
                                                                                grant.dispatch_generation),
                current_execution_state=snapshot, start_state_tolerances=profile.start_state_tolerances(),
                max_joint_state_age_s=profile.max_joint_state_age_s, monotonic=clock, cell_profile=profile,
                gripper_readback=lambda: gripper_observation("held"), held_object_id=pick.item,
            )
            record["phases"] = {}
            for phase in plan.phases:
                pid = phase.phase_id
                if pid == "release":
                    record["sim_aid_detach_before_release"] = aid.detach(block)
                    record["block_pose_at_detach"] = model_pose(block)
                t0, s0 = time.monotonic(), clock()
                try:
                    (runner.start if pid == "approach" else runner.advance)()
                except Exception as exc:
                    record["phases"][pid] = {"submit_error": f"{type(exc).__name__}: {exc}",
                                             "cause": repr(exc.__cause__), "journal": recorder.phases(),
                                             "parent": recorder.parent(),
                                             "gripper_joint_1": runtime.latest_joint_state.positions.get(
                                                 profile.gripper_joint)}
                    log("phase_submit_failed", transfer=index, phase=pid, error=str(exc), cause=repr(exc.__cause__))
                    raise
                owner_state = wait_owner_idle(config.action_timeout_s * config.wall_clock_bound_factor + 30)
                row = next((r for r in recorder.phases() if r["phase_id"] == pid), None)
                settled = settle()
                wall_s, sim_s = time.monotonic() - t0, clock() - s0
                result = row.get("result") if row else None
                entry = {"planned_s": phase.points[-1].time_from_start_s, "wall_s": wall_s, "sim_s": sim_s,
                         "rtf": sim_rtf(sim_s, wall_s), "owner": owner_state,
                         "owner_decision": repr(runtime.last_terminal_decision),
                         "journal_state": row and row["state"], "journal_result": result,
                         "gripper_joint_1": settled["positions"].get(profile.gripper_joint),
                         "gripper_joint_2": settled["positions"].get("gripper_joint_2"),
                         "gripper_target": phase.points[-1].positions[-1],
                         "block_pose": model_pose(block),
                         # Earlier blocks of this run: any change is a neighbour disturbance.
                         "placed_blocks": {t["block_model"]: model_pose(t["block_model"])
                                           for t in evidence["transfers"][:-1]}}
                following = next((p for p in plan.phases if p.ordinal == phase.ordinal + 1), None)
                if following is not None:
                    # Readback minus the next phase's planned start: wrist deflection under load (A5).
                    entry["next_start_deviation_rad"] = {
                        name: settled["positions"][name] - expected
                        for name, expected in zip(following.joint_names, following.start_state_positions)}
                record["phases"][pid] = entry
                log("phase_done", transfer=index, phase=pid,
                    **{k: v for k, v in entry.items() if k not in ("block_pose", "owner_decision", "placed_blocks")})
                if owner_state != "ready" or not row or row["state"] != "SUCCEEDED":
                    raise RuntimeError(f"{pid} did not succeed: owner={owner_state} journal={row and row['state']}")
                if pid == "grasp":
                    obs = gripper_observation("held")
                    entry["gripper_observation"] = vars(obs)
                    try:
                        entry["hold_receipt"] = vars(verify_held_object(
                            obs, object_id=pick.item, now=clock(), max_age_s=profile.max_joint_state_age_s))
                    except GripperReadbackError as exc:
                        entry["hold_rejected"] = str(exc)
                        recorder.hold(reason="GRIPPER_HOLD_NOT_PROVEN")
                        raise
                    # SIM AID: triggered only by a readback that already proved the hold.
                    record["sim_aid_attach_after_hold"] = aid.attach(block)
                    if not record["sim_aid_attach_after_hold"]["confirmed"]:
                        recorder.hold(reason="SIM_AID_ATTACH_UNCONFIRMED")
                        raise RuntimeError("sim aid attach was not confirmed")
                    time.sleep(1.0)
                    after = settle()
                    entry["after_attach"] = {
                        "gripper_joint_1": after["positions"].get(profile.gripper_joint),
                        "gripper_joint_2": after["positions"].get("gripper_joint_2"),
                        "block_pose": model_pose(block)}
                if pid == "transfer":
                    entry["gripper_observation_before_release"] = vars(gripper_observation("held"))
                if pid == "release":
                    obs = gripper_observation("open")
                    entry["gripper_observation"] = vars(obs)
                    entry["release_receipt"] = vars(verify_released_object(
                        obs, object_id=pick.item, now=clock(), max_age_s=profile.max_joint_state_age_s))

            time.sleep(1.0)
            final = model_pose(block)
            top_expected = place.target.z + box.grasp_depth
            yaw_err = wrap_angle(final["yaw"] - place.target.yaw)
            if abs(yaw_err) > math.pi / 2:  # the box is symmetric under 180 deg (D-402 §5)
                yaw_err = wrap_angle(yaw_err - math.pi)
            error = {
                "xy_m": math.hypot(final["x"] - place.target.x, final["y"] - place.target.y),
                "dx_m": final["x"] - place.target.x, "dy_m": final["y"] - place.target.y,
                "top_z_m": final["z"] + box.height / 2 - top_expected, "yaw_rad_mod_pi": yaw_err,
                "tilt_rad": math.hypot(final["roll"], final["pitch"]),
            }
            record["block_pose_final"] = final
            # Re-judge every earlier block: a later transfer may have pushed it.
            record["placed_blocks_after"] = {}
            for earlier in evidence["transfers"][:-1]:
                pose = model_pose(earlier["block_model"])
                target = earlier["place"]
                record["placed_blocks_after"][earlier["block_model"]] = {
                    "pose": pose, "xy_m": math.hypot(pose["x"] - target["x"], pose["y"] - target["y"])}
            record["placement_error"] = error
            record["placement_ok"] = (error["xy_m"] <= PLACE_TOL["xy_m"] and abs(error["top_z_m"]) <= PLACE_TOL["top_z_m"]
                                      and abs(error["yaw_rad_mod_pi"]) <= PLACE_TOL["yaw_rad"]
                                      and error["tilt_rad"] <= PLACE_TOL["tilt_rad"])
            record["journal"] = {"parent": recorder.parent(), "phases": recorder.phases()}
            log("placement", transfer=index, ok=record["placement_ok"], **error)
            save()
            if not record["placement_ok"]:
                break
        evidence["placement_tolerance"] = PLACE_TOL
        undisturbed = all(entry["xy_m"] <= PLACE_TOL["xy_m"]
                          for entry in evidence["transfers"][-1].get("placed_blocks_after", {}).values())
        evidence["earlier_blocks_undisturbed"] = undisturbed
        exit_code = 0 if all(t.get("placement_ok") for t in evidence["transfers"]) and undisturbed and \
            len(evidence["transfers"]) == len(indices) else 2
    except Exception as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        log("failure", error=evidence["failure"], owner=runtime.owner.state,
            decision=repr(runtime.last_terminal_decision))
    finally:
        evidence["owner_final"] = {"state": runtime.owner.state, "last": repr(runtime.last_terminal_decision)}
        save()
        executor.shutdown()
        runtime.destroy()
        node.destroy_node()
        rclpy.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
