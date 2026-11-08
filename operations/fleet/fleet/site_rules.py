"""D-982 ``rosy.site_rules/1``: per-site operating rules as one validated document.

Pure data and validation; no clock, network or robot. Every default equals the constant the
code used before the document existed, so a site with no document behaves exactly as before.
A rule may only restrict further: each bound below sits on the safe side of the constant it
replaces, and nothing here reaches CORE's final authority, guard limits or human confirmation
(D-911). Platform-neutral: places are map place ids, never a business meaning.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.charge_bays import GO_PERCENT, LEAVE_PERCENT
from fleet.swarm.api.types import MIN_SPACING
from fleet.traffic.blocks import HELD_PER_ROBOT, MERGE_MAX_WAIT_S

SCHEMA = "rosy.site_rules/1"
#: CORE's critical level is 10 %; the go level may only be higher (go charging earlier).
MAX_GO_PERCENT = 50.0
MIN_LEAVE_PERCENT = 50.0
#: The follow speed the code used before the document; rules may only lower it.
FOLLOW_SPEED_MPS = 0.15
MIN_FOLLOW_SPEED_MPS = 0.02
MAX_HELD_PER_ROBOT = 8
MAX_STOPS = 50


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, allow_inf_nan=False)


class Departure(_Section):
    merge_max_wait_s: float = Field(default=MERGE_MAX_WAIT_S, ge=1.0, le=60.0)
    #: Fewer blocks per robot would admit more robots on a loop, so 3 is the floor.
    blocks_per_robot: int = Field(default=HELD_PER_ROBOT, ge=HELD_PER_ROBOT, le=MAX_HELD_PER_ROBOT, strict=True)
    order: Literal["fair"] = "fair"


class WhenFull(_Section):
    wait_at: str = Field(min_length=1, max_length=64)
    order: Literal["lowest_battery"] = "lowest_battery"


class Return(_Section):
    go_percent: float = Field(default=GO_PERCENT, ge=GO_PERCENT, le=MAX_GO_PERCENT)
    leave_percent: float = Field(default=LEAVE_PERCENT, ge=MIN_LEAVE_PERCENT, le=100.0)
    when_full: Optional[WhenFull] = None

    @model_validator(mode="after")
    def _leave_above_go(self) -> "Return":
        if self.leave_percent <= self.go_percent:
            raise ValueError("leave_percent must be above go_percent")
        return self


class Stop(_Section):
    place: str = Field(min_length=1, max_length=64)
    role: Literal["load", "unload", "wait"]
    release: Literal["external", "timer"] = "external"
    timeout_s: float = Field(default=300.0, ge=1.0, le=3600.0)
    #: A timeout hands the stop to a person; no rule departs on its own.
    on_timeout: Literal["hold"] = "hold"


class Formation(_Section):
    """Optional refusals for an explicit formation request: a smaller gap or a higher speed is refused."""

    min_gap_m: Optional[float] = Field(default=None, ge=MIN_SPACING, le=5.0)
    max_speed_mps: Optional[float] = Field(default=None, ge=MIN_FOLLOW_SPEED_MPS, le=FOLLOW_SPEED_MPS)

    def refusal(self, spacing: float, speed: float) -> Optional[tuple[str, str]]:
        """``(code, message)`` when a request breaks a limit, else None."""
        if self.min_gap_m is not None and spacing < self.min_gap_m:
            return "GAP_BELOW_SITE_MIN", f"spacing {spacing} m is below the site minimum {self.min_gap_m} m"
        if self.max_speed_mps is not None and speed > self.max_speed_mps:
            return "SPEED_ABOVE_SITE_MAX", f"speed {speed} m/s is above the site maximum {self.max_speed_mps} m/s"
        return None


class SiteRules(_Section):
    schema_: Literal["rosy.site_rules/1"] = Field(default=SCHEMA, alias="schema")
    departure: Departure = Field(default_factory=Departure)
    return_: Return = Field(default_factory=Return, alias="return")
    stops: list[Stop] = Field(default_factory=list, max_length=MAX_STOPS)
    formation: Formation = Field(default_factory=Formation)

    @model_validator(mode="after")
    def _one_stop_per_place_role(self) -> "SiteRules":
        keys = [(stop.place, stop.role) for stop in self.stops]
        if len(set(keys)) != len(keys):
            raise ValueError("a place can have one stop rule per role")
        return self

    def body(self) -> dict:
        return self.model_dump(mode="json", by_alias=True)

    def place_ids(self) -> set[str]:
        """Map places this document names; activation checks them against the active map."""
        names = {stop.place for stop in self.stops}
        if self.return_.when_full is not None:
            names.add(self.return_.when_full.wait_at)
        return names
