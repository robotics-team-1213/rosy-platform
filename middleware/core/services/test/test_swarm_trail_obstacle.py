"""D-559: swarm trail follow borrows the line-follow D-422 obstacle judgement for its own twist."""

import pytest

from core_features.line_follow.manager import LineFollowConfig, LineFollowManager

PINKY = dict(body_lidar_x_m=-0.017, body_rear_x_m=-0.076, body_rotation_radius_m=0.08257,
             body_half_width_m=0.05655, body_front_x_m=0.04205)
LIDAR_TO_FRONT = 0.04205 + 0.017


class _Events:
    def publish(self, *args, **kwargs):
        pass


def _manager(**overrides):
    config = dict(obstacle_mode="path", obstacle_path_horizon_m=0.60, **PINKY)
    config.update(overrides)
    return LineFollowManager(_Events(), config=LineFollowConfig(**config), clock=lambda: 10.0)


def _wall(x):
    return [(x, -0.3 + i * 0.005) for i in range(121)]


def test_the_body_sweep_measures_the_trail_twist_while_line_follow_is_off():
    m = _manager()
    m.observe_scan_points(_wall(0.40), received_at=10.0)
    before = m.status()
    gap, stop, resume = m.obstacle_gap(0.15, 0.0, 10.0)
    assert gap == pytest.approx(0.40 - LIDAR_TO_FRONT, abs=0.01)
    assert stop == pytest.approx(m.config.derived_stop_gap_m(0.15))
    assert resume > stop
    assert m.status() == before          # line-follow status is not touched


def test_a_turning_twist_sweeps_its_arc_not_the_straight_line():
    m = _manager()
    m.observe_scan_points([(0.40, 0.0)], received_at=10.0)
    straight = m.obstacle_gap(0.15, 0.0, 10.0)[0]
    turning = m.obstacle_gap(0.15, 0.8, 10.0)[0]
    assert straight is not None and (turning is None or turning > straight)


def test_no_fresh_scan_is_no_judgement():
    m = _manager()
    assert m.obstacle_gap(0.1, 0.0, 10.0) is None
    m.observe_scan_points(_wall(0.4), received_at=10.0)
    assert m.obstacle_gap(0.1, 0.0, 10.0 + m.config.clearance_stale_s + 0.1) is None


def test_sector_mode_reports_the_front_distance():
    m = _manager(obstacle_mode="sector")
    m.observe_clearance(0.33, received_at=10.0)
    assert m.obstacle_gap(0.1, 0.0, 10.0) == (0.33, m.config.sector_stop_m, m.config.sector_resume_m)
