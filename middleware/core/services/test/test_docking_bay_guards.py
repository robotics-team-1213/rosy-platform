"""Charge bay reverse parking guards (D-1013, panel r1, 2026-11-19): less overshoot at the end, a blind-lateral
budget, a measured-only along, an entry window, off-axis contact, and a LiDAR rear check. Same kinematic harness
as test_docking_bay.py (a bay at the origin, inward axis +x, the robot reverses toward it; tray tip 0.135 behind the axle)."""

from __future__ import annotations

import math
import pytest

from core_features.docking.bay_guards import entry_ok, heading_gate, rear_band_gap, rear_blocked
from core_features.docking.feed import CAMERA_LINE, DockObservationFeed
from core_features.docking.manager import DockingConfig, DockPhase, DockState
from test_docking_bay import DOCKED_ALONG, DT, NECK, a_bay, done

CFG = DockingConfig()
TIP = 0.135


def drive(p, until, *, rear_gap=None, hook=None, max_s=240.0):
    """test_docking_bay.run with a LiDAR rear gap per scan and a per-tick hook; returns the phase order."""
    order, k, t0 = [], 0, p.clock.now
    while p.clock.now - t0 < max_s:
        if k % 4 == 0:
            p.detector.capture()
            p.manager._bay_phases.note_body_scan(None, None, rear_gap(p) if rear_gap else None, p.clock.now)
        if hook:
            hook(p)
        p.manager.tick()
        phase = p.manager.phase.value if p.manager.phase else None
        if not order or order[-1] != phase:
            order.append(phase)
        if until(p.manager):
            break
        p.world.step()
        p.clock.now += DT
        k += 1
    return order


def reasons(p, kind):
    return [(data or {}).get("reason", "") for name, data in p.events if name == kind]


def test_bay_reverse_overshoot_lateral_5cm():
    """A 5 cm start: the gain and the bearing cap keep the swing small and the lateral near zero at the guide neck."""
    p = a_bay()
    p.world.arrival_error = (0.05, 0.0)
    seen = {"peak": 0.0, "neck": None}

    def hook(p):
        x, y, yaw = p.world.pose
        if p.manager.phase is DockPhase.ALIGNING:
            seen["peak"] = max(seen["peak"], abs(math.atan2(math.sin(yaw - math.pi), math.cos(yaw - math.pi))))
            if x < -NECK[0]:
                seen["neck"] = y                 # the last free sample before the 3D guide holds the robot
    p.manager.dock()
    drive(p, done, hook=hook)
    assert p.manager.state is DockState.DOCKED
    assert seen["peak"] < math.radians(15.0)
    assert abs(seen["neck"]) < 0.005


def test_lateral_blind_budget_stops():
    """Only the corridor line in view all the way: the reverse stops inside 0.10 m and re-enters, never drives on."""
    p = a_bay()
    capture = p.detector.capture

    def corridor_only():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ALIGNING:
            p.detector.latest = p.detector.latest.model_copy(update={"lateral_measured": False})
    p.detector.capture = corridor_only
    start = {}

    def hook(p):
        if p.manager.phase is DockPhase.ALIGNING:
            start.setdefault("x", p.world.pose[0])
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.BACKOFF, hook=hook)
    assert p.manager.phase is DockPhase.BACKOFF
    # budget = (entry along - 0.305) + 0.05; the stop adds a frame of delay
    budget = max(0.0, -start["x"] - CFG.bay_line_view_m) + CFG.bay_blind_margin_m
    assert abs(p.world.pose[0] - start["x"]) <= budget + 0.03
    assert any("blind budget" in r for r in reasons(p, "docking.retry"))


def test_normal_entry_not_stopped_by_blind_budget():
    """Corridor line only until the bay line comes into view at 0.305 m (the observer's range): the normal blind
    stretch of the entry run must not trip the budget."""
    p = a_bay()
    capture = p.detector.capture

    def corridor_until_view():
        capture()
        if (p.detector.latest is not None and p.manager.phase is DockPhase.ALIGNING
                and p.world.pose[0] < -CFG.bay_line_view_m):
            p.detector.latest = p.detector.latest.model_copy(update={"lateral_measured": False})
    p.detector.capture = corridor_until_view
    p.manager.dock()
    drive(p, done)
    assert p.manager.state is DockState.DOCKED
    assert not reasons(p, "docking.retry")


def test_unmeasured_along_does_not_shorten_travel_cap():
    """Far from the stop face the observer reports a stand-in along (here 0.10 m, unmeasured): the travel cap and
    the slip check must not use it, or the reverse would settle 12 cm into a 49 cm run."""
    p = a_bay()
    capture = p.detector.capture

    def far_field():
        capture()
        if (p.detector.latest is not None and p.world.pose[0] < -0.30
                and p.manager.phase in (DockPhase.ACQUIRING, DockPhase.ALIGNING)):
            p.detector.latest = p.detector.latest.model_copy(update={"x": 0.10, "along_measured": False})
    p.detector.capture = far_field
    settled = {}

    def hook(p):
        if p.manager.phase is DockPhase.SETTLING:
            settled.setdefault("x", p.world.pose[0])
    p.manager.dock()
    drive(p, done, hook=hook)
    assert p.manager.state is DockState.DOCKED
    assert settled["x"] >= -DOCKED_ALONG - 0.01


def test_feed_carries_along_measured():
    feed = DockObservationFeed()
    seen = {"source": CAMERA_LINE, "visible": True, "stamp": 10.0, "tag_id": None,
            "x": 0.2, "y": 0.01, "yaw": math.pi, "confidence": 0.8}
    assert feed.ingest(seen, received_at=10.2, source_now=10.3)
    assert feed.latest(source=CAMERA_LINE).along_measured is True
    assert feed.ingest(dict(seen, along_measured=False), received_at=10.2, source_now=10.3)
    assert feed.latest(source=CAMERA_LINE).along_measured is False


def test_bay_wide_entry_error_backs_off_not_reverses():
    """8 cm off at the first sight is outside the entry window: no reverse command is ever sent; it backs out and
    starts over from staging (a straight back-off would keep the error), and the same reason twice is a person's call."""
    p = a_bay()
    p.world.arrival_error = (0.08, 0.0)
    p.manager.dock()
    order = drive(p, done)
    assert "backoff" in order and "aligning" not in order, order
    assert not [c for ph, c in p.world.commands if ph is DockPhase.ALIGNING]
    assert any("entry error" in r for r in reasons(p, "docking.retry"))
    assert p.manager.state is DockState.DOCK_FAILED


def test_entry_inside_the_flat_window_aligns():
    p = a_bay()
    p.world.arrival_error = (0.065, math.radians(-8.0))
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.ALIGNING)
    assert p.manager.phase is DockPhase.ALIGNING and not reasons(p, "docking.retry")


def _pinned_off_axis(p):
    """A guide funnel that holds the robot 1.8 cm off the axis near the stop face (the line stays truthful)."""
    step = p.world.step

    def pinned():
        step()
        x, y, yaw = p.world.pose
        if x > -0.20:
            p.world.pose = (x, max(y, 0.018), yaw)
    p.world.step = pinned


def test_contact_off_axis_is_retry():
    p = a_bay()
    _pinned_off_axis(p)
    p.manager.dock()
    seen = []
    order = drive(p, lambda m: seen.append(m.phase) or (m.phase is DockPhase.BACKOFF and DockPhase.ALIGNING in seen))
    assert "settling" not in order, order            # no 20 s voltage wait: it went straight back
    assert reasons(p, "docking.reseat")[0].startswith("bay contact off the line axis")


def test_same_reason_twice_fails_early():
    """The second failure for the same guard reason is a person's call even with max_retries left."""
    p = a_bay(max_retries=3)
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.ACQUIRING)
    bay = p.manager._bay_phases
    bay._guard_fail("contact", "contact off the line axis", p.manager._reseat)
    assert p.manager.state is DockState.DOCKING and p.manager.phase is DockPhase.BACKOFF
    bay._guard_fail("contact", "contact off the line axis", p.manager._reseat)
    assert p.manager.state is DockState.DOCK_FAILED
    assert len(reasons(p, "docking.reseat")) == 1


def test_a_guide_that_keeps_the_robot_off_axis_fails_before_the_retry_budget_is_spent():
    p = a_bay(max_retries=3)
    _pinned_off_axis(p)
    p.manager.dock()
    order = drive(p, done)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "settling" not in order, order
    assert len(reasons(p, "docking.reseat")) < 3


def test_aligning_stops_on_lidar_rear_gap_shorter_than_line():
    """Something stands in the bay 25 cm from the stop face: the LiDAR gap is far shorter than the distance the
    camera says is left, so the reverse never starts."""
    p = a_bay()
    p.manager.dock()
    gap = lambda p: max(0.0, -0.25 - (p.world.pose[0] + TIP))   # noqa: E731 - obstacle at x = -0.25
    drive(p, lambda m: m.phase is DockPhase.BACKOFF, rear_gap=gap)
    assert p.manager.phase is DockPhase.BACKOFF
    assert p.world.pose[0] <= -0.45
    assert any("LiDAR" in r for r in reasons(p, "docking.retry"))


def test_normal_approach_not_stopped_by_rear_gap():
    """The stop face itself is the nearest return: gap == what the camera says is left (minus noise) is normal."""
    p = a_bay()
    p.manager.dock()
    gap = lambda p: max(0.0, -(p.world.pose[0] + TIP)) - 0.03   # noqa: E731 - the stop face at x = 0
    drive(p, done, rear_gap=gap)
    assert p.manager.state is DockState.DOCKED
    assert not reasons(p, "docking.retry")


def test_stale_frame_gate_widens_with_turn_rate():
    assert heading_gate(CFG, 0.0, 0.2) == pytest.approx(CFG.bay_gate_jump_rad)
    assert heading_gate(CFG, 0.3, 0.2) == pytest.approx(CFG.bay_gate_jump_rad + 0.06)
    assert heading_gate(CFG, 0.3, 0.5) == pytest.approx(CFG.bay_gate_jump_rad + 0.3 * CFG.bay_obs_max_age_s)   # age capped
    assert heading_gate(CFG, -0.3, -1.0) == pytest.approx(CFG.bay_gate_jump_rad)      # a future stamp adds nothing


def test_a_frame_older_than_the_age_cap_is_discarded_not_followed():
    """0.4 s old frames (the detector would still pass them at 0.6 s): no evidence, so the coast and scan ladder runs."""
    p = a_bay(max_retries=1)
    capture = p.detector.capture

    def old():
        capture()
        if p.detector.latest is not None and p.manager.phase is DockPhase.ALIGNING:
            p.detector.latest = p.detector.latest.model_copy(update={"at": p.clock() - 0.4})
    p.detector.capture = old
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.BACKOFF)
    assert any("line lost" in r for r in reasons(p, "docking.retry"))


def test_entry_window_is_flat_and_rear_gap_needs_both_values():
    assert entry_ok(CFG, 0.07, math.radians(15)) and not entry_ok(CFG, 0.08, 0.0)
    assert not entry_ok(CFG, 0.0, math.radians(16))
    assert not rear_blocked(CFG, None, 0.4) and not rear_blocked(CFG, 0.1, None)
    assert rear_blocked(CFG, 0.10, 0.40) and not rear_blocked(CFG, 0.10, 0.15)


def test_rear_band_gap_ignores_the_neighbour_beside_the_strip_and_sees_the_obstacle_in_it():
    rear_x = -0.135
    neighbour = [(x / 100.0, 0.031) for x in range(-30, 5)]       # a body just outside the 3 cm strip
    assert rear_band_gap(neighbour, rear_x) is None
    assert rear_band_gap(neighbour + [(-0.30, 0.02)], rear_x) == pytest.approx(0.165)
    assert rear_band_gap([], rear_x) is None
