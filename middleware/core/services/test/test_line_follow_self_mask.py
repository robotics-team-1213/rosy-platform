"""LiDAR self-mask: returns of the robot's own body never count as an obstacle (2026-10-01, 8kcn)."""
import math

import pytest

from core_features.line_follow.clearance import (SELF_MASK_MAX_RANGE_M, front_clearance, scan_points,
                                                 self_mask_from_config)


def _scan(points, forward_deg=180.0, n=720):
    """A scan with returns at robot-frame (deg, range); everything else out of range (inf)."""
    ranges = [math.inf] * n
    step = 2 * math.pi / n
    for deg, r in points:
        scan_angle = math.radians(deg + forward_deg)
        idx = round(((scan_angle + math.pi) % (2 * math.pi)) / step) % n
        ranges[idx] = r
    return {"ranges": ranges, "angle_min": -math.pi, "angle_max": -math.pi + step * (n - 1),
            "range_min": 0.05, "range_max": 12.0}


MASK = self_mask_from_config([{"from_deg": -66, "to_deg": -52, "max_range_m": 0.17}])


def test_own_body_return_is_ignored_but_a_real_obstacle_beyond_it_is_not():
    sample = _scan([(-58, 0.12)])
    assert scan_points(sample, forward_deg=180.0) != ()
    assert scan_points(sample, forward_deg=180.0, self_mask=MASK) == ()
    far = _scan([(-58, 0.25)])            # same direction but beyond the mask's reach
    assert len(scan_points(far, forward_deg=180.0, self_mask=MASK)) == 1


def test_mask_applies_to_the_front_sector_too():
    sample = _scan([(-10, 0.30), (5, 0.12)])
    mask = self_mask_from_config([{"from_deg": 0, "to_deg": 10, "max_range_m": 0.15}])
    assert front_clearance(sample, forward_deg=180.0) == pytest.approx(0.12)
    assert front_clearance(sample, forward_deg=180.0, self_mask=mask) == pytest.approx(0.30)


@pytest.mark.parametrize("bad", [
    [{"from_deg": 10, "to_deg": -10, "max_range_m": 0.1}],
    [{"from_deg": -10, "to_deg": 10, "max_range_m": SELF_MASK_MAX_RANGE_M + 0.01}],
    [{"from_deg": -10, "to_deg": 10}],
    {"from_deg": -10, "to_deg": 10, "max_range_m": 0.1},
])
def test_invalid_masks_are_refused(bad):
    with pytest.raises(ValueError):
        self_mask_from_config(bad)

