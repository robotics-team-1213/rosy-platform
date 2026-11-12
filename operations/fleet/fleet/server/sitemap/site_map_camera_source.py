"""The camera draft entrance: Vision's draft-map candidates become a save-ready draft body.

The browser fetched Vision's ``draft-map`` proposal with a Fleet-issued lease (the D-375
pattern) and posts it here; the candidates are already in map metres on the rectified
plane, so this is validation and assembly only. Each usable lane becomes a two-way edge
between two junction places at its ends (endpoints closer than ``ENDPOINT_TOL_M`` share a
place), each zone an exclusion facility, and the whole body is proven against the
``SiteMap`` model before it is returned. Nothing is written — saving is the operator's
existing PUT draft, so the operator stays the author of the draft.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fleet.site_map import ENDPOINT_TOL_M, IMPORT_SPEED_CAP_MPS, SiteMap

MIN_LANE_M = 0.15          # a lane shorter than this cannot carry the MIN_EDGE_M place pair
MIN_WIDTH_M, MAX_WIDTH_M = 0.05, 1.0


class CameraDraftError(ValueError):
    """Unusable candidates; the route answers 422 SITE_MAP_CAMERA_INVALID with the reason."""


class CameraLane(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polyline_m: list[tuple[float, float]] = Field(min_length=2, max_length=128)
    width_px: float = Field(gt=0.0, le=10000.0)
    id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    from_id: str | None = Field(default=None, max_length=64)
    to_id: str | None = Field(default=None, max_length=64)
    direction: Literal["one_way", "two_way"] | None = None
    speed_cap_mps: float | None = Field(default=None, gt=0.0, le=5.0)


class CameraZone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    polygon_m: list[tuple[float, float]] = Field(min_length=3, max_length=32)
    kind: Literal["exclusion"]


class CameraPlane(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bounds_m: tuple[float, float, float, float]
    px_per_m: float = Field(gt=0.0, le=10000.0)
    calibration_revision: str = Field(min_length=1, max_length=57,   # "camera-" + this fits the survey Identifier
                                      pattern=r"^[A-Za-z0-9_.-]{1,57}$")


class CameraDetector(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1, max_length=64)


class CameraDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=64)
    plane: CameraPlane
    detector: CameraDetector
    lanes: list[CameraLane] = Field(default_factory=list, max_length=200)
    zones: list[CameraZone] = Field(default_factory=list, max_length=50)
    places: list[dict] | None = None
    edges: list[dict] | None = None
    map_id: str | None = Field(default=None, max_length=64)


def _finite(points) -> None:
    if any(not math.isfinite(value) for point in points for value in point):
        raise CameraDraftError("candidate coordinates must be finite")


def camera_draft(body: CameraDraftRequest) -> dict:
    """``{map, provenance}``; raises :class:`CameraDraftError` when nothing usable arrives."""
    revision = f"camera-{body.plane.calibration_revision}"
    note = f"{body.source_id} {body.detector.version} {body.plane.calibration_revision}"
    evidence = {"source": "camera", "status": "reviewed", "reference_revision": revision, "note": note}
    min_x, min_y, max_x, max_y = body.plane.bounds_m

    # Fast path: when Vision's world_261026 tracer provides structured places & edges directly
    if body.places and body.edges:
        traced_edges = []
        for edge in body.edges:
            pts = edge.get("polyline") or []
            _finite(pts)
            traced_edges.append({
                "id": edge["id"],
                "name": edge.get("name") or edge["id"],
                "from": edge["from"],
                "to": edge["to"],
                "polyline": [[round(float(p[0]), 4), round(float(p[1]), 4)] for p in pts],
                "width_m": float(edge.get("width_m", 0.18)),
                "direction": edge.get("direction", "one_way"),
                "drive_mode": edge.get("drive_mode", "lane"),
                "speed_cap_mps": float(edge.get("speed_cap_mps", IMPORT_SPEED_CAP_MPS)),
                "evidence": dict(evidence),
            })
        draft = {
            "schema": "rosy.site_map/1",
            "map_id": body.map_id or "world_261026",
            "places": body.places,
            "edges": traced_edges,
            "facilities": [],
            "survey": {
                "revision": revision,
                "origin": [0.0, 0.0],
                "heading_rad": 0.0,
                "scale_source": "measured",
                "measured_distance_m": 2.44,
                "description": f"카메라 자동 실측 초안 ({note})"[:1000],
            },
        }
        try:
            checked = SiteMap.model_validate(draft)
        except ValidationError as exc:
            raise CameraDraftError(f"the assembled draft does not validate: {exc.error_count()} errors") from exc
        return {
            "map": checked.body(),
            "provenance": {
                "source_id": body.source_id,
                "calibration_revision": body.plane.calibration_revision,
                "detector_version": body.detector.version,
                "lanes": len(traced_edges),
                "zones": 0,
                "skipped": [],
            },
        }

    places: list[dict] = []
    edges: list[dict] = []
    skipped: list[dict] = []
    kept = 0

    def place_at(x: float, y: float, name: str) -> str:
        for place in places:  # endpoints of one camera's lanes that meet share a junction
            if math.dist((place["x"], place["y"]), (x, y)) <= ENDPOINT_TOL_M:
                return place["id"]
        place = {"id": f"cam{len(places) + 1}", "name": name, "x": x, "y": y, "kind": "junction"}
        places.append(place)
        return place["id"]

    for index, lane in enumerate(body.lanes):
        _finite(lane.polyline_m)
        length = sum(math.dist(a, b) for a, b in zip(lane.polyline_m, lane.polyline_m[1:]))
        if length < MIN_LANE_M:
            skipped.append({"index": index, "reason": f"shorter than {MIN_LANE_M} m"})
            continue
        start_id = place_at(*lane.polyline_m[0], f"카메라 끝 {len(places) + 1}")
        end_id = place_at(*lane.polyline_m[-1], f"카메라 끝 {len(places) + 1}")
        start = next(p for p in places if p["id"] == start_id)
        end = next(p for p in places if p["id"] == end_id)
        if math.dist((start["x"], start["y"]), (end["x"], end["y"])) < 0.10:  # SiteMap's MIN_EDGE_M
            skipped.append({"index": index, "reason": "its ends share junctions less than 0.10 m apart"})
            continue
        kept += 1
        edges.append({"id": f"cam-lane{index}", "name": f"카메라 차로 {index + 1}",
                      "from": start_id, "to": end_id,
                      "polyline": [list(point) for point in lane.polyline_m],
                      "width_m": min(MAX_WIDTH_M, max(MIN_WIDTH_M, lane.width_px / body.plane.px_per_m)),
                      "direction": "two_way", "drive_mode": "lane",
                      "speed_cap_mps": IMPORT_SPEED_CAP_MPS, "evidence": dict(evidence)})
    for index, zone in enumerate(body.zones):
        _finite(zone.polygon_m)
    if not kept and not body.zones:
        raise CameraDraftError("no usable lane or zone candidate")
    facilities = [{"id": f"cam-zone{index}", "name": f"카메라 구역 {index + 1}",
                   "kind": zone.kind, "geometry": [list(point) for point in zone.polygon_m],
                   "evidence": dict(evidence)}
                  for index, zone in enumerate(body.zones)]
    min_x, min_y, max_x, max_y = body.plane.bounds_m
    draft = {"schema": "rosy.site_map/1", "map_id": "site", "places": places, "edges": edges,
             "facilities": facilities,
             "survey": {"revision": revision,
                        "origin": [round((min_x + max_x) / 2, 4), round((min_y + max_y) / 2, 4)],
                        "heading_rad": 0.0, "scale_source": "measured",
                        "measured_distance_m": round(max_x - min_x, 4),
                        "description": f"카메라 초안 {note}"[:1000]}}
    try:
        checked = SiteMap.model_validate(draft)
    except ValidationError as exc:
        raise CameraDraftError(f"the assembled draft does not validate: {exc.error_count()} errors") from exc
    return {"map": checked.body(),
            "provenance": {"source_id": body.source_id,
                           "calibration_revision": body.plane.calibration_revision,
                           "detector_version": body.detector.version,
                           "lanes": kept, "zones": len(facilities), "skipped": skipped}}
