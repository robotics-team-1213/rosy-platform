"""D-655 survey references and road facilities; never an operational pose or command."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer

Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-1000, le=1000)]
Point = tuple[Coordinate, Coordinate]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")]


class SurveyReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: Identifier
    origin: Point
    heading_rad: float = Field(ge=-math.tau, le=math.tau, allow_inf_nan=False)
    scale_source: Literal["odometry", "measured"]
    measured_distance_m: Optional[float] = Field(default=None, gt=0, le=2000, allow_inf_nan=False)
    description: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    reviewed: bool = False
    review_note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _evidence(self) -> "SurveyReference":
        if self.scale_source == "measured" and self.measured_distance_m is None:
            raise ValueError("measured scale needs measured_distance_m")
        if self.reviewed and not self.review_note.strip():
            raise ValueError("reviewed survey needs review_note")
        return self


class RoadEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["camera", "odometry", "operator"]
    status: Literal["observed", "inferred", "reviewed"] = "observed"
    reference_revision: Identifier
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _review(self) -> "RoadEvidence":
        if self.status == "reviewed" and not self.note.strip():
            raise ValueError("reviewed road evidence needs a note")
        return self


class FacilityApproach(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,32}$")
    forward: bool
    stop_s_m: Optional[float] = Field(default=None, ge=0, le=2000, allow_inf_nan=False)


class SiteFacility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Identifier
    name: str = Field(min_length=1, max_length=64, pattern=r"\S")
    kind: Literal["traffic_signal", "stop_line", "landmark", "exclusion"]
    geometry: list[Point] = Field(min_length=1, max_length=32)
    approaches: list[FacilityApproach] = Field(default_factory=list, max_length=64)
    signal_id: Optional[Identifier] = None
    signal_kind: Optional[Literal["physical", "virtual"]] = None
    evidence: Optional[RoadEvidence] = None

    @model_serializer(mode="wrap")
    def _optional_evidence(self, handler):
        body = handler(self)
        if self.evidence is None:
            body.pop("evidence", None)
        return body

    @model_validator(mode="after")
    def _geometry_and_device(self) -> "SiteFacility":
        count = len(self.geometry)
        if self.kind in ("traffic_signal", "landmark") and count != 1:
            raise ValueError("signal or landmark geometry must be one point")
        if self.kind == "stop_line" and (count != 2 or math.dist(*self.geometry) < .001):
            raise ValueError("stop line needs two distinct points")
        if self.kind == "exclusion":
            if count < 3:
                raise ValueError("exclusion needs a polygon")
            ring = list(zip(self.geometry, self.geometry[1:] + self.geometry[:1]))
            area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in ring)) / 2
            if area < .0001 or any(math.dist(a, b) < .001 for a, b in ring):
                raise ValueError("exclusion polygon is degenerate")
            def side(a, b, p):
                return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
            for i, (a, b) in enumerate(ring):
                for j, (c, d) in enumerate(ring):
                    if j <= i + 1 or (i == 0 and j == count - 1):
                        continue
                    overlap = all(max(min(a[k], b[k]), min(c[k], d[k]))
                                  <= min(max(a[k], b[k]), max(c[k], d[k])) for k in (0, 1))
                    if overlap and side(a, b, c) * side(a, b, d) <= 0 and side(c, d, a) * side(c, d, b) <= 0:
                        raise ValueError("exclusion polygon must not intersect itself")
        if self.kind == "traffic_signal":
            if self.signal_id is None or self.signal_kind is None or not self.approaches:
                raise ValueError("signal needs signal_id, signal_kind and controlled approaches")
        elif self.signal_id is not None or self.signal_kind is not None:
            raise ValueError("device metadata belongs to a traffic signal")
        if len({(a.edge_id, a.forward) for a in self.approaches}) != len(self.approaches):
            raise ValueError("facility approaches must be unique")
        return self
