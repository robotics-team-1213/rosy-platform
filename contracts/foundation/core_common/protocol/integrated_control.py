"""Bounded control-unit observations and fenced stop delivery receipts."""

import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .control_units import Coordinate, DelegationId, UnitId
from .work import FleetTaskStatus


MapId = Annotated[str, Field(strict=True, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
MapElementId = Annotated[str, Field(strict=True, min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")]
_Count = Annotated[int, Field(strict=True, ge=0)]
_Revision = Annotated[int, Field(strict=True, ge=1)]
_Age = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Bool = Annotated[bool, Field(strict=True)]
_Error = Annotated[str, Field(strict=True, min_length=1, max_length=96, pattern=r"^[A-Z][A-Z0-9_]*$")]
_Availability = Literal["AVAILABLE", "STALE", "UNAVAILABLE"]


def _unique(values):
    values = list(values)
    if len(values) != len(set(values)):
        raise ValueError("duplicate resource identity")


def _bounded_json(value, limit):
    encoded = json.dumps(value.model_dump(mode="json"), ensure_ascii=False, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError(f"payload exceeds {limit} bytes")


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Summary(_Wire):
    @model_validator(mode="after")
    def bounded_summary(self):
        _bounded_json(self, 128 * 1024)
        return self


class ControlDispatchFence(_Wire):
    authority_epoch: _Count
    generation: _Count


class ControlMapRef(_Wire):
    map_id: MapId
    version: _Revision
    frame: Literal["unit_local"]


class ControlUnitSummary(_Wire):
    unit_id: UnitId
    parent: UnitId | None
    availability: _Availability
    sampled_at: AwareDatetime | None
    age_s: _Age | None
    robots_total: Annotated[int, Field(strict=True, ge=0, le=256)]
    robots_online: Annotated[int, Field(strict=True, ge=0, le=256)]
    tasks_active: _Count
    map: ControlMapRef | None
    dispatch: ControlDispatchFence | None
    error: _Error | None
    stop_pending: _Count = 0

    @model_validator(mode="after")
    def valid_online_count(self):
        if self.robots_online > self.robots_total:
            raise ValueError("online robots exceed total robots")
        return self


class ControlOverview(_Summary):
    unit_id: UnitId
    config_revision: UnitId
    units: list[ControlUnitSummary] = Field(max_length=64)

    @field_validator("units")
    @classmethod
    def unique_units(cls, values):
        _unique(value.unit_id for value in values)
        return values


class ControlRobotPose(_Wire):
    x: Coordinate
    y: Coordinate
    yaw: Coordinate
    map_id: MapId | None
    source: str = Field(strict=True, min_length=1, max_length=64)
    frame: Literal["map", "odom", "unknown"]


class ControlRobotInfo(_Wire):
    robot_id: UnitId
    online: _Bool
    state_age_s: _Age | None
    mode: Annotated[str, Field(strict=True, min_length=1, max_length=32)] | None
    battery_percent: Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)] | None
    estop: _Bool | None
    pose: ControlRobotPose | None
    evidence: dict[Literal["pose", "battery", "safety"],
                   Literal["fresh", "delayed", "disconnected", "unavailable", "unknown"]] = Field(
                       default_factory=dict, max_length=3)


class ControlTaskInfo(_Wire):
    task_id: DelegationId
    robot_id: UnitId
    status: FleetTaskStatus
    updated_at: AwareDatetime


class ControlUnitDetail(_Summary):
    unit_id: UnitId
    config_revision: UnitId
    availability: _Availability
    sampled_at: AwareDatetime | None
    age_s: _Age | None
    robots: list[ControlRobotInfo] = Field(max_length=256)
    tasks: list[ControlTaskInfo] = Field(max_length=100)
    tasks_truncated: _Bool
    map: ControlMapRef | None
    dispatch: ControlDispatchFence | None

    @field_validator("robots")
    @classmethod
    def unique_robots(cls, values):
        _unique(value.robot_id for value in values)
        return values

    @field_validator("tasks")
    @classmethod
    def unique_tasks(cls, values):
        _unique(value.task_id for value in values)
        return values


class ControlMapPoint(_Wire):
    x: Coordinate
    y: Coordinate


class ControlMapPlace(ControlMapPoint):
    id: MapElementId
    label: str = Field(strict=True, min_length=1, max_length=128)


class ControlMapLane(_Wire):
    id: MapElementId
    points: list[ControlMapPoint] = Field(min_length=2, max_length=20_000)


class ControlMapSnapshot(_Wire):
    unit_id: UnitId
    config_revision: UnitId
    map: ControlMapRef
    places: list[ControlMapPlace] = Field(max_length=500)
    lanes: list[ControlMapLane] = Field(max_length=1000)

    @field_validator("places", "lanes")
    @classmethod
    def unique_elements(cls, values):
        _unique(value.id for value in values)
        return values

    @model_validator(mode="after")
    def bounded_geometry(self):
        if sum(len(lane.points) for lane in self.lanes) > 20_000:
            raise ValueError("map exceeds 20000 lane points")
        _bounded_json(self, 2 * 1024 * 1024)
        return self


class ControlStopRequest(_Wire):
    stop_id: DelegationId
    target_unit: UnitId
    config_revision: UnitId
    expected_controls: dict[UnitId, ControlDispatchFence] = Field(min_length=1, max_length=64)


class ControlStopIngress(ControlStopRequest):
    origin_id: UnitId


class ControlStopUnitResult(_Wire):
    unit_id: UnitId
    state: Literal["PENDING", "SENDING", "ACKNOWLEDGED", "PARTIAL", "UNKNOWN", "STALE_FENCE", "NOT_REACHED",
                   "SUPERSEDED_BY_OPERATOR_RECOMMISSIONING"]
    dispatch: ControlDispatchFence | None
    acknowledged_robots: _Count
    unknown_robots: _Count
    omx_state: Literal["NOT_CONFIGURED", "REQUESTED", "LOCAL_LATCHED", "UNKNOWN", "PARTIAL"]
    physical_stop: Literal["UNVERIFIED"]
    error: _Error | None = None


class ControlStopSnapshot(_Summary):
    unit_id: UnitId
    origin_id: UnitId
    stop_id: DelegationId
    target_unit: UnitId
    config_revision: UnitId
    results: list[ControlStopUnitResult] = Field(max_length=64)
    revision: _Revision

    @field_validator("results")
    @classmethod
    def unique_results(cls, values):
        _unique(value.unit_id for value in values)
        return values


class ControlStopReconcile(_Wire):
    expected_generation: _Count
    receiver_channels_terminated: Literal[True]
    receivers_recommissioned: Literal[True]
    evidence: str = Field(strict=True, min_length=16, max_length=2048)
    affected_units: list[UnitId] = Field(min_length=1, max_length=64)

    @field_validator("receiver_channels_terminated", "receivers_recommissioned", mode="before")
    @classmethod
    def strict_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit boolean confirmation required")
        return value

    @field_validator("affected_units")
    @classmethod
    def unique_affected_units(cls, values):
        _unique(values)
        return values


class ControlStopReference(_Wire):
    origin_id: UnitId
    stop_id: DelegationId
    target_unit: UnitId
    config_revision: UnitId
    revision: _Revision
    incomplete: _Bool
    local_reconciliation_required: _Bool
    updated_at: AwareDatetime


class ControlStopHistory(_Summary):
    unit_id: UnitId
    config_revision: UnitId
    stops: list[ControlStopReference] = Field(max_length=100)

    @field_validator("stops")
    @classmethod
    def unique_stop_identities(cls, values):
        _unique((value.origin_id, value.stop_id) for value in values)
        return values
