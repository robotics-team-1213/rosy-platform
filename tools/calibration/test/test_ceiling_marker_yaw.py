"""D-587 5: sticker yaw offset from a straight forward drive (travel direction, not odom)."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ceiling_marker_yaw import EstimateError, estimate  # noqa: E402


def _drive(heading_deg, sighting_yaw_deg, *, n=12, length=0.4, wobble=0.0, yaw_noise=0.0):
    h = math.radians(heading_deg)
    rows = []
    for i in range(n):
        s = length * i / (n - 1)
        side = wobble * (1 if i % 2 else -1)
        rows.append((100.0 + 0.4 * i, 0.3 + s * math.cos(h) - side * math.sin(h),
                     -0.5 + s * math.sin(h) + side * math.cos(h),
                     math.radians(sighting_yaw_deg + yaw_noise * (1 if i % 3 else -1))))
    return rows


@pytest.mark.parametrize("heading, seen, current, expected, nearest", [
    (0.0, 0.0, 0.0, 0.0, 0),            # sticker right: no change
    (30.0, 200.0, 0.0, 170.0, 180),     # sticker on backwards, 10 deg short
    (-120.0, -30.0, 0.0, 90.0, 90),     # turned 90 deg left
    (90.0, 92.0, 180.0, -178.0, 180),   # already corrected by 180, 2 deg left
])
def test_offset_is_the_current_plus_the_yaw_minus_the_travel_direction(heading, seen, current, expected, nearest):
    result = estimate(_drive(heading, seen, yaw_noise=0.5), current)
    assert result["offset_deg"] == pytest.approx(expected, abs=0.3)
    assert result["travel_deg"] == pytest.approx(heading, abs=0.1)
    assert result["nearest_90_deg"] == nearest


def test_travel_direction_follows_time_not_the_axis_sign():
    rows = _drive(180.0, 180.0)
    assert estimate(rows)["offset_deg"] == pytest.approx(0.0, abs=0.1)
    reversed_time = [(200.0 - t, x, y, yaw) for t, x, y, yaw in rows]   # same points, driven the other way
    assert abs(estimate(reversed_time)["offset_deg"]) == pytest.approx(180.0, abs=0.1)


@pytest.mark.parametrize("rows, message", [
    (_drive(0.0, 0.0, n=4), "need 5"),
    (_drive(0.0, 0.0, length=0.2), "at least"),
    (_drive(0.0, 0.0, wobble=0.03), "straight line"),
    (_drive(0.0, 0.0, yaw_noise=6.0), "yaw spread"),
])
def test_refuses_a_drive_it_cannot_trust(rows, message):
    with pytest.raises(EstimateError, match=message):
        estimate(rows)
