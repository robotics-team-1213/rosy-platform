"""Measured calibration candidates, independent checks and bounded AI advice."""
import cv2
import numpy as np
import pytest
import json

from rosy_vision.camera_calibration import (
    AprilGrid, detect_grid, fit_lenses, corrected_image, fit_floor,
    plane_image, advice_request, validate_advice,
    main,
)


def views(model="pinhole"):
    grid = AprilGrid()
    obj = grid.points(list(range(9)))
    k = np.array([[700., 0, 320], [0, 710., 240], [0, 0, 1]])
    d = np.array([-.12, .015, .001, -.001, .0]) if model == "pinhole" else np.array([-.06, .004, 0., 0.])
    result = []
    for i in range(14):
        rv = np.array([.12 + .08 * (i % 4), -.3 + .1 * (i % 7), .02 * i])
        tv = np.array([-.11 + .035 * (i % 5), -.08 + .03 * (i % 4), .3 + .03 * (i % 3)])
        if model == "pinhole":
            image, _ = cv2.projectPoints(obj, rv, tv, k, d)
        else:
            image, _ = cv2.fisheye.projectPoints(obj.reshape(-1, 1, 3), rv, tv, k, d)
        result.append({"object_points": obj, "image_points": image.reshape(-1, 2),
                       "digest": f"image-{i}"})
    return result


def test_metric_target_and_partial_board_detection():
    grid = AprilGrid()
    image = grid.image(120)
    measured = detect_grid(image, grid)
    assert len(measured["image_points"]) == 36
    partial = detect_grid(image[:image.shape[0] // 2], grid)
    assert 12 <= len(partial["image_points"]) < 36
    assert grid.points([0])[1, 0] == pytest.approx(.03)
    assert 'width="186.000mm"' in grid.svg()
    with pytest.raises(ValueError):
        AprilGrid(tag_size_m=float("nan"))


@pytest.mark.parametrize("model", ["pinhole", "fisheye"])
def test_fit_uses_independent_frames_and_preserves_identity(model):
    samples = views(model)
    report = fit_lenses(samples[:12], samples[12:], (640, 480), source_id="ceiling_north",
                        capture_signature="fixed-standard-640x480", models=(model,))
    candidate = report["candidates"][0]
    assert candidate["validation"]["p95_px"] < .01
    assert candidate["source_id"] == "ceiling_north"
    assert candidate["status"] == "candidate" and not candidate["applied"]
    assert np.asarray(candidate["K"])[0, 0] == pytest.approx(700, abs=.2)
    image = np.full((480, 640, 3), 120, np.uint8)
    corrected, mask = corrected_image(image, candidate, source_id="ceiling_north",
                                      capture_signature="fixed-standard-640x480")
    assert corrected.shape == image.shape and mask.shape == image.shape[:2]
    with pytest.raises(ValueError, match="identity"):
        corrected_image(image, candidate, source_id="other", capture_signature="fixed-standard-640x480")
    with pytest.raises(ValueError, match="independent"):
        fit_lenses(samples[:12], samples[:2], (640, 480), source_id="s", capture_signature="g")


def test_measured_floor_and_plane_are_separate_from_raw_homography():
    samples = views()
    c = fit_lenses(samples[:12], samples[12:], (640, 480), source_id="s",
                   capture_signature="g", models=("pinhole",))["candidates"][0]
    pixels = np.array([[50., 50.], [550, 50], [550, 400], [50, 400], [300, 200], [100, 300]])
    metres = pixels / 200 - 1
    checks = np.array([[160., 120.], [440., 330.], [410., 120.]])
    floor = fit_floor(c, pixels, metres, checks, checks / 200 - 1, map_id="measured-map",
                      pixel_space="undistorted")
    assert floor["validation"]["max_m"] < 1e-5
    image, mask = plane_image(np.full((480, 640, 3), 120, np.uint8), c, floor,
                              (-2., -2., 3., 3.), source_id="s", capture_signature="g", px_per_m=100)
    assert image.shape == (500, 500, 3) and 0 < mask.mean() < 1
    with pytest.raises(ValueError, match="undistorted"):
        fit_floor(c, pixels, metres, checks, checks / 200 - 1, map_id="m", pixel_space="raw")
    with pytest.raises(ValueError, match="independent"):
        fit_floor(c, pixels, metres, checks, metres[:3], map_id="m", pixel_space="undistorted")
    with pytest.raises(ValueError):
        fit_floor({"revision": "r", "source_id": "s"}, pixels, metres, checks, checks / 200 - 1,
                  map_id="m", pixel_space="undistorted")
    with pytest.raises(ValueError, match="outside"):
        fit_floor(c, pixels + 1000, metres, checks, checks / 200 - 1, map_id="m", pixel_space="undistorted")
    outlier_pixels = np.vstack((pixels, [[620., 460.]]))
    outlier_metres = np.vstack((metres, [[100., 100.]]))
    robust = fit_floor(c, outlier_pixels, outlier_metres, checks, checks / 200 - 1,
                       map_id="m", pixel_space="undistorted")
    assert robust["inliers"] == len(pixels)
    assert robust["reference_pixel"] == pytest.approx(pixels.mean(axis=0))
    with pytest.raises(ValueError, match="revision"):
        plane_image(np.zeros((480, 640, 3), np.uint8), c,
                    {**floor, "lens_revision": "other"}, (-1., -1., 1., 1.),
                    source_id="s", capture_signature="g")


def test_ai_is_advisory_and_cannot_supply_geometry():
    report = {"candidates": [], "failures": [{"model": "pinhole", "reason": "fit_failed"}],
              "warnings": ["edge_coverage_low"], "private_path": "secret-file"}
    request = advice_request(report)
    assert "private_path" not in request and request["authority"] == "advisory"
    advice = validate_advice({"recommendations": ["move_target_to_edges"], "explanation": "Retake edges."})
    assert advice["needs_human_review"]
    with pytest.raises(ValueError):
        validate_advice({"recommendations": [], "K": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]})
    with pytest.raises(ValueError):
        validate_advice({"recommendations": ["move_robot"], "explanation": ""})


def test_cli_print_target_and_never_overwrite_output(tmp_path):
    output = tmp_path / "target"
    assert main(["target", "--output", str(output)]) == 0
    assert json.loads((output / "target.json").read_text())["tag_size_m"] == .03
    assert cv2.imread(str(output / "target.png")) is not None
    with pytest.raises(SystemExit) as error:
        main(["target", "--output", str(output)])
    assert error.value.code == 2
    assert (output / "target.svg").read_text().startswith('<svg')


def test_failed_fit_keeps_original_output_and_emits_bounded_review_for_new_output(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "report.json").write_text("previous result")
    with pytest.raises(SystemExit):
        main(["fit", "--input", str(manifest), "--output", str(existing)])
    assert (existing / "report.json").read_text() == "previous result"
    new = tmp_path / "failed"
    with pytest.raises(SystemExit):
        main(["fit", "--input", str(manifest), "--output", str(new)])
    request = json.loads((new / "ai-request.json").read_text())
    assert request["authority"] == "advisory"
    assert "capture_or_measurement_failed" in request["warnings"]


def test_bad_or_insufficient_measurements_do_not_make_a_candidate():
    samples = views()
    with pytest.raises(ValueError, match="eight"):
        fit_lenses(samples[:2], samples[12:], (640, 480), source_id="s", capture_signature="g")
    samples[0]["image_points"][0, 0] = float("nan")
    with pytest.raises(ValueError, match="points"):
        fit_lenses(samples[:12], samples[12:], (640, 480), source_id="s", capture_signature="g")


def test_fit_partial_target_points_in_varied_views():
    samples = views()
    for i, view in enumerate(samples):
        count = 12 + (i % 3)*4
        view["object_points"] = view["object_points"][:count]
        view["image_points"] = view["image_points"][:count]
    report = fit_lenses(samples[:12], samples[12:], (640, 480), source_id="s",
                        capture_signature="g", models=("pinhole",))
    assert report["candidates"][0]["validation"]["max_px"] < .01


def test_detector_refuses_duplicate_board_tag_ids():
    grid = AprilGrid()
    image = grid.image(120)
    # Add a fourth complete tag with the same ID to an otherwise visible target.
    marker = cv2.aruco.generateImageMarker(grid.dictionary, 0, 120)
    image[10:130, 10:130] = marker
    with pytest.raises(ValueError, match="duplicate"):
        detect_grid(image, grid)
