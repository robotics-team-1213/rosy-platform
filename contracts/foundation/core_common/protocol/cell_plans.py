"""Strict Pydantic v2 wire contracts for dual-mode OMX cell plans (rosy.cell-plan.v1)."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

CELL_PLAN_SCHEMA = "rosy.cell-plan.v1"

CellPlanMode = Literal["harbor_plan", "outbound", "rehandle", "goal"]
CellPlanOrderSource = Literal["harbor", "rosy_r"]
CellPlanStatus = Literal[
    "PROPOSED",
    "PARTIALLY_ADMITTED",
    "QUEUED",
    "RUNNING",
    "PAUSED_HUMAN",
    "COMPLETED",
    "CANCELLED",
    "ABORTED",
]


def _clean_short_text(value: Any, *, max_len: int = 192, label: str = "text") -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    text = value.strip()
    if not text or len(text) > max_len or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"{label} must be clean non-empty text within {max_len} chars")
    return text


class CellPlanStepInput(BaseModel):
    """Single explicit step proposed by Harbor under harbor_plan mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    src_site: Annotated[str, Field(min_length=1, max_length=96)]
    dst_site: Annotated[str, Field(min_length=1, max_length=96)]
    cargo_id: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    arm_id: Literal["arm_a", "arm_b"] | None = None
    phase_label: Annotated[str, Field(min_length=1, max_length=48)] = "이동"


class CellPlanCancelRequest(BaseModel):
    """Operator or owning-service cancellation request for pending cell-plan steps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        return _clean_short_text(value, max_len=192, label="reason")


class CellPlanMoveOut(BaseModel):
    """Planned move item serialized inside a cell-plan summary or dry-run response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    src_site: str
    dst_site: str
    arm_id: str
    tier: Annotated[int, Field(strict=True, ge=1)]
    phase_label: str
    src_wire_ref: str | None = None
    dst_wire_ref: str | None = None
    task_id: str | None = None
    cargo_id: str | None = None


class CellPlanSummaryOut(BaseModel):
    """Aggregate view of one dual-mode OMX cell plan."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    plan_id: str
    schema_version: Literal["rosy.cell-plan.v1"] = Field(default=CELL_PLAN_SCHEMA, alias="schema")
    mode: CellPlanMode
    order_source: CellPlanOrderSource
    cell_id: str
    status: CellPlanStatus
    total_steps: Annotated[int, Field(strict=True, ge=0)]
    completed_steps: Annotated[int, Field(strict=True, ge=0)]
    proposer: str | None = None
    request_key: str | None = None
    request_digest: str | None = None
    hold_reason: str | None = None
    cell_phase: str | None = None
    task_ids: list[str]
    moves: list[dict[str, Any]]
    created_at: float


class CellPlanDryRunResponse(BaseModel):
    """Read-only planning simulation response from POST /api/fleet/pipeline/cell-plans/dry-run."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    ok: StrictBool = True
    schema_version: Literal["rosy.cell-plan.v1"] = Field(default=CELL_PLAN_SCHEMA, alias="schema")
    mode: CellPlanMode
    order_source: CellPlanOrderSource
    moves: list[dict[str, Any]]
    final_state: dict[str, str] | None = None
    why: str | None = None


class CellPlanResponse(BaseModel):
    """Create / single-read response envelope for rosy.cell-plan.v1."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    ok: StrictBool = True
    schema_version: Literal["rosy.cell-plan.v1"] = Field(default=CELL_PLAN_SCHEMA, alias="schema")
    plan: CellPlanSummaryOut
    tasks: list[dict[str, Any]]


class CellPlanCancelResponse(BaseModel):
    """Cancellation response envelope returning updated plan, tasks, and cancelled step IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    ok: StrictBool = True
    schema_version: Literal["rosy.cell-plan.v1"] = Field(default=CELL_PLAN_SCHEMA, alias="schema")
    plan: CellPlanSummaryOut
    tasks: list[dict[str, Any]]
    cancelled_task_ids: list[str]
