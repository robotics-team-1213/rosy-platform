"""Charge-bay guide line evidence: magenta tape frames to the virtual dock.

The observer is ROS-free and owns no motion output (D-1013): it reports the
pink guide line as the dock/observation payload CORE's ``approach="line"``
phases consume. The tests render synthetic tape through an independent
pinhole (the same declared Gazebo geometry the launch passes) and check the
payload, the fail-closed paths and the far-end saturation flag.
"""

import math

import numpy as np
import pytest

from control.sensing.bay_line_observer import BayLineObserver, ground_to_pixel, nominal_geometry
from control.sensing.dock_tag import CameraMount

W, H = 320, 180
HFOV = 1.1519
MOUNT = CameraMount(height_m=0.060194, pitch_rad=math.radians(25.0),
                    x_offset_m=0.028481)
PINK = (217, 38, 242)     # the world's 0.95/0.15/0.85 diffuse as rendered BGR
LINE_TOTAL_M = 0.65


def observer(**kw):
    args = dict(mount=MOUNT, hfov_rad=HFOV, width=W, height=H,
                line_total_m=LINE_TOTAL_M)
    args.update(kw)
    return BayLineObserver(**args)


def render(offset_m, heading_rad, south_of_camera_m, *, carpet=105, tape_dim=1.0):
    """A pink tape on grey carpet: the line passes ``offset_m`` left of the
    robot, runs at ``heading_rad`` (the bay axis in base_link), and its
    corridor-side end sits ``south_of_camera_m`` ahead of the camera."""
    rng = np.random.RandomState(7)
    frame = np.clip(carpet + rng.normal(0, 5, (H, W, 3)), 0, 255).astype(np.uint8)
    tape = tuple(int(c * tape_dim) for c in PINK)
    axis = np.array([math.cos(heading_rad), math.sin(heading_rad)])
    south = -axis
    foot = np.array([0.0, offset_m])
    # The param is camera-relative: base x = south_of_camera_m + x_offset.
    south_base_x = south_of_camera_m + MOUNT.x_offset_m
    for t in np.arange(0.0, south_base_x, 0.004):
        p = foot + south * (south_base_x - t)
        for lateral in (-0.006, 0.0, 0.006):
            q = p + np.array([-axis[1], axis[0]]) * lateral
            ahead = q[0] - MOUNT.x_offset_m
            if ahead <= 0.05:
                continue
            px = ground_to_pixel(ahead, q[1], width=W, height=H,
                                 hfov_rad=HFOV, pitch_rad=MOUNT.pitch_rad,
                                 height_m=MOUNT.height_m)
            if px is not None:
                u, v = int(round(px[0])), int(round(px[1]))
                # A tape has width: paint a patch so the mask sees one component.
                frame[max(0, v - 2):v + 3, max(0, u - 2):u + 3] = tape
    return frame


def errors(payload):
    """CORE's rear_errors: (along to the stop face, lateral of the robot from the axis, heading)."""
    ax, ay = math.cos(payload["yaw"]), math.sin(payload["yaw"])
    return payload["x"] * ax + payload["y"] * ay, ay * payload["x"] - ax * payload["y"]


def heading_error(yaw, want):
    """|yaw - want| wrapped to (-pi, pi]: -pi and +pi are the same heading."""
    return abs(math.atan2(math.sin(yaw - want), math.cos(yaw - want)))


def test_a_centred_visible_line_reads_the_virtual_dock():
    payload = observer().observe(render(0.0, math.pi, 0.30), stamp=10.0)
    assert payload["visible"] is True
    assert payload["source"] == "CAMERA_LINE" and payload["tag_id"] is None
    assert heading_error(payload["yaw"], math.pi) <= math.radians(1.5)
    along, lateral = errors(payload)
    assert lateral == pytest.approx(0.0, abs=0.005)
    # the stop face is behind: line_total minus the corridor end's distance ahead of base_link
    assert along == pytest.approx(LINE_TOTAL_M - 0.30 - MOUNT.x_offset_m, abs=0.015)
    assert payload["x"] < 0.0
    assert payload["along_measured"] is True


def test_a_lateral_offset_and_heading_read_through():
    payload = observer().observe(render(0.03, math.pi + math.radians(5.0), 0.28),
                                 stamp=10.0)
    assert payload["visible"] is True
    assert errors(payload)[1] == pytest.approx(0.03, abs=0.008)
    assert heading_error(payload["yaw"], math.pi + math.radians(5.0)) <= math.radians(1.5)


@pytest.mark.parametrize("south_m", [0.55, 0.70])
def test_beyond_the_far_field_the_along_degrades_but_steering_stays(south_m):
    payload = observer().observe(render(0.0, math.pi, south_m), stamp=10.0)
    assert payload["visible"] is True
    assert payload["along_measured"] is False
    assert errors(payload)[1] == pytest.approx(0.0, abs=0.008)
    assert heading_error(payload["yaw"], math.pi) <= math.radians(1.5)


def test_no_tape_and_a_speck_fail_closed():
    rng = np.random.RandomState(3)
    empty = np.clip(105 + rng.normal(0, 5, (H, W, 3)), 0, 255).astype(np.uint8)
    assert observer().observe(empty, stamp=1.0)["visible"] is False
    speck = empty.copy()
    speck[100:102, 40:42] = PINK
    assert observer().observe(speck, stamp=1.0)["visible"] is False


def test_shadowed_tape_is_still_the_line():
    # A shadow halves the tape brightness; the HSV gate keeps the line while
    # a brightness threshold would lose it (the D-1013 reason for a colour source).
    payload = observer().observe(render(0.0, math.pi, 0.30, tape_dim=0.5), stamp=10.0)
    assert payload["visible"] is True
    assert heading_error(payload["yaw"], math.pi) <= math.radians(1.5)


def test_bad_geometry_is_refused_not_guessed():
    with pytest.raises(ValueError):
        observer(line_total_m=0.30)          # must exceed far_field_m (0.45)
    with pytest.raises(ValueError):
        BayLineObserver(mount=MOUNT, hfov_rad=0.0, width=W, height=H,
                        line_total_m=LINE_TOTAL_M)


def test_the_node_is_an_installed_entry_point_and_publishes_only_evidence():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    setup = (root / "setup.py").read_text(encoding="utf-8")
    assert "'bay_line_observer_node = control.bay_line_observer_node:main'" in setup
    source = (root / "observers" / "bay_line_observer_node.py").read_text(encoding="utf-8")
    assert "cmd_vel" not in source.replace("``cmd_vel``", "")
    assert "Twist" not in source
    assert "source != 'GAZEBO' or not use_sim_time" in source
    assert "payload['ground'] = self._ground" in source   # labelled, so CORE knows the ground


def test_the_robot_s_nominal_camera_profile_gives_a_projecting_observer():
    """A real Pinky watches the line through camera_nominal.yaml (labelled NOMINAL by the node)."""
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    profile = yaml.safe_load((root / "middleware/devices/pinky/profile/config/camera_nominal.yaml")
                             .read_text(encoding="utf-8"))
    mount, hfov, width, height = nominal_geometry(profile)
    assert (width, height) == (320, 240) and abs(math.degrees(hfov) - 59.2) < 0.2
    assert BayLineObserver(mount=CameraMount(**mount), hfov_rad=hfov, width=width, height=height,
                           line_total_m=LINE_TOTAL_M)
    with pytest.raises(ValueError):
        nominal_geometry(dict(profile, cx=150.0))      # off-centre: refused, not projected wrong


def test_an_l_shaped_bay_mouth_is_read_from_the_bay_line_alone():
    """2026-11-18 y8xs: the corridor line across the bay line pulled a one-line fit 16 deg off."""
    frame = render(0.02, math.pi, 0.30)
    # the corridor line: across the robot's axis, 0.25 m ahead of the camera, 0.4 m long
    for t in np.arange(-0.20, 0.20, 0.004):
        for w in (-0.006, 0.0, 0.006):
            px = ground_to_pixel(0.25 + w, t, width=W, height=H, hfov_rad=HFOV,
                                 pitch_rad=MOUNT.pitch_rad, height_m=MOUNT.height_m)
            if px is not None:
                u, v = int(round(px[0])), int(round(px[1]))
                frame[max(0, v - 2):v + 3, max(0, u - 2):u + 3] = PINK
    payload = observer().observe(frame, stamp=10.0)
    assert payload["visible"] is True
    assert heading_error(payload["yaw"], math.pi) <= math.radians(3.0)
    assert abs(errors(payload)[1] - 0.02) <= 0.01


def test_the_corridor_line_alone_gives_the_bay_axis_and_distance_not_the_lateral():
    """Nose at the bay mouth: only the corridor line is in view (2026-11-18 y8xs, no painted extension)."""
    frame = render(0.0, math.pi, 0.30, tape_dim=0.0)          # no bay line drawn (black tape is not pink)
    for t in np.arange(-0.20, 0.20, 0.004):
        for w in (-0.006, 0.0, 0.006):
            px = ground_to_pixel(0.25 + w, t, width=W, height=H, hfov_rad=HFOV,
                                 pitch_rad=MOUNT.pitch_rad, height_m=MOUNT.height_m)
            if px is not None:
                u, v = int(round(px[0])), int(round(px[1]))
                frame[max(0, v - 2):v + 3, max(0, u - 2):u + 3] = PINK
    payload = observer().observe(frame, stamp=10.0)
    assert payload["visible"] is True and payload["lateral_measured"] is False
    assert heading_error(payload["yaw"], math.pi) <= math.radians(3.0)
    assert abs(errors(payload)[0] - (LINE_TOTAL_M - (0.25 + MOUNT.x_offset_m))) <= 0.02
