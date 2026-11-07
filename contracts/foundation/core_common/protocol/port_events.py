"""D-996 1: the four port events a business app reads. Port words only: no workcell, arm, marker or catalogue."""
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .arm_transfer_preflight import ArmPhysicalRef

PortEventKind = Literal["container.received_at_intake", "container.stored", "container.handling_failed",
                        "vehicle.release_permitted"]
_Ref = Annotated[ArmPhysicalRef, Field(max_length=128)]

#: kind -> the optional fields it must carry; every other optional field must be null (object_ref is checked apart)
REQUIRED = {"container.received_at_intake": {"intake_point", "identity"},
            "container.stored": {"slot_ref", "identity"},
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
    intake_point: _Ref | None = None
    slot_ref: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]+-r\d+-c\d+-l\d+$", max_length=128)] | None = None
    vehicle_id: _Ref | None = None
    reason: Literal["MISMATCH", "UNREADABLE", "LOST", "DAMAGED"] | None = None
    identity: Literal["observed", "attested"] | None = None
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def _by_kind(self):
        required = REQUIRED[self.kind]
        missing = sorted(f for f in required if getattr(self, f) is None)
        forbidden = sorted(f for f in _OPTIONAL - required if getattr(self, f) is not None)
        if missing or forbidden:
            raise ValueError(f"{self.kind}: missing {missing}, forbidden {forbidden}")
        if self.kind in {"container.received_at_intake", "container.stored"} and self.object_ref is None:
            raise ValueError(f"{self.kind} names its container")
        if self.kind == "vehicle.release_permitted" and self.object_ref is not None:
            raise ValueError("vehicle.release_permitted names no container")
        if self.observed_at.utcoffset().total_seconds() != 0:
            raise ValueError("observed_at is UTC")
        return self

    def matches(self, source: str) -> bool:
        return self.event_id == event_id(source, self.observation_ref, self.kind)


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
