"""Canonical phase intent encoding shared by the coordinator and its journal."""
import hashlib
import json


def phase_command_digest(command, phase, plan, state, tolerances):
    document = {
        "command_id": command.command_id,
        "phase_id": phase.phase_id,
        "ordinal": phase.ordinal,
        "joint_names": command.joint_names,
        "points": [
            {
                "time_from_start_s": point.time_from_start_s,
                "positions": point.positions,
                "velocities": point.velocities,
                "accelerations": point.accelerations,
            }
            for point in command.trajectory_points
        ],
        "planned_source_state_sequence": phase.source_state_sequence,
        "execution_state_sequence": state.sequence,
        "execution_joint_positions": dict(state.joint_positions),
        "start_state_positions": phase.start_state_positions,
        "start_state_tolerances": tolerances,
        "calibration_revision": phase.calibration_revision,
        "transform_revision": phase.transform_revision,
        "planning_scene_revision": phase.planning_scene_revision,
        "planner_revision": plan.planner_revision,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
