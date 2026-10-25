"""D-876 passive Fleet connection cache; no commands or collection side effects."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .connect_reason import REASONS


_RobotId = Annotated[str, Field(strict=True, min_length=1, max_length=96,
                                 pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
_Age = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
_Bool = Annotated[bool, Field(strict=True)]
_Code = Annotated[str, Field(strict=True, min_length=1, max_length=64)]
_Link = Literal["up", "degraded", "unreachable", "moved", "tls-refused", "protocol", "unknown"]


class FleetLinkObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    robot_id: _RobotId
    link: _Link
    reachable: _Bool | None
    reason_code: _Code | None
    state_age_s: _Age | None

    @field_validator("reason_code")
    @classmethod
    def known_reason(cls, value):
        if value is not None and value not in REASONS:
            raise ValueError("unknown connection reason")
        return value


class FleetMonitoringRead(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    sampled_at: AwareDatetime | None
    cache_age_s: _Age | None
    robots: Annotated[list[FleetLinkObservation], Field(max_length=256)]

    @field_validator("sampled_at", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("expected an aware ISO timestamp")
        return value

    @model_validator(mode="after")
    def coherent_cache(self):
        if (self.sampled_at is None) != (self.cache_age_s is None):
            raise ValueError("cache time and age must be present together")
        if self.sampled_at is None and self.robots:
            raise ValueError("missing cache cannot contain robot observations")
        ids = [row.robot_id for row in self.robots]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate robot identity")
        return self
