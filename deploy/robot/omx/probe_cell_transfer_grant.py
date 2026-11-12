#!/usr/bin/env python3
"""C3b Cell Transfer Grant Builder & Placement Evaluator (`probe_cell_transfer_grant.py`).

Single Responsibility:
  - Builds validated `FleetCellTransferGrant` diagnostic payloads (`build_probe_grant`),
    records initial action rows (`create_probe_action`), and evaluates 6-DOF block placement
    accuracy (`evaluate_placement`) against C3b tolerances (`PLACE_TOL`).
"""
from __future__ import annotations

from datetime import timedelta
import math

WORKCELL_ID, INSTANCE_ID = "omx_cell_sim", "omx_cell_sim_01"
CALIBRATION = "omx-f-gazebo-only-v1"
TRANSFORM = "gz-world-is-link0-v1"
OPEN_TOL_RAD = 0.05
# Acceptance for one placement (C3b brief): upright, xy <= 5 mm, yaw <= 0.05 rad mod pi,
# block top within 2 mm of the expected top.
PLACE_TOL = {"xy_m": 0.005, "yaw_rad": 0.05, "top_z_m": 0.002, "tilt_rad": 0.05}


def build_probe_grant(job, cell, *, transfer_index, profile_revision, now, action_id):
    """Validated diagnostic authority; no RGB-D placeholders or Fleet approval claim."""
    from core_common.protocol.schemas import FleetCellTransferGrant
    from omx_adapter.action_api import action_grant_digest

    moves = [step for step in job.steps if step.kind != "pallet_done"]
    if (
        isinstance(transfer_index, bool)
        or not isinstance(transfer_index, int)
        or not 0 <= transfer_index < len(moves) // 2
    ):
        raise ValueError("transfer index must identify one compiled pair")
    pick, place = moves[2 * transfer_index : 2 * transfer_index + 2]
    if pick.kind != "pick" or place.kind != "place" or (pick.item, pick.pallet, pick.layer) != (
        place.item,
        place.pallet,
        place.layer,
    ):
        raise ValueError("transfer must be a matching compiled pick/place pair")
    value = {
        "mission_id": "c3b-mission",
        "step_id": f"c3b-step-{transfer_index}",
        "action_id": action_id,
        "attempt_id": "attempt-1",
        "request_digest": "0" * 64,
        "workcell_id": WORKCELL_ID,
        "instance_id": INSTANCE_ID,
        "action_kind": "CELL_TRANSFER",
        "cell_transfer": {
            "job_id": "c3b-omx-sim",
            "recipe_sha256": job.recipe_hash,
            "cell_sha256": job.cell_hash,
            "step_index": transfer_index,
            "item": pick.item,
            "pallet": pick.pallet,
            "layer": pick.layer,
            "frame": "robot_base",
            "home": vars(cell.home),
            "pick": vars(pick.target),
            "place": vars(place.target),
            "pick_approach_z": pick.approach_z,
            "place_approach_z": place.approach_z,
            "carry_z": job.carry_z,
        },
        "capability_revision": "cell-transfer-sim-v1",
        "config_revision": profile_revision,
        "authority_epoch": 1,
        "dispatch_generation": 1,
        "issued_at": now,
        "expires_at": now + timedelta(minutes=30),
    }
    value["request_digest"] = action_grant_digest(value)
    return FleetCellTransferGrant.model_validate(value)


def create_probe_action(store, grant):
    """Use the Cell journal shape: observation_id is empty, never synthetic RGB-D."""
    return store.create_action(
        workcell_id=grant.workcell_id,
        instance_id=grant.instance_id,
        principal_id="c3b-probe",
        request_key=grant.action_id,
        action_id=grant.action_id,
        action_kind=grant.action_kind,
        configuration_revision=grant.config_revision,
        observation_id="",
        owner_generation=grant.dispatch_generation,
        payload=grant.model_dump(mode="json"),
    )


def evaluate_placement(pose, target, *, height_m, grasp_depth_m):
    """Recheck every object's pose, including uprightness and height, after later motion."""
    from omx_adapter.kinematics import wrap_angle

    yaw_error = wrap_angle(pose["yaw"] - target["yaw"])
    if abs(yaw_error) > math.pi / 2:
        yaw_error = wrap_angle(yaw_error - math.pi)
    error = {
        "xy_m": math.hypot(pose["x"] - target["x"], pose["y"] - target["y"]),
        "dx_m": pose["x"] - target["x"],
        "dy_m": pose["y"] - target["y"],
        "top_z_m": pose["z"] + height_m / 2 - (target["z"] + grasp_depth_m),
        "yaw_rad_mod_pi": yaw_error,
        "tilt_rad": math.hypot(pose["roll"], pose["pitch"]),
    }
    ok = (
        error["xy_m"] <= PLACE_TOL["xy_m"]
        and abs(error["top_z_m"]) <= PLACE_TOL["top_z_m"]
        and abs(error["yaw_rad_mod_pi"]) <= PLACE_TOL["yaw_rad"]
        and error["tilt_rad"] <= PLACE_TOL["tilt_rad"]
    )
    return error, ok
