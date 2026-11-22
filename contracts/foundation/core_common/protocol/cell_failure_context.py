"""Wire contract models for rich OMX failure context bundles and cell readiness (D-1072)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FAILURE_CONTEXT_SCHEMA = "rosy.omx-failure-context.v1"
CELL_READINESS_SCHEMA = "rosy.cell-readiness.v1"
FAILURE_CONTEXT_MAX_BYTES = 49_152
FAILURE_CONTEXT_MAX_DEPTH = 6
FAILURE_CONTEXT_DEFAULT_TTL_S = 30.0
FAILURE_BUNDLE_MAX_FRAMES = 24
FAILURE_ASSET_MAX_BYTES = 16 * 1024 * 1024

FALLBACK_VERBS = (
    "reinsert",
    "release_and_rise",
    "align_push",
    "retry_ik_slower",
    "retry_ik_alt_axis",
    "redirect_alt_dest",
    "home_unwedge",
    "propose_ik_fallback_for_policy",
    "escalate_human",
)
FALLBACK_STRATA = ("reflex", "tier2_auto", "tier1_propose", "human_only")
MEASURED_VETO_CODES = (
    "OUT_OF_HOME_POSE",
    "TOP_CAMERA_SHIFTED",
    "MISSING_SITE_MAP",
    "ARM_INCIDENT_HELD",
    "LATCHED_HW_ERROR",
    "WINDUP_HIT",
    "CAPS_UNRESTORED",
    "EXTENDED_TORQUE_DROP_FORBIDDEN",
    "HOLDING_HIGH_NO_RELEASE",
    "REPEAT_UNKNOWN_ESCALATION",
    "AMR_BED_REQUIRES_FLEET_R",
    "MISSING_REQUIRED_CAMERA",
    "PENDING_INTENT_PRESENT",
    "PEER_ARM_LOCKED_OR_HELD",
    "FLEET_SAFETY_STOP_OR_ABORTED",
    "NO_MEASURED_OBJECTS",
)

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
BundleId = Annotated[str, Field(pattern=r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
SafeAssetName = Annotated[str, Field(pattern=r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
_LONG_B64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]{2048,}$")


def _norm_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _norm_for_hash(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_norm_for_hash(x) for x in value]
    if isinstance(value, float) and not isinstance(value, bool):
        return int(value) if math.isfinite(value) and value.is_integer() else value
    return value


def canonical_sha256(payload: dict[str, Any], *, omit_keys: tuple[str, ...] = ()) -> str:
    """Return canonical sorted-JSON SHA-256 hex digest with selected top-level keys omitted."""
    filtered = {k: v for k, v in payload.items() if k not in omit_keys} if omit_keys else payload
    normed = _norm_for_hash(filtered)
    raw = json.dumps(normed, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _check_depth(value: Any, level: int = 0) -> None:
    if level > FAILURE_CONTEXT_MAX_DEPTH:
        raise ValueError(f"JSON nested deeper than {FAILURE_CONTEXT_MAX_DEPTH}")
    if isinstance(value, dict):
        for item in value.values():
            _check_depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, level + 1)


def _check_no_inline_images(value: Any) -> None:
    if isinstance(value, str):
        if "data:image/" in value.lower() or _LONG_B64_RE.fullmatch(value):
            raise ValueError("inline base64 image payloads are forbidden in failure context JSON")
    elif isinstance(value, dict):
        for item in value.values():
            _check_no_inline_images(item)
    elif isinstance(value, list):
        for item in value:
            _check_no_inline_images(item)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, populate_by_name=True)


class MeasuredVeto(_Strict):
    code: Literal[MEASURED_VETO_CODES]
    severity: Literal["hard", "soft"]
    detail: Annotated[str, Field(min_length=1, max_length=300)]
    evidence_path: Annotated[str, Field(min_length=1, max_length=120)]


class FallbackMenuOption(_Strict):
    verb: Literal[FALLBACK_VERBS]
    tier: Annotated[int, Field(ge=0, le=3)]
    stratum: Literal[FALLBACK_STRATA]
    target_surface: Literal["human_request", "cell_job_api", "fleet_pipeline", "in_carry"]
    requires_human_operator: bool
    requires_person_at_switch: bool
    preconditions_met: bool
    blocked_by: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list)


class CameraManifestEntry(_Strict):
    status: Literal["ok", "missing_device", "stale", "error", "disabled"]
    required_for_mode: bool
    source_seq: Annotated[int, Field(ge=0)] | None = None
    source_stamp: float | None = None
    age_at_stop_s: Annotated[float, Field(ge=0.0)] | None = None
    quality: dict[str, Any] | None = None
    error: Annotated[str, Field(max_length=200)] | None = None


class FailureAssetRef(_Strict):
    id: Annotated[str, Field(min_length=1, max_length=80)]
    file: SafeAssetName
    camera: Annotated[str, Field(min_length=1, max_length=32)] | None = None
    kind: Literal["tip_crop", "at", "pre", "post", "before", "after", "clip", "trace"]
    t_rel_s: float | None = None
    source_seq: Annotated[int, Field(ge=0)] | None = None
    source_stamp: float | None = None
    width: Annotated[int, Field(ge=1)] | None = None
    height: Annotated[int, Field(ge=1)] | None = None
    bytes: Annotated[int, Field(ge=1, le=FAILURE_ASSET_MAX_BYTES)]
    sha256: Sha256Hex
    asset_url: Annotated[str, Field(max_length=240)] | None = None
    tip_projection: dict[str, Any] | None = None


class FailureFreshness(_Strict):
    age_s: Annotated[float, Field(ge=0.0)]
    current_cell_state_gen: Annotated[int, Field(ge=0)]
    gen_matches: bool
    still_valid_for_action: bool
    invalidated_reasons: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list)


class FailureContextFence(_Strict):
    parent_task_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    expected_attempt_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    expected_context_sha256: Sha256Hex
    expected_readiness_digest: Sha256Hex | None = None
    expected_cell_state_gen: Annotated[int, Field(ge=0)]
    expected_dispatch_generation: Annotated[int, Field(ge=0)] | None = None
    expected_stop_generation: Annotated[int, Field(ge=0)] | None = None
    max_age_s: Annotated[float, Field(gt=0.0, le=FAILURE_CONTEXT_DEFAULT_TTL_S)] = FAILURE_CONTEXT_DEFAULT_TTL_S


class VisualBundleSection(_Strict):
    camera_manifest: dict[Annotated[str, Field(min_length=1, max_length=32)], CameraManifestEntry] = Field(default_factory=dict)
    frames: Annotated[list[FailureAssetRef], Field(max_length=FAILURE_BUNDLE_MAX_FRAMES)] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    control_ref: dict[str, Any] | None = None
    depth_summary: dict[str, Any] | None = None


class HistoryConstraintsSection(_Strict):
    recent_attempts: list[dict[str, Any]] = Field(default_factory=list)
    recent_decisions: list[dict[str, Any]] = Field(default_factory=list)
    decisions_digest: Annotated[str, Field(max_length=600)] = ""
    recent_why: list[dict[str, Any]] = Field(default_factory=list)
    repeat_unknown_count: Annotated[int, Field(ge=0)] = 0
    repeat_unknown_tripped: bool = False
    knowledge_sha: Annotated[str, Field(max_length=64)] | None = None
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    choices_record: dict[str, Any] = Field(default_factory=dict)
    compensation: dict[str, Any] = Field(default_factory=dict)
    measured_vetoes: list[MeasuredVeto] = Field(default_factory=list)
    allowed_fallback_menu: list[FallbackMenuOption] = Field(default_factory=list)


class CellFailureContext(_Strict):
    schema_id: Literal["rosy.omx-failure-context.v1"] = Field(FAILURE_CONTEXT_SCHEMA, alias="schema")
    bundle_id: BundleId
    kind: Literal["stop", "refusal", "verify_fail", "policy_fail", "fault", "control"]
    created_at_s: float
    monotonic_s: float
    ttl_s: Annotated[float, Field(gt=0.0, le=FAILURE_CONTEXT_DEFAULT_TTL_S)] = FAILURE_CONTEXT_DEFAULT_TTL_S
    arm_id: Literal["arm_s", "arm_a", "arm_b"]
    cell_id: Literal["cell_s", "cell_ab"]
    executor_mode: Literal["ik_auto_pick", "act_paced", "act_timed", "hybrid", "taught", "recovery"]
    correlation: dict[str, Any]
    generation: dict[str, Any]
    measurement: dict[str, Any]
    spatial: dict[str, Any]
    visual: VisualBundleSection
    history_and_constraints: HistoryConstraintsSection
    context_sha256: Sha256Hex
    freshness: FailureFreshness | None = None

    @model_validator(mode="after")
    def _validate_integrity(self) -> "CellFailureContext":
        core = _norm_for_hash(self.model_dump(mode="json", by_alias=True, exclude={"context_sha256", "freshness"}, exclude_none=True))
        _check_depth(core)
        _check_no_inline_images(core)
        encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > FAILURE_CONTEXT_MAX_BYTES:
            raise ValueError(f"failure context exceeds {FAILURE_CONTEXT_MAX_BYTES} bytes")
        if hashlib.sha256(encoded).hexdigest() != self.context_sha256:
            raise ValueError("context_sha256 mismatch")
        for frame in self.visual.frames:
            if frame.camera and frame.camera in self.visual.camera_manifest:
                if self.visual.camera_manifest[frame.camera].status == "missing_device":
                    raise ValueError(f"frame supplied for missing_device camera {frame.camera}")
        return self


class CellReadiness(_Strict):
    schema_id: Literal["rosy.cell-readiness.v1"] = Field(CELL_READINESS_SCHEMA, alias="schema")
    observed_at: float
    max_age_s: Annotated[float, Field(gt=0.0, le=5.0)] = 5.0
    cell_state_gen: Annotated[int, Field(ge=0)]
    readiness_digest: Sha256Hex
    arms: dict[Literal["arm_s", "arm_a", "arm_b"], dict[str, Any]]
    blocking_refusals: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list)
    allowed_tiers_now: list[Annotated[int, Field(ge=0, le=3)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_digest(self) -> "CellReadiness":
        core = self.model_dump(mode="json", by_alias=True, exclude={"readiness_digest"}, exclude_none=True)
        _check_depth(core)
        _check_no_inline_images(core)
        if canonical_sha256(core) != self.readiness_digest:
            raise ValueError("readiness_digest mismatch")
        return self


__all__ = [
    "CELL_READINESS_SCHEMA",
    "CameraManifestEntry",
    "CellFailureContext",
    "CellReadiness",
    "FAILURE_ASSET_MAX_BYTES",
    "FAILURE_BUNDLE_MAX_FRAMES",
    "FAILURE_CONTEXT_DEFAULT_TTL_S",
    "FAILURE_CONTEXT_MAX_BYTES",
    "FAILURE_CONTEXT_MAX_DEPTH",
    "FAILURE_CONTEXT_SCHEMA",
    "FALLBACK_STRATA",
    "FALLBACK_VERBS",
    "FailureAssetRef",
    "FailureContextFence",
    "FailureFreshness",
    "FallbackMenuOption",
    "HistoryConstraintsSection",
    "MEASURED_VETO_CODES",
    "MeasuredVeto",
    "VisualBundleSection",
    "canonical_sha256",
]
