"""D-636 offline measured lens/floor candidates; no runtime writer or approval."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


def _revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class AprilGrid:
    rows: int = 3
    cols: int = 3
    tag_size_m: float = .03
    spacing_ratio: float = .3
    first_id: int = 0

    def __post_init__(self):
        if (any(type(v) is not int for v in (self.rows, self.cols, self.first_id))
                or not 2 <= self.rows <= 12 or not 2 <= self.cols <= 12
                or self.first_id < 0 or self.first_id + self.rows * self.cols > 587
                or not math.isfinite(self.tag_size_m) or not .005 <= self.tag_size_m <= .5
                or not math.isfinite(self.spacing_ratio) or not .1 <= self.spacing_ratio <= 1):
            raise ValueError("invalid AprilGrid dimensions or IDs")

    @property
    def dictionary(self):
        return cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)

    @property
    def pitch(self):
        return self.tag_size_m * (1 + self.spacing_ratio)

    def points(self, ids):
        points = []
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate target IDs")
        for tag in ids:
            index = int(tag) - self.first_id
            if not 0 <= index < self.rows * self.cols:
                raise ValueError("unknown target ID")
            row, col = divmod(index, self.cols)
            x, y, s = col * self.pitch, row * self.pitch, self.tag_size_m
            points.extend(((x, y, 0), (x + s, y, 0), (x + s, y + s, 0), (x, y + s, 0)))
        return np.asarray(points, np.float64)

    def image(self, tag_px=160):
        if type(tag_px) is not int or not 32 <= tag_px <= 512:
            raise ValueError("tag pixels must be 32..512")
        pitch = round(tag_px * (1 + self.spacing_ratio))
        width, height = (self.cols + 1) * pitch + tag_px, (self.rows + 1) * pitch + tag_px
        image = np.full((height, width), 255, np.uint8)
        for index in range(self.rows * self.cols):
            row, col = divmod(index, self.cols)
            x, y = (col + 1) * pitch, (row + 1) * pitch
            image[y:y + tag_px, x:x + tag_px] = cv2.aruco.generateImageMarker(
                self.dictionary, self.first_id + index, tag_px)
        return image

    def svg(self):
        # The white border is one grid pitch; the black tag border is part of tag_size_m.
        p, s = self.pitch * 1000, self.tag_size_m * 1000
        width, height = (self.cols + 1) * p + s, (self.rows + 1) * p + s
        lines = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.3f}mm" height="{height:.3f}mm" '
                 f'viewBox="0 0 {width:.6f} {height:.6f}">', '<rect width="100%" height="100%" fill="white"/>']
        for index in range(self.rows * self.cols):
            row, col = divmod(index, self.cols)
            bits = cv2.aruco.generateImageMarker(self.dictionary, self.first_id + index, 8)
            for y, x in np.argwhere(bits == 0):
                lines.append(f'<rect x="{(col + 1)*p + x*s/8:.6f}" y="{(row + 1)*p + y*s/8:.6f}" '
                             f'width="{s/8:.6f}" height="{s/8:.6f}" fill="black"/>')
        return '\n'.join([*lines, '</svg>'])


def detect_grid(image, grid):
    if image is None or image.ndim not in (2, 3):
        raise ValueError("target image unavailable")
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(grid.dictionary, parameters)
    corners, ids, _ = detector.detectMarkers(image)
    selected = [] if ids is None else [(int(tag), corner.reshape(4, 2))
        for tag, corner in zip(ids.reshape(-1), corners)
        if grid.first_id <= int(tag) < grid.first_id + grid.rows * grid.cols]
    selected.sort(key=lambda row: row[0])
    if len(selected) < 3:
        raise ValueError("need at least three complete target tags; retake closer")
    return {"object_points": grid.points([tag for tag, _ in selected]),
            "image_points": np.concatenate([points for _, points in selected]).astype(np.float64),
            "min_tag_side_px": float(min(np.linalg.norm(np.roll(points, -1, axis=0)-points, axis=1).min()
                                          for _, points in selected))}


def _points(value, dim, minimum):
    array = np.asarray(value, np.float64)
    if array.ndim != 2 or array.shape[1] != dim or len(array) < minimum or not np.isfinite(array).all():
        raise ValueError("invalid measured points")
    if len(np.unique(array, axis=0)) != len(array):
        raise ValueError("duplicate measured points")
    if cv2.contourArea(cv2.convexHull(array[:, :2].astype(np.float32))) < 1e-8:
        raise ValueError("degenerate measured points")
    return array


def _identity(source_id, capture_signature):
    if any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in (source_id, capture_signature)):
        raise ValueError("source and capture geometry identity required")


def fit_lenses(training, validation, size, *, source_id, capture_signature, models=("pinhole", "fisheye")):
    _identity(source_id, capture_signature)
    if len(training) < 8 or len(validation) < 2:
        raise ValueError("need eight training and two independent validation frames")
    if (len(size) != 2 or any(type(v) is not int or not 32 <= v <= 8192 for v in size)
            or not models or len(models) != len(set(models)) or set(models) - {"pinhole", "fisheye"}):
        raise ValueError("invalid image size or lens models")
    hashes = [view.get("digest") for view in [*training, *validation]]
    if any(not isinstance(v, str) or not v for v in hashes) or len(set(hashes)) != len(hashes):
        raise ValueError("independent original images required")
    views = []
    for view in [*training, *validation]:
        obj, image = _points(view["object_points"], 3, 12), _points(view["image_points"], 2, 12)
        if len(obj) != len(image) or not np.allclose(obj[:, 2], 0):
            raise ValueError("planar target correspondence required")
        if np.any(image < 0) or np.any(image >= np.asarray(size)):
            raise ValueError("target points outside source frame")
        views.append((obj, image))
    n = len(training)
    hull = np.concatenate([image for _, image in views[:n]])
    coverage = float(cv2.contourArea(cv2.convexHull(hull.astype(np.float32))) / (size[0] * size[1]))
    warnings = ["independent_floor_survey_required", "capture_settings_require_operator_verification"]
    if min(view.get("min_tag_side_px", math.inf) for view in [*training, *validation]) < 24:
        warnings.append("tag_pixels_low")
    if coverage < .4 or np.any(hull.min(axis=0) > np.asarray(size)*.15) or np.any(hull.max(axis=0) < np.asarray(size)*.85):
        warnings.append("edge_coverage_low")
    report = {"status": "review_required", "applied": False, "source_id": source_id,
              "capture_signature": capture_signature, "coverage_fraction": coverage,
              "training_digests": hashes[:n], "validation_digests": hashes[n:],
              "warnings": warnings, "candidates": [], "failures": []}
    for model in models:
        try:
            if model == "pinhole":
                rms, k, d, rvs, _ = cv2.calibrateCamera(
                    [o.astype(np.float32) for o, _ in views[:n]],
                    [i.astype(np.float32) for _, i in views[:n]], tuple(size), None, None)
            else:
                rms, k, d, rvs, _ = cv2.fisheye.calibrate(
                    [o.reshape(-1, 1, 3) for o, _ in views[:n]],
                    [i.reshape(-1, 1, 2) for _, i in views[:n]], tuple(size), None, None,
                    flags=cv2.fisheye.CALIB_RECOMPUTE_EXTRINSIC | cv2.fisheye.CALIB_FIX_SKEW,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-8))
            if not np.isfinite(k).all() or not np.isfinite(d).all() or k[0, 0] <= 0 or k[1, 1] <= 0:
                raise ValueError("invalid fitted intrinsics")
            errors = []
            for obj, image in views[n:]:
                pixels = cv2.fisheye.undistortPoints(image.reshape(-1, 1, 2), k, d) if model == "fisheye" else image
                ok, rv, tv = cv2.solvePnP(obj, pixels, np.eye(3) if model == "fisheye" else k,
                                          None if model == "fisheye" else d)
                if not ok or np.any((cv2.Rodrigues(rv)[0] @ obj.T + tv)[2] <= 0):
                    raise ValueError("validation pose invalid")
                if model == "fisheye":
                    predicted, _ = cv2.fisheye.projectPoints(obj.reshape(-1, 1, 3), rv, tv, k, d)
                else:
                    predicted, _ = cv2.projectPoints(obj, rv, tv, k, d)
                errors.extend(np.linalg.norm(predicted.reshape(-1, 2) - image, axis=1))
            normals = np.array([cv2.Rodrigues(rv)[0][:, 2] for rv in rvs])
            tilt_span = float(np.linalg.norm(normals.max(axis=0) - normals.min(axis=0)))
            candidate = {"status": "candidate", "applied": False, "model": model, "K": k.tolist(),
                         "D": d.reshape(-1).tolist(), "image_size": list(size), "source_id": source_id,
                         "capture_signature": capture_signature, "training_rms_px": float(rms),
                         "tilt_span": tilt_span, "validation": {"p95_px": float(np.percentile(errors, 95)),
                         "max_px": float(max(errors)), "rms_px": float(np.sqrt(np.mean(np.square(errors))))}}
            candidate["revision"] = _revision({**candidate, "digests": hashes})
            report["candidates"].append(candidate)
            if tilt_span < .15 and "tilt_diversity_low" not in warnings:
                warnings.append("tilt_diversity_low")
        except (cv2.error, ValueError):
            report["failures"].append({"model": model, "reason": "fit_or_validation_failed"})
    report["candidates"].sort(key=lambda c: c["validation"]["p95_px"])
    return report


def _lens(candidate):
    _identity(candidate.get("source_id"), candidate.get("capture_signature"))
    size = candidate.get("image_size")
    if not isinstance(size, (list, tuple)) or len(size) != 2 or any(type(v) is not int or not 32 <= v <= 8192 for v in size):
        raise ValueError("invalid lens image geometry")
    k, d = np.asarray(candidate["K"], np.float64), np.asarray(candidate["D"], np.float64)
    expected = 4 if candidate.get("model") == "fisheye" else 5 if candidate.get("model") == "pinhole" else 0
    if (not expected or k.shape != (3, 3) or d.shape != (expected,) or not np.isfinite(k).all()
            or not np.isfinite(d).all() or k[0, 0] <= 0 or k[1, 1] <= 0
            or k[0, 1] != 0 or k[1, 0] != 0 or not np.allclose(k[2], [0, 0, 1])
            or not isinstance(candidate.get("revision"), str) or not candidate["revision"]):
        raise ValueError("invalid lens candidate")
    return k, d


def _camera(image, candidate, source_id, capture_signature):
    k, d = _lens(candidate)
    _identity(source_id, capture_signature)
    if (candidate.get("source_id") != source_id or candidate.get("capture_signature") != capture_signature
            or list(image.shape[1::-1]) != candidate.get("image_size")):
        raise ValueError("camera identity or image geometry mismatch")
    return k, d


def _remap(image, x, y, forward=None):
    valid = np.isfinite(x) & np.isfinite(y) & (x >= 0) & (y >= 0) & (x < image.shape[1]-1) & (y < image.shape[0]-1)
    if forward is not None:
        valid &= forward
    x, y = np.where(valid, x, -1).astype(np.float32), np.where(valid, y, -1).astype(np.float32)
    out = cv2.remap(image, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(24, 24, 24))
    out[~valid] = 24
    return out, valid


def corrected_image(image, candidate, *, source_id, capture_signature):
    k, d = _camera(image, candidate, source_id, capture_signature)
    size = tuple(candidate["image_size"])
    if candidate["model"] == "fisheye":
        x, y = cv2.fisheye.initUndistortRectifyMap(k, d, np.eye(3), k, size, cv2.CV_32FC1)
    else:
        x, y = cv2.initUndistortRectifyMap(k, d, None, k, size, cv2.CV_32FC1)
    return _remap(image, x, y)


def fit_floor(candidate, pixels, metres, check_pixels, check_metres, *, map_id, pixel_space):
    _lens(candidate)
    if pixel_space != "undistorted":
        raise ValueError("floor anchors must be measured in undistorted pixels")
    if not isinstance(map_id, str) or not map_id.strip() or len(map_id) > 200:
        raise ValueError("measured map identity required")
    p, m = _points(pixels, 2, 4), _points(metres, 2, 4)
    cp, cm = _points(check_pixels, 2, 3), _points(check_metres, 2, 3)
    all_pixels = np.concatenate((p, cp))
    if np.any(all_pixels < 0) or np.any(all_pixels >= np.asarray(candidate["image_size"])):
        raise ValueError("floor points outside corrected image")
    if (len(p) != len(m) or len(cp) != len(cm)
            or any(np.any(np.all(p == point, axis=1)) for point in cp)
            or any(np.any(np.all(m == point, axis=1)) for point in cm)):
        raise ValueError("independent floor check correspondences required")
    # MAGSAC's noise scoring is poorly scaled for sub-unit metre coordinates.
    h, inliers = cv2.findHomography(p, m * 1000, cv2.USAC_MAGSAC, 20.)
    if h is not None:
        h[:2] /= 1000
    if h is None or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12 or int(inliers.sum()) < 4:
        raise ValueError("floor registration failed")
    accepted = p[inliers.reshape(-1).astype(bool)]
    reference = accepted.mean(axis=0)
    weights = (h @ np.column_stack((np.concatenate((accepted, cp)), np.ones(len(accepted)+len(cp)))).T)[2]
    reference_w = (h @ np.array([*reference, 1.]))[2]
    if np.any(weights * reference_w <= 1e-12):
        raise ValueError("floor correspondences cross projective horizon")
    projected = cv2.perspectiveTransform(cp.reshape(-1, 1, 2), h).reshape(-1, 2)
    errors = np.linalg.norm(projected - cm, axis=1)
    record = {"status": "candidate", "applied": False, "map_id": map_id, "pixel_space": pixel_space,
              "lens_revision": candidate["revision"], "source_id": candidate["source_id"],
              "undistorted_to_map": h.tolist(), "reference_pixel": reference.tolist(),
              "inliers": int(inliers.sum()), "validation": {"p95_m": float(np.percentile(errors, 95)),
              "max_m": float(max(errors))}}
    record["revision"] = _revision(record)
    return record


def plane_image(image, candidate, floor, bounds, *, source_id, capture_signature, px_per_m=400):
    k, d = _camera(image, candidate, source_id, capture_signature)
    if floor.get("lens_revision") != candidate["revision"] or floor.get("source_id") != source_id:
        raise ValueError("floor and lens revision mismatch")
    if floor.get("pixel_space") != "undistorted":
        raise ValueError("undistorted floor registration required")
    if (len(bounds) != 4 or not all(math.isfinite(v) for v in bounds)
            or not math.isfinite(px_per_m) or not 1 <= px_per_m <= 1000):
        raise ValueError("invalid plane bounds or scale")
    min_x, min_y, max_x, max_y = bounds
    width, height = round((max_x-min_x)*px_per_m), round((max_y-min_y)*px_per_m)
    if not 2 <= width <= 1920 or not 2 <= height <= 1920:
        raise ValueError("plane size must be 2..1920 pixels")
    h = np.asarray(floor["undistorted_to_map"], np.float64)
    if h.shape != (3, 3) or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
        raise ValueError("invalid floor transform")
    inv = np.linalg.inv(h)
    u, v = np.meshgrid(np.arange(width), np.arange(height))
    mapped = inv @ np.stack((min_x + (u.ravel()+.5)/px_per_m,
                             max_y - (v.ravel()+.5)/px_per_m, np.ones(u.size)))
    reference = h @ np.array([*floor["reference_pixel"], 1.])
    forward = mapped[2] * reference[2] > 1e-10
    with np.errstate(divide="ignore", invalid="ignore"):
        pixels = (mapped[:2] / mapped[2]).T
    pixels[~forward] = 0
    rays = np.linalg.inv(k) @ np.column_stack((pixels, np.ones(len(pixels)))).T
    if candidate["model"] == "fisheye":
        raw, _ = cv2.fisheye.projectPoints(rays.T.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), k, d)
    else:
        raw, _ = cv2.projectPoints(rays.T, np.zeros(3), np.zeros(3), k, d)
    raw = raw.reshape(height, width, 2)
    return _remap(image, raw[:, :, 0], raw[:, :, 1], forward.reshape(height, width))


RECOMMENDATIONS = ("increase_tag_size", "move_target_to_edges", "vary_target_tilt", "fix_capture_settings",
                   "collect_validation", "survey_floor", "manual_review", "additional_camera")


def advice_request(report):
    return {"authority": "advisory", "allowed_recommendations": list(RECOMMENDATIONS),
            "warnings": [w for w in report.get("warnings", []) if w in {
                "edge_coverage_low", "tilt_diversity_low", "independent_floor_survey_required",
                "capture_settings_require_operator_verification", "tag_pixels_low", "capture_or_measurement_failed"}],
            "models": [{"model": c["model"], "validation": c["validation"]}
                       for c in report.get("candidates", [])],
            "failed_models": [c["model"] for c in report.get("failures", []) if c.get("model") in {"pinhole", "fisheye"}],
            "forbidden_outputs": ["geometry", "approval", "map_activation", "robot_commands"]}


def validate_advice(value):
    if not isinstance(value, dict) or set(value) != {"recommendations", "explanation"}:
        raise ValueError("only recapture recommendations and explanation allowed")
    rec, explanation = value["recommendations"], value["explanation"]
    if (not isinstance(rec, list) or len(rec) > 8 or any(not isinstance(r, str) or r not in RECOMMENDATIONS for r in rec)
            or not isinstance(explanation, str) or len(explanation) > 4000):
        raise ValueError("invalid advisory response")
    return {**value, "authority": "advisory", "needs_human_review": True}


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("manifest too large")
    return json.loads(raw)


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding="utf-8")


def _image(path):
    raw = Path(path).read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("source image too large")
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None or min(image.shape[:2]) < 32 or max(image.shape[:2]) > 8192:
        raise ValueError("source image unavailable or unsupported")
    return image, hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("target", "fit", "preview", "floor", "plane", "advice", "bundle"))
    parser.add_argument("--input", help="JSON manifest, candidate or advice")
    parser.add_argument("--output", required=True, help="new output directory")
    parser.add_argument("--image")
    parser.add_argument("--source-id")
    parser.add_argument("--capture-signature")
    parser.add_argument("--floor", help="separate floor candidate for plane")
    parser.add_argument("--bounds", nargs=4, type=float)
    args = parser.parse_args(argv)
    created = False
    try:
        value = _read(args.input) if args.input else {}
        out = Path(args.output)
        out.mkdir(parents=True, exist_ok=False)
        created = True
        if args.action == "target":
            grid = AprilGrid(**value)
            (out / "target.svg").write_text(grid.svg(), encoding="utf-8")
            if not cv2.imwrite(str(out / "target.png"), grid.image()):
                raise ValueError("target image write failed")
            _write(out / "target.json", asdict(grid))
        elif args.action == "fit":
            grid, size, groups = AprilGrid(**value["grid"]), None, []
            root = Path(args.input).resolve().parent
            for name in ("training", "validation"):
                entries = value[name]
                if not isinstance(entries, list) or len(entries) > 100:
                    raise ValueError("frame list must contain at most 100 paths")
                group = []
                for path in entries:
                    image, digest = _image(root / path)
                    current = tuple(image.shape[1::-1])
                    if size is not None and current != size:
                        raise ValueError("mixed capture dimensions")
                    size = current
                    group.append({**detect_grid(image, grid), "digest": digest})
                groups.append(group)
            report = fit_lenses(*groups, size, source_id=value["source_id"], capture_signature=value["capture_signature"])
            report["grid"] = asdict(grid)
            _write(out / "report.json", report)
            _write(out / "ai-request.json", advice_request(report))
            for candidate in report["candidates"]:
                _write(out / (candidate["model"] + ".json"), candidate)
            return 0 if report["candidates"] else 2
        elif args.action in ("preview", "plane"):
            image, _ = _image(args.image)
            if args.action == "preview":
                corrected, mask = corrected_image(image, value, source_id=args.source_id,
                                                  capture_signature=args.capture_signature)
            else:
                corrected, mask = plane_image(image, value, _read(args.floor), args.bounds,
                                               source_id=args.source_id, capture_signature=args.capture_signature)
            for filename, pixels in (("raw.png", image), ("corrected.png", corrected), ("valid-mask.png", mask.astype(np.uint8)*255)):
                if not cv2.imwrite(str(out / filename), pixels):
                    raise ValueError("preview image write failed")
            _write(out / "coverage.json", {"observed_fraction": float(mask.mean()), "applied": False})
        elif args.action == "bundle":
            from rosy_vision.calibration_bundle import export_bundle
            root = Path(args.input).resolve().parent
            report = _read(root / value['report'])
            floor = _read(root / value['floor'])
            _write(out / 'bundle.json', export_bundle(report, floor, value['context']))
        elif args.action == "floor":
            candidate = _read(Path(args.input).resolve().parent / value["lens_candidate"])
            floor = fit_floor(candidate, value["pixels"], value["metres"], value["check_pixels"],
                              value["check_metres"], map_id=value["map_id"], pixel_space=value["pixel_space"])
            _write(out / "floor.json", floor)
        else:
            _write(out / "advice.json", validate_advice(value))
    except (ValueError, KeyError, TypeError, OSError, cv2.error) as error:
        if args.action == "fit" and created:
            report = {"status": "review_required", "applied": False, "candidates": [],
                      "failures": [], "warnings": ["capture_or_measurement_failed"]}
            _write(out / "report.json", report)
            _write(out / "ai-request.json", advice_request(report))
        parser.exit(2, f"calibration failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
