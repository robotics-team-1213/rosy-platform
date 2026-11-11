"""D-594 path history against the map: does the map match where the robots drove?"""

from __future__ import annotations

import math

from fleet.map_reality import compare, transform_map
from fleet.site_map import SiteMap

W = 0.2


def _map(*, north: bool = False, box: bool = False, long: bool = False) -> SiteMap:
    """Two lanes east (A-B-C, 12 m), an optional north lane and an optional exclusion area."""
    end = 30 if long else 12
    places = {"A": (0, 0, "start"), "B": (6, 0, "junction"), "C": (end, 0, "junction")}
    edges = [{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [6, 0]],
              "width_m": W, "speed_cap_mps": 1.0},
             {"id": "bc", "from": "B", "to": "C", "polyline": [[6, 0], [end, 0]],
              "width_m": W, "speed_cap_mps": 1.0}]
    if north:
        places["N"] = (6, 2, "junction")
        edges.append({"id": "bn", "from": "B", "to": "N", "polyline": [[6, 0], [6, 2]],
                      "width_m": W, "speed_cap_mps": 1.0})
    return SiteMap(
        map_id="site",
        places=[{"id": pid, "name": pid, "x": x, "y": y, "kind": kind, "yaw": 0.0 if kind == "start" else None}
                for pid, (x, y, kind) in places.items()],
        edges=edges,
        facilities=[{"id": "box", "name": "box", "kind": "exclusion",
                     "geometry": [[6.6, -0.3], [7.4, -0.3], [7.4, 0.3], [6.6, 0.3]]}] if box else [])


def _drive(x0: float, x1: float, y: float, *, step: float = 0.05) -> list[list[float]]:
    count = int(abs(x1 - x0) / step)
    return [[x0 + (x1 - x0) * k / count, y] for k in range(count + 1)]


def _lane(report: dict, lane_id: str) -> dict:
    return next(lane for lane in report["lanes"] if lane["id"] == lane_id)


def test_a_drive_along_the_mapped_lanes_is_a_match():
    report = compare(_map(), [_drive(0.0, 12.0, 0.03)])

    assert report["verdict"] == "match"
    assert _lane(report, "ab")["state"] == "matched"
    assert _lane(report, "ab")["coverage"] == 1.0
    assert _lane(report, "ab")["median_offset_m"] <= 0.15
    assert report["off_lane"]["points"] == 0
    assert report["fit"]["accepted"] is False
    assert report["fit"]["reason"] == "the driven points already lie on the mapped lanes"


def test_an_unmatched_window_reports_no_evidence_instead_of_a_verdict():
    report = compare(_map(), [])

    assert report["verdict"] == "no_evidence"
    assert report["fit"] is None
    assert report["lanes"] == []
    assert report["notes"] == ["no robot drive was recorded for this window"]


def test_a_lane_no_robot_drove_is_reported_uncovered():
    report = compare(_map(north=True), [_drive(0.0, 12.0, 0.0)])

    assert _lane(report, "bn")["state"] == "uncovered"
    assert _lane(report, "bn")["coverage"] < 0.5
    assert report["verdict"] == "partial"
    assert "bn" in report["notes"][0]


def test_driving_through_an_exclusion_area_is_a_mismatch():
    report = compare(_map(box=True), [_drive(0.0, 12.0, 0.0)])

    zone = next(zone for zone in report["zones"] if zone["id"] == "box")
    assert zone["state"] == "entered" and zone["points"] > 0
    assert report["verdict"] == "mismatch"
    assert "exclusion" in report["notes"][0]


def test_a_map_offset_from_the_drive_is_corrected_and_then_matches():
    site = _map()
    drive = [_drive(0.0, 12.0, 0.4)]
    report = compare(site, drive)

    assert report["fit"]["accepted"] is True, report["fit"]
    assert report["verdict"] == "offset"
    assert abs(report["fit"]["yaw_deg"]) < 1.0
    assert report["fit"]["ty_m"] > 0.3
    assert report["fit"]["after_median_m"] <= report["fit"]["before_median_m"] / 2

    corrected = SiteMap.model_validate(transform_map(site.body(), report["fit"]))
    after = compare(corrected, drive)
    assert after["verdict"] == "match"
    assert after["fit"]["accepted"] is False


def test_a_drive_on_lanes_the_map_does_not_have_is_not_fitted():
    report = compare(_map(), [_drive(0.0, 12.0, 3.0)])

    assert report["fit"]["accepted"] is False
    assert "fewer than 20 lane samples" in report["fit"]["reason"]
    assert report["verdict"] == "unmapped"
    assert report["off_lane"]["points"] > 0


def test_a_partial_drive_does_not_drag_the_whole_map():
    report = compare(_map(long=True), [_drive(0.0, 5.0, 0.0)])

    assert report["fit"]["accepted"] is False
    assert "not the same lanes" in report["fit"]["reason"]


def test_transform_map_moves_the_frame_and_keeps_the_geometry():
    site = SiteMap(
        map_id="site",
        places=[{"id": "A", "name": "A", "x": 0, "y": 0, "yaw": 0.3, "kind": "start"},
                {"id": "B", "name": "B", "x": 2, "y": 0, "kind": "junction"}],
        edges=[{"id": "ab", "from": "A", "to": "B", "polyline": [[0, 0], [2, 0]],
                "width_m": W, "speed_cap_mps": 1.0,
                "evidence": {"source": "operator", "status": "reviewed", "reference_revision": "s1",
                             "note": "surveyed"}}],
        survey={"revision": "s1", "origin": [0, 0], "heading_rad": 0.1, "scale_source": "measured",
                "measured_distance_m": 1.0, "description": "survey", "reviewed": True,
                "review_note": "checked"})

    moved = transform_map(site.body(), {"yaw_deg": 90.0, "tx_m": 1.0, "ty_m": 2.0})

    places = {place["id"]: place for place in moved["places"]}
    assert places["A"]["x"] == 1.0 and places["A"]["y"] == 2.0
    assert places["B"]["x"] == 1.0 and places["B"]["y"] == 4.0
    assert math.isclose(places["A"]["yaw"], 0.3 + math.pi / 2, abs_tol=1e-6)
    assert moved["edges"][0]["polyline"] == [[1.0, 2.0], [1.0, 4.0]]
    assert moved["survey"]["origin"] == [1.0, 2.0]
    assert math.isclose(moved["survey"]["heading_rad"], 0.1 + math.pi / 2, abs_tol=1e-6)
    assert moved["survey"]["revision"] == "s1"          # evidence rows stay bound to it
    assert moved["edges"][0]["evidence"]["reference_revision"] == "s1"
    SiteMap.model_validate(moved)                       # the caller's re-validation passes
