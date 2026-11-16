"""cable_twist: turn measured from scans, twist tracking, direction probe, and the unwind run on a simulated cable.

No robot: a synthetic room scanned from a point, and a fake CORE whose cable resists turning the way it was wound."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cable_twist as ct  # noqa: E402

N, INC = 720, 2 * math.pi / 720
XMIN, XMAX, YMIN, YMAX = -1.0, 2.0, -1.2, 1.4          # a room, robot at the origin: no 180 deg symmetry


def room_range(phi):
    c, s = math.cos(phi), math.sin(phi)
    ts = []
    if c > 1e-9:
        ts.append(XMAX / c)
    if c < -1e-9:
        ts.append(XMIN / c)
    if s > 1e-9:
        ts.append(YMAX / s)
    if s < -1e-9:
        ts.append(YMIN / s)
    return min(ts)


def scan_at(yaw_deg):
    """Ranges at robot yaw `yaw_deg`: a feature at world bearing phi shows at sensor angle phi - yaw."""
    psi = math.radians(yaw_deg)
    return [room_range(-math.pi + i * INC + psi) for i in range(N)]


@pytest.mark.parametrize("turn", [0.0, 5.0, -5.0, 23.3, -37.6, 44.0])
def test_scan_yaw_delta_measures_the_turn_and_its_sign(turn):
    got = ct.scan_yaw_delta(scan_at(10.0), scan_at(10.0 + turn), INC)
    assert got == pytest.approx(turn, abs=0.3)


def test_a_featureless_scan_cannot_be_measured():
    assert ct.scan_yaw_delta([2.0] * N, [2.0] * N, INC) is None


def test_twist_tracker_states_and_unwind_direction():
    t = ct.TwistTracker()
    t.add(120.0)
    t.add(-30.0)
    assert t.twist_deg == pytest.approx(90.0) and t.state() == "ok" and t.unwind_sign() == -1
    t.add(100.0)
    assert t.state() == "warn"
    t.add(100.0)
    assert t.state() == "unwind"
    t.add(-400.0)
    assert t.twist_deg == pytest.approx(-110.0) and t.unwind_sign() == +1 and t.turned_deg == 750.0
    assert ct.TwistTracker(-420.0).state() == "trip"


def test_probe_names_the_resisted_direction_as_the_winding_one():
    ccw_wound = ct.probe_verdict(achieved_ccw_deg=18.0, achieved_cw_deg=-29.0, commanded_deg=30.0)
    assert ccw_wound["verdict"] == "twisted" and ccw_wound["winding_sign"] == +1 and ccw_wound["unwind_sign"] == -1
    cw_wound = ct.probe_verdict(achieved_ccw_deg=29.0, achieved_cw_deg=-15.0, commanded_deg=30.0)
    assert cw_wound["unwind_sign"] == +1
    assert ct.probe_verdict(28.0, -27.0, 30.0)["verdict"] == "symmetric"
    assert ct.probe_verdict(2.0, -1.0, 30.0)["verdict"] == "not_turning"


class Sim:
    """Fake CORE + clock. The cable has `twist` degrees wound (+ = counter-clockwise); turning further the winding way
    is resisted in proportion to the twist, turning back is free. `snag` holds the robot almost still."""

    def __init__(self, twist, snag=False):
        self.t, self.twist, self.yaw, self.snag, self.cmd = 1000.0, float(twist), 0.0, False, 0.0
        self.snag = snag

    def sleep(self, dt):
        self.t += dt
        if self.cmd:
            sign = 1 if self.cmd > 0 else -1
            ratio = 0.05 if self.snag else (max(0.2, 1 - abs(self.twist) / 300.0) if self.twist * sign > 0 else 1.0)
            moved = math.degrees(self.cmd * dt) * ratio
            self.yaw += moved
            self.twist += moved

    def call(self, method, path, body=None, **kw):
        if method == "POST" and path == "/teleop":
            self.cmd = body["angular"]
            return 200, {}
        if method == "GET" and path == "/sensors/lidar":
            return 200, dict(ranges=scan_at(self.yaw), angle_min=-math.pi, angle_increment=INC, range_min=0.05,
                             range_max=12.0, received_at=self.t - 0.05)
        raise AssertionError((method, path))


@pytest.fixture
def sim(monkeypatch):
    def make(twist, snag=False):
        s = Sim(twist, snag)
        monkeypatch.setattr(ct, "_now", lambda: s.t)
        monkeypatch.setattr(ct, "_sleep", s.sleep)
        return s
    return make


class Args:
    probe_deg, max_deg, twist_deg = 30.0, 360.0, None


def run(fn, core, **overrides):
    args = Args()
    for k, v in overrides.items():
        setattr(args, k, v)
    rows = []
    result = fn(core, args, rows.append, 180.0)
    return result, rows


def test_judge_finds_the_unwind_direction_of_a_wound_cable(sim):
    s = sim(+150.0)
    verdict, _ = run(ct.run_judge, s)
    assert verdict["verdict"] == "twisted" and verdict["unwind_sign"] == -1
    s = sim(-150.0)
    assert run(ct.run_judge, s)[0]["unwind_sign"] == +1


def test_judge_sees_no_twist_on_a_slack_cable(sim):
    assert run(ct.run_judge, sim(0.0))[0]["verdict"] == "symmetric"


def test_unwind_with_a_known_twist_brings_it_to_slack(sim):
    s = sim(+130.0)
    result, rows = run(ct.run_unwind, s, twist_deg=130.0)
    assert result["outcome"] == "slack" and abs(s.twist) <= ct.SLACK_DEG + 5
    assert all(r.get("sign") == -1 for r in rows if r["event"] == "step")      # only ever clockwise


def test_unwind_with_an_unknown_twist_probes_for_the_direction_and_stops_near_slack(sim):
    s = sim(-200.0)
    result, _ = run(ct.run_unwind, s)
    assert result["outcome"] in ("slack_reached", "passed_slack") and abs(s.twist) < 70.0


def test_unwind_stops_and_asks_a_person_when_the_cable_holds_the_robot(sim):
    s = sim(+130.0, snag=True)
    with pytest.raises(ct.Abort):
        run(ct.run_unwind, s, twist_deg=130.0)


def test_unwind_does_nothing_on_a_slack_cable(sim):
    s = sim(0.0)
    result, _ = run(ct.run_unwind, s)
    assert result["outcome"] == "no_twist_detected"
