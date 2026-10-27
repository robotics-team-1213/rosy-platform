"""Canonical persisted physical facts; writing them alone grants no authority."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
import json
from uuid import uuid4

from .mission_store import MissionConflict, _json


def world_observations(samples):
    from rosy.world.state.projections.physical_transfer import (
        ArmPhysicalState, Bounds3, LinkPhysicalState, PhysicalPose, TransferObservation)
    result = []
    for sample in samples:
        data = sample.model_dump()
        owners = []
        for owner in data.pop("owners"):
            links = {name: LinkPhysicalState(bounds=Bounds3(**link["bounds"]),
                linear_velocity_m_s=link["linear_velocity_m_s"], angular_velocity_rad_s=link["angular_velocity_rad_s"])
                for name, link in owner.pop("links").items()}
            owners.append(ArmPhysicalState(**owner, links=links))
        pose = data.pop("object_pose")
        result.append(TransferObservation(**data, object_pose=None if pose is None else PhysicalPose(**pose),
                                          owners=tuple(owners)))
    return tuple(result)


def _document(value):
    if is_dataclass(value):
        return {field.name: _document(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _document(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_document(item) for item in value]
    return value


def evidence_document(context, observations):
    return _json(dict(context=context.model_dump(mode="json"), samples=_document(observations)))


def validate_post_action_order(connection, mission_id, observations):
    row = connection.execute("SELECT evidence_json FROM fleet_physical_transfer_observations "
        "WHERE mission_id=? AND phase='PRE_DISPATCH'", (mission_id,)).fetchone()
    if row is None:
        raise MissionConflict("post-action evidence requires the original preconditions")
    pre = json.loads(row[0])["samples"]
    if ({sample.evidence_id for sample in observations} & {sample["evidence_id"] for sample in pre}
            or observations[0].sequence <= max(sample["sequence"] for sample in pre)):
        raise MissionConflict("physical closure requires new ordered observations after the preconditions")


def record(connection, *, mission_id, grant, context, observations, validated_at_ns):
    document = evidence_document(context, observations)
    evidence_digest = sha256(document.encode()).hexdigest()
    connection.execute("""INSERT INTO fleet_physical_transfer_observations
        (mission_id,phase,record_id,request_digest,evidence_digest,evidence_json,validated_at_ns)
        VALUES(?,?,?,?,?,?,?)""", (mission_id, context.phase, "physical-record-" + uuid4().hex,
        grant.request_digest, evidence_digest, document, validated_at_ns))
