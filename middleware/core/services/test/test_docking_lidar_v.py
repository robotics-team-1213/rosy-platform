"""Rear dock V marker (D-972): LiDAR points to the dock origin and inward axis.

Scans are ray-cast against the marker's two fin faces (research scad
`lidar_target`) placed behind the stop face, seen from a robot whose back
faces the dock. The detector must return the stop-face centre and the inward
axis, and must refuse anything that is not that V.
"""

import json
import math
import random

import pytest

from core_features.docking.lidar_v import SOURCE, DockVSpec, detect_dock_v, lidar_v_payload

SPEC = DockVSpec()
STEP = math.radians(0.72)            # RPLidar C1 at 10 Hz


def fins(half_angle=SPEC.arm_angle_rad, depth=SPEC.apex_depth_m, gap=0.0118, length=0.0545):
    """Fin front faces in the dock frame (stop face centre, inward axis -y)."""
    apex = (0.0, -depth)
    out = []
    for side in (1.0, -1.0):
        d = (side * math.cos(half_angle), math.sin(half_angle))
        out.append(((apex[0] + d[0] * gap, apex[1] + d[1] * gap),
                    (apex[0] + d[0] * (gap + length), apex[1] + d[1] * (gap + length))))
    return out


def robot_frame(segments, lateral, along, heading):
    """Dock-frame segments -> base_link, robot at (lateral, along) with its
    back toward the dock, turned by `heading`."""
    psi = math.pi / 2 + heading
    c, s = math.cos(psi), math.sin(psi)

    def tf(p):
        dx, dy = p[0] - lateral, p[1] - along
        return (c * dx + s * dy, -s * dx + c * dy)
    return [(tf(a), tf(b)) for a, b in segments]


def cast(segments, noise=0.0, seed=1):
    """Ranges from base_link over the full circle; nearest segment hit."""
    rng = random.Random(seed)
    n = int(round(2 * math.pi / STEP))
    ranges = []
    for i in range(n):
        a = -math.pi + i * STEP
        dx, dy = math.cos(a), math.sin(a)
        best = float("inf")
        for (ax, ay), (bx, by) in segments:
            ex, ey = bx - ax, by - ay
            det = dx * -ey + ex * dy
            if abs(det) < 1e-12:
                continue
            t = (ax * -ey + ex * ay) / det
            u = (dx * ay - dy * ax) / det
            if t > 0 and 0.0 <= u <= 1.0:
                best = min(best, t)
        ranges.append(best + (rng.uniform(-noise, noise) if math.isfinite(best) else 0.0))
    return ranges, -math.pi


def observe(segments, noise=0.0, drop=None):
    ranges, angle_min = cast(segments, noise)
    points = [(r * math.cos(angle_min + i * STEP), r * math.sin(angle_min + i * STEP))
              for i, r in enumerate(ranges) if math.isfinite(r)]
    if drop is not None:
        points = [p for p in points if not drop(p)]
    return detect_dock_v(points)


def truth(lateral, along, heading):
    """Stop-face centre and the inward axis (dock -y) in base_link."""
    psi = math.pi / 2 + heading
    c, s = math.cos(psi), math.sin(psi)
    ox, oy = c * -lateral + s * -along, -s * -lateral + c * -along
    ax, ay = 0.0, -1.0                                   # inward axis in the dock frame
    return ox, oy, math.atan2(-s * ax + c * ay, c * ax + s * ay)


@pytest.mark.parametrize("lateral", [-0.03, 0.0, 0.02])
@pytest.mark.parametrize("along", [0.3, 0.55, 0.8])
@pytest.mark.parametrize("heading_deg", [-6.0, 0.0, 4.0])
def test_a_clean_scan_gives_the_stop_face_and_axis(lateral, along, heading_deg):
    heading = math.radians(heading_deg)
    segments = robot_frame(fins(), lateral, along, heading)
    obs = observe(segments)
    assert obs is not None
    x, y, yaw = truth(lateral, along, heading)
    assert math.hypot(obs.x - x, obs.y - y) <= 0.003
    assert abs(math.atan2(math.sin(obs.yaw - yaw), math.cos(obs.yaw - yaw))) <= math.radians(0.6)
    assert obs.confidence > 0.5


def test_range_noise_of_two_millimetres_keeps_the_pose_close():
    segments = robot_frame(fins(), 0.01, 0.55, math.radians(2.0))
    obs = observe(segments, noise=0.002)
    x, y, yaw = truth(0.01, 0.55, math.radians(2.0))
    assert obs is not None
    assert math.hypot(obs.x - x, obs.y - y) <= 0.008
    assert abs(obs.yaw - yaw) <= math.radians(2.0)


def test_half_a_fin_hidden_still_finds_the_v():
    segments = robot_frame(fins(), 0.0, 0.5, 0.0)
    # Hide the outer half of one fin (a cable, a hand): drop points far to one side.
    obs = observe(segments, drop=lambda p: p[1] > 0.05)
    assert obs is not None
    x, y, yaw = truth(0.0, 0.5, 0.0)
    assert math.hypot(obs.x - x, obs.y - y) <= 0.006


@pytest.mark.parametrize("scene", ["one_fin", "flat_wall", "right_angle_v", "nothing"])
def test_anything_but_the_declared_v_is_refused(scene):
    if scene == "one_fin":
        dock = fins()[:1]
    elif scene == "flat_wall":
        dock = [((-0.3, -0.07), (0.3, -0.07))]
    elif scene == "right_angle_v":
        dock = fins(half_angle=math.radians(45.0))
    else:
        dock = []
    segments = robot_frame(dock, 0.0, 0.5, 0.0)
    assert observe(segments) is None


def test_a_v_that_opens_away_from_the_robot_is_refused():
    # Robot on the far side of the marker sees the fins' backs: the V opens away.
    segments = robot_frame(fins(), 0.0, -0.6, 0.0)
    assert observe(segments) is None


def test_the_payload_is_the_dock_observation_wire_shape():
    lost = lidar_v_payload(5.0, None)
    assert lost["source"] == SOURCE == "LIDAR_V" and lost["visible"] is False
    assert lost["tag_id"] is None and lost["x"] is None and lost["confidence"] == 0.0
    segments = robot_frame(fins(), 0.0, 0.5, 0.0)
    seen = lidar_v_payload(5.0, observe(segments))
    assert seen["visible"] is True and seen["tag_id"] is None
    assert seen["range_m"] == pytest.approx(math.hypot(seen["x"], seen["y"]))
    json.dumps(seen)
    with pytest.raises(ValueError):
        lidar_v_payload(float("nan"), None)


def test_core_feeds_the_v_from_its_scan_only_while_docking_looks():
    """`core.bridge.observation.rear_dock_scan`: the laser sits 17 mm behind base_link."""
    from types import SimpleNamespace

    from core.bridge import observation
    from core_features.docking.feed import LIDAR_V, DockObservationFeed
    from core_features.docking.model import DockPhase

    lidar_x = -0.017
    base = robot_frame(fins(), 0.0, 0.5, math.radians(3.0))
    ranges, angle_min = cast([((a[0] - lidar_x, a[1]), (b[0] - lidar_x, b[1])) for a, b in base])
    sample = {"ranges": ranges, "angle_min": angle_min,
              "angle_max": angle_min + (len(ranges) - 1) * STEP, "range_min": 0.05,
              "range_max": 12.0, "source_stamp_ns": 100_000_000_000,
              "source_now_ns": 100_050_000_000}
    docking = SimpleNamespace(active=True, phase=DockPhase.ACQUIRING)
    services = SimpleNamespace(
        docking=docking, dock_feed=DockObservationFeed(),
        line_follow=SimpleNamespace(config=SimpleNamespace(
            lidar_forward_deg=0.0, lidar_self_mask=(), body_lidar_x_m=lidar_x)))
    observation.rear_dock_scan(services, sample, received_at=50.0)
    seen = services.dock_feed.latest(source=LIDAR_V)
    x, y, yaw = truth(0.0, 0.5, math.radians(3.0))
    assert seen is not None and math.hypot(seen.x - x, seen.y - y) <= 0.004
    assert seen.at == pytest.approx(49.95)            # captured 50 ms before receipt

    for phase, active in ((DockPhase.REVERSING, True), (DockPhase.ACQUIRING, False)):
        services.dock_feed = DockObservationFeed()
        docking.phase, docking.active = phase, active
        observation.rear_dock_scan(services, sample, received_at=50.0)
        assert services.dock_feed.latest(source=LIDAR_V) is None
