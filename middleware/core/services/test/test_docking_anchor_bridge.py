"""An in-bay re-dock THROUGH THE BRIDGE with the seat-anchor probe wired (the integration level the unit tests lacked, 2026-11-21 regression report).

A synthetic LiDAR scan is ray-cast from the stored empty-bay reference points at the sim robot's pose and fed to observation.bay_body_scan; the body scan (front/rear gap,
rotation check), the seat gap and every scan request of the dock path then reach the manager through the bridge exactly as on the robot. The matching thread runs inline and
answers with the true pose (the matcher itself is covered elsewhere). The same run is made with the probe idle, with a start-up anchor present and with the probe armed.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from core.bridge import observation
from core_common.protocol.localization import OdomPose
from core_common.protocol.schemas import DockState
from core_common.robot_body import PINKY_PRO as BODY
from core_features.docking import bay_scan_pose
from core_features.docking.bay_scan_pose import BayScanPose
from test_docking_bay import DT, done
from test_docking_bay_scan_pose import SCANS, true_bay_pose, with_reference
from test_docking_bay_zone import a_row

CFG = SimpleNamespace(body_front_x_m=BODY.front_x_m, body_rear_x_m=BODY.rear_x_m, body_half_width_m=BODY.half_width_m, body_rotation_radius_m=BODY.rotation_radius_m,
                      body_lidar_x_m=BODY.lidar_x_m, lidar_forward_deg=180.0, obstacle_body_margin_m=0.02, lidar_self_mask=())
COUNT = 720


def _reference_points():
    view = BODY.scan_view(SCANS["seated"], forward_deg=180.0)
    return list(view.points)


def lidar_scan(points, pose):
    """The scan an empty bay gives at the bay-frame robot pose (x out of the stop face, y, heading): ray-cast from the reference points (nearest per beam)."""
    c, s = math.cos(-pose.heading), math.sin(-pose.heading)
    step = 2.0 * math.pi / COUNT
    ranges = [math.inf] * COUNT
    for px, py in points:
        dx, dy = px - pose.x, py - pose.y
        bx, by = dx * c - dy * s, dx * s + dy * c                       # base_link frame
        sx, sy = bx - BODY.lidar_x_m, by
        angle = math.atan2(sy, sx) + math.pi                            # the scan's angle 0 is the robot's back (forward_deg 180)
        angle = math.atan2(math.sin(angle), math.cos(angle))
        index = int(round((angle + math.pi) / step)) % COUNT
        rng = math.hypot(sx, sy)
        if rng < ranges[index]:
            ranges[index] = rng
    return {"ranges": ranges, "angle_min": -math.pi, "angle_increment": step, "range_min": 0.05, "range_max": 10.0}


class _Inline:
    """threading.Thread that runs its target at once: the bridge's matching thread, made deterministic."""

    def __init__(self, target=None, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _wire(monkeypatch, p):
    monkeypatch.setattr(observation.threading, "Thread", _Inline)
    true = lambda *a, **k: true_bay_pose(p.world)                        # noqa: E731 - every matcher answers with the sim's true pose
    for name in ("locate", "locate_near", "locate_track", "locate_step"):
        monkeypatch.setattr(bay_scan_pose, name, true)
    p.manager._anchor._odom = lambda: OdomPose(x=0.0, y=0.0, yaw=0.0, stamp=1000.0, epoch=0, mono_s=1.0)
    p.manager._anchor._wall = lambda: 1000.0


@pytest.mark.parametrize("mode", ["probe_idle", "startup_anchor_present", "probe_armed", "two_indistinguishable", "only_named_bay_fits"])
def test_an_in_bay_redock_through_the_bridge_docks_with_the_probe_wired(monkeypatch, mode):
    p, row = a_row(start=(-0.157, 0.0, math.pi), others=(), charges=False)    # 10.7 cm out of the stop face, straight in its lane
    with_reference(p)
    p.battery.percent = 100.0
    _wire(monkeypatch, p)
    if mode in ("two_indistinguishable", "only_named_bay_fits"):
        first = p.manager._db.get("bay1")
        other = first.model_copy(deep=True, update={"id": "bay2"})
        if mode == "only_named_bay_fits":
            ref = other.metadata["reference_scan"]
            ref["ranges"] = [1.4] * len(ref["ranges"])
            compared = bay_scan_pose.locate
            def locate(ref_points, live_points):
                if ref_points and all(abs(math.hypot(x - BODY.lidar_x_m, y) - 1.4) < 0.001 for x, y in ref_points):
                    return BayScanPose(x=0.12, y=0., heading=0., inliers=0.95, margin=0.6, median_m=0.002)
                return compared(ref_points, live_points)
            monkeypatch.setattr(bay_scan_pose, "locate", locate)
        p.manager._db.add(other)
    if mode == "startup_anchor_present":
        p.manager._anchor.record("bay1", "startup_probe", {"along_m": 0.0, "lateral_m": 0.0, "heading_deg": 0.0, "inliers": 0.9, "margin": 0.6},
                                 p.manager._anchor.observe())
    mono = {"now": 0.0}
    p.manager._anchor._mono = lambda: mono["now"]
    from core_features.state.manager import StateManager
    state = StateManager("p", clock=lambda: 1000.0, monotonic=lambda: mono["now"])
    p.manager._anchor._odom = state.odom_pose_record
    p.manager._anchor._history = state.odom_window_from
    services = SimpleNamespace(docking=p.manager, line_follow=SimpleNamespace(config=CFG))
    points = _reference_points()
    p.manager.dock("bay1")
    last_event = []
    for k in range(6000):
        mono["now"] = k * DT
        stamp = 1_000_000_000 + int(k * DT * 1e9)
        state.set_odom_pose(*p.world.pose, frame="odom", source_stamp_ns=stamp)
        if k % 2 == 0:
            p.detector.capture()
            scan = lidar_scan(points, true_bay_pose(p.world))
            scan["source_stamp_ns"] = scan["source_now_ns"] = stamp
            observation.bay_body_scan(services, scan, received_at=p.clock.now)
        p.manager.tick()
        event = p.manager.status().last_event
        if event and event not in last_event:
            last_event.append(event)
        if done(p.manager):
            break
        p.world.step()
        p.clock.now += DT
    assert p.manager.state is DockState.DOCKED, (mode, p.manager._error, last_event)
    if mode == "two_indistinguishable":
        assert p.manager.status().anchor is None
    if mode == "only_named_bay_fits":
        assert p.manager.status().anchor is not None and p.manager.status().anchor.dock_id == "bay1"
    assert not any("something" in (e or "") for e in last_event), last_event


def test_a_blocked_anchor_comparison_does_not_delay_the_next_two_operational_seat_results(monkeypatch):
    import threading
    from core_features.docking.dock_anchor import DockAnchorKeeper, SeatComparison, SeatObservation
    from core_features.docking.model import DockingConfig

    keeper = DockAnchorKeeper(DockingConfig(), lambda: None, lambda: None, lambda *a: None)
    first_working, release, finished = threading.Event(), threading.Event(), threading.Event()
    replies = {n: threading.Event() for n in (1, 2, 3)}
    submitted = {n: threading.Event() for n in replies}
    accepted, comparisons = [], []
    fit = BayScanPose(x=0., y=0., heading=0., inliers=0.95, margin=0.6, median_m=0.002)
    body = SimpleNamespace(scan_view=lambda *a, **k: SimpleNamespace(points=((0.0, 0.0),)))
    def compare(*args):
        comparisons.append(1)
        first_working.set()
        release.wait(10)
        return {"C1": fit}
    monkeypatch.setattr(observation, "_match_seat_references", compare)
    monkeypatch.setattr(bay_scan_pose, "locate_track", lambda *args: fit)
    def launch(number):
        def submit(fn):
            accepted.append(keeper.submit_comparison(fn))
            submitted[number].set()
        docking = SimpleNamespace(note_bay_scan_match=lambda *a, **k: replies[number].set(), submit_anchor_comparison=submit,
                                  note_bay_seat_matches=lambda *a: finished.set())
        pose = OdomPose(x=0, y=0, yaw=0, stamp=0, epoch=0)
        frame = SeatComparison(number, "run", "C1", SeatObservation(pose, 0., 1), {"C1": {}})
        observation._match_bay_scan(docking, body, CFG, (), {}, number, track=True, near=(0, 0, 0), seat_frame=frame)
    try:
        launch(1)
        assert replies[1].wait(2) and first_working.wait(2) and submitted[1].wait(2)
        for n in (2, 3):
            launch(n)
            assert replies[n].wait(2) and submitted[n].wait(2)
        assert accepted == [True, False, False] and len(comparisons) == 1
    finally:
        release.set()
    assert finished.wait(2)
