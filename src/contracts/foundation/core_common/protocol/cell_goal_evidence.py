"""Bounded attestation from an independent, registered simulation evaluator."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=192, pattern=r"^[^\s\x00-\x1f\x7f]+$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Timestamp = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class CellModelPose(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    x_m: float
    y_m: float
    z_m: float
    roll_rad: float
    pitch_rad: float
    yaw_rad: float


class CellGoalEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    producer_id: Text
    evidence_id: Text
    evidence_source: Literal["sim_model_pose"]
    evaluator_revision: Text
    job_id: Text
    step_id: Text
    step_index: Annotated[int, Field(ge=0)]
    action_id: Text
    attempt_id: Text
    request_digest: Digest
    recipe_sha256: Digest
    cell_sha256: Digest
    model_id: Text
    observation_id: Text
    observation_digest: Digest
    evidence_revision: Text
    observed_at: Timestamp
    model_pose_base: CellModelPose
    initial_observation_id: Text
    initial_observation_digest: Digest
    initial_observed_at: Timestamp
    initial_model_pose_base: CellModelPose
    gripper_state: Literal["OPEN"]
    gripper_evidence_id: Text
    gripper_evidence_revision: Text
    gripper_observed_at: Timestamp
    # No ``satisfied`` field: Fleet judges the pose against the step's stored item_at_pose
    # predicate; a producer cannot assert that the goal is met (C4b, D-328 §4).


class CellGoalEvidenceSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mission_id: Text
    evidence: CellGoalEvidence
