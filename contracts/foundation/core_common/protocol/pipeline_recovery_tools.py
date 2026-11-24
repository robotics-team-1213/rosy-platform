"""Strict wire schemas & forbidden-key guards for guarded Fleet LLM/VLA recovery tools."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cell_failure_context import MEASURED_VETO_CODES, Sha256Hex

RECOVERY_TOOLS_SCHEMA = "rosy.pipeline.recovery-tools.v1"

ALLOWED_RECOVERY_TOOLS: tuple[str, ...] = (
    "inspect_failure_context",
    "safe_fold_home",
    "record_visual_checkpoint",
    "enqueue_displaced_recovery",
    "request_repark",
    "enqueue_vla_act_fallback",
    "dispatch_pinky_reroute",
    "escalate_human",
)

HOMING_STRATEGIES: tuple[str, ...] = (
    "auto_fold",
    "release_and_lift",
    "guarded_slow_park",
    "finalize_home_verify",
)

REQUIRED_HOMING_CAMERAS: dict[str, tuple[str, ...]] = {
    "arm_s": ("arm_s_top", "arm_s_wrist"),
    "arm_a": ("top", "side", "arm_a_wrist"),
    "arm_b": ("top", "side", "arm_b_wrist"),
}

FORBIDDEN_TOOL_ARG_KEYS: frozenset[str] = frozenset({
    "cmd_vel",
    "twist",
    "joints",
    "joints_deg",
    "pose",
    "pwm",
    "torque",
    "torque_off",
    "eeprom",
    "raw_ticks",
    "goal_pos",
    "motor_id",
    "bus",
    "fifo",
    "shell",
    "command",
    "path",
    "file_path",
    "url",
    "uri",
    "operator_confirmed",
    "bypass_presence",
    "clear_estop",
    "clear_human_hold",
    "x",
    "y",
    "z",
    "yaw",
})

MAX_RECOVERIES_PER_ROOT = 1
MAX_SAFE_HOME_PER_ARM_24H = 3
MAX_ACT_FALLBACK_CHUNKS = 4
MAX_ARG_DEPTH = 8
MAX_INVOKE_BODY_BYTES = 32768
_ID_PAT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")

BoundedId = Annotated[str, Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]


def find_forbidden_key(value: Any, *, _depth: int = 0, max_depth: int = MAX_ARG_DEPTH) -> str | None:
    """Return 'PAYLOAD_TOO_DEEP' or the first raw-hardware/bypass key in a nested JSON payload."""
    if _depth > max_depth:
        return "PAYLOAD_TOO_DEEP"
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.strip().lower() in FORBIDDEN_TOOL_ARG_KEYS:
                return key
            nested = find_forbidden_key(item, _depth=_depth + 1, max_depth=max_depth)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = find_forbidden_key(item, _depth=_depth + 1, max_depth=max_depth)
            if nested is not None:
                return nested
    return None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class InspectArgs(_Strict):
    cell_id: Literal["cell_s", "cell_ab"] | None = None
    root_task_id: BoundedId | None = None


class SafeFoldHomeArgs(_Strict):
    arm_id: Literal["arm_s", "arm_a", "arm_b"] | None = None
    strategy: Literal["auto_fold", "release_and_lift", "guarded_slow_park", "finalize_home_verify"] = "auto_fold"


class VisualCheckpointArgs(_Strict):
    arm_id: Literal["arm_s", "arm_a", "arm_b"] | None = None
    stage: Literal["pre_park", "after_lift", "after_park"]
    verdict: Literal["CLEAR", "FOLDED_HOME", "OBSTRUCTED", "UNCERTAIN"]
    cargo_detached: bool
    gripper_open: bool | None = None
    overhead_clear: bool
    cameras_checked: dict[BoundedId, Annotated[int, Field(ge=0)]]
    observation_summary: Annotated[str, Field(min_length=1, max_length=240)]


class DisplacedRecoveryArgs(_Strict):
    site: Literal["belt_far", "floor_front"]
    robot_id: BoundedId | None = None


class ReparkArgs(_Strict):
    task_id: BoundedId | None = None


class VlaActFallbackArgs(_Strict):
    mode: Literal["act", "vla_shadow"] = "act"
    max_chunks: Annotated[int, Field(ge=1, le=MAX_ACT_FALLBACK_CHUNKS)] = 2
    robot_id: BoundedId | None = None
    note: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class PinkyRerouteArgs(_Strict):
    target_place: BoundedId
    robot_id: BoundedId | None = None


class EscalateHumanArgs(_Strict):
    summary: Annotated[str, Field(min_length=1, max_length=240)] | None = None


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "inspect_failure_context": InspectArgs,
    "safe_fold_home": SafeFoldHomeArgs,
    "record_visual_checkpoint": VisualCheckpointArgs,
    "enqueue_displaced_recovery": DisplacedRecoveryArgs,
    "request_repark": ReparkArgs,
    "enqueue_vla_act_fallback": VlaActFallbackArgs,
    "dispatch_pinky_reroute": PinkyRerouteArgs,
    "escalate_human": EscalateHumanArgs,
}


class RecoveryToolInvokeRequest(_Strict):
    tool_name: Literal[
        "inspect_failure_context",
        "safe_fold_home",
        "record_visual_checkpoint",
        "enqueue_displaced_recovery",
        "request_repark",
        "enqueue_vla_act_fallback",
        "dispatch_pinky_reroute",
        "escalate_human",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)
    caller_kind: Literal["operator", "llm_agent", "vla_agent", "system"] = "operator"
    request_id: BoundedId
    expected_context_sha256: Sha256Hex | None = None
    root_task_id: BoundedId | None = None
    rationale: Annotated[str, Field(min_length=1, max_length=300)]

    @model_validator(mode="after")
    def _validate_args_for_tool(self) -> "RecoveryToolInvokeRequest":
        bad_key = find_forbidden_key(self.arguments)
        if bad_key == "PAYLOAD_TOO_DEEP":
            raise ValueError("PAYLOAD_TOO_DEEP")
        if bad_key is not None:
            raise ValueError(f"FORBIDDEN_RAW_COMMAND_KEY:{bad_key}")
        TOOL_ARG_MODELS[self.tool_name].model_validate(self.arguments)
        return self


__all__ = [
    "ALLOWED_RECOVERY_TOOLS",
    "FORBIDDEN_TOOL_ARG_KEYS",
    "HOMING_STRATEGIES",
    "MAX_ACT_FALLBACK_CHUNKS",
    "MAX_ARG_DEPTH",
    "MAX_INVOKE_BODY_BYTES",
    "MAX_RECOVERIES_PER_ROOT",
    "MAX_SAFE_HOME_PER_ARM_24H",
    "MEASURED_VETO_CODES",
    "RECOVERY_TOOLS_SCHEMA",
    "REQUIRED_HOMING_CAMERAS",
    "DisplacedRecoveryArgs",
    "EscalateHumanArgs",
    "InspectArgs",
    "PinkyRerouteArgs",
    "RecoveryToolInvokeRequest",
    "ReparkArgs",
    "SafeFoldHomeArgs",
    "TOOL_ARG_MODELS",
    "VisualCheckpointArgs",
    "VlaActFallbackArgs",
    "find_forbidden_key",
]
