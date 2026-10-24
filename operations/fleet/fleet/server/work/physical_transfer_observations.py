"""Canonical persisted physical facts; writing them alone grants no authority."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
from uuid import uuid4

from .mission_store import _json


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


def record(connection, *, mission_id, grant, context, observations, validated_at_ns):
    document = evidence_document(context, observations)
    evidence_digest = sha256(document.encode()).hexdigest()
    connection.execute("""INSERT INTO fleet_physical_transfer_observations
        (mission_id,phase,record_id,request_digest,evidence_digest,evidence_json,validated_at_ns)
        VALUES(?,?,?,?,?,?,?)""", (mission_id, context.phase, "physical-record-" + uuid4().hex,
        grant.request_digest, evidence_digest, document, validated_at_ns))
