"""sim_model_pose goal-evidence producer for the OMX simulation cell (D-403 §5, C4b G6).

The producer reads where Gazebo has the item and the gripper release readback, and reports
both. It never judges the goal: Fleet compares the pose with the step predicate. It imports
neither the owner nor Fleet. Wave 1 provides the interface and the Gazebo reader; posting to
Fleet's goal-evidence endpoint with the producer's own token is wave 2 wiring.
"""

from __future__ import annotations

import uuid
from typing import Callable, Mapping, Protocol


class ModelPoseReader(Protocol):
    def pose(self, model_name: str) -> Mapping[str, float]: ...


class GripperReleaseReadback(Protocol):
    def released(self) -> tuple[str, str]:
        """(gripper_state, evidence_id) of the newest owner-side gripper readback."""


class GazeboModelPoseReader:
    """Reads ``gz model -m <name> -p`` (retried) through the C3 probe helper."""

    def pose(self, model_name: str) -> Mapping[str, float]:
        from cell_sim_tools import model_pose

        return model_pose(model_name)


class SimItemPoseProducer:
    def __init__(self, producer_id: str, poses: ModelPoseReader, gripper: GripperReleaseReadback, *,
                 clock: Callable[[], float]) -> None:
        if not isinstance(producer_id, str) or not producer_id.strip():
            raise ValueError("producer_id is required")
        self.producer_id, self.poses, self.gripper, self.clock = producer_id, poses, gripper, clock

    def evidence(self, *, mission_id: str, step_index: int, action_id: str, attempt_id: str,
                 model_name: str) -> dict:
        pose = dict(self.poses.pose(model_name))
        gripper_state, gripper_evidence_id = self.gripper.released()
        item_id = f"{mission_id}:{step_index}"
        return {
            "predicate_id": f"{item_id}:item_at_pose", "item_id": item_id,
            "evidence_source": "sim_model_pose", "evidence_id": str(uuid.uuid4()),
            "producer_id": self.producer_id, "model_name": model_name, "pose": pose,
            "observed_at": self.clock(), "action_id": action_id, "attempt_id": attempt_id,
            "gripper_state": gripper_state, "gripper_evidence_id": gripper_evidence_id,
        }
