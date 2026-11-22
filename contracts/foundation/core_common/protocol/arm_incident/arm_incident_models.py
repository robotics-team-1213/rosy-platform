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


def _intact_jpeg(frame):
    try:
        data = base64.b64decode(frame.jpeg_b64, validate=True)
    except binascii.Error as error:
        raise ValueError("frame is not base64") from error
    if len(data) > ARM_INCIDENT_FRAME_BYTES or data[:2] != b"\xff\xd8":
        raise ValueError("frame is not a JPEG within the size limit")
    if hashlib.sha256(data).hexdigest() != frame.sha256:
        raise ValueError("frame sha256 differs")
    return frame


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ArmIncidentFrame(_Strict):
    role: Literal["top", "side"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    jpeg_b64: Annotated[str, Field(min_length=8, max_length=ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 8)]

    @model_validator(mode="after")
    def intact_jpeg(self):
        return _intact_jpeg(self)


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


#: what stopped the arm, as the cell names it (cell_why's causes and the kinds of stop); and how the person knows it.
#: 2026-11-07: people, models and frame strips all misread contact while measurement and repeats decided, so a cause
#: comes with its basis and only a repeat or a measurement is scored as truth.
CAUSES = ("blocked", "wrong_position", "snagged", "too_fast", "no_room", "software_or_config", "camera_or_map", "other",
          "unknown")
BASES = ("repeat", "measured", "seen", "unknown")
ARM_INCIDENT_EVIDENCE_FRAMES = 24             # per incident, beside the report's two stills


MOTOR_IDS = ("11", "12", "13", "14", "15", "16")  # the follower's six motors
BODY_JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll")
MotorInts = dict[Literal[MOTOR_IDS], Annotated[int, Field(ge=0, le=255)]]


class ArmIncidentRemeasureFrame(_Strict):
    role: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ArmIncidentFaultRecord(_Strict):
    """One motor-fault record the incident names (the report sends only its file name), as the cell reads it again."""
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,128}\.json$")]
    fault_type: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.]{1,64}$")]
    fault: Text


class ArmIncidentRemeasure(_Strict):
    """D-1040: a fresh motionless read of the arm after the incident (omx_incident.py reassess): which arm and follower
    board it read (the cell's board map, Fleet's manifest binding) for which incident, every motor's torque and hardware
    error registers, the body joints' distance to the arm's own plan home, the stills' sha256, and the motor-fault
    records the incident names."""
    arm: SourceId
    board_serial: Annotated[str, Field(pattern=r"^[0-9A-F]{8,64}$")]
    incident_id: IncidentId | None = None     # set by `clear --reassess` for the one incident it clears
    at: Annotated[float, Field(gt=0)]
    torque_after: MotorInts
    hardware_error: MotorInts
    folded: bool
    max_home_err: Annotated[float, Field(ge=0, le=400)]
    frames: Annotated[list[ArmIncidentRemeasureFrame], Field(min_length=1, max_length=3)]
    fault_records: Annotated[list[ArmIncidentFaultRecord], Field(max_length=8)] = []
    # D-1040 amendment (2026-11-18): signed per-joint error (read - home, units) of two reads first_at..at apart; the
    # contract recomputes stability and the sag envelope from these, a client `stable` is ignored
    home_err: dict[Literal[BODY_JOINTS], Annotated[float, Field(ge=-400, le=400)]] | None = None
    first_home_err: dict[Literal[BODY_JOINTS], Annotated[float, Field(ge=-400, le=400)]] | None = None
    first_at: Annotated[float, Field(gt=0)] | None = None
    stable: bool | None = None
    # held_object: the jaw gap (gripper units, motor 16) of the same two reads
    gripper_pos: Annotated[float, Field(ge=0, le=100)] | None = None
    first_gripper_pos: Annotated[float, Field(ge=0, le=100)] | None = None

    @model_validator(mode="after")
    def every_motor(self):
        if set(self.torque_after) != set(MOTOR_IDS) or set(self.hardware_error) != set(MOTOR_IDS):
            raise ValueError("all six motors are read")
        return self


HELD_ROLES = {"top", "wrist"}
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ArmHeldVerdict(_Strict):
    """Held object: a model's answers to closed questions about the top and wrist stills. A model only classifies;
    anything but these literal answers ('unclear' included) does not validate, so it cannot clear."""
    incident_id: IncidentId
    evaluated_at: Annotated[float, Field(gt=0)]
    frame_sha256: dict[Literal["top", "wrist"], Sha]
    in_jaws: Literal["one_box"]
    single_object: Literal["yes"]
    box_cells: Literal[1, 2, 3]
    person_in_view: Literal["no"]
    foreign_in_jaws: Literal["no"]       # cable, tool, wall lip
    arm_body_clear: Literal["yes"]
    model: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:@/-]+$")]


class ArmIncidentClear(_Strict):
    note: Text
    cause: Literal[CAUSES] | None = None
    basis: Literal[BASES] | None = None
    remeasured: ArmIncidentRemeasure | None = None  # D-1040, v1.407
    verdict: ArmHeldVerdict | None = None            # held_object only
    recovery: BoundedJson | None = None  # D-1048: an assessor's measured auto-fold evidence (clearable_after_fold)


class ArmIncidentEvidenceFrame(_Strict):
    """One frame of the seconds around a stop, sent after the report and on its own (each within the frame limit), so
    the report stays small and a dropped link loses a frame, not the incident."""
    camera: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
    t_rel_s: Annotated[float, Field(ge=-30, le=30)]
    kind: Literal["full", "tip"]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    jpeg_b64: Annotated[str, Field(min_length=8, max_length=ARM_INCIDENT_FRAME_BYTES * 4 // 3 + 8)]

    @model_validator(mode="after")
    def intact_jpeg(self):
        return _intact_jpeg(self)
