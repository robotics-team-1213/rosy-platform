"""Canonical persisted physical facts; writing them alone grants no authority."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from hashlib import sha256
from uuid import uuid4

from .mission_store import _json


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
