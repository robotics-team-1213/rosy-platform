#!/usr/bin/env python3
"""Rosy Cell C3: one CELL_TRANSFER in Gazebo through the single OMX owner (ROS-SIM only).

Run inside the container started by run_cell_sim.sh (docker exec). This process IS the one
owner process of the workcell (D-403 §8): it builds ArmCommandOwner from the simulation cell
profile, plans with AnalyticCellTransferPlanner, executes with PickPlaceRunner through
/arm_controller/follow_joint_trajectory, judges the gripper with gripper_contract, and reads
the block's Gazebo model pose (sim_model_pose) before and after.

Stand-ins, recorded in the output and the evidence README (C4 replaces them):
* The grant envelope is built locally. FleetActionGrant does not admit CELL_TRANSFER yet, so
  the probe validates a PICK_PLACE envelope and copies action_kind, as the C2 tests do. Its
  RGB-D evidence fields are placeholders; nothing in planning or verification reads them.
* The submission fence is always open (no Fleet stop producer in C3).
* Gripper readback = gripper_joint_1 position: a finger stopped above the closed target by
  more than CONTACT_RAD means an object is between the fingers.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(os.environ.get("ROSY_SIM_REPO", "/repo"))
# Appended, not prepended: every other import would otherwise stat the (slow) bind mount first.
for _part in ("src/contracts/foundation", "src/products/omx/adapter", "src/site/cell"):
    sys.path.append(str(REPO / _part))

WORKCELL_ID, INSTANCE_ID = "omx_cell_sim", "omx_cell_sim_01"
CALIBRATION = "omx-f-gazebo-only-v1"
TRANSFORM = "gz-world-is-link0-v1"
CONTACT_RAD = 0.08   # ~11 mm jaw gap; a 30 mm block stops the finger near 0.2 rad
OPEN_TOL_RAD = 0.05
SENSOR_REVISION = f"omx-sim-gripper-joint-position-v1:contact>{CONTACT_RAD}:open+-{OPEN_TOL_RAD}"


from cell_sim_tools import model_pose, refuse_second_owner, sha256_lf, sim_aid  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cell", default=str(REPO / "src/site/cell/examples/omx_sim/cell.yaml"))
    parser.add_argument("--recipe", default=str(REPO / "src/site/cell/examples/omx_sim/recipe.yaml"))
    parser.add_argument("--profile", default=str(REPO / "deploy/robot/omx/sim/cell_profile.yaml"))
    parser.add_argument("--world", default=str(REPO / "src/sim/gz_sim/worlds/omx_cell_workcell.sdf"))
    parser.add_argument("--transfer-index", type=int, default=0, help="index of the pick/place pair in the Job")
    parser.add_argument("--block-model", default="infeed_block")
    parser.add_argument("--grasp-depth", type=float, default=0.015,
                        help="TCP below the box top face for pick and place (m); Steps carry the top face")
    parser.add_argument("--submit-from", choices=("caller", "executor", "rebind"), default="caller",
                        help="caller = PickPlaceRunner as is; executor = run start/advance in the joint-state "
                             "callback group; rebind = probe stand-in that re-checks the start state and "
                             "rebinds source_state_sequence under the owner lock (see README)")
    parser.add_argument("--feedback-to-runner", choices=("all", "first"), default="all",
                        help="first = hand only the first RUNNING_FEEDBACK per phase to PickPlaceRunner")
    parser.add_argument("--sim-aid", choices=("none", "detachable-joint"), default="none",
                        help="SIM AID: attach block to link5 after the gripper readback proves a hold, "
                             "detach before release (friction grasp failed, see README)")
    parser.add_argument("--arm-start-tolerance", type=float, default=None,
                        help="stand-in: widen the arm joints' start-state tolerance (rad) for all phases")
    parser.add_argument("--journal-dir", default="/dev/shm/rosy-cell-c3",
                        help="SQLite phase journal; tmpfs because a /tmp write took 0.64 s inside the "
                             "ROS callback (run7) and starved the joint-state subscription")
    parser.add_argument("--out", required=True, help="directory for the JSON evidence")
    args = parser.parse_args()

    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("C3 probe requires localhost-only ROS discovery")
    if Path("/dev/serial/by-id").exists() or list(Path("/dev").glob("video*")):
        raise RuntimeError("C3 probe refuses hardware device grants")
    refuse_second_owner()

    import rclpy
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.clock import Clock, ClockType
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
    from omx_adapter.pick_place_runner import PhaseDispatch, PickPlaceRunner
    from omx_adapter.pose_plan import (
        AnalyticCellTransferPlanner, CellPlanningProfile, CellTransferPlanRejected, CellTransferRequest,
    )
    from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort
    from rosy_cell.cell import load_cell
    from rosy_cell.compiler import compile_job
    from rosy_cell.recipe import load_recipe

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict = {"schema": "rosy.cell-c3-transfer-probe.v1", "stand_ins": {
        "grant_envelope": "local PICK_PLACE-validated envelope with action_kind copied to CELL_TRANSFER; "
                          "RGB-D evidence fields are placeholders not read by planning/verification",
        "submission_fence": "always open; no Fleet stop producer in C3",
        "gripper_sensor": SENSOR_REVISION,
    }, "submit_from": args.submit_from, "feedback_to_runner": args.feedback_to_runner,
        "grasp_depth_m": args.grasp_depth, "events": []}
    log_lock = threading.Lock()

    def log(kind: str, **facts) -> None:
        entry = {"wall": time.time(), "kind": kind, **facts}
        with log_lock:
            evidence["events"].append(entry)
        print(json.dumps(entry, default=str), flush=True)

    def save() -> None:
        (out_dir / "c3-transfer.json").write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")

    kin = OmxKinematics.load()
    profile = CellPlanningProfile.load(args.profile)
    cell = load_cell(Path(args.cell).read_text(encoding="utf-8"))
    recipe = load_recipe(Path(args.recipe).read_text(encoding="utf-8"))
    job = compile_job(recipe, cell, tol_m=0.001)
    if not (cell.kinematics_revision == profile.kinematics_revision == kin.revision):
        raise RuntimeError("cell, profile and kinematics revisions disagree")
    moves = [step for step in job.steps if step.kind != "pallet_done"]
    pick, place = moves[2 * args.transfer_index], moves[2 * args.transfer_index + 1]
    if pick.kind != "pick" or place.kind != "place" or pick.item != "box":
        raise RuntimeError("selected transfer is not a box pick/place pair")
    evidence["revisions"] = {
        "profile_revision": profile.revision, "kinematics_revision": kin.revision,
        "cell_sha256": job.cell_hash, "recipe_sha256": job.recipe_hash,
        "world_sha256_lf": sha256_lf(Path(args.world)), "carry_z": job.carry_z,
        "planner_revision": AnalyticCellTransferPlanner.planner_revision,
    }
    evidence["step"] = {"transfer_index": args.transfer_index, "item": pick.item, "pallet": place.pallet,
                        "layer": place.layer, "pick": vars(pick.target), "place": vars(place.target),
                        "pick_approach_z": pick.approach_z, "place_approach_z": place.approach_z}
    log("job", transfer_index=args.transfer_index, place=vars(place.target), carry_z=job.carry_z)

    rclpy.init()
    node = Node("rosy_cell_c3_probe", parameter_overrides=[Parameter("use_sim_time", value=True)])
    config = profile.arm_command_config(workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID,
                                        calibration_revision=CALIBRATION)
    runtime = RosArmCommandRuntime(
        node, config, joint_state_topic="/joint_states",
        trajectory_action="/arm_controller/follow_joint_trajectory",
        on_goal_event=lambda event: (event.kind == "RUNNING_FEEDBACK") or log(
            "ros_goal_event", event=event.kind, command=event.command_id, phase=event.phase_id,
            status=event.status, result_code=event.result_code),
    )
    raw: dict = {}
    node.create_subscription(JointState, "/joint_states",
                             lambda m: raw.update(msg=m, wall=time.monotonic()),
                             qos_profile_sensor_data, callback_group=ReentrantCallbackGroup())
    queued: list = []
    queue_lock = threading.Lock()

    def pump() -> None:
        with queue_lock:
            jobs = queued[:]
            queued.clear()
        for fn, box in jobs:
            try:
                box["result"] = fn()
            except BaseException as exc:  # handed back to the caller thread
                box["error"] = exc
            box["done"].set()

    # Default (mutually exclusive) group = same group as the owner's joint-state subscription.
    node.create_timer(0.01, pump, clock=Clock(clock_type=ClockType.STEADY_TIME))
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    def call(fn):
        if args.submit_from == "caller":
            return fn()
        box = {"done": threading.Event()}
        with queue_lock:
            queued.append((fn, box))
        box["done"].wait(30.0)
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def sim_now() -> float:
        return node.get_clock().now().nanoseconds / 1e9

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

    exit_code = 1
    try:
        start = time.monotonic()
        while (runtime.latest_joint_state is None or not runtime.action_port.server_is_ready()
               or "msg" not in raw):
            if time.monotonic() - start > 120:
                raise RuntimeError("no joint states or action server within 120 s")
            time.sleep(0.1)
        if args.sim_aid != "none":
            # The world's DetachableJoint starts attached; free the block before any motion.
            evidence["sim_aid"] = {"kind": "gz DetachableJoint infeed_block::block <-> omx_f::link5",
                                   "label": "SIM AID, not a grasp", "detach_at_start": sim_aid("detach")}
            time.sleep(1.0)
        evidence["block_pose_initial"] = model_pose(args.block_model)
        evidence["joint_state_initial"] = raw_state()
        log("ready", owner=runtime.owner.state, block=evidence["block_pose_initial"])

        # 1. Move to the taught home with the gripper open (one joint-space goal, same owner).
        home = TopDownPose(cell.home.x, cell.home.y, cell.home.z, cell.home.yaw)
        home_q = kin.solve_top_down(home, profile.ik_limits()).joints
        target = dict(zip(ARM_JOINTS, home_q))
        target[profile.gripper_joint] = profile.gripper_open
        current = runtime.latest_joint_state
        delta = max(abs(target[n] - current.positions[n]) for n in config.joint_names)
        duration = max(3.0, 2.0 * delta / (min(profile.velocity_limits.values()) * profile.planning_limit_fraction))

        def submit_home():
            # The owner demands the exact latest joint-state sequence; at ~60 Hz joint states even
            # this short path lost the race once (run6). Bind under the owner lock (probe stand-in).
            with runtime.owner._lock:
                command = TrajectoryCommand(
                    workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID,
                    command_id=f"c3-home-{int(time.time())}", session_id=runtime.owner.session_id,
                    owner="rule_based", positions=target, duration_s=duration,
                    source_state_sequence=runtime.owner._joint_state.sequence,
                    calibration_revision=CALIBRATION, joint_names=config.joint_names,
                )
                return runtime.submit(command)

        t0, s0 = time.monotonic(), sim_now()
        decision = call(submit_home) if args.submit_from != "rebind" else submit_home()
        log("home_submit", decision=decision.reason, duration_s=duration)
        if not decision.accepted:
            raise RuntimeError(f"home goal rejected: {decision.reason}")
        state = wait_owner_idle(config.action_timeout_s + 30)
        settled = settle()
        evidence["home"] = {"target": target, "planned_s": duration, "wall_s": time.monotonic() - t0,
                            "sim_s": sim_now() - s0, "owner": state, "readback": settled}
        log("home_done", owner=state, gripper=settled["positions"].get(profile.gripper_joint),
            gripper_2=settled["positions"].get("gripper_joint_2"))
        if state != "ready":
            raise RuntimeError(f"owner after home: {state} {runtime.last_terminal_decision}")

        # 2. Plan the CELL_TRANSFER (Step poses are box top faces; the probe grasps grasp_depth lower).
        d = args.grasp_depth
        request = CellTransferRequest(
            job_id="c3-omx-sim", recipe_sha256=job.recipe_hash, cell_sha256=job.cell_hash,
            step_index=args.transfer_index, item=pick.item, home=home,
            pick=TopDownPose(pick.target.x, pick.target.y, pick.target.z - d, pick.target.yaw),
            place=TopDownPose(place.target.x, place.target.y, place.target.z - d, place.target.yaw),
            pick_approach_z=pick.approach_z, place_approach_z=place.approach_z, carry_z=job.carry_z,
        )
        planner = AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: job.cell_hash)
        try:
            plan = planner.plan_transfer(request, profile, snapshot())
        except CellTransferPlanRejected as exc:
            evidence["plan_rejected"] = {"reason": exc.reason, "detail": exc.detail}
            raise
        evidence["plan"] = {phase.phase_id: {"points": len(phase.points),
                                             "planned_s": phase.points[-1].time_from_start_s}
                            for phase in plan.phases}
        log("planned", phases=evidence["plan"])

        # 3. Grant envelope (stand-in) + journal.
        now = datetime.now(timezone.utc)
        placeholder = {
            "object_id": f"c3:{args.transfer_index}", "observation_id": "c3-no-observation",
            "frame_sha256": "0" * 64, "camera_identity": "none", "optical_frame_id": "none",
            "calibration_revision": CALIBRATION, "transform_revision": TRANSFORM,
            "capture_time_ns": time.time_ns(), "selector_kind": "point", "image_bbox_xyxy": [0, 0, 1, 1],
        }
        value = {
            "mission_id": "c3-mission", "step_id": f"c3-step-{args.transfer_index}",
            "action_id": f"c3-action-{int(time.time())}", "attempt_id": "attempt-1",
            "request_digest": "0" * 64, "workcell_id": WORKCELL_ID, "instance_id": INSTANCE_ID,
            "action_kind": "PICK_PLACE", "source_evidence": placeholder,
            "destination_evidence": {**placeholder, "object_id": f"c3:{args.transfer_index}:place"},
            "capability_revision": "cell-transfer-sim-v1", "config_revision": profile.revision,
            "observation_revision": "c3-no-observation", "authority_epoch": 1, "dispatch_generation": 1,
            "issued_at": now, "expires_at": now + timedelta(minutes=30),
        }
        value["request_digest"] = action_grant_digest(value)
        grant = FleetActionGrant.model_validate(value).model_copy(update={"action_kind": "CELL_TRANSFER"})
        grant = grant.model_copy(update={"request_digest": action_grant_digest(grant)})
        store = ActionStore(Path(args.journal_dir) / f"{grant.action_id}.sqlite3")
        store.create_action(
            workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID, principal_id="c3-probe",
            request_key=grant.action_id, action_id=grant.action_id, action_kind=grant.action_kind,
            configuration_revision=grant.config_revision, observation_id=grant.observation_revision,
            owner_generation=grant.dispatch_generation, payload=grant.model_dump(mode="json"),
        )
        store.begin_submission(grant.action_id, expected_generation=grant.dispatch_generation,
                               attempt_id=grant.attempt_id)
        recorder = ActionPhaseRecorder(store, action_id=grant.action_id, attempt_id=grant.attempt_id)

        class ProbeFence:
            def run_if_open(self, *, authority_epoch, dispatch_generation, fleet_fence_current, operation):
                if not fleet_fence_current():
                    raise LocalStopBlocked("fleet fence is not current")
                return operation()

            def is_open(self, *, authority_epoch, dispatch_generation):
                return True

        goal_port = RosArmPhaseGoalPort(runtime)
        starts = {phase.phase_id: dict(zip(phase.joint_names, phase.start_state_positions))
                  for phase in plan.phases}
        tolerances = profile.start_state_tolerances()
        if args.arm_start_tolerance is not None:
            # STAND-IN (labelled in evidence): the grip squeeze deflects joint4/joint5 by 0.02-0.33 rad
            # (runs 10/11/13/14), past the profile's 0.02 rad start tolerance for transfer.
            tolerances = {name: (args.arm_start_tolerance if name in ARM_JOINTS else value)
                          for name, value in tolerances.items()}
            evidence["stand_ins"]["arm_start_tolerance_rad"] = args.arm_start_tolerance

        class RebindingPort:
            """C3 stand-in, not production: PickPlaceRunner binds source_state_sequence before its
            journal writes, and ArmCommandOwner demands that exact sequence, so a joint state that
            lands in between rejects the phase (run1). Under the owner's lock this port repeats the
            runner's start-state check against the newest joint state and rebinds to it."""

            def submit(self, command, *, on_goal_event):
                owner = runtime.owner
                with owner._lock:  # blocks observe_joint_state for the few lines below
                    latest = owner._joint_state
                    for name, expected in starts[command.phase_id].items():
                        if name == profile.gripper_joint and command.phase_id in ("transfer", "release"):
                            continue
                        if abs(latest.positions[name] - expected) > tolerances[name]:
                            log("rebind_refused", phase=command.phase_id, joint=name)
                            return PhaseDispatch(dispatched=False)
                    log("rebind", phase=command.phase_id, planned_sequence=command.source_state_sequence,
                        latest_sequence=latest.sequence)
                    return goal_port.submit(replace(command, source_state_sequence=latest.sequence),
                                            on_goal_event=on_goal_event)

            def cancel_goal(self, driver_goal_id):
                return goal_port.cancel_goal(driver_goal_id)

        feedback_stats: dict = {}

        class MeasuringPort:
            """Times the runner's ROS event handling (it journals to SQLite in the ROS callback).
            With --feedback-to-runner first, RUNNING_FEEDBACK after the first per phase is
            acknowledged here and not handed to the runner (C3 stand-in, see README)."""

            def __init__(self, inner):
                self.inner = inner

            def submit(self, command, *, on_goal_event):
                stats = feedback_stats.setdefault(command.phase_id, {
                    "feedback_seen": 0, "feedback_to_runner": 0, "runner_s_total": 0.0, "runner_s_max": 0.0})

                def measured(event):
                    if event.kind == "RUNNING_FEEDBACK":
                        stats["feedback_seen"] += 1
                        if args.feedback_to_runner == "first" and stats["feedback_to_runner"]:
                            return True
                        stats["feedback_to_runner"] += 1
                    t = time.monotonic()
                    try:
                        return on_goal_event(event)
                    finally:
                        spent = time.monotonic() - t
                        stats["runner_s_total"] += spent
                        stats["runner_s_max"] = max(stats["runner_s_max"], spent)

                return self.inner.submit(command, on_goal_event=measured)

            def cancel_goal(self, driver_goal_id):
                return self.inner.cancel_goal(driver_goal_id)

        gates = {"approach": True, "grasp": False, "transfer": False, "release": False}
        runner = PickPlaceRunner(
            recorder, grant, plan,
            command_for_phase=lambda phase: TrajectoryCommand(
                workcell_id=WORKCELL_ID, instance_id=INSTANCE_ID,
                command_id=f"{grant.action_id}-{phase.phase_id}", session_id=runtime.owner.session_id,
                owner="rule_based", positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
                duration_s=phase.points[-1].time_from_start_s,
                source_state_sequence=phase.source_state_sequence, calibration_revision=CALIBRATION,
                joint_names=phase.joint_names, trajectory_points=phase.points, phase_id=phase.phase_id,
            ),
            goal_port=MeasuringPort(RebindingPort() if args.submit_from == "rebind" else goal_port),
            submission_fence=ProbeFence(),
            phase_gate=lambda phase_id: gates[phase_id],
            current_fence=lambda epoch, gen: (epoch, gen) == (grant.authority_epoch, grant.dispatch_generation),
            current_execution_state=snapshot, start_state_tolerances=tolerances,
            max_joint_state_age_s=profile.max_joint_state_age_s, cell_profile=profile,
        )

        def gripper_observation(phase_id: str) -> GripperObservation:
            js = runtime.latest_joint_state
            q = js.positions[profile.gripper_joint]
            if phase_id == "grasp":
                present = q > profile.gripper_closed + CONTACT_RAD
                return GripperObservation(WORKCELL_ID, INSTANCE_ID, SENSOR_REVISION, js.sequence, js.received_at,
                                          "CLOSED", present, request.item if present else None,
                                          grant.dispatch_generation)
            is_open = abs(q - profile.gripper_open) <= OPEN_TOL_RAD
            return GripperObservation(WORKCELL_ID, INSTANCE_ID, SENSOR_REVISION, js.sequence, js.received_at,
                                      "OPEN" if is_open else "UNKNOWN", False if is_open else None, None,
                                      grant.dispatch_generation)

        evidence["phases"] = {}
        for phase in plan.phases:
            pid = phase.phase_id
            if pid == "release" and args.sim_aid != "none":
                evidence["sim_aid"]["detach_before_release"] = sim_aid("detach")
                evidence["sim_aid"]["block_pose_at_detach"] = model_pose(args.block_model)
            gates[pid] = True
            t0, s0 = time.monotonic(), sim_now()
            try:
                call(runner.start if pid == "approach" else runner.advance)
            except Exception as exc:
                evidence["phases"][pid] = {"submit_error": f"{type(exc).__name__}: {exc}",
                                           "cause": repr(exc.__cause__), "journal": recorder.phases(),
                                           "parent": recorder.parent()}
                log("phase_submit_failed", phase=pid, error=str(exc), cause=repr(exc.__cause__))
                raise
            owner_state = wait_owner_idle(config.action_timeout_s + 30)
            row = next((r for r in recorder.phases() if r["phase_id"] == pid), None)
            settled = settle()
            record = {"planned_s": phase.points[-1].time_from_start_s, "wall_s": time.monotonic() - t0,
                      "sim_s": sim_now() - s0, "owner": owner_state,
                      "owner_decision": repr(runtime.last_terminal_decision),
                      "journal_state": row and row["state"],
                      "ros_events": dict(feedback_stats.get(pid, {})),
                      "gripper_joint_1": settled["positions"].get(profile.gripper_joint),
                      "gripper_joint_2": settled["positions"].get("gripper_joint_2"),
                      "block_pose": model_pose(args.block_model)}
            following = next((p for p in plan.phases if p.ordinal == phase.ordinal + 1), None)
            if following is not None:
                # Readback minus the next phase's planned start (the runner allows start_state_tolerance).
                record["next_start_deviation_rad"] = {
                    name: settled["positions"][name] - expected
                    for name, expected in zip(following.joint_names, following.start_state_positions)}
            evidence["phases"][pid] = record
            log("phase_done", phase=pid, **{k: v for k, v in record.items() if k != "block_pose"},
                block=record["block_pose"])
            if owner_state != "ready" or not row or row["state"] != "SUCCEEDED":
                raise RuntimeError(f"{pid} did not succeed: owner={owner_state} journal={row and row['state']}")
            if pid == "transfer":
                # Not required by D-402 §8 (held is checked only after grasp); without it a block
                # dropped in transit passes every gate (run8). Same position sensor, same contract.
                obs = gripper_observation("grasp")
                record["gripper_observation_before_release"] = vars(obs)
                try:
                    verify_held_object(obs, object_id=request.item, now=time.monotonic(),
                                       max_age_s=profile.max_joint_state_age_s)
                except GripperReadbackError as exc:
                    record["held_before_release_rejected"] = str(exc)
                    recorder.hold(reason="GRIPPER_OBJECT_LOST_IN_TRANSFER")
                    raise
            if pid == "grasp":
                obs = gripper_observation(pid)
                record["gripper_observation"] = vars(obs)
                try:
                    receipt = verify_held_object(obs, object_id=request.item, now=time.monotonic(),
                                                 max_age_s=profile.max_joint_state_age_s)
                    record["hold_receipt"] = vars(receipt)
                    if args.sim_aid != "none":
                        # Triggered only by a gripper readback that already proved a hold.
                        evidence["sim_aid"]["attach_after_hold"] = sim_aid("attach")
                        evidence["sim_aid"]["block_pose_at_attach"] = model_pose(args.block_model)
                        if not evidence["sim_aid"]["attach_after_hold"]["confirmed"]:
                            recorder.hold(reason="SIM_AID_ATTACH_UNCONFIRMED")
                            raise RuntimeError("sim aid attach was not confirmed")
                except GripperReadbackError as exc:
                    record["hold_rejected"] = str(exc)
                    recorder.hold(reason="GRIPPER_HOLD_NOT_PROVEN")
                    raise
            if pid == "release":
                obs = gripper_observation(pid)
                record["gripper_observation"] = vars(obs)
                receipt = verify_released_object(obs, object_id=request.item, now=time.monotonic(),
                                                 max_age_s=profile.max_joint_state_age_s)
                record["release_receipt"] = vars(receipt)

        time.sleep(1.0)
        final = model_pose(args.block_model)
        box_h = recipe.box.height
        target_centre = (place.target.x, place.target.y, place.target.z - box_h / 2)
        yaw_err = wrap_angle(final["yaw"] - place.target.yaw)
        if abs(yaw_err) > math.pi / 2:  # the box is symmetric under 180 deg (D-402 §5)
            yaw_err = wrap_angle(yaw_err - math.pi)
        evidence["block_pose_final"] = final
        evidence["placement_error"] = {
            "xy_m": math.hypot(final["x"] - target_centre[0], final["y"] - target_centre[1]),
            "dx_m": final["x"] - target_centre[0], "dy_m": final["y"] - target_centre[1],
            "z_m": final["z"] - target_centre[2], "yaw_rad_mod_pi": yaw_err,
            "tilt_rad": math.hypot(final["roll"], final["pitch"]),
        }
        evidence["journal"] = {"parent": recorder.parent(), "phases": recorder.phases()}
        error = evidence["placement_error"]
        # item_at_pose-style judgement (D-403 §5); tolerances are C3 probe values, not a contract.
        evidence["placement_tolerance"] = {"xy_m": 0.01, "z_m": 0.005, "yaw_rad": 0.1, "tilt_rad": 0.1}
        evidence["placement_ok"] = (error["xy_m"] <= 0.01 and abs(error["z_m"]) <= 0.005
                                    and abs(error["yaw_rad_mod_pi"]) <= 0.1 and error["tilt_rad"] <= 0.1)
        log("placement", ok=evidence["placement_ok"], **error)
        exit_code = 0 if evidence["placement_ok"] else 2
    except Exception as exc:
        evidence["failure"] = f"{type(exc).__name__}: {exc}"
        log("failure", error=evidence["failure"], owner=runtime.owner.state,
            decision=repr(runtime.last_terminal_decision))
        try:
            evidence["block_pose_at_failure"] = model_pose(args.block_model)
        except Exception:
            pass
    finally:
        evidence["owner_final"] = {"state": runtime.owner.state, "last": repr(runtime.last_terminal_decision)}
        evidence["ros_event_stats"] = locals().get("feedback_stats")
        save()
        executor.shutdown()
        runtime.destroy()
        node.destroy_node()
        rclpy.shutdown()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
