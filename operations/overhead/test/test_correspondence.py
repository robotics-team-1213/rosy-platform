"""Robot pose/marker correspondences -> reviewable calibration candidate (D-1007).

Synthetic drive in a pinhole camera modelled on ceiling_north (1280x720, hfov 67.8 on the
long side) hung low enough to see only part of the 2.81 x 1.26 m track.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

import rosy_vision.correspondence as cs
from rosy_vision.correspondence import Sample, solve_candidate
from rosy_vision.project import MARKER_HEIGHT_M, MARKER_MOUNT_XY_M

SIZE, HFOV, TRACK = (1280, 720), 67.8, (0.0, 0.0, 2.81, 1.26)
NADIR, CAM_H, YAW = (0.9, 0.6), 1.5, math.radians(7)
FOCAL = 640.0 / math.tan(math.radians(HFOV / 2))
K = np.array([[FOCAL, 0, 640.0], [0, FOCAL, 360.0], [0, 0, 1.0]])


def project(x, y, z):
    c, s = math.cos(YAW), math.sin(YAW)
    dx, dy = x - NADIR[0], y - NADIR[1]
    cam = np.array([c * dx + s * dy, -(-s * dx + c * dy), CAM_H - z])  # looking straight down
    p = K @ cam
    return p[:2] / p[2]


def floor_to_pixel(x, y):
    return project(x, y, 0.0)


def drive(rng, n=240, amplitude=(0.8, 0.45), noise_px=0.5, outliers=0.15, speed=0.1):
    out = []
    for i in range(n):
        t = i * 0.5
        x = NADIR[0] + amplitude[0] * math.sin(0.21 * t)
        y = NADIR[1] + amplitude[1] * math.sin(0.37 * t + 1.0)
        yaw = 0.3 * t % math.tau
        mx, my = MARKER_MOUNT_XY_M
        marker = (x + mx * math.cos(yaw) - my * math.sin(yaw), y + mx * math.sin(yaw) + my * math.cos(yaw))
        px = project(*marker, MARKER_HEIGHT_M) + rng.normal(0, noise_px, 2)
        if rng.random() < outliers:
            px = px + rng.uniform(30, 60, 2)
        out.append(Sample(t, t + 0.02, (float(px[0]), float(px[1])), x + rng.normal(0, 0.005),
                          y + rng.normal(0, 0.005), yaw, "LOCALIZED", 0.05, speed))
    return out


def solve(samples, **kw):
    return solve_candidate(samples, image_size=SIZE, hfov_deg=HFOV, track_bounds_m=TRACK, **kw)


@pytest.fixture(scope="module")
def candidate():
    return solve(drive(np.random.default_rng(3)))


def test_partial_view_fit_is_ok_and_floor_accurate_inside_the_hull(candidate):
    assert candidate["status"] == "ok", candidate
    assert candidate["use"] == "review-only"
    assert candidate["spread"] < 0.6  # the drive covers only part of the track
    h = np.array(candidate["image_to_map"]).reshape(3, 3)
    for fx, fy in [(0.4, 0.3), (0.9, 0.6), (1.4, 0.9)]:  # floor points inside the drive
        px = floor_to_pixel(fx, fy)
        mapped = cs.geometry.apply(h, [px])[0]
        assert np.linalg.norm(mapped - [fx, fy]) < 0.02


def test_valid_region_is_the_driven_hull_not_the_track(candidate):
    region = np.array(candidate["valid_region_m"])
    assert 0.0 <= region[:, 0].min() and region[:, 0].max() <= 1.8
    assert cs._hull_area(region) < 0.6 * (TRACK[2] * TRACK[3])
    # floor frame: the driven floor points lie inside the (floor-scaled) region
    assert all(_inside(region, p) for p in [(0.5, 0.4), (0.9, 0.6), (1.3, 0.8)])
    assert candidate["heldout_rms_m"] < 0.03 and candidate["n_heldout"] >= cs.MIN_HELDOUT


def test_approved_delta_shows_a_moved_camera(candidate):
    moved = np.array(candidate["image_to_map"]).reshape(3, 3)
    shift = np.array([[1, 0, 0.12], [0, 1, 0], [0, 0, 1.0]])  # approved record 12 cm off
    approved = np.linalg.inv(shift @ moved)
    delta = solve(drive(np.random.default_rng(3)), approved_map_to_image=approved.reshape(-1))["approved_delta_m"]
    assert delta["median_m"] == pytest.approx(0.12, abs=0.01)


def test_lane_only_drive_is_rejected_for_spread(monkeypatch):
    monkeypatch.setattr(cs, "DEDUPE_M", 0.04)  # a line gives few 15 cm-apart samples
    result = solve(drive(np.random.default_rng(4), n=600, amplitude=(0.9, 0.02)))
    assert result["status"] == "insufficient_spread"
    assert "image_to_map" not in result


def test_unusable_samples_are_dropped_with_reasons():
    base = drive(np.random.default_rng(5), outliers=0.0)
    bad = [dataclasses.replace(base[0], amcl_state="LOST"), dataclasses.replace(base[1], pose_age_s=1.0),
           dataclasses.replace(base[2], t_pose=base[2].t_image + 0.5),
           dataclasses.replace(base[3], speed_mps=0.5), dataclasses.replace(base[4], x=float("nan"))]
    kept, dropped = cs.gate_samples(bad)
    assert kept == [] and dropped["not_localized"] == dropped["stale"] == dropped["skewed"] == 1
    assert dropped["fast"] == dropped["invalid"] == 1


def test_one_short_burst_is_not_enough_time():
    result = solve(drive(np.random.default_rng(6), n=240)[:30])
    assert result["status"] != "ok"
    assert "image_to_map" not in result


def test_wrong_marker_pixels_never_become_a_candidate():
    rng = np.random.default_rng(7)
    shuffled = [dataclasses.replace(s, px=(float(rng.uniform(0, 1280)), float(rng.uniform(0, 720))))
                for s in drive(rng)]
    assert solve(shuffled)["status"] != "ok"


def test_unknown_lens_gives_no_floor_homography():
    result = solve_candidate(drive(np.random.default_rng(3)), image_size=SIZE, hfov_deg=None,
                             track_bounds_m=TRACK)
    assert result["status"] == "camera_not_solvable"


def _inside(poly, p):
    h = cs._hull(np.vstack([poly, [p]]))
    return len(h) == len(cs._hull(poly))


def test_nan_residual_cannot_pass_the_heldout_gate(monkeypatch):
    monkeypatch.setattr(cs, "_rms", lambda *a: float("nan"))
    assert solve(drive(np.random.default_rng(3)))["status"] == "camera_not_solvable"
