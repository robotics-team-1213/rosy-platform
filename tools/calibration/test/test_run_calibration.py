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
    assert "clearance" in rc.clearance_reason(s, fwd, 182.0)
    assert rc.clearance_reason(s, back, 182.0) is None
    # The same return is 8 deg off the nose, still inside the +-25 sector, for a 190 mount;
    # at 40 deg off it is outside.
    assert "clearance" in rc.clearance_reason(s, fwd, 190.0)
    assert rc.clearance_reason(sample({222: 0.15}), fwd, 182.0) is None


def test_pivot_guard_is_all_around_and_self_returns_are_ignored():
    pivot = rc.Step("p", angular=0.1, seconds=1)
    assert rc.clearance_reason(sample({90: 0.12}), pivot, 182.0) is not None
    assert rc.clearance_reason(sample({90: 0.05}), pivot, 182.0) is None   # chassis
    assert rc.clearance_reason(sample({90: 0.30}), pivot, 182.0) is None


def test_stale_or_missing_scan_aborts():
    fwd = rc.Step("f", linear=0.03, seconds=1)
    assert rc.clearance_reason(None, fwd, 182.0) == "no LiDAR sample"
    assert rc.clearance_reason(sample({}), fwd, 182.0, fresh=False) == "LiDAR sample stale"


def test_freshness_uses_the_pc_monotonic_clock_not_the_robot_clock():
    # H4: a robot clock days off must not matter; only whether received_at moves.
    f = rc.ScanFreshness()
    assert f.fresh(sample({}, received_at=1.0e6), 10.0)          # first sight: fresh
    assert f.fresh(sample({}, received_at=1.0e6), 10.4)          # unchanged 0.4 s
    assert not f.fresh(sample({}, received_at=1.0e6), 10.6)      # unchanged 0.6 s: stale
    assert f.fresh(sample({}, received_at=1.0e6 + 0.1), 10.7)    # moved again: fresh
    for bad in (None, "12.0", True, float("nan")):
        assert not rc.ScanFreshness().fresh(sample({}, received_at=bad), 0.0)
    assert not rc.ScanFreshness().fresh(None, 0.0)


class FakeCore:
    def __init__(self, stop_event=None, fail_on_teleop=False):
        self.sent, self.stops, self.stop_event, self.fail = [], 0, stop_event, fail_on_teleop
        self.t = 0.0

    def lidar(self):
        self.t += 0.1
        return sample({}, received_at=self.t)

    def teleop(self, linear, angular):
        if self.fail:
            raise OSError("link down")
        self.sent.append((linear, angular))
        if self.stop_event is not None and len(self.sent) == 3:
            self.stop_event.set()

    def stop(self):
        self.stops += 1


def test_drive_stops_on_the_shared_event_and_always_sends_zero():
    # H5: the operator's Ctrl-C sets the event; every drive loop checks it each tick.
    import threading
    event = threading.Event()
    core = FakeCore(event)
    reason = rc.drive(core, [rc.Step("s", linear=0.03, seconds=5.0)], 182.0, lambda m: None, event)
    assert reason == "stopped by the operator" and len(core.sent) == 3 and core.stops == 1


def test_stop_all_zeroes_every_robot_and_stops_recorders(monkeypatch):
    import threading
    calls = []
    monkeypatch.setattr(rc, "ssh", lambda host, cmd, timeout=60: calls.append((host, cmd)))
    cores = {"a": (FakeCore(), "h1"), "b": (FakeCore(), "h2")}
    event = threading.Event()
    rc.stop_all(event, cores, [])
    assert event.is_set() and all(c.stops == 1 for c, _ in cores.values())
    assert sorted(calls) == [("h1", "~/rosy_rec.sh stop"), ("h2", "~/rosy_rec.sh stop")]


def test_stop_all_zeroes_everyone_first_even_when_one_robot_raises(monkeypatch):
    # F3: pass 1 zero to every robot, pass 2 every recorder; a raising core skips nobody.
    import threading
    order = []

    class Boom(FakeCore):
        def stop(self):
            order.append("zero-a")
            raise RuntimeError("socket gone")

    class Ok(FakeCore):
        def stop(self):
            order.append("zero-b")

    def fake_ssh(host, cmd, timeout=60):
        order.append(f"rec-{host}")
        if host == "h1":
            raise OSError("ssh down")

    monkeypatch.setattr(rc, "ssh", fake_ssh)
    rc.stop_all(threading.Event(), {"a": (Boom(), "h1"), "b": (Ok(), "h2")}, [])
    assert order == ["zero-a", "zero-b", "rec-h1", "rec-h2"]


def test_core_stop_swallows_value_errors():
    # F3: a garbled HTTP reply (JSON ValueError) must not break the zero loop.
    core = rc.Core("192.0.2.1")
    calls = []

    def bad(*a, **k):
        calls.append(1)
        raise ValueError("not json")
    core.teleop = bad
    core.stop()
    assert len(calls) == 3


def test_run_robot_checks_the_stop_event_before_each_attempt(monkeypatch):
    # F5
    import threading
    import types

    class Core(FakeCore):
        def __init__(self, host):
            super().__init__()

        def pair(self, code):
            pass

        def call(self, *a, **k):
            return 200, {}

    calls = []
    monkeypatch.setattr(rc, "Core", Core)
    monkeypatch.setattr(rc, "ssh", lambda host, cmd, timeout=60: calls.append(cmd))
    event = threading.Event()
    event.set()
    args = types.SimpleNamespace(max_angular={}, max_linear={}, lidar_yaw_deg=181.9, dry_run=False,
                                 session_api=False, session_api_path="")
    results = {}
    rc.run_robot("t", "h", "CODE", args, results, stop_event=event)
    assert results["t"]["error"] == "stopped by the operator" and calls == []


def test_join_all_is_bounded():
    import threading
    gate = threading.Event()
    t = threading.Thread(target=gate.wait, name="calib-slow")
    t.start()
    try:
        assert rc.join_all([t], 0.2) == ["calib-slow"]
    finally:
        gate.set()
        t.join()


def test_device_name_matches_rosy_rec_sh():
    # rosy_rec.sh: device = hostname with [^A-Za-z0-9_-] -> '_'
    assert rc.device_name("9dfk") == "rosy-pinky-9dfk"
    assert rc.device_name("8kcn") == "rosy-pinky-8kcn"
    assert rc.rec_device("rosy-pinky-9dfk") == "rosy-pinky-9dfk"
    assert rc.rec_device("rosy.pinky 9dfk") == "rosy_pinky_9dfk"


def test_run_robot_records_an_error_and_stops_the_recorder_it_started(monkeypatch):
    # M5: an exception mid-protocol still stops the recorder and leaves a result.
    import types
    calls = []

    def fake_ssh(host, cmd, timeout=60):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="recording: /home/rosy/recordings/x\n", stderr="")

    class Core(FakeCore):
        def __init__(self, host):
            super().__init__(fail_on_teleop=True)

        def pair(self, code):
            pass

        def call(self, *a, **k):
            return 200, {}

    monkeypatch.setattr(rc, "ssh", fake_ssh)
    monkeypatch.setattr(rc, "Core", Core)
    monkeypatch.setattr(rc, "drive", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    args = types.SimpleNamespace(max_angular={}, max_linear={}, lidar_yaw_deg=181.9, dry_run=False,
                                 session_api=False, session_api_path="")
    results = {}
    rc.run_robot("t", "h", "CODE", args, results)
    assert "boom" in results["t"]["error"]
    assert calls[-1] == "~/rosy_rec.sh stop"


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
