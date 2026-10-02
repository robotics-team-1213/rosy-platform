"""Per-kind rules for Actions dispatched from the ordered step ledger (D-403 §2, §7).

The step ledger (``CellJobStore``) and its dispatcher stay kind-neutral; everything that differs
by ``action_kind`` is looked up here: which deployment profiles may dispatch it, the typed grant
model and body, how a ledger step's inputs become that body, the ordered device phases a success
must report, and how a device rejection code is recorded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from pydantic import BaseModel

from core_common.protocol.schemas import FleetCellTransferGrant


@dataclass(frozen=True)
class StepActionKind:
    action_kind: str
    open_profiles: frozenset[str]
    grant_model: type[BaseModel]
    body_field: str
    body: Callable[[Mapping[str, Any], int, Mapping[str, Any]], dict[str, Any]]
    phase_ids: tuple[str, ...]
    rejection_reasons: Mapping[str, str]


def _cell_transfer_body(job: Mapping[str, Any], step_index: int,
                        inputs: Mapping[str, Any]) -> dict[str, Any]:
    """The persisted pallet.transfer/1.0.0 inputs as the D-403 §2 ``cell_transfer`` body."""
    def pose(value: Mapping[str, Any]) -> dict[str, float]:
        return {"x": value["x_m"], "y": value["y_m"], "z": value["z_m"], "yaw": value["yaw_rad"]}

    return {
        "job_id": job["job_id"], "recipe_sha256": job["recipe_digest"],
        "cell_sha256": job["cell_digest"], "step_index": step_index,
        "item": inputs["item"], "pallet": inputs["pallet_id"],
        "layer": inputs["layer_index"], "frame": "robot_base",
        "home": pose(inputs["home_pose_base"]),
        "pick": pose(inputs["source_pose_base"]),
        "place": pose(inputs["destination_pose_base"]),
        "pick_approach_z": inputs["source_approach_z_base_m"],
        "place_approach_z": inputs["destination_approach_z_base_m"],
        "carry_z": inputs["carry_z_base_m"],
    }


_KINDS = {
    "CELL_TRANSFER": StepActionKind(
        action_kind="CELL_TRANSFER",
        # D-403 §7: simulation only; every other profile, and every other kind, stays closed.
        open_profiles=frozenset({"simulation"}),
        grant_model=FleetCellTransferGrant,
        body_field="cell_transfer",
        body=_cell_transfer_body,
        phase_ids=("approach", "grasp", "transfer", "release"),
        # D-403 §9: a cell-hash or capability refusal is recorded as LOCAL_ACTION_REJECTED.
        rejection_reasons={"GRANT_REJECTED": "LOCAL_ACTION_REJECTED",
                           "UNSUPPORTED_VERSION": "LOCAL_ACTION_PROTOCOL_MISMATCH"},
    ),
}


def step_action_kind(action_kind: str) -> StepActionKind:
    kind = _KINDS.get(action_kind)
    if kind is None:
        raise ValueError(f"action kind {action_kind!r} has no step-ledger dispatch rules")
    return kind


def dispatch_open(deployment_profile: str, action_kind: str) -> bool:
    """True only for a (profile, kind) pair whose owner opened Fleet dispatch."""
    kind = _KINDS.get(action_kind)
    return kind is not None and deployment_profile in kind.open_profiles


def open_kinds(deployment_profile: str) -> tuple[str, ...]:
    return tuple(name for name, kind in _KINDS.items() if deployment_profile in kind.open_profiles)


def rejection_reason(action_kind: str, code: str) -> str:
    return step_action_kind(action_kind).rejection_reasons.get(code, "LOCAL_ACTION_REJECTED")


def step_grant_digest(grant: Mapping[str, Any] | BaseModel) -> str:
    """sha256 over the canonical complete grant without its digest (the OMX owner's rule)."""
    if isinstance(grant, BaseModel):
        document = grant.model_dump(mode="json")
    else:
        document = step_action_kind(grant["action_kind"]).grant_model.model_validate(
            dict(grant)).model_dump(mode="json")
    document.pop("request_digest")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "StepActionKind", "dispatch_open", "open_kinds", "rejection_reason", "step_action_kind",
    "step_grant_digest",
]
