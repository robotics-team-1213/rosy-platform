"""edge_drive nudge body advisory (D-422/D-424): warns, never blocks; LiDAR angle source order.

No robot: synthetic GET /api/v1/sensors/lidar samples."""
import math
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import edge_drive  # noqa: E402
from core_common.robot_body import PINKY_PRO  # noqa: E402


def sample(returns_by_deg, n=360, rest=1.5, range_min=0.05):
    """Scan angle_min -pi, 1 deg steps; {scan deg: range}, `rest` elsewhere."""
    ranges = [rest] * n
    for deg, r in returns_by_deg.items():
        ranges[(deg + 180) % n] = r
    return {"ranges": ranges, "angle_min": -math.pi, "angle_increment": 2 * math.pi / n,
            "range_min": range_min, "range_max": 12.0}


def view(returns=None, forward=180.0, range_min=0.05):
    return PINKY_PRO.scan_view(sample(returns or {}, range_min=range_min), forward_deg=forward)


def test_clear_path_has_no_warning():
    report, warn = edge_drive.advisory(view(), 0.05, 2.0)
    assert warn is None and report.startswith("body gap front")


def test_box_ahead_warns_forward_but_not_backward():
    ahead = view({d: 0.15 for d in range(170, 191)})      # LiDAR faces 180: this is the robot's front
    assert edge_drive.advisory(ahead, 0.05, 2.0)[1].startswith("body path blocked")
    assert edge_drive.advisory(ahead, -0.05, 2.0)[1] is None


def test_unknown_band_ahead_warns():
    # CORE sends a no-return beam as null; it may hide an object out to range_min.
    blind = view({d: None for d in range(175, 186)}, range_min=0.12)
    assert "unknown True" in edge_drive.advisory(blind, 0.05, 1.0)[1]


def test_turn_with_a_near_return_warns_and_clear_turn_does_not():
    assert edge_drive.advisory(view(), 0.0, 1.0)[1] is None
    near = view({90: 0.06})
    assert edge_drive.advisory(near, 0.0, 1.0)[1].startswith("in-place turn not clear")


def test_wrong_forward_angle_moves_the_box():
    box = {d: 0.15 for d in range(170, 191)}
    assert edge_drive.advisory(view(box, forward=0.0), 0.05, 2.0)[1] is None


def test_lidar_angle_is_urdf_nominal_then_record_then_override(tmp_path):
    assert edge_drive.lidar_forward_deg()[0] == PINKY_PRO.lidar_forward_deg == 180.0
    deg, source = edge_drive.lidar_forward_deg("pinky-x", store_root=tmp_path)   # no record yet
    assert deg == 180.0 and "URDF" in source
    deg, source = edge_drive.lidar_forward_deg("pinky-x", 181.8, store_root=tmp_path)
    assert math.isclose(deg, 181.8) and "override" in source
    deg, _ = edge_drive.lidar_forward_deg("pinky-x", 30.0, store_root=tmp_path)    # implausible: refused
    assert deg == 180.0


def test_nudge_moves_even_when_the_advisory_warns(monkeypatch, tmp_path, capsys):
    calls = []

    class FakeCore:
        def call(self, method, path, body=None, raw=False, timeout=3.0):
            calls.append((method, path, body))
            if path == "/sensors/lidar":
                return 200, sample({d: 0.08 for d in range(170, 191)})
            if path == "/vision/front/status":
                return 200, {"sequence": 1}
            if path.startswith("/vision/front/frame"):
                return 200, b"jpg"
            return 200, {}

        def raw_frame(self, timeout=5.0):
            return None

    monkeypatch.setattr(edge_drive.time, "sleep", lambda s: None)
    args = edge_drive.argparse.Namespace(linear=0.05, angular=0.0, seconds=0.3, out=str(tmp_path / "f.jpg"),
                                         device=None, lidar_forward_deg=None)
    edge_drive.cmd_nudge(FakeCore(), args)
    assert "WARN (advisory only" in capsys.readouterr().out
    assert ("POST", "/teleop", {"linear": 0.05, "angular": 0.0}) in calls
    stop = calls.index(("POST", "/teleop", {"linear": 0.0, "angular": 0.0}))
    assert calls[stop + 1] == ("POST", "/mode", {"mode": "IDLE"})
    assert (tmp_path / "f.jpg").read_bytes() == b"jpg"



def test_drive_holds_inside_the_deadman_when_status_reads_are_slow(monkeypatch):
    """Status reads take 0.4 s (loaded Pi): holds still arrive well inside the 1 s deadman,
    and line-follow is switched OFF at the end."""
    import threading
    lock, holds, calls = threading.Lock(), [], []

    class SlowCore:
        def clone(self):
            return self

        def call(self, method, path, body=None, raw=False, timeout=3.0):
            with lock:
                calls.append((method, path, body))
                if path == "/line-follow/hold":
                    holds.append(time.monotonic())
            if path == "/line-follow":
                time.sleep(0.4)
                return 200, {"state": "TRACKING", "reason": "tracking", "linear": 0.035, "angular": 0.0}
            if path == "/line-follow/mode":
                return 200, {"mode": body["mode"], "state": "WAITING", "reason": "no_observation"}
            return 200, {}

    monkeypatch.setattr(edge_drive, "rec_start", lambda core: None)
    monkeypatch.setattr(edge_drive, "rec_stop", lambda core: None)
    edge_drive.cmd_drive(SlowCore(), edge_drive.argparse.Namespace(max_s=1.5))
    gaps = [b - a for a, b in zip(holds, holds[1:])]
    assert len(holds) >= 4 and max(gaps) < 0.6
    assert calls[-1] == ("PUT", "/line-follow/mode", {"mode": "OFF"})


def test_drive_rearms_after_a_link_stall_release_then_gives_up(monkeypatch):
    calls, state = [], {"released": 0}

    class StallCore:
        def clone(self):
            return self

        def call(self, method, path, body=None, raw=False, timeout=3.0):
            calls.append((method, path, body))
            if path == "/line-follow/hold":
                return 409, None
            if path == "/line-follow":
                time.sleep(0.05)
                return 200, {"state": "OFF", "reason": "driver_released", "linear": 0.0, "angular": 0.0}
            if path == "/line-follow/mode":
                return 200, {"mode": body["mode"], "state": "WAITING", "reason": "no_observation"}
            return 200, {}

    monkeypatch.setattr(edge_drive, "rec_start", lambda core: None)
    monkeypatch.setattr(edge_drive, "rec_stop", lambda core: calls.append(("rec", "stop", None)))
    monkeypatch.setattr(edge_drive.time, "sleep", lambda s: None)
    edge_drive.cmd_drive(StallCore(), edge_drive.argparse.Namespace(max_s=5.0, rearm=2))
    arms = [c for c in calls if c[1] == "/line-follow/mode" and c[2]["mode"] == "CAMERA_LINE"]
    assert len(arms) == 3                     # first arm + 2 re-arms, then stop
    assert calls[-2] == ("PUT", "/line-follow/mode", {"mode": "OFF"}) and calls[-1][0] == "rec"
