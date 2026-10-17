"""Fixed-cell transfer grant (D-403) with the optional pair and barrier fields (D-779 §7, D-780).

Split from ``schemas.py``, which has no size room; ``schemas.py`` re-exports every name here.
A grant without the pair fields and a payload without ``barriers`` serialize exactly as before
those fields existed, so the request digest of a single-arm grant does not change.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

_ACTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")
_ARM_ROLE = r"^[a-z][a-z0-9_]{0,31}$"

#: Ordered CELL_TRANSFER phases (D-402 §3); a barrier sits on a boundary between two of them.
CELL_TRANSFER_PHASES = ("approach", "grasp", "transfer", "release")
#: Coupling strength order (D-778 §6); a pair grant's ``coupling`` is the strongest of its Step.
COUPLINGS = ("independent", "loose", "tight")
Coupling = Literal["independent", "loose", "tight"]
#: Longest local wait at one barrier; the compiler picks the real bound per Step (D-780 §3).
MAX_BARRIER_WAIT_S = 600.0


def _omit_absent(handler, model, optional: tuple[str, ...]) -> dict:
    document = handler(model)
    for name in optional:
        if name in document and document[name] is None:
            del document[name]
    return document


class CellTransferPose(BaseModel):
    """Finite robot-base pose carried by the fixed-cell transfer grant (D-403)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float = Field(strict=True, allow_inf_nan=False)
    y: float = Field(strict=True, allow_inf_nan=False)
    z: float = Field(strict=True, allow_inf_nan=False)
    yaw: float = Field(strict=True, allow_inf_nan=False)


class CellTransferBarrier(BaseModel):
    """One named barrier on a phase boundary of a coordinated Step (D-780 §3)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    barrier_id: str = Field(min_length=1, max_length=96)
    after_phase: Optional[Literal["approach", "grasp", "transfer"]] = None
    before_first_phase: Optional[Literal[True]] = None
    coupling_after: Coupling
    max_wait_s: float = Field(strict=True, gt=0, le=MAX_BARRIER_WAIT_S, allow_inf_nan=False)

    @field_validator("barrier_id")
    @classmethod
    def _barrier_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("barrier_id must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _one_boundary(self):
        if (self.after_phase is None) == (self.before_first_phase is None):
            raise ValueError("a barrier names exactly one of after_phase or before_first_phase")
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        return _omit_absent(handler, self, ("after_phase", "before_first_phase"))

    @property
    def gated_phase(self) -> str:
        """The phase this barrier holds back."""
        if self.before_first_phase:
            return CELL_TRANSFER_PHASES[0]
        return CELL_TRANSFER_PHASES[CELL_TRANSFER_PHASES.index(self.after_phase) + 1]


class CellTransferPayload(BaseModel):
    """One inseparable pick/place pair compiled from an approved Cell Job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1, max_length=192)
    recipe_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    step_index: int = Field(strict=True, ge=0)
    item: Literal["box", "slip_sheet"]
    pallet: str = Field(min_length=1, max_length=96)
    layer: int = Field(strict=True, ge=0)
    frame: Literal["robot_base"]
    home: CellTransferPose
    pick: CellTransferPose
    place: CellTransferPose
    pick_approach_z: float = Field(strict=True, allow_inf_nan=False)
    place_approach_z: float = Field(strict=True, allow_inf_nan=False)
    carry_z: float = Field(strict=True, allow_inf_nan=False)
    # D-780 §3: absent means no barrier; an empty list is not a distinct value.
    barriers: Optional[tuple[CellTransferBarrier, ...]] = Field(default=None, min_length=1, max_length=4)

    @field_validator("job_id", "pallet")
    @classmethod
    def _cell_transfer_identifier(cls, value: str) -> str:
        if not _ACTION_ID.fullmatch(value):
            raise ValueError("Cell Transfer identity must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _approaches_are_carried(self):
        if (self.pick_approach_z < self.pick.z or self.place_approach_z < self.place.z
                or self.carry_z < max(self.pick_approach_z, self.place_approach_z)):
            raise ValueError("carry_z must cover both target approach heights")
        if self.barriers is not None:
            if len({barrier.barrier_id for barrier in self.barriers}) != len(self.barriers):
                raise ValueError("barrier ids must be unique within one Action")
            gated = [CELL_TRANSFER_PHASES.index(barrier.gated_phase) for barrier in self.barriers]
            if gated != sorted(set(gated)):
                raise ValueError("barriers must sit on distinct boundaries in phase order")
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        return _omit_absent(handler, self, ("barriers",))

    def strongest_coupling(self) -> str:
        if not self.barriers:
            return COUPLINGS[0]
        return max((barrier.coupling_after for barrier in self.barriers), key=COUPLINGS.index)


class FleetCellTransferGrant(BaseModel):
    """Fleet authority for exactly one ordered Cell Job transfer step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mission_id: str = Field(min_length=1, max_length=192)
    step_id: str = Field(min_length=1, max_length=192)
    action_id: str = Field(min_length=1, max_length=192)
    attempt_id: str = Field(min_length=1, max_length=192)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)
    action_kind: Literal["CELL_TRANSFER"]
    cell_transfer: CellTransferPayload
    capability_revision: str = Field(min_length=1, max_length=128)
    config_revision: str = Field(min_length=1, max_length=128)
    authority_epoch: int = Field(strict=True, ge=0)
    dispatch_generation: int = Field(strict=True, ge=0)
    issued_at: datetime
    expires_at: datetime
    # D-779 §7 / D-780 §5 pair fields; a single-arm grant carries none of them.
    arm_role: Optional[str] = Field(default=None, pattern=_ARM_ROLE)
    pair_id: Optional[str] = Field(default=None, min_length=1, max_length=192)
    partner_instance_id: Optional[str] = Field(default=None, min_length=1, max_length=96)
    coupling: Optional[Coupling] = None

    @field_validator("mission_id", "step_id", "action_id", "attempt_id", "workcell_id",
                     "instance_id", "capability_revision", "config_revision", "pair_id",
                     "partner_instance_id")
    @classmethod
    def _cell_grant_identifier(cls, value: str | None) -> str | None:
        if value is not None and not _ACTION_ID.fullmatch(value):
            raise ValueError("identity must be a trimmed identifier")
        return value

    @model_validator(mode="after")
    def _cell_grant_consistency(self):
        identities = (self.mission_id, self.step_id, self.action_id, self.attempt_id)
        if len(set(identities)) != len(identities):
            raise ValueError("mission, step, action and attempt identities must be distinct")
        if (self.issued_at.tzinfo is None or self.expires_at.tzinfo is None
                or self.expires_at <= self.issued_at):
            raise ValueError("grant expiry must follow an aware issuance timestamp")
        if (self.pair_id is None) != (self.partner_instance_id is None):
            raise ValueError("pair_id and partner_instance_id are both present or both absent")
        if self.partner_instance_id is not None and self.partner_instance_id == self.instance_id:
            raise ValueError("partner_instance_id must name the other arm's instance")
        if self.coupling is not None and self.pair_id is None:
            raise ValueError("coupling belongs to a pair grant")
        if self.cell_transfer.barriers is not None and self.coupling is None:
            raise ValueError("barriers require a pair grant with coupling")
        if self.coupling is not None and self.coupling != self.cell_transfer.strongest_coupling():
            raise ValueError("grant coupling disagrees with the plan's barrier coupling")
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler):
        return _omit_absent(handler, self, ("arm_role", "pair_id", "partner_instance_id", "coupling"))


__all__ = [
    "CELL_TRANSFER_PHASES", "COUPLINGS", "CellTransferBarrier", "CellTransferPayload",
    "CellTransferPose", "Coupling", "FleetCellTransferGrant", "MAX_BARRIER_WAIT_S",
]
