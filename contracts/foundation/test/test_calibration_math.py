import math

import pytest

from core_common.calibration_math import (
    default_lens_profile,
    distort_point,
    fit_homography_dlt,
    project_pixel_to_plane,
    scale_lens_profile,
    solve_planar_pose,
    undistort_point,
)


def _synth_camera():
    profile = {
        "model": "pinhole",
        "K": [[960.0, 0.0, 640.0], [0.0, 960.0, 360.0], [0.0, 0.0, 1.0]],
        "D": [-0.28, 0.08, 0.002, -0.001, -0.01],
        "image_size": [1280, 720],
        "source": "measured",
    }
    # Tilted camera (~18 deg pitch about X, 8 deg yaw about Z) at (0.15, -0.60, 2.05) in world
    pitch = math.radians(162.0)  # camera +Z looks down (-Z world) with tilt
    yaw = math.radians(8.0)
    rx = [[1.0, 0.0, 0.0], [0.0, math.cos(pitch), -math.sin(pitch)], [0.0, math.sin(pitch), math.cos(pitch)]]
    rz = [[math.cos(yaw), -math.sin(yaw), 0.0], [math.sin(yaw), math.cos(yaw), 0.0], [0.0, 0.0, 1.0]]
    r_wc = [[sum(rz[i][k] * rx[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    rot = [[r_wc[j][i] for j in range(3)] for i in range(3)]
    cw = [0.15, -0.55, 2.05]
    t = [-sum(rot[i][j] * cw[j] for j in range(3)) for i in range(3)]
    return profile, rot, t, cw


@pytest.mark.parametrize("model,d", [
    ("pinhole", [-0.32, 0.11, 0.003, -0.002, -0.02]),
    ("fisheye", [-0.08, 0.02, -0.004, 0.001]),
])
def test_distort_undistort_round_trip(model, d):
    profile = {
        "model": model,
        "K": [[820.0, 0.0, 640.0], [0.0, 820.0, 360.0], [0.0, 0.0, 1.0]],
        "D": d,
        "image_size": [1280, 720],
    }
    for xu, yu in [(120.0, 80.0), (640.0, 360.0), (1180.0, 650.0), (200.0, 620.0)]:
        u, v = distort_point(xu, yu, profile)
        rx, ry = undistort_point(u, v, profile)
        assert (rx, ry) == pytest.approx((xu, yu), abs=1e-5)


def test_scale_lens_profile_pixel_center_rule():
    prof = default_lens_profile(1280, 720, 67.8)
    half = scale_lens_profile(prof, (640, 360))
    assert half["image_size"] == [640, 360]
    assert half["K"][0][0] == pytest.approx(prof["K"][0][0] * 0.5)
    assert half["K"][0][2] == pytest.approx(0.5 * (640.0 + 0.5) - 0.5)
    with pytest.raises(ValueError, match="aspect"):
        scale_lens_profile(prof, (640, 480))


def test_se3_solver_recovers_pose_and_floor_with_distortion():
    profile, rot, t, cw = _synth_camera()
    k = profile["K"]
    map_pts = [(-1.0, -0.5), (1.0, -0.5), (1.0, 0.5), (-1.0, 0.5), (0.0, 0.0), (0.4, -0.2)]
    raw_pts = []
    for mx, my in map_pts:
        xc = rot[0][0] * mx + rot[0][1] * my + t[0]
        yc = rot[1][0] * mx + rot[1][1] * my + t[1]
        zc = rot[2][0] * mx + rot[2][1] * my + t[2]
        xu = k[0][0] * (xc / zc) + k[0][2]
        yu = k[1][1] * (yc / zc) + k[1][2]
        raw_pts.append(distort_point(xu, yu, profile))

    fit = solve_planar_pose(raw_pts, map_pts, image_size=(1280, 720), lens_profile=profile,
                            track_bounds_m=(-1.2, -0.6, 1.2, 0.6))
    assert fit["accepted"] is True, fit["reason"]
    assert fit["rms_m"] < 0.002
    assert fit["camera_pose_m"] == pytest.approx(cw, abs=0.005)

    # Parallax check for elevated marker at z = 0.125 m
    mx_top, my_top, mz_top = 0.5, 0.25, 0.125
    xc = rot[0][0] * mx_top + rot[0][1] * my_top + rot[0][2] * mz_top + t[0]
    yc = rot[1][0] * mx_top + rot[1][1] * my_top + rot[1][2] * mz_top + t[1]
    zc = rot[2][0] * mx_top + rot[2][1] * my_top + rot[2][2] * mz_top + t[2]
    u_top, v_top = distort_point(k[0][0] * (xc / zc) + k[0][2], k[1][1] * (yc / zc) + k[1][2], profile)
    px, py = project_pixel_to_plane(
        u_top, v_top, fit["image_to_map"], height_m=mz_top, lens_profile=profile, camera_pose=fit["camera_pose_m"]
    )
    assert (px, py) == pytest.approx((mx_top, my_top), abs=0.003)


def test_solver_rejects_collinear_and_sheared_correspondences():
    profile, *_ = _synth_camera()
    collinear_map = [(0.0, 0.0), (0.3, 0.0), (0.6, 0.0), (0.9, 0.0)]
    raw = [(200.0, 300.0), (400.0, 300.0), (600.0, 300.0), (800.0, 300.0)]
    with pytest.raises(ValueError):
        fit_homography_dlt(collinear_map, raw)

    # Severely sheared 5-point mapping with calibrated lens must be rejected
    map_pts = [(-1.0, -0.5), (1.0, -0.5), (1.0, 0.5), (-1.0, 0.5), (0.0, 0.0)]
    sheared_px = [(200.0, 500.0), (900.0, 500.0), (1200.0, 180.0), (150.0, 180.0), (640.0, 360.0)]
    res = solve_planar_pose(sheared_px, map_pts, image_size=(1280, 720), lens_profile=profile,
                            track_bounds_m=(-1.2, -0.6, 1.2, 0.6))
    assert res["accepted"] is False
    assert res["reason"] in ("excessive_shear", "high_reprojection_error", "camera_height_out_of_range")
