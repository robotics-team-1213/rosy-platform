"""Inside the row the pose is TRACKED, not re-found (panel B R26): b8xy C2 round 2, margin 0.21 < 0.40 dropped every TRUE pose of a self-similar bay."""

from __future__ import annotations

from core_common.protocol.schemas import DockState
from core_features.docking.bay_scan_pose import BayScanPose
from core_features.docking.manager import DockPhase
from test_docking_bay_reseat import _dock, run


def _weak_first(p, margin, prior):
    """Global (first acquisition) ALIGNING answers have a weak margin; tracked ones carry the sentinel margin 1.0; everything else is clean."""
    bp = p.manager._bay_phases
    if prior:
        p.manager._seated_dock_id = p.manager._dock.id

    real = bp.tracking
    bp.tracking = lambda: real() and (bp._lp is not None or p.manager.phase is not DockPhase.ALIGNING)    # the first ALIGNING pose is a first acquisition

    def answer(kind, pose, now):
        if bp._req_track:
            return BayScanPose(x=pose.x, y=pose.y, heading=pose.heading, inliers=0.9, margin=1.0, median_m=0.003)
        if kind == "align":
            return BayScanPose(x=pose.x, y=pose.y, heading=pose.heading, inliers=0.9, margin=margin, median_m=0.003)
        return pose
    return answer


def test_a_weak_margin_first_pose_is_accepted_on_the_rear_gap_with_a_prior_then_tracked():
    p = _dock()
    seen = []
    run(p, answer=_weak_first(p, 0.21, prior=True), seen=seen)
    assert p.manager.state is DockState.DOCKED, (p.manager._error, seen)
    assert p.manager._bay_phases.bay_identity == "confirmed"
    assert any(e and e.startswith("first LiDAR pose accepted on the rear gap") for e in seen), seen


def test_without_a_prior_the_weak_first_pose_needs_margin_012_and_is_unconfirmed():
    p = _dock()
    run(p, answer=_weak_first(p, 0.21, prior=False))
    assert p.manager.state is DockState.DOCKED and p.manager._bay_phases.bay_identity == "unconfirmed"
    for margin, words in ((0.08, "ambiguous"), (0.03, "another bay")):
        q = _dock(charges=False)
        run(q, answer=_weak_first(q, margin, prior=margin == 0.08), limit_s=60.0)
        assert q.manager.state is DockState.DOCK_FAILED and words in q.manager._error, (margin, q.manager._error)


def test_a_tracked_request_is_local_and_a_tracked_pose_with_few_inliers_or_off_centre_in_the_rails_is_dropped():
    p = _dock()
    bp = p.manager._bay_phases
    bp._row_pose = (0.12, 0.0, 0.0, p.clock.now, 0.0)
    req = bp._open_request({"points": []}, "align", None)
    assert req[2] == "track" and bp._req_track
    assert bp._track_gate(BayScanPose(x=0.12, y=0.0, heading=0.0, inliers=0.6, margin=1.0, median_m=0.0)).startswith("inliers")
    assert bp._track_gate(BayScanPose(x=0.05, y=0.03, heading=0.0, inliers=0.9, margin=1.0, median_m=0.0)).startswith("lateral")
    assert bp._track_gate(BayScanPose(x=0.12, y=0.04, heading=0.0, inliers=0.9, margin=1.0, median_m=0.0)) is None
    bp._row_pose = (0.12, 0.0, 0.0, p.clock.now - 10.0, 0.0)                    # lost: back to first acquisition (global)
    assert len(bp._open_request({"points": []}, "align", None)) == 2

def test_the_first_acquisition_rule_also_serves_the_zone_entry_and_rowpose_answers():
    p = _dock()
    bp = p.manager._bay_phases
    p.manager._seated_dock_id = p.manager._dock.id

    def weak(kind, pose, now):
        return BayScanPose(x=pose.x, y=pose.y, heading=pose.heading, inliers=0.9, margin=0.21 if not bp._req_track else 1.0, median_m=0.003)
    run(p, answer=weak)
    assert p.manager.state is DockState.DOCKED, p.manager._error          # zone, entry, rowpose and align all had margin 0.21


def test_a_weak_first_answer_with_the_robot_in_the_neighbour_bay_is_refused():
    p = _dock(charges=False)
    bp = p.manager._bay_phases

    def neighbour(kind, pose, now):
        return BayScanPose(x=pose.x, y=pose.y + 0.21, heading=pose.heading, inliers=0.9, margin=0.21, median_m=0.003)
    run(p, answer=neighbour, limit_s=60.0)
    assert p.manager.state is not DockState.DOCKED and bp.bay_identity == "confirmed"


def test_charge_unconfirmed_is_its_own_flag_and_the_seated_prior_is_cleared_on_a_move():
    p = _dock(charges=False)
    p.battery.percent = 100.0
    p.battery.__class__ = type("Unreadable", (type(p.battery),), {"voltage": property(lambda self: None)})        # the voltage is unreadable
    run(p, answer=None)
    assert p.manager.state is DockState.DOCKED and p.manager.status().charge_unconfirmed       # voltage unreadable: still flagged
    assert p.manager._seated_dock_id == p.manager._dock.id
    p.manager._seated_dock_id = "other"
    p.manager._dock_type_for = None
    p.manager._state = DockState.UNDOCKED
    p.manager.dock()
    assert p.manager._seated_dock_id is None