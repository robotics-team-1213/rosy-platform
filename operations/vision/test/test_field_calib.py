"""D-484: field-boundary calibration state machine, stability gates, orientation."""

import math

import pytest
from games.field.homography import fit

from rosy_vision.field_calib import FieldCalibrator

WORLD = ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0))
QUAD = ((100.0, 100.0), (500.0, 120.0), (520.0, 400.0), (80.0, 380.0))
SIZE = (640, 480)
DIAGONAL = math.hypot(SIZE[0] - 1, SIZE[1] - 1)


def _matrix(homography):
    h = homography.h
    return [list(h[0:3]), list(h[3:6]), list(h[6:9])]


def _map_to_image(world=WORLD):
    return _matrix(fit(world, QUAD))


def _detection(corners=None, reason="", image_size=SIZE):
    proposal = None
    if corners is not None:
        proposal = type("P", (), {"corners": tuple(corners), "confidence": 0.9})()
    return type("D", (), {"proposal": proposal, "reason": reason, "image_size": image_size})()


def _shifted(delta=(30.0, 0.0)):
    return tuple((x + delta[0], y + delta[1]) for x, y in QUAD)


def test_constructor_refuses_bad_world_corners():
    with pytest.raises(ValueError):
        FieldCalibrator(((0, 0), (4, 0), (4, 3)))
    with pytest.raises(ValueError):
        FieldCalibrator(((0, 0), (0, 0), (4, 3), (0, 3)))
    with pytest.raises(ValueError):
        FieldCalibrator(WORLD, move_fraction=0)


def test_first_quad_waits_for_orientation_and_never_guesses():
    calibrator = FieldCalibrator(WORLD)
    state = calibrator.feed(_detection(QUAD))
    assert state.state == "orientation_pending"
    assert calibrator.needs_orientation() is True
    assert calibrator.homography() is None


def test_orientation_resolves_from_paint_projection_and_maps_corners():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    ok, reason = calibrator.resolve_orientation(_map_to_image(), SIZE)
    assert (ok, reason) == (True, "ok")
    state = calibrator.snapshot()
    assert state.state == "calibrated" and state.orientation == 0
    homography = calibrator.homography()
    assert homography is not None
    for image_corner, world_corner in zip(QUAD, WORLD):
        assert homography.apply(*image_corner) == pytest.approx(world_corner, abs=1e-6)


def test_orientation_detects_each_cyclic_rotation():
    rotation = 1
    # image corner i shows world corner (i + rotation) % 4
    rotated_quad = [QUAD[(i + rotation) % 4] for i in range(4)]
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(rotated_quad))
    ok, _ = calibrator.resolve_orientation(_map_to_image(), SIZE)
    assert ok is True
    assert calibrator.snapshot().orientation == rotation
    homography = calibrator.homography()
    for image_corner, world_corner in zip(rotated_quad, WORLD[rotation:] + WORLD[:rotation]):
        assert homography.apply(*image_corner) == pytest.approx(world_corner, abs=1e-6)


def test_orientation_rejects_far_projections_and_reports_why():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    matrix = _map_to_image()
    matrix[0][2] += 200.0  # every projection lands far from the detected corners
    ok, reason = calibrator.resolve_orientation(matrix, SIZE)
    assert ok is False and "px away" in reason
    assert calibrator.needs_orientation() is True


def test_orientation_rejects_a_reflected_world_order():
    reflected = (WORLD[0], WORLD[3], WORLD[2], WORLD[1])
    calibrator = FieldCalibrator(reflected)
    calibrator.feed(_detection(QUAD))
    ok, reason = calibrator.resolve_orientation(_map_to_image(), SIZE)
    assert ok is False and "cyclic" in reason


def test_orientation_rejects_a_different_frame_size():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    ok, reason = calibrator.resolve_orientation(_map_to_image(), (1280, 720))
    assert ok is False and "frame size" in reason


def test_small_moves_keep_the_frozen_quad_and_big_jumps_go_stale():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    calibrator.resolve_orientation(_map_to_image(), SIZE)
    frozen = calibrator.homography().h
    # D-595: noise below the move gate is a drift diagnostic; the quad and homography stay.
    noise = tuple((x + 1.0, y) for x, y in QUAD)
    state = calibrator.feed(_detection(noise))
    assert state.state == "calibrated" and state.corners == QUAD
    assert state.drift_px == pytest.approx(1.0) and state.to_dict()["drift_px"] == 1.0
    assert calibrator.homography().h == frozen
    # A jump larger than the gate is stale: no sightings from the old quad.
    state = calibrator.feed(_detection(_shifted((60.0, 0.0))))
    assert state.state == "stale"
    assert calibrator.homography() is None
    assert state.corners == QUAD  # the accepted quad is still the frozen one


def test_a_stable_quad_at_the_new_position_is_reacquired_with_orientation_kept():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    calibrator.resolve_orientation(_map_to_image(), SIZE)
    moved = _shifted((60.0, 0.0))
    calibrator.feed(_detection(moved))
    assert calibrator.snapshot().state == "stale"
    calibrator.feed(_detection(moved))
    state = calibrator.feed(_detection(moved))
    assert state.state == "calibrated" and state.orientation == 0
    assert calibrator.homography() is not None


def test_an_inconsistent_new_position_never_reacquires():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    calibrator.resolve_orientation(_map_to_image(), SIZE)
    calibrator.feed(_detection(_shifted((60.0, 0.0))))
    calibrator.feed(_detection(_shifted((-60.0, 0.0))))
    calibrator.feed(_detection(_shifted((60.0, 0.0))))
    assert calibrator.snapshot().state == "stale"
    assert calibrator.homography() is None


def test_a_flipped_aspect_on_reacquire_clears_the_orientation():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    calibrator.resolve_orientation(_map_to_image(), SIZE)
    # A quad rotated about 90 degrees: width and height swap (portrait vs landscape).
    rotated = ((150.0, 80.0), (290.0, 80.0), (290.0, 470.0), (150.0, 470.0))
    calibrator.feed(_detection(rotated))
    calibrator.feed(_detection(rotated))
    state = calibrator.feed(_detection(rotated))
    assert state.state == "orientation_pending"
    assert calibrator.homography() is None
    assert calibrator.needs_orientation() is True


def test_consecutive_failures_lose_the_field_and_the_orientation():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    calibrator.resolve_orientation(_map_to_image(), SIZE)
    for _ in range(4):  # grace: the calibration survives brief detection gaps
        state = calibrator.feed(_detection(None, reason="no white boundary"))
        assert state.state == "calibrated"
    state = calibrator.feed(_detection(None, reason="no white boundary"))
    assert state.state == "no_field" and state.reason == "field lost"
    assert calibrator.homography() is None and calibrator.needs_orientation() is False


def test_report_dict_carries_normalized_corners_for_the_preview():
    calibrator = FieldCalibrator(WORLD)
    calibrator.feed(_detection(QUAD))
    report = calibrator.snapshot().to_dict()
    assert report["version"] == "field-calib/1"
    assert report["state"] == "orientation_pending"
    assert report["corners_normalized"] == [
        [round(x / 639, 5), round(y / 479, 5)] for x, y in QUAD]
    assert report["orientation"] is None
