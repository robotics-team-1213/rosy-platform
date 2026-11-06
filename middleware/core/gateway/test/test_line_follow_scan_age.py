"""Obstacle freshness counts from the scan stamp: a queued old scan is not 'just seen'."""
from core.bridge import observation


class _Line:
    config = type("C", (), {"obstacle_mode": "sector", "lidar_forward_deg": 0.0,
                            "obstacle_half_angle_deg": 20.0, "lidar_self_mask": ()})()
    wants_crosswalk_scan = wants_body_points = wants_return_scan = False

    def __init__(self):
        self.seen = []
        self.crosswalk = None

    def observe_clearance(self, distance, received_at=None):
        self.seen.append(received_at)


class _Services:
    loc_mission = None

    def __init__(self):
        self.line_follow = _Line()


def _sample(**kw):
    return {"ranges": [1.0] * 4, "angle_min": 0.0, "angle_max": 3.0, "angle_increment": 1.0,
            "range_min": 0.1, "range_max": 5.0, "frame_id": "l", **kw}


def _seen(**kw):
    s = _Services()
    observation.front_clearance(s, _sample(**kw), received_at=10.0)
    return s.line_follow.seen[0]


def test_queued_scan_is_dated_by_its_stamp():
    assert _seen(source_stamp_ns=1_000_000_000, source_now_ns=1_400_000_000) == 10.0 - 0.4


def test_unprovable_or_future_stamp_keeps_arrival_time():
    assert _seen(source_stamp_ns=0, source_now_ns=5_000_000_000) == 10.0
    assert _seen() == 10.0
    assert _seen(source_stamp_ns=2_000_000_000, source_now_ns=1_000_000_000) == 10.0


def test_path_mode_backdates_freshness_but_not_odometry_time():
    from test_line_follow_obstacle_path import _manager
    m = _manager()
    seen = []
    m._remember_near = lambda now: seen.append(now)
    m.observe_scan_points([(1.0, 0.0)], received_at=10.0, lag_s=0.4)
    assert m._clearance_at == 10.0 - 0.4 and seen == [10.0]
    m.observe_scan_points([(1.0, 0.0)], received_at=11.0)
    assert m._clearance_at == 11.0
