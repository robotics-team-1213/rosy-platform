import math

import pytest

from rosy_vision.project import CameraMap, project_frame


def _quad(cx, cy, half=2):
    return ((cx - half, cy - half), (cx + half, cy - half),
            (cx + half, cy + half), (cx - half, cy + half))


def _camera():
    return CameraMap(
        source_id="ceiling_north",
        map_id="site-v1",
        calibration_revision="cal-v3",
        processor_revision="aruco-v1",
        corner_marker_ids=(30, 31, 32, 33),
        corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
        robot_markers={"rosy_01": 7},
        heading_edge=(1, 2),
    )


def _markers():
    # Pixel map corners form a 400x200 rectangle; the robot marker faces +X.
    return {
        30: _quad(100, 100),
        31: _quad(500, 100),
        32: _quad(500, 300),
        33: _quad(100, 300),
        7: ((290, 190), (310, 190), (310, 210), (290, 210)),
    }


def test_project_frame_preserves_lineage_and_projects_robot_pose():
    result = project_frame(_camera(), source_id="ceiling_north", seq=17,
                           captured_at=1_790_000_000.5, markers=_markers())

    assert len(result) == 1
    sighting = result[0]
    assert sighting.robot_id == "rosy_01"
    # D-587 4: the robot centre is the marker centre minus the nominal mount (-0.017, 0).
    assert math.isclose(sighting.x, 2.017, abs_tol=1e-6)
    assert math.isclose(sighting.y, 1.0, abs_tol=1e-6)
    assert math.isclose(sighting.yaw, 0.0, abs_tol=1e-6)
    assert (sighting.seq, sighting.captured_at) == (17, 1_790_000_000.5)
    assert (sighting.map_id, sighting.calibration_revision, sighting.processor_revision) == (
        "site-v1", "cal-v3", "aruco-v1")
    assert sighting.corner_marker_ids == (30, 31, 32, 33)
    assert sighting.quality is None


def test_project_frame_rejects_wrong_source_and_incomplete_corner_set():
    camera = _camera()
    assert project_frame(camera, source_id="other_camera", seq=1,
                         captured_at=10.0, markers=_markers()) == ()
    incomplete = _markers()
    incomplete.pop(32)
    assert project_frame(camera, source_id="ceiling_north", seq=2,
                         captured_at=10.0, markers=incomplete) == ()


def test_project_frame_fails_closed_on_malformed_calibration_or_robot_corners():
    camera = _camera()
    malformed_corner = _markers()
    malformed_corner[31] = ((1.0, 2.0), (3.0, 4.0))
    assert project_frame(camera, source_id="ceiling_north", seq=3,
                         captured_at=10.0, markers=malformed_corner) == ()

    malformed_robot = _markers()
    malformed_robot[7] = ((1.0, 2.0), (3.0, 4.0))
    assert project_frame(camera, source_id="ceiling_north", seq=4,
                         captured_at=10.0, markers=malformed_robot) == ()


def test_camera_map_rejects_duplicate_corner_markers():
    try:
        _camera().__class__(
            source_id="ceiling_north", map_id="site-v1",
            calibration_revision="cal-v3", processor_revision="aruco-v1",
            corner_marker_ids=(30, 30, 32, 33),
            corner_world_m=((0, 0), (4, 0), (4, 2), (0, 2)),
            robot_markers={"rosy_01": 7},
        )
    except ValueError:
        return
    raise AssertionError("duplicate calibration corner markers must be rejected")


def test_marker_homography_needs_all_four_corners():
    from rosy_vision.project import marker_homography

    camera = _camera()
    homography = marker_homography(camera, _markers())
    assert homography.apply(500, 300) == pytest.approx((4.0, 2.0))
    assert marker_homography(camera, {30: _markers()[30]}) is None


def _field_camera():
    return CameraMap(
        source_id="ceiling_north",
        map_id="site-v1",
        calibration_revision="cal-v3",
        processor_revision="aruco-v1",
        corner_marker_ids=None,
        corner_world_m=((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)),
        robot_markers={"rosy_01": 7},
        heading_edge=(1, 2),
        calibration_source="field_boundary",
    )


def test_field_camera_map_rejects_mixed_calibration_sources():
    with pytest.raises(ValueError, match="no corner marker ids"):
        _camera().__class__(**{**_field_camera().__dict__, "corner_marker_ids": (30, 31, 32, 33)})
    with pytest.raises(ValueError, match="corner marker ids are required"):
        _camera().__class__(**{**_camera().__dict__, "corner_marker_ids": None})
    with pytest.raises(ValueError, match="calibration source"):
        _camera().__class__(**{**_camera().__dict__, "calibration_source": "magic"})


def test_project_frame_uses_the_field_homography_and_names_the_source():
    from games.field.homography import fit

    quad = ((100.0, 100.0), (500.0, 100.0), (500.0, 300.0), (100.0, 300.0))
    world = ((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0))
    homography = fit(quad, world)

    result = project_frame(_field_camera(), source_id="ceiling_north", seq=21,
                           captured_at=1_790_000_000.5, markers={7: _markers()[7]},
                           homography=homography)

    assert len(result) == 1
    sighting = result[0]
    assert math.isclose(sighting.x, 2.017, abs_tol=1e-6)  # D-587 4 mount
    assert math.isclose(sighting.y, 1.0, abs_tol=1e-6)
    assert sighting.calibration_source == "field_boundary"
    assert sighting.corner_marker_ids is None


def test_project_frame_field_source_without_a_homography_publishes_nothing():
    assert project_frame(_field_camera(), source_id="ceiling_north", seq=22,
                         captured_at=10.0, markers={7: _markers()[7]}) == ()


def test_project_frame_applies_the_robot_marker_yaw_offset():
    """D-587 4: a sticker stuck turned 90 deg left is corrected by the per-robot offset."""
    camera = CameraMap(**{**_camera().__dict__, "marker_yaw_offset_deg": {"rosy_01": 90.0}})
    sighting = project_frame(camera, source_id="ceiling_north", seq=17,
                             captured_at=1_790_000_000.5, markers=_markers())[0]
    assert math.isclose(sighting.yaw, -math.pi / 2, abs_tol=1e-6)
    assert (sighting.x, sighting.y) == pytest.approx((2.0, 1.0 - 0.017))
    with pytest.raises(ValueError, match="marker yaw offsets"):
        CameraMap(**{**_camera().__dict__, "marker_yaw_offset_deg": {"rosy_01": float("inf")}})
