"""Calibration protocol, clearance guard and repeat rule (tools/calibration/run_calibration.py).

No robot: the guard is fed synthetic GET /api/v1/sensors/lidar samples."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_calibration as rc  # noqa: E402


def sample(returns_by_deg, n=360, received_at=100.0, rest=2.0):
    """Scan with angle_min -pi, 1-deg steps; {scan deg: range}, `rest` elsewhere (D-424: a turn
    needs returns all around the base)."""
    ranges = [rest] * n
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
    # D-424: the stop is the body gap g(0.03) ~0.025 m, ~0.085 m from the LiDAR straight ahead.
    s = sample({182: 0.08})                      # 0.08 m at the nose of a 182-deg mount
    assert "clearance" in rc.clearance_reason(s, fwd, 182.0)
    assert rc.clearance_reason(s, back, 182.0) is None
    assert rc.clearance_reason(sample({182: 0.15}), fwd, 182.0) is None   # was refused (< 0.20)
    # The same return 8 deg off the nose (190 mount) is still in the body strip; 40 deg off is not.
    assert "clearance" in rc.clearance_reason(s, fwd, 190.0)
    assert rc.clearance_reason(sample({222: 0.12}), fwd, 182.0) is None


def test_pivot_guard_is_all_around_in_the_base_frame_and_the_body_is_masked():
    pivot = rc.Step("p", angular=0.1, seconds=1)
    assert rc.clearance_reason(sample({90: 0.09}), pivot, 182.0) is not None
    assert rc.clearance_reason(sample({90: 0.05}), pivot, 182.0) is None   # inside the body outline
    assert rc.clearance_reason(sample({90: 0.30}), pivot, 182.0) is None


def test_side_wall_013_from_the_lidar_allows_the_pivot():
    """D-424: rotation radius 0.0826 + 0.02; the old guard refused anything within 0.20 m."""
    pivot = rc.Step("p", angular=0.1, seconds=1)
    wall = {deg: 0.13 / math.cos(math.radians(deg - 272)) for deg in range(242, 303)}
    assert rc.clearance_reason(sample(wall), pivot, 182.0) is None


def test_a_return_at_007_is_an_obstacle_not_a_self_return():
    """D-424: the old 0.08 m self-return cut let a robot touching a wall pivot."""
    pivot = rc.Step("p", angular=0.1, seconds=1)
    near = dict(sample({182: 0.07}), range_min=0.15)          # also below range_min
    assert "clearance" in rc.clearance_reason(near, pivot, 182.0)
    assert rc.plan_step(near, pivot, 182.0)[0] is None


def test_a_straight_with_030_ahead_is_shortened_not_aborted():
    fwd = rc.Step("straight+0", linear=0.03, seconds=0.24 / 0.03)
    planned, note = rc.plan_step(sample({182: 0.30}), fwd, 182.0)
    assert planned is not None and "shortened" in note
    assert planned.linear == fwd.linear
    # room = (0.30 - 0.05905) - g(0.03) = 0.2155 m
    assert planned.linear * planned.seconds == pytest.approx(0.2155, abs=1e-3)
    assert rc.plan_step(sample({182: 0.30}), rc.Step("b", linear=-0.03, seconds=8.0), 182.0) == (
        rc.Step("b", linear=-0.03, seconds=8.0), None)
    # No room at all: wait (None) with a reason, never a scan problem.
    held, why = rc.plan_step(sample({182: 0.10}), fwd, 182.0)
    assert held is None and rc.scan_problem(sample({182: 0.10})) is None and "room" in why


def test_an_unknown_beam_ahead_holds_the_straight_and_the_pivot():
    """D-424 review M2: this tool has no ultrasonic, so an unknown band in front of the body
    is neither free to drive into nor clear for the sweep; a reverse is still free."""
    blind = dict(sample({182: 0.30}), range_min=0.15)
    blind["ranges"][(181 + 180) % 360] = 0.0                  # no return 1 deg off the nose
    assert rc.straight_room_m(blind, rc.Step("f", linear=0.03, seconds=1), 182.0) == 0.0
    assert rc.straight_room_m(blind, rc.Step("b", linear=-0.03, seconds=1), 182.0) > 1.0
    assert "without a return" in rc.clearance_reason(blind, rc.Step("p", angular=0.1, seconds=1), 182.0)


def test_drive_skips_a_blocked_straight_and_keeps_going(monkeypatch):
    monkeypatch.setattr(rc, "CLEARANCE_WAIT_S", 0.0)

    class Wall(FakeCore):
        def lidar(self):
            self.t += 0.1
            return sample({182: 0.125}, received_at=self.t)   # pivot ok, straight room 0.04

    core, logs = Wall(), []
    steps = [rc.Step("straight+0", linear=0.03, seconds=8.0), rc.Step("pivot+", angular=0.1, seconds=0.2)]
    assert rc.drive(core, steps, 182.0, logs.append) is None
    assert any("skipped" in line for line in logs)
    assert core.sent and all(v == 0.0 for v, _ in core.sent) and any(w for _, w in core.sent)


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


def test_one_finite_beam_or_an_empty_scan_is_not_a_clear_pivot():
    """D-424 review M1/L2: all([]) is not clearance."""
    pivot = rc.Step("p", angular=0.1, seconds=1)
    assert "sectors" in rc.clearance_reason(sample({90: 2.0}, rest=math.inf), pivot, 182.0)
    assert "no LiDAR return" in rc.clearance_reason(sample({}, rest=math.inf), pivot, 182.0)


def test_self_mask_cli_hides_a_known_fixed_part():
    masks = rc.parse_self_mask("8kcn=-66:-52:0.17/10:20:0.1,9dfk=-5:5:0.12")
    assert masks["8kcn"] == ((-66.0, -52.0, 0.17), (10.0, 20.0, 0.1)) and "9dfk" in masks
    pivot = rc.Step("p", angular=0.1, seconds=1)
    part = sample({182 - 59: 0.09})                      # robot-frame -59 deg, base ~0.08 from the centre
    assert rc.clearance_reason(part, pivot, 182.0) is not None
    assert rc.clearance_reason(part, pivot, 182.0, self_mask=masks["8kcn"]) is None
    for bad in ("8kcn=-66:-52:0.5", "8kcn=10:5:0.1", "=1:2:0.1"):
        with pytest.raises(ValueError):
            rc.parse_self_mask(bad)


def test_an_all_skipped_run_is_reported_and_never_a_success(monkeypatch):
    monkeypatch.setattr(rc, "CLEARANCE_WAIT_S", 0.0)

    class Boxed(FakeCore):
        def lidar(self):
            self.t += 0.1
            return sample({}, received_at=self.t, rest=0.09)      # walls all around

    adjustments = []
    steps = [rc.Step("straight+0", linear=0.03, seconds=8.0), rc.Step("pivot+", angular=0.1, seconds=1.0)]
    assert rc.drive(Boxed(), steps, 182.0, lambda m: None, adjustments=adjustments) is None
    assert [a["action"] for a in adjustments] == ["skipped", "skipped"]
    full = {"records": [{"kind": "straight", "ds": 0.24, "phi_l": 8.6, "phi_r": 8.6}] * 4
            + [{"kind": "pivot", "dth": 6.28, "phi_r": 4.0, "phi_l": -4.0}] * 2}
    assert "was skipped" in rc.repeat_reason(full, adjustments, steps)
    assert rc.repeat_reason(full, [], steps) is None


def test_skipping_every_pivot_or_every_straight_is_not_accepted():
    """D-424 follow-up (LOW): a run that kept its straights but skipped all pivots measured
    no turn gain; one that skipped all straights measured no wheel radius."""
    steps = rc.protocol(max_linear=0.03, max_angular=0.1)
    full = {"records": [{"kind": "straight", "ds": 0.24, "phi_l": 8.6, "phi_r": 8.6}] * 4
            + [{"kind": "pivot", "dth": 6.28, "phi_r": 4.0, "phi_l": -4.0}] * 2}
    pivots = [{"step": s.name, "action": "skipped"} for s in steps if s.angular and not s.linear]
    straights = [{"step": s.name, "action": "skipped"} for s in steps if s.linear]
    assert "every pivot step" in rc.repeat_reason(full, pivots, steps)
    assert "every straight step" in rc.repeat_reason(full, straights, steps)
    assert rc.repeat_reason(full, pivots[:1] + straights[:1], steps) is None


def test_a_flickering_scan_does_not_end_a_pivot_a_near_return_does(monkeypatch):
    """D-424 follow-up: an unseen base sector for fewer than PIVOT_GAP_DEBOUNCE_TICKS scans in a
    row keeps the pivot going; a seen return inside the sweep ends it at once."""
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    clock = {"t": 0.0}
    monkeypatch.setattr(rc.time, "monotonic", lambda: clock.__setitem__("t", clock["t"] + 0.05) or clock["t"])
    gap = sample({}, rest=math.inf)
    for deg in range(-180, 180, 30):
        gap["ranges"][(deg + 180) % 360] = 2.0           # returns in a few sectors only
    for deg in range(-180, -90):
        gap["ranges"][(deg + 180) % 360] = math.inf     # one quadrant unseen

    class Flicker(FakeCore):
        def __init__(self, script):
            super().__init__()
            self.script = list(script)

        def lidar(self):
            self.t += 0.1
            kind = self.script.pop(0) if self.script else "ok"
            base = {"ok": sample({}), "gap": gap, "near": sample({90: 0.05 + 0.04})}[kind]
            return dict(base, received_at=self.t)

    pivot = [rc.Step("pivot+", angular=0.1, seconds=1.0)]
    flicker = ["ok"] + ["gap"] * (rc.PIVOT_GAP_DEBOUNCE_TICKS - 1) + ["ok"] * 40
    logs = []
    assert rc.drive(Flicker(flicker), pivot, 182.0, logs.append) is None
    assert not any("ended early" in line for line in logs)
    logs = []
    assert rc.drive(Flicker(["ok", "near"]), pivot, 182.0, logs.append) is None
    assert any("ended early" in line for line in logs)


def test_core_uses_https_pinned_to_the_robot_ca(tmp_path):
    """ROSY_API_TLS=required robots answer HTTPS only; the leaf names <host>.local, not the IP."""
    import ssl
    import subprocess
    ca = tmp_path / "ca.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                    "-nodes", "-keyout", str(tmp_path / "k.pem"), "-out", str(ca), "-days", "1",
                    "-subj", "/CN=test-ca"], check=True, capture_output=True)
    core = rc.Core("192.0.2.1", ca_file=ca)
    assert core.base == "https://192.0.2.1:8080"
    assert core.context.verify_mode == ssl.CERT_REQUIRED and core.context.check_hostname is False
    assert rc.Core("192.0.2.1").base == "http://192.0.2.1:8080"
