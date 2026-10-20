"""D-769 internal CORE-to-camera selected-route prior; no movement grant."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class AuthorityRouteGuide(BaseModel):
    """Fleet geometry at the enclosing authority's echoed odom pose_stamp."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    map_id: str = Field(min_length=1, max_length=128)
    map_revision: StrictInt = Field(ge=0)
    heading_here_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    heading_ahead_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    ahead_m: float = Field(gt=0, le=2, allow_inf_nan=False)
    s_m: float = Field(ge=0, allow_inf_nan=False)
    off_route_m: float = Field(ge=0, allow_inf_nan=False)
    #: D-769 rev 2: the same offset signed, + left of the route centre line in the travel direction (optional)
    off_route_left_m: float | None = Field(default=None, ge=-2, le=2, allow_inf_nan=False)
    #: D-573 rev 8: the nearest map wall face beside the lane ahead, across the lane from the robot
    #: (+ left; left > 0 > right); None = no map wall there (optional)
    wall_left_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)
    wall_right_m: float | None = Field(default=None, ge=-2, lt=0, allow_inf_nan=False)
    #: how far along the lane from the robot those walls run; CORE clips the look only that far
    wall_ahead_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)
    #: Fleet sends 1 s; up to 3 s for a simulator at ~0.3 real time (D-769 rev 3), where 1 s of wall time
    #: aged every prior out between authorities (v2 lap r37-r41).
    max_age_s: float = Field(gt=0, le=3, allow_inf_nan=False)


class SelectedRoutePrior(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    leg_id: str = Field(min_length=1, max_length=128)
    authority_seq: StrictInt = Field(ge=0)
    map_id: str = Field(min_length=1, max_length=128)
    map_revision: StrictInt = Field(ge=0)
    source_stamp_s: float = Field(ge=0, allow_inf_nan=False)
    valid_until_s: float = Field(gt=0, allow_inf_nan=False)
    heading_here_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    heading_ahead_deg: float = Field(ge=-180, le=180, allow_inf_nan=False)
    ahead_m: float = Field(gt=0, le=2, allow_inf_nan=False)
    s_m: float = Field(ge=0, allow_inf_nan=False)
    off_route_m: float = Field(ge=0, allow_inf_nan=False)
    off_route_left_m: float | None = Field(default=None, ge=-2, le=2, allow_inf_nan=False)
    wall_left_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)
    wall_right_m: float | None = Field(default=None, ge=-2, lt=0, allow_inf_nan=False)
    wall_ahead_m: float | None = Field(default=None, gt=0, le=2, allow_inf_nan=False)
    pivot_ok: Literal[False] = False

    @model_validator(mode="after")
    def bounded_lifetime(self):
        if not self.source_stamp_s < self.valid_until_s <= self.source_stamp_s + 3.0:
            raise ValueError("route prior needs a source-based lifetime of at most three seconds")
        return self


class LaneRouteGuide(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    v: Literal[1]
    publisher_epoch: str = Field(min_length=1, max_length=128)
    seq: StrictInt = Field(ge=0)
    guide: SelectedRoutePrior | None
