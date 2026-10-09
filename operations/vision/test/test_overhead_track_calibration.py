"""D-457 2: corner markers win; an approved record is used only for its source, map, lens and aspect."""

import json
from pathlib import Path

import pytest

from rosy_vision.project import CameraMap
from rosy_vision.track import geometry
from rosy_vision.track.calibration import choose, from_record, same_lens

FIXTURE = json.loads((Path(__file__).resolve().parents[3]
                      / "test/fixtures/protocol/overhead-detections.v1.json").read_text(encoding="utf-8"))
RECORD = FIXTURE["config_example"]["calibration"]
LENS = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9}
CAMERA = CameraMap(
    source_id="ceiling_north", map_id="map_v2_fleet", calibration_revision="cal-v3",
    processor_revision="aruco-v1", corner_marker_ids=(30, 31, 32, 33),
    corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)), robot_markers={"rosy_01": 7},
)


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half), (cx + half, cy + half), (cx - half, cy + half))


MARKERS = {30: _quad(100, 100), 31: _quad(500, 100), 32: _quad(500, 300), 33: _quad(100, 300)}


def _from(record=RECORD, **changes):
    args = dict(source_id="ceiling_north", map_id="map_v2_fleet", frame_size=(640, 360), lens=None)
    args.update(changes)
    return from_record(record, **args)


def test_record_maps_frames_of_its_own_size():
    calibration = _from()
    assert calibration.revision == "paint-3f9a1c2b7d40"
    assert calibration.image_to_map == pytest.approx((0.01, 0.0, 0.0, 0.0, -0.01, 3.6, 0.0, 0.0, 1.0))
    assert calibration.track_bounds_m == (0.0, 0.0, 6.4, 3.6)
    assert calibration.image_size == (640, 360) and calibration.hfov_deg is None


def test_same_aspect_other_resolution_is_scaled_by_pixel_centres():
    own = _from()
    double = _from(frame_size=(1280, 720))
    assert double.image_size == (1280, 720)
    assert double.image_to_map[0] == pytest.approx(0.005)
    assert double.image_to_map[4] == pytest.approx(-0.005)
    # Pixel (100, 50) at 640x360 and the centre of pixels 200-201 / 100-101 at 1280x720 are
    # the same floor point.
    at_own = geometry.apply(geometry.as_matrix(own.image_to_map), [[100.0, 50.0]])[0]
    at_double = geometry.apply(geometry.as_matrix(double.image_to_map), [[200.5, 100.5]])[0]
    assert at_own == pytest.approx((1.0, 3.1)) and at_double == pytest.approx(at_own)


@pytest.mark.parametrize("changes", [
    {"source_id": "ceiling_south"},
    {"map_id": "other_map"},
    {"frame_size": (640, 480)},
    {"lens": LENS},
])
def test_record_is_unusable_for_other_source_map_aspect_or_lens(changes):
    assert _from(**changes) is None


def test_lens_must_match_and_brings_its_fov():
    calibration = _from({**RECORD, "lens": LENS}, lens=dict(LENS))
    assert calibration.hfov_deg == pytest.approx(66.9)
    assert _from({**RECORD, "lens": LENS}, lens=None) is None


def test_lens_match_tolerates_header_rounding():
    printed = {"kind": "standard", "focal_mm": 5.4, "hfov_deg": 66.9123}
    assert same_lens({**printed, "hfov_deg": 66.912345}, printed)
    assert not same_lens({**printed, "kind": "wide"}, printed)
    assert not same_lens({**printed, "hfov_deg": 70.0}, printed)
    assert same_lens(None, None) and not same_lens(None, printed)


@pytest.mark.parametrize("record", [
    {**RECORD, "map_to_image": [0.0] * 9},
    {key: value for key, value in RECORD.items() if key != "image"},
    {**RECORD, "track_bounds_m": {"min_x": 1.0, "min_y": 0.0, "max_x": 1.0, "max_y": 3.6}},
    None,
])
def test_malformed_record_is_unusable(record):
    assert _from(record) is None


def test_the_approved_record_wins_over_per_frame_corner_markers():
    # D-595: an accepted record is frozen; corner markers in the frame never re-fit it.
    assert choose(CAMERA, MARKERS, RECORD, frame_size=(640, 360), lens=None).revision == "paint-3f9a1c2b7d40"
    assert choose(CAMERA, {}, RECORD, frame_size=(640, 360), lens=None).revision == "paint-3f9a1c2b7d40"
    # Without a usable record the four markers of the frame still calibrate it.
    marker = choose(CAMERA, MARKERS, None, frame_size=(640, 360), lens=None)
    assert marker.revision == "cal-v3" and marker.track_bounds_m == (0.0, 0.0, 4.0, 2.0)
    other_map = {**RECORD, "map_id": "elsewhere"}
    assert choose(CAMERA, MARKERS, other_map, frame_size=(640, 360), lens=None).revision == "cal-v3"
    assert choose(CAMERA, {30: MARKERS[30]}, None, frame_size=(640, 360), lens=None) is None
