"""Calibration protocol, clearance guard and repeat rule (tools/calibration/run_calibration.py).

No robot: the guard is fed synthetic GET /api/v1/sensors/lidar samples."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_calibration as rc  # noqa: E402


def sample(returns_by_deg, n=360, received_at=100.0):
    """Scan with angle_min -pi, 1-deg steps; {scan deg: range}."""
    ranges = [math.inf] * n
    for deg, r in returns_by_deg.items():
        ranges[(deg + 180) % n] = r
    return {"ranges": ranges, "angle_min": -math.pi, "angle_max": math.pi * (n - 2) / n,
            "received_at": received_at}


def test_protocol_fits_the_time_budget_and_respects_limits():
    steps = rc.protocol(max_linear=0.03, max_angular=0.1)
    assert rc.duration_s(steps) <= 6 * 60
    assert max(abs(s.angular) for s in steps) <= 0.1 + 1e-9
    assert max(abs(s.linear) for s in steps) <= 0.03 + 1e-9
    pivots = [s for s in steps if s.name.endswith("360")]
    assert [round(s.angular * s.seconds / math.pi, 3) for s in pivots] == [2.0, -2.0]
    fast = rc.protocol(max_linear=0.2, max_angular=0.3)
    assert {round(abs(s.angular), 1) for s in fast if s.name.startswith("gain")} == {0.1, 0.2, 0.3}
    assert any(s.name == "fast+" for s in fast)


def test_straight_guard_looks_in_the_direction_of_travel_with_the_given_yaw():
    fwd = rc.Step("f", linear=0.03, seconds=1)
    back = rc.Step("b", linear=-0.03, seconds=1)
    s = sample({182: 0.15})                      # 0.15 m at the nose of a 182-deg mount
    assert "clearance" in rc.clearance_reason(s, fwd, 182.0, 100.1)
    assert rc.clearance_reason(s, back, 182.0, 100.1) is None
    # The same return is 8 deg off the nose, still inside the +-25 sector, for a 190 mount;
    # at 40 deg off it is outside.
    assert "clearance" in rc.clearance_reason(s, fwd, 190.0, 100.1)
    assert rc.clearance_reason(sample({222: 0.15}), fwd, 182.0, 100.1) is None


def test_pivot_guard_is_all_around_and_self_returns_are_ignored():
    pivot = rc.Step("p", angular=0.1, seconds=1)
    assert rc.clearance_reason(sample({90: 0.12}), pivot, 182.0, 100.1) is not None
    assert rc.clearance_reason(sample({90: 0.05}), pivot, 182.0, 100.1) is None   # chassis
    assert rc.clearance_reason(sample({90: 0.30}), pivot, 182.0, 100.1) is None


def test_stale_or_missing_scan_aborts():
    fwd = rc.Step("f", linear=0.03, seconds=1)
    assert rc.clearance_reason(None, fwd, 182.0, 100.0) == "no LiDAR sample"
    assert rc.clearance_reason(sample({}, received_at=90.0), fwd, 182.0, 100.0) == "LiDAR sample stale"


def rec(kind, ds=0.0, dth=0.0, phi_l=0.0, phi_r=0.0):
    return {"kind": kind, "ds": ds, "dth": dth, "phi_l": phi_l, "phi_r": phi_r}


def test_repeat_rule():
    good = [rec("straight", ds=0.24, phi_l=8.88, phi_r=8.88) for _ in range(4)]
    good += [rec("pivot", dth=2 * math.pi, phi_l=-11.2, phi_r=11.2),
             rec("pivot", dth=-2 * math.pi, phi_l=11.2, phi_r=-11.2)]
    assert rc.repeat_reason({"records": good}) is None
    bad = good[:3] + [rec("straight", ds=0.24 * 1.02, phi_l=8.88, phi_r=8.88)] + good[4:]
    assert "radius spread" in rc.repeat_reason({"records": bad})
    assert "too few" in rc.repeat_reason({"records": good[:2]})
