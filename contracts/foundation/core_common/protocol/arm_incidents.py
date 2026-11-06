"""D-971: an OMX arm incident reported by its control PC, explained by the AI PC, cleared by a named operator.

Display and hold only: nothing here is a command. Measured facts are a bounded JSON object, frames are JPEG with a
sha256 the receiver recomputes."""
import base64
import binascii
import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

SessionId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
SourceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
IncidentId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Text = Annotated[str, Field(min_length=1, max_length=400, pattern=r"^[^\x00-\x1f\x7f]+$")]
ARM_INCIDENT_FRAME_BYTES = 200_000            # one JPEG
ARM_INCIDENT_BODY_BYTES = 700_000             # report: two frames in base64 plus the facts
ARM_INCIDENT_JSON_BYTES = 12_288              # each of facts, decision, recovery


def _depth(value, level=0):
    if level > 6:
        raise ValueError("JSON nested too deep")
    for item in (value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()):
        _depth(item, level + 1)
    return value


def _bounded(value):
    try:
        text = json.dumps(_depth(value), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("a finite JSON object is required") from error
    if len(text.encode()) > ARM_INCIDENT_JSON_BYTES:
        raise ValueError("JSON object too large")
    return value


BoundedJson = Annotated[dict[str, Any], AfterValidator(_bounded)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ArmIncidentFrame(_Strict):
    role: Literal["top", "side"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    jpeg_b64: Annotated[str, Field(min_length=8, max_length=ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 8)]

    @model_validator(mode="after")
    def intact_jpeg(self):
        try:
            data = base64.b64decode(self.jpeg_b64, validate=True)
        except binascii.Error as error:
            raise ValueError("frame is not base64") from error
        if len(data) > ARM_INCIDENT_FRAME_BYTES or data[:2] != b"\xff\xd8":
            raise ValueError("frame is not a JPEG within the size limit")
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise ValueError("frame sha256 differs")
        return self


class ArmIncidentReport(_Strict):
    source_id: SourceId
    session_id: SessionId
    facts: BoundedJson        # latched motors with hw_error and bits, torque_after, folded, windup hits, runner rows
    decision: BoundedJson     # the measurement decision (hold, reason, offered actions)
    recovery: BoundedJson | None = None  # the device's own safety reboot result, registers before and after
    frames: Annotated[list[ArmIncidentFrame], Field(max_length=2)] = []

    @model_validator(mode="after")
    def one_frame_per_role(self):
        UUID(self.session_id)
        if len({f.role for f in self.frames}) != len(self.frames):
            raise ValueError("one frame per role")
        return self


class ArmIncidentHold(_Strict):
    held: bool
    incident_ids: Annotated[list[IncidentId], Field(max_length=64)]
    reason: Text | None = None


class ArmIncidentAccepted(_Strict):
    incident_id: IncidentId
    hold: ArmIncidentHold


class ArmIncidentExplanation(_Strict):
    seen: Text
    suspected_cause: Text
    model: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@/-]+$")]


class ArmIncidentClear(_Strict):
    note: Text
