"""Strict display-only workcell source registration and arm observation payloads."""
import math
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")]
SourceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]
JointName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")]
Label = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[^\x00-\x1f\x7f-\x9f]+$")]
TokenEnv = Annotated[str, Field(pattern=r"^[A-Z_][A-Z0-9_]*$", max_length=128)]


def _json_number(value):
    if type(value) not in (int, float):
        raise ValueError("a finite JSON number is required")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError("a finite JSON number is required")
    return value


JsonNumber = Annotated[float, BeforeValidator(_json_number), Field(allow_inf_nan=False)]


def _observation_topic(value):
    if any(part.lower() in {"command", "commands", "control", "cmd", "cmd_vel"}
           for part in value.split("/")):
        raise ValueError("command topics cannot be observation sources")
    return value


JointTopic = Annotated[str, Field(max_length=256, pattern=r"^/omx_commissioning/[A-Za-z_][A-Za-z0-9_]*/joint_states$"),
                       AfterValidator(_observation_topic)]
ImageTopic = Annotated[str, Field(max_length=256, pattern=r"^/(?:[A-Za-z_][A-Za-z0-9_]*/)*image_raw$"),
                       AfterValidator(_observation_topic)]
DevicePath = Annotated[str, Field(max_length=256, pattern=r"^/dev/v4l/by-(?:id|path)/[^/.\x00-\x20][^/\x00-\x20]*$")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ArmObservation(_StrictModel):
    epoch: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    sequence: Annotated[int, Field(gt=0)]
    captured_at: Annotated[JsonNumber, Field(gt=0)]
    positions: Annotated[dict[JointName, JsonNumber], Field(min_length=1, max_length=8)]


class WorkcellArm(_StrictModel):
    source_id: SourceId
    arm_id: Identifier
    label: Label
    board_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f-\x9f]+$")]
    joint_topic: JointTopic
    joint_names: Annotated[list[JointName], Field(min_length=1, max_length=8)]
    token_env: TokenEnv

    @model_validator(mode="after")
    def unique_joints(self):
        if len(set(self.joint_names)) != len(self.joint_names):
            raise ValueError("joint names must be unique within an arm")
        return self


class WorkcellCamera(_StrictModel):
    source_id: SourceId
    label: Label
    role: Literal["overhead", "wrist"]
    arm_id: Identifier | None
    image_topic: ImageTopic
    device_path: DevicePath
    token_env: TokenEnv


class WorkcellObservation(_StrictModel):
    workcell_id: Identifier
    label: Label
    arms: Annotated[list[WorkcellArm], Field(min_length=1, max_length=8)]
    cameras: Annotated[list[WorkcellCamera], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def camera_arm_binding(self):
        arms = {arm.arm_id for arm in self.arms}
        for camera in self.cameras:
            if ((camera.role == "overhead" and camera.arm_id is not None)
                    or (camera.role == "wrist" and camera.arm_id not in arms)):
                raise ValueError("camera role requires a matching local arm binding")
        return self


class WorkcellObservationManifest(_StrictModel):
    schema_version: Literal["rosy.workcell-observations/1"] = Field(alias="schema")
    workcells: Annotated[list[WorkcellObservation], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique_sources(self):
        seen = {field: set() for field in ("workcell_id", "arm_id", "source_id", "topic", "device", "token_env")}

        def remember(field, value):
            if value in seen[field]:
                raise ValueError(f"duplicate {field} in workcell observation manifest")
            seen[field].add(value)

        for cell in self.workcells:
            remember("workcell_id", cell.workcell_id)
            for arm in cell.arms:
                remember("arm_id", arm.arm_id)
                remember("source_id", arm.source_id)
                remember("topic", arm.joint_topic)
                remember("device", arm.board_id)
                remember("token_env", arm.token_env)
            for camera in cell.cameras:
                remember("source_id", camera.source_id)
                remember("topic", camera.image_topic)
                remember("device", camera.device_path)
                remember("token_env", camera.token_env)
        return self
