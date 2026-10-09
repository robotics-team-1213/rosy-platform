"""D-531 short-lived CORE route context for camera lane evidence."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class RouteContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1]
    seq: StrictInt | None
    place_id: str | None = Field(default=None, min_length=1)
    map_id: str | None = Field(default=None, min_length=1)
    stamp_s: float | None = Field(default=None, allow_inf_nan=False)
    valid_until_s: float | None = Field(default=None, allow_inf_nan=False)
    kind: Literal["junction", "bend", "ring"] | None = None
    ahead_m: tuple[float, float] | None = None
    bend_phase: Literal["bending", "reacquiring"] | None = None
    lane_turn_deg: float | None = Field(default=None, allow_inf_nan=False)
    curvature_1pm: float | None = Field(default=None, allow_inf_nan=False)

    def message(self) -> dict:
        return {**self.model_dump(exclude_none=True), "seq": self.seq}

    @model_validator(mode="after")
    def valid_context(self):
        if self.seq is None:
            if any(getattr(self, key) is not None for key in (
                    "place_id", "map_id", "stamp_s", "valid_until_s", "kind",
                    "ahead_m", "bend_phase", "lane_turn_deg", "curvature_1pm")):
                raise ValueError("clear context contains a place")
            return self
        if self.seq <= 0 or any(getattr(self, key) is None for key in (
                "place_id", "map_id", "stamp_s", "valid_until_s", "kind")):
            raise ValueError("active context needs a positive sequence, place, map and times")
        if not self.stamp_s < self.valid_until_s <= self.stamp_s + 1.0:
            raise ValueError("route context lifetime must be at most one second")
        if self.ahead_m is not None and (not all(math.isfinite(v) and -.5 <= v <= 2.0 for v in self.ahead_m)
                                         or self.ahead_m[0] > self.ahead_m[1]):
            raise ValueError("invalid route distance window")
        if self.lane_turn_deg is not None and abs(self.lane_turn_deg) > 360.0:
            raise ValueError("invalid lane turn")
        if self.bend_phase is not None and self.kind != "bend":
            raise ValueError("bend phase belongs to bend context")
        if self.kind == "ring":
            if self.curvature_1pm is None or not .5 <= abs(self.curvature_1pm) <= 5.0:
                raise ValueError("ring needs bounded curvature")
        elif self.curvature_1pm is not None:
            raise ValueError("curvature belongs to ring context")
        return self
