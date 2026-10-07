"""D-468 real-pose corridor containment and local-first recovery policy."""
import math

import pytest

from core_features.line_follow.recovery.lane_return import (
    Boundary, Corridor, Footprint, Pose, PoseTrail, ReturnController, ReturnInput,
)


BODY = Footprint(front=.08, rear=-.08, half_width=.06)
LANE = Corridor(Boundary(0, .10), Boundary(0, -.10), "camera-a")
# Body .02 m over the left boundary: positive departure evidence (D-507 7).
OUT = Corridor(Boundary(0, .04), Boundary(0, -.16), "camera-a")


def pose(t, x=0, y=0, yaw=0, frame="odom"):
    return Pose(t, int(t*1e9), frame, x, y, yaw)


def inp(t, **kwargs):
    values = dict(now=t, pose=pose(t), corridor=LANE, corridor_at=t,
                  front_clear=True, rear_clear=True, turn_clear=True,
                  clearance_at=t, floor_safe=True, authorized=True,
                  linear_limit=.04, angular_limit=.15)
    values.update(kwargs)
    values['corridor_stamp_ns'] = (None if values['corridor_at'] is None
                                  else round(values['corridor_at']*1e9))
    return ReturnInput(**values)


def test_visible_line_does_not_mean_body_is_inside_lane():
    assert LANE.margin(BODY) == pytest.approx(.04)
    crossing = Corridor(Boundary(0, .04), Boundary(0, -.16), "camera-a")
    assert crossing.margin(BODY) == pytest.approx(-.02)


def test_angled_boundary_checks_front_and_rear_corners():
    lane = Corridor(Boundary(1, .10), Boundary(1, -.10), "camera-a")
    assert lane.margin(BODY) < 0


def test_pose_history_invalidates_frame_reset_jump_and_timestamp_replay():
    trail = PoseTrail()
    assert trail.add(pose(1))
    assert trail.add(pose(1.1, .004))
    assert trail.distance == pytest.approx(.004)
    assert not trail.add(pose(1.1, .004))
    assert trail.distance == 0
    assert trail.add(pose(1.2, .008))
    assert not trail.add(pose(1.3, .008, frame="map"))
    assert not trail.add(pose(1.4, 2, frame="map"))


def test_checkpoint_freezes_and_reverse_uses_measured_pose():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2):
        ctl.tick(inp(t))
    crossing = Corridor(Boundary(0, .04), Boundary(0, -.16), "camera-a")
    # A measured .025 m advance with lateral drift, within odom continuity bounds.
    action = ctl.tick(inp(1.3, pose=pose(1.3, .025, .015), corridor=crossing))
    assert action.phase == "departure_stop"
    assert action.linear == 0
    checkpoint = ctl.checkpoint
    action = ctl.tick(inp(1.4, pose=pose(1.4, .025, .015), corridor=crossing))
    assert action.phase == "retrace"
    assert action.linear < 0
    # Standing still for a second must not be counted as having reversed.
    for t in (1.5, 1.6, 1.7):
        action = ctl.tick(inp(t, pose=pose(t, .025, .015), corridor=crossing))
    assert ctl.checkpoint == checkpoint
    assert action.phase == "retrace"


def test_clear_sensor_search_is_attempted_without_checkpoint_before_fleet():
    ctl = ReturnController(BODY)
    assert ctl.tick(inp(1, corridor=OUT)).phase == "departure_stop"
    action = ctl.tick(inp(1.1, corridor=None))
    assert action.phase == "search"
    assert action.angular != 0
    assert not action.fleet_required


@pytest.mark.parametrize("change", [dict(authorized=False), dict(floor_safe=False),
    dict(clearance_at=0), dict(pose=pose(0)), dict(turn_clear=False)])
def test_search_never_moves_when_evidence_or_authority_is_missing(change):
    ctl = ReturnController(BODY)
    ctl.tick(inp(1, corridor=OUT))
    action = ctl.tick(inp(1.1, corridor=None, **change))
    assert action.linear == action.angular == 0


def test_visible_adjacent_parallel_lane_is_not_previous_corridor():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2): ctl.tick(inp(t))
    # A full, centered corridor can be the next parallel lane .20 m away.
    ctl.tick(inp(1.3, pose=pose(1.3, 0, .20)))
    for t in (1.4, 1.5, 1.6):
        action = ctl.tick(inp(t, pose=pose(t, 0, .20)))
    assert action.phase != "tracking"
    assert not action.recovered


def test_return_verifies_several_new_frames_and_geometry_identity():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2): ctl.tick(inp(t))
    ctl.tick(inp(1.3, corridor=OUT, pose=pose(1.3, .03)))
    ctl.tick(inp(1.4, pose=pose(1.4)))
    assert ctl.tick(inp(1.5)).phase == "verify"
    assert ctl.tick(inp(1.5)).phase == "verify"  # duplicate evidence cannot count
    assert ctl.tick(inp(1.6)).phase == "tracking"


def test_nonfinite_sensor_values_are_rejected():
    with pytest.raises(ValueError): Boundary(math.nan, .1)
    with pytest.raises(ValueError): pose(1, x=math.inf)
    with pytest.raises(ValueError): pose(1, frame=True)


def test_curved_retrace_requires_rotation_clearance():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2): ctl.tick(inp(t))
    crossing = Corridor(Boundary(0, .04), Boundary(0, -.16), "camera-a")
    ctl.tick(inp(1.3, pose=pose(1.3, .025, .015), corridor=crossing))
    action = ctl.tick(inp(1.4, pose=pose(1.4, .025, .015), corridor=crossing, turn_clear=False))
    assert action.linear == action.angular == 0


def test_odom_reset_cannot_restore_old_checkpoint_by_returning_to_old_coordinates():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2): ctl.tick(inp(t))
    ctl.tick(inp(1.3, pose=pose(1.3, 2)))
    for t in (1.4, 1.5, 1.6, 1.7):
        action = ctl.tick(inp(t))
    assert not action.recovered
    assert action.phase != "tracking"


def test_no_checkpoint_verification_compares_one_frozen_world_corridor():
    ctl = ReturnController(BODY)
    ctl.tick(inp(1, corridor=OUT))
    for t, y in ((1.1, 0), (1.2, .02), (1.3, .04)):
        action = ctl.tick(inp(t, pose=pose(t, y=y)))
    assert not action.recovered
    assert action.phase == "verify"


def test_replayed_frame_does_not_complete_verification():
    ctl = ReturnController(BODY)
    ctl.tick(inp(1, corridor=OUT))
    ctl.tick(inp(1.1))
    ctl.tick(inp(1.2))
    action = ctl.tick(inp(1.25, corridor_at=1.1))
    assert not action.recovered
    assert action.phase == "verify"


def test_alignment_candidate_times_out_without_measured_yaw_progress():
    ctl = ReturnController(BODY)
    lane = Corridor(Boundary(.2, .13), Boundary(.2, -.13), "camera-a")
    ctl.tick(inp(1, corridor=OUT))
    assert ctl.tick(inp(1.1, corridor=lane)).phase == "align"
    for i in range(1, 22):
        t = 1.1+i*.1
        action = ctl.tick(inp(t, corridor=lane))
    assert action.phase == "search"


def test_initial_checkpoint_requires_consistent_world_corridor():
    ctl = ReturnController(BODY)
    for t, y in ((1., 0), (1.1, .02), (1.2, .04)):
        ctl.tick(inp(t, pose=pose(t, y=y)))
    assert ctl.checkpoint is None


def test_receipt_time_cannot_count_repeated_source_image_as_new_verification():
    ctl = ReturnController(BODY)
    ctl.tick(inp(1., corridor=OUT))
    for t in (1.1,1.2,1.3):
        from dataclasses import replace
        action = ctl.tick(replace(inp(t), corridor_stamp_ns=100000000000))
    assert not action.recovered
    assert action.phase == "verify"


def test_continuity_epoch_change_invalidates_path_even_if_coordinates_do_not_jump():
    from dataclasses import replace
    ctl = ReturnController(BODY)
    for t in (1.,1.1,1.2): ctl.tick(inp(t))
    for t in (1.3,1.4,1.5,1.6):
        action = ctl.tick(replace(inp(t), epoch=1))
    assert not action.recovered
    assert action.phase != "tracking"


# D-507 decision 7: departure opens only on positive evidence (margin + uncertainty < 0).
@pytest.mark.parametrize("change", [dict(corridor=None), dict(corridor_at=.5),
    dict(corridor=Corridor(Boundary(0, .055), Boundary(0, -.055), "camera-a", .01))])
def test_unproven_containment_never_opens_departure(change):
    # Missing, stale, or eroded-negative but geometrically inside (-.005 + .01 >= 0).
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2, 1.3):
        action = ctl.tick(inp(t, **change))
        assert (action.phase, action.reason) == ("tracking", "containment_unknown")
        assert action.linear == action.angular == 0 and not action.fleet_required
    assert ctl.checkpoint is None


def test_body_geometrically_outside_opens_departure_on_the_first_frame():
    ctl = ReturnController(BODY)
    over = Corridor(Boundary(0, .055), Boundary(0, -.055), "camera-a", .004)   # -.005+.004 < 0
    action = ctl.tick(inp(1, corridor=over))
    assert (action.phase, action.reason) == ("departure_stop", "containment_unconfirmed")


def test_unknown_frames_between_contained_frames_do_not_make_a_checkpoint():
    ctl = ReturnController(BODY)
    ctl.tick(inp(1))
    ctl.tick(inp(1.1))
    assert ctl.tick(inp(1.2, corridor=None)).reason == "containment_unknown"
    ctl.tick(inp(1.3))
    ctl.tick(inp(1.4))
    assert ctl.checkpoint is None
    ctl.tick(inp(1.5))
    assert ctl.checkpoint is not None

# D-507 7 revision (2026-10-08 user decision): (2) a pose discontinuity or epoch change while
# following, or (3) a proven-inside lane that is not the checkpointed one, also opens it.
# Each case below is built so that only that one trigger can fire.
def _checkpointed():
    ctl = ReturnController(BODY)
    for t in (1, 1.1, 1.2): ctl.tick(inp(t))
    assert ctl.checkpoint is not None and ctl.phase == "tracking"
    return ctl


def test_pose_jump_while_following_opens_departure_without_lane_evidence():
    ctl = _checkpointed()
    action = ctl.tick(inp(1.3, pose=pose(1.3, 2), corridor=None))
    # Departure opened this tick; with no checkpoint path left the same tick goes to search.
    assert ctl._opened == 1.3 and (action.phase, action.reason) == ("search", "sensor_search")


def test_epoch_change_while_following_opens_departure_without_lane_evidence():
    from dataclasses import replace
    ctl = _checkpointed()
    action = ctl.tick(replace(inp(1.3, corridor=None), epoch=1))
    assert ctl._opened == 1.3 and (action.phase, action.reason) == ("search", "sensor_search")


def test_continuous_drift_into_a_lane_that_is_not_the_checkpointed_one_opens_departure():
    ctl = _checkpointed()
    # Continuous odom (no jump), a centered ready lane, body well inside (margin .04):
    # only "inside but not the checkpointed corridor" (> .015 m off) can open it.
    action = ctl.tick(inp(1.3, pose=pose(1.3, 0, .016)))
    assert (action.phase, action.reason) == ("departure_stop", "containment_unconfirmed")

def test_checkpoint_taken_after_a_jump_is_the_new_reference():
    # Review finding 2: a jump before any checkpoint must not leave the reference invalid
    # forever, or the re-verified lane would read as "not the checkpointed one" (3).
    ctl = ReturnController(BODY)
    assert ctl.tick(inp(1)).reason == "contained"
    assert ctl.tick(inp(1.1, pose=pose(1.1, 2))).phase != "tracking"
    action = None
    for t in (1.2, 1.3, 1.4, 1.5):
        action = ctl.tick(inp(t, pose=pose(t, 2)))
        if action.recovered:
            break
    assert action.recovered and ctl.checkpoint is not None
    for t in (1.6, 1.7):
        action = ctl.tick(inp(t, pose=pose(t, 2)))
        assert (action.phase, action.reason) == ("tracking", "contained")

def test_checkpoint_first_taken_while_tracking_after_a_jump_is_the_new_reference():
    # Same as above, but verification sees an off-centre lane (contained, not "normal"), so
    # the first checkpoint after the jump is taken in tracking, not at verification.
    off = Corridor(Boundary(0, .07), Boundary(0, -.13), "camera-a")
    ctl = ReturnController(BODY)
    ctl.tick(inp(1))
    ctl.tick(inp(1.1, pose=pose(1.1, 2)))
    action = None
    for t in (1.2, 1.3, 1.4, 1.5):
        action = ctl.tick(inp(t, pose=pose(t, 2), corridor=off))
        if action.recovered:
            break
    assert action.recovered and ctl.checkpoint is None
    for t in (1.6, 1.7, 1.8):
        ctl.tick(inp(t, pose=pose(t, 2)))
    assert ctl.checkpoint is not None
    action = ctl.tick(inp(1.9, pose=pose(1.9, 2)))
    assert (action.phase, action.reason) == ("tracking", "contained")
