import math

from overhead.project import CameraMap, project_frame


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
    assert math.isclose(sighting.x, 2.0, abs_tol=1e-6)
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
