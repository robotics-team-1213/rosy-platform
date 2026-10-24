"""Per-kind rules for Actions dispatched from the ordered step ledger (D-403 §2, §7).

The step ledger (``CellJobStore``) and its dispatcher stay kind-neutral; everything that differs
by ``action_kind`` is looked up here: which deployment profiles may dispatch it, the typed grant
model and body, how a ledger step's inputs become that body, the ordered device phases a success
must report, how a device rejection code is recorded, and who may approve it (D-763 item 7).
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
    grant_model: type[BaseModel] | None  # None: not a device Action (TRIP runs as a Fleet trip)
    body_field: str
    body: Callable[[Mapping[str, Any], int, Mapping[str, Any]], dict[str, Any]]
    phase_ids: tuple[str, ...]
    rejection_reasons: Mapping[str, str]
    approval: str


#: D-763 item 7, strictest first: two_person (a named operator other than the proposer; every arm
#: step), proposer_only (legacy PICK_PLACE until the slice connecting its dispatch, D-763 rev 2 Q5),
#: one_person (one named operator; motion-only kinds: TRIP).
APPROVALS = ("two_person", "proposer_only", "one_person")
_LEGACY_APPROVALS = {"PICK_PLACE": "proposer_only"}  # no step-ledger dispatch rules, so not in _KINDS


def _cell_transfer_body(job: Mapping[str, Any], step_index: int,
                        inputs: Mapping[str, Any]) -> dict[str, Any]:
    """pallet.transfer/1.0.0 inputs as the D-403 §2 ``cell_transfer`` body; a recipe/3 ``sku`` is copied (D-781 §2)."""
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
        "carry_z": inputs["carry_z_base_m"], **({"sku": inputs["sku"]} if "sku" in inputs else {}),
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
        approval="two_person",
    ),
    # D-763 7: a 운행 step is a Fleet trip (``job_trip_steps``), never a device Action; SIM until device proof.
    "TRIP": StepActionKind(action_kind="TRIP", open_profiles=frozenset({"simulation"}), grant_model=None,
                           body_field="trip", body=None, phase_ids=(), rejection_reasons={}, approval="one_person"),
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


def required_approval(action_kinds) -> str:
    """Strictest approval over a job's step kinds; ValueError for none or an unregistered kind."""
    return min((_LEGACY_APPROVALS.get(kind) or step_action_kind(kind).approval
                for kind in action_kinds), key=APPROVALS.index)


def rejection_reason(action_kind: str, code: str) -> str:
    return step_action_kind(action_kind).rejection_reasons.get(code, "LOCAL_ACTION_REJECTED")


def parse_step_grant(grant: Mapping[str, Any]) -> BaseModel:
    """Parse only a registered device Action; TRIP uses its own Fleet execution path."""
    if not isinstance(grant, Mapping) or not isinstance(grant.get("action_kind"), str):
        raise ValueError("a device Action grant needs a registered action_kind")
    kind = step_action_kind(grant["action_kind"])
    if kind.grant_model is None:
        raise ValueError(f"{kind.action_kind} is not a device Action")
    return kind.grant_model.model_validate(dict(grant))


def validate_step_grant(parsed: BaseModel, job: Mapping[str, Any], step: Mapping[str, Any], *,
                        step_index: int, action_id: str, attempt_id: str) -> None:
    """Bind common authority and the kind's complete payload to the persisted step."""
    kind = step_action_kind(step["action_kind"])
    if kind.grant_model is None or kind.body is None or not isinstance(parsed, kind.grant_model):
        raise ValueError("typed device grant does not match the persisted step kind")
    if (parsed.action_kind != step["action_kind"]
            or parsed.mission_id != job["mission_id"] or parsed.step_id != step["step_id"]
            or parsed.action_id != action_id or parsed.attempt_id != attempt_id
            or parsed.workcell_id != job["workcell_id"] or parsed.instance_id != job["instance_id"]
            or parsed.authority_epoch != job["authority_epoch"]
            or parsed.dispatch_generation != job["dispatch_generation"]):
        raise ValueError(f"{kind.action_kind} grant does not match the current persisted step")
    expected_payload = kind.body(job, step_index, json.loads(step["step_json"])["inputs"])
    if getattr(parsed, kind.body_field).model_dump(mode="json") != expected_payload:
        raise ValueError(f"{kind.action_kind} payload does not match the persisted PlanBundle step")


def step_grant_digest(grant: Mapping[str, Any] | BaseModel) -> str:
    """sha256 over the canonical complete grant without its digest (the OMX owner's rule)."""
    if isinstance(grant, BaseModel):
        document = grant.model_dump(mode="json")
    else:
        document = parse_step_grant(grant).model_dump(mode="json")
    document.pop("request_digest")
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "APPROVALS", "StepActionKind", "dispatch_open", "open_kinds", "rejection_reason",
    "required_approval", "step_action_kind", "step_grant_digest", "parse_step_grant", "validate_step_grant",
]
