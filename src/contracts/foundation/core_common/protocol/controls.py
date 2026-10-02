"""D-411 B: rosy.controls/1 — a device announces the controls it accepts (D-323, D-366).

Drivers only transport; Pilot has one widget per kind. Arm controls are bounded goals
issued one after another, never a 100 ms stream (D-390 §2).

Compatibility: these models are the *producer* schema (strict, extra="forbid"), so a
device never emits a malformed descriptor. Within ``rosy.controls/1`` new kinds and new
optional fields may be added; consumers (Pilot) must ignore kinds and fields they do not
know and show "unsupported control" instead of failing. Removing or redefining a field
is a breaking change and needs ``rosy.controls/2``.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTROLS_SCHEMA = "rosy.controls/1"
#: Largest single bounded arm goal (rad). One bound for the descriptor and the
#: OMX SIM jog request it describes (D-390 §2).
BOUNDED_JOG_MAX_STEP_RAD = 0.05
_ID = r"^[a-z][a-z0-9_]{0,31}$"


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class BaseVelocityControl(_Wire):
    """A mobile base driven by velocity.

    ``max_linear``/``max_angular`` are the live manual limits; 0 means the drive is
    announced but currently limited to standstill (``PUT /safety/limits`` allows 0).
    ``autonomy`` lists the modes the device provides (CORE: it has the line-follow
    service). It is not evidence that the mode can start right now; the mode's own
    start/status API decides that. Pinky's ``pivot`` and
    ``fine`` are profile constants of that base, not runtime evidence.
    """

    id: str = Field(pattern=_ID)
    kind: Literal["base_velocity"] = "base_velocity"
    label: str = Field(min_length=1, max_length=40)
    max_linear: float = Field(ge=0, allow_inf_nan=False)
    max_angular: float = Field(ge=0, allow_inf_nan=False)
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
    """Bounded joint goals: each request moves one joint by at most ``max_step_rad``.

    ``duration_s`` is the goal duration the client should send with each request.
    """

    id: str = Field(pattern=_ID)
    kind: Literal["joint_jog"] = "joint_jog"
    label: str = Field(min_length=1, max_length=40)
    joints: tuple[JointRange, ...] = Field(min_length=1, max_length=8)
    max_step_rad: float = Field(gt=0, le=BOUNDED_JOG_MAX_STEP_RAD)
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
        if self.presets.open != self.open or self.presets.close != self.closed:
            raise ValueError("open/close presets must be the open/closed positions")
        if not low < self.presets.half < high:
            raise ValueError("half preset must lie strictly between closed and open")
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


def pinky_controls(*, provides, max_linear: float, max_angular: float,
                   autonomy: tuple[Literal["line"], ...] = ()) -> dict:
    """Pinky's controls from its adapter manifest's `provides` (D-411 §8).

    `autonomy` is what the caller provides (not live readiness); pivot/fine are Pinky profile constants.
    """
    items = []
    if "drive" in provides:
        items.append(BaseVelocityControl(id="base", label="주행", max_linear=max_linear,
                                         max_angular=max_angular, pivot=True, fine=True,
                                         autonomy=autonomy))
    return ControlsDescriptor(items=tuple(items)).model_dump(by_alias=True, mode="json")
