"""D-411 B: rosy.controls/1 — a device announces the controls it accepts (D-323, D-366).

Drivers only transport; Pilot has one widget per kind. Arm controls are bounded goals
issued one after another, never a 100 ms stream (D-390 §2).
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTROLS_SCHEMA = "rosy.controls/1"
_ID = r"^[a-z][a-z0-9_]{0,31}$"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class BaseVelocityControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["base_velocity"] = "base_velocity"
    label: str = Field(min_length=1, max_length=40)
    max_linear: float = Field(gt=0, le=2.0)
    max_angular: float = Field(gt=0, le=6.0)
    pivot: bool
    fine: bool
    autonomy: tuple[Literal["line"], ...] = ()


class JointRange(_Wire):
    name: str = Field(min_length=1, max_length=64)
    lower: float
    upper: float

    @model_validator(mode="after")
    def _ordered(self) -> "JointRange":
        if not (math.isfinite(self.lower) and math.isfinite(self.upper) and self.lower < self.upper):
            raise ValueError("joint range must be finite with lower < upper")
        return self


class JointJogControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["joint_jog"] = "joint_jog"
    label: str = Field(min_length=1, max_length=40)
    joints: tuple[JointRange, ...] = Field(min_length=1, max_length=8)
    max_step_rad: float = Field(gt=0, le=0.05)
    duration_s: float = Field(ge=0.1, le=1.0)
    command: Literal["bounded_goal"] = "bounded_goal"

    @model_validator(mode="after")
    def _unique(self) -> "JointJogControl":
        names = [joint.name for joint in self.joints]
        if len(set(names)) != len(names):
            raise ValueError("joint names must be unique")
        return self


class GripperPresets(_Wire):
    open: float
    half: float
    close: float


class GripperControl(_Wire):
    id: str = Field(pattern=_ID)
    kind: Literal["gripper"] = "gripper"
    label: str = Field(min_length=1, max_length=40)
    joint: str = Field(min_length=1, max_length=64)
    closed: float
    open: float
    unit: Literal["rad"] = "rad"
    presets: GripperPresets
    readback: tuple[Literal["position", "grasp"], ...] = ("position", "grasp")

    @model_validator(mode="after")
    def _within(self) -> "GripperControl":
        low, high = sorted((self.closed, self.open))
        if not (math.isfinite(low) and math.isfinite(high)) or low == high:
            raise ValueError("open and closed must be finite and differ")
        if any(not low <= value <= high for value in (self.presets.open, self.presets.half, self.presets.close)):
            raise ValueError("presets must lie between closed and open")
        return self


Control = Annotated[Union[BaseVelocityControl, JointJogControl, GripperControl], Field(discriminator="kind")]


class ControlsDescriptor(_Wire):
    schema_id: Literal["rosy.controls/1"] = Field(CONTROLS_SCHEMA, alias="schema")
    items: tuple[Control, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def _ids(self) -> "ControlsDescriptor":
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("control ids must be unique")
        return self


def pinky_controls(*, provides, max_linear: float, max_angular: float) -> dict:
    """Pinky's controls from its adapter manifest's `provides` (D-411 §8)."""
    items = []
    if "drive" in provides:
        items.append(BaseVelocityControl(id="base", label="주행", max_linear=max_linear,
                                         max_angular=max_angular, pivot=True, fine=True,
                                         autonomy=("line",)))
    return ControlsDescriptor(items=tuple(items)).model_dump(by_alias=True, mode="json")
