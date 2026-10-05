"""D-468 optional image-bound ground boundary evidence, never a motion command."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LaneBoundaryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    side: Literal["left", "right"]
    slope: float
    intercept_m: float
    observed_x_min_m: float
    observed_x_max_m: float

    @model_validator(mode="after")
    def segment_order(self):
        if self.observed_x_min_m >= self.observed_x_max_m:
            raise ValueError("nonempty boundary segment required")
        return self


class LaneContainmentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    stamp: float = Field(ge=0)
    geometry_id: str = Field(min_length=1, max_length=128)
    ground_source: Literal["NOMINAL", "CALIBRATED", "GAZEBO"]
    uncertainty_m: float | None = Field(default=None, ge=0, le=1)
    boundaries: list[LaneBoundaryEvidence] = Field(max_length=2)

    @model_validator(mode="after")
    def unique_sides(self):
        if len({b.side for b in self.boundaries}) != len(self.boundaries):
            raise ValueError("duplicate boundary side")
        if len(self.boundaries) == 2:
            edges = {b.side: b for b in self.boundaries}
            if edges["left"].intercept_m <= edges["right"].intercept_m:
                raise ValueError("crossed boundary ordering")
        return self
