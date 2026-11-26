"""D-996 1: the four port events a business app reads. Port words only: no workcell, arm, marker or catalogue."""
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_serializer, model_validator

from .arm_transfer_preflight import ArmPhysicalRef

PortEventKind = Literal["container.received_at_intake", "container.stored", "container.loaded_for_outbound",
                        "container.handling_failed", "vehicle.release_permitted"]
_Ref = Annotated[ArmPhysicalRef, Field(max_length=128)]
EPC_PATTERN = r"^(?:[0-9A-Fa-f]{2}){2,64}$"
Epc = Annotated[str, StringConstraints(pattern=EPC_PATTERN, to_upper=True)]

#: kind -> the optional fields it must carry; every other optional field must be null (object_ref is checked apart)
REQUIRED = {"container.received_at_intake": {"intake_point", "identity"},
            "container.stored": {"slot_ref", "identity"},
            "container.loaded_for_outbound": {"vehicle_id", "identity"},
            "container.handling_failed": {"reason"},
            "vehicle.release_permitted": {"vehicle_id"}}
_OPTIONAL = {"intake_point", "slot_ref", "vehicle_id", "reason", "identity"}


def event_id(source: str, observation_ref: str, kind: str) -> str:
    """sha256(source|observation_ref|kind): the same observation resent is the same event."""
    return sha256(f"{source}|{observation_ref}|{kind}".encode()).hexdigest()


class PortEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    kind: PortEventKind
    observation_ref: _Ref
    object_ref: _Ref | None = None
    intake_occurrence_id: _Ref | None = None
    placement_attempt_id: _Ref | None = None
    intake_point: _Ref | None = None
    slot_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+-r[1-9]\d*-c[1-9]\d*-l[1-9]\d*$", max_length=128)] | None = None
    vehicle_id: _Ref | None = None
    reason: Literal["MISMATCH", "UNREADABLE", "LOST", "DAMAGED"] | None = None
    identity: Literal["observed", "attested"] | None = None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def _by_kind(self):
        if self.intake_occurrence_id is not None and self.kind not in {"container.received_at_intake", "container.stored"}:
            raise ValueError("intake occurrence belongs to intake or storage")
        if self.placement_attempt_id is not None and (self.kind != "container.stored" or not self.intake_occurrence_id):
            raise ValueError("placement attempt requires a stored intake occurrence")
        if self.kind == "container.stored" and bool(self.intake_occurrence_id) != bool(self.placement_attempt_id):
            raise ValueError("correlated storage requires both references")
        required = REQUIRED[self.kind]
        missing = sorted(f for f in required if getattr(self, f) is None)
        forbidden = sorted(f for f in _OPTIONAL - required if getattr(self, f) is not None)
        if missing or forbidden:
            raise ValueError(f"{self.kind}: missing {missing}, forbidden {forbidden}")
        if self.kind in {"container.received_at_intake", "container.stored", "container.loaded_for_outbound"} and self.object_ref is None:
            raise ValueError(f"{self.kind} names its container")
        if self.kind == "vehicle.release_permitted" and self.object_ref is not None:
            raise ValueError("vehicle.release_permitted names no container")
        if self.observed_at.utcoffset().total_seconds() != 0:
            raise ValueError("observed_at is UTC")
        return self

    def matches(self, source: str) -> bool:
        return self.event_id == event_id(source, self.observation_ref, self.kind)

    @model_serializer(mode="wrap")
    def _omit_absent_correlation(self, handler):
        wire = handler(self)
        for name in ("intake_occurrence_id", "placement_attempt_id"):
            if wire.get(name) is None:
                wire.pop(name, None)
        return wire


class PortEventPage(BaseModel):
    """``GET /api/fleet/port-events``: ``cursor`` is opaque to the reader; ``complete`` is false when a cell was
    unreachable or had a gap, and that cell's position did not move past it."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    events: list[PortEvent]
    cursor: str
    complete: bool


class PortEventLedgerRow(BaseModel):
    """One cell's ledger row as a peer reads it: its own seq, the event unchanged."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    seq: Annotated[int, Field(ge=1)]
    event: PortEvent


class PortEventLedgerPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rows: list[PortEventLedgerRow]


class IntakeCandidate(BaseModel):
    """Mapped Cell-local reading, available only to the Cell's configured direct parent."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    workcell_id: _Ref
    observation_ref: _Ref
    observed_at: AwareDatetime
    mapping_revision: _Ref
    object_ref: _Ref | None = None
    outcome: Literal["MAPPED", "UNKNOWN_EPC", "NO_READ", "LABEL_CONFLICT", "CLOSED_THROUGH"]
    reader_epoch: _Ref | None = None
    reader_seq: Annotated[int, Field(strict=True, ge=1)] | None = None
    coverage_start: AwareDatetime | None = None

    @model_validator(mode="after")
    def _mapped(self):
        _check_reader_order(self.reader_epoch, self.reader_seq, self.coverage_start, self.observed_at,
                            self.outcome == "CLOSED_THROUGH")
        if (self.outcome in {"MAPPED", "LABEL_CONFLICT"}) != bool(self.object_ref) or self.observed_at.utcoffset().total_seconds() != 0:
            raise ValueError("invalid mapped identity or timestamp")
        return self


class IntakeCandidateRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    seq: Annotated[int, Field(strict=True, ge=1)]
    candidate: IntakeCandidate


class IntakeCandidatePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rows: list[IntakeCandidateRow] = Field(max_length=200)


def _check_reader_order(epoch, seq, start, observed_at, watermark):
    if (epoch is None) != (seq is None) or (start is not None) != watermark:
        raise ValueError("invalid reader ordering fields")
    if watermark and (epoch is None or start > observed_at or start.utcoffset().total_seconds() != 0):
        raise ValueError("invalid reader coverage")


class IntakeReading(BaseModel):
    """D-996 2-3: what a cell PC read at one point. The cell Fleet maps the marker ID or EPC to an object_ref and
    compares it with what the trip declared, so the PC never holds the app's cargo codes."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_ref: _Ref
    point: Literal["conveyor_end", "wrist", "rfid_intake"]
    state: Literal["read", "unreadable", "mismatch", "closed_through"]
    tag: Annotated[int, Field(ge=0, le=999)] | None = None
    epc: Epc | None = None
    #: wrist only: the A/B ARM_TRANSFER job placing this container; its target is the slot
    arm_mission_id: ArmPhysicalRef | None = None
    observed_at: AwareDatetime
    reader_epoch: _Ref | None = None
    reader_seq: Annotated[int, Field(strict=True, ge=1)] | None = None
    coverage_start: AwareDatetime | None = None

    @model_validator(mode="after")
    def _shape(self):
        rfid = self.point == "rfid_intake"
        _check_reader_order(self.reader_epoch, self.reader_seq, self.coverage_start, self.observed_at,
                            self.state == "closed_through")
        if self.reader_epoch is not None and not rfid:
            raise ValueError("reader ordering belongs to the RFID intake")
        if (rfid and self.tag is not None) or (not rfid and self.epc is not None):
            raise ValueError("RFID intake uses an EPC; camera readings use a marker ID")
        if (self.state == "read") != ((self.epc if rfid else self.tag) is not None):
            raise ValueError("a tag or EPC is given exactly when the state is read")
        if self.point != "wrist" and self.arm_mission_id is not None:
            raise ValueError("only a wrist reading names an arm job")
        if self.observed_at.utcoffset().total_seconds() != 0:
            raise ValueError("observed_at is UTC")
        return self
