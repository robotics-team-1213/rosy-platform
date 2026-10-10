"""D-573 6 개정 2026-10-10: CORE reports ``line_follow.crosswalk`` with the gate on or off.

null = the body and its D-407 back-off are positively outside every camera crosswalk zone;
a zone object inside/ahead; ``state: unknown`` when CORE cannot know (Fleet D-577 stays closed)."""
from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.model import LineObservation, LineFollowMode
from test_crosswalk_gate import B, BODY, FAR, NEAR, Sim

EDGES = (0.09, -0.09)
#: The camera's nearest seen ground in Sim is observed_x_min_m 0.1 plus the frame's crosswalk along-track
#: bound (Sim 0.02): the body rear and the back-off (recovery_back_m 0.08) must have driven onto it.
TRAVEL = 0.1 + 0.02 - B.rear_x_m + 0.08


def _state(s):
    dumped = s.m.status().model_dump()
    assert "crosswalk" in dumped                       # reported, gate on or off
    return None if dumped["crosswalk"] is None else dumped["crosswalk"]["state"]


def _drive(s, metres):
    start = s.x
    while s.x - start < metres:
        s.frame()


def test_gate_off_unknown_until_the_back_off_ground_was_seen_then_null():
    s = Sim(enabled=False, edges=EDGES)
    s.frame()
    assert s.m.status().crosswalk.reason == "not_watched"
    _drive(s, TRAVEL - 0.03)
    assert _state(s) == "unknown"
    _drive(s, 0.04)
    assert _state(s) is None


def test_no_lane_edges_means_the_camera_never_watched():
    s = Sim(enabled=False)                              # containment without boundaries
    _drive(s, 1.0)
    assert _state(s) == "unknown" and s.m.status().crosswalk.reason == "not_watched"


def test_gate_off_zone_ahead_then_inside_then_null_once_passed():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL)
    s.frame(crosswalk=(s.x + NEAR, s.x + FAR))
    far = s.x + FAR
    assert _state(s) == "ahead"
    while s.x + B.front_x_m < far - (FAR - NEAR) / 2:
        s.frame()
    assert _state(s) == "inside"
    while s.x + B.rear_x_m - 0.08 <= far + 0.10:
        s.frame()
        assert _state(s) in ("inside", None)
    _drive(s, 0.10)
    assert _state(s) is None


def test_stale_perception_is_unknown():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    assert _state(s) is None
    s.t += 0.5                                          # odom keeps coming, camera does not
    s.m.observe_return_pose(stamp_ns=round(s.t * 1e9), source_now_ns=round(s.t * 1e9), frame="odom",
                            x=s.x, y=0.0, yaw=0.0, received_at=s.t)
    assert s.m.status().crosswalk.reason == "perception_stale"


def test_stale_pose_is_unknown():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    s.t += 0.5
    assert s.m.status().crosswalk.reason == "pose_stale"


def _blind(s, metres, *, steps=10, uncertainty=None):
    """Frames the report must not count: lane lost (no containment) or, with uncertainty, an over-limit one."""
    for _ in range(steps):
        s.t += 0.05
        s.x += metres / steps
        s.m.observe_return_pose(stamp_ns=round(s.t * 1e9), source_now_ns=round(s.t * 1e9), frame="odom",
                                x=s.x, y=0.0, yaw=0.0, received_at=s.t)
        containment = None if uncertainty is None else LaneContainmentEvidence.model_validate(dict(
            stamp=s.t, geometry_id="rig", ground_source="CALIBRATED", uncertainty_m=uncertainty,
            crosswalk_uncertainty_m=0.02,
            boundaries=[dict(side=side, slope=0.0, intercept_m=y, observed_x_min_m=0.1, observed_x_max_m=0.6)
                        for side, y in zip(("left", "right"), EDGES)]))
        s.m.observe(LineObservation(LineFollowMode.CAMERA_LINE, s.t, containment is not None,
                                    0.0 if containment is not None else None, 0.9 if containment else 0.0,
                                    containment=containment), received_at=s.t, source_now=s.t)


def test_lane_lost_frames_keep_the_answer_only_while_stationary():
    """A lost lane is fresh perception: standing still, the seen ground still holds."""
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    _blind(s, 0.0)
    assert _state(s) is None
    _blind(s, 0.12)                                     # drove blind past the 0.1 m the camera saw ahead
    assert s.m.status().crosswalk.reason == "not_watched"


def test_over_limit_uncertainty_frames_are_blind():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    _blind(s, 0.12, uncertainty=0.02)
    assert s.m.status().crosswalk.reason == "not_watched"
    _drive(s, 0.03)          # watched again: its span overlaps the last good frame's [0.12, 0.58], no gap
    assert _state(s) is None


def test_a_blind_gap_past_the_last_span_restarts_the_run():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    _blind(s, 0.60, steps=40, uncertainty=0.02)        # past the last good frame's far span end 0.58
    _drive(s, 0.03)
    assert s.m.status().crosswalk.reason == "not_watched"
    _drive(s, TRAVEL)
    assert _state(s) is None


def test_mode_off_is_unknown():
    s = Sim(enabled=False, edges=EDGES)
    _drive(s, TRAVEL + 0.02)
    s.m.set_mode(LineFollowMode.OFF)
    assert _state(s) == "unknown"


def test_gate_on_armed_zone_wins_and_unwatched_is_unknown():
    s = Sim(edges=EDGES)
    s.frame()
    assert _state(s) == "unknown"
    s.frame(crosswalk=(s.x + NEAR, s.x + FAR))
    s.frame()
    assert _state(s) in ("armed", "approaching")


def test_ir_guard_pruning_never_drops_the_reported_zone():
    """D-491 drops a zone once the IR row passes far + margin; the back-off reach is still on it."""
    import test_ir_guard_crosswalk as ir
    r = ir.rig(**BODY)
    t, x = 1.0, 0.0
    while x < TRAVEL + 0.05:
        ir.step(r, t, x, crosswalk_uncertainty=0.02)
        t, x = t + 0.05, x + 0.01
    ir.step(r, t, x, crosswalk=(0.15, 0.27), crosswalk_uncertainty=0.02)
    far = x + 0.27
    m = r[1]
    states = []
    while x < far + 0.5:
        t, x = t + 0.05, x + 0.01
        ir.step(r, t, x, crosswalk_uncertainty=0.02)
        cw = m.status().crosswalk
        states.append((x, None if cw is None else cw.state))
    assert not m._crosswalks._zones                     # D-491 itself dropped it
    reach = (0.08 - B.rear_x_m)
    assert all(state == "inside" for px, state in states if far - 0.10 <= px and px - reach <= far)
    assert states[-1][1] is None


# ---- D-573 6 개정 (review 2026-10-10): crosswalk along-track bound, crosswalk_uncertainty_m ----

def test_missing_crosswalk_bound_is_unadmittable():
    """Today's perception does not state it: the detector's along-track error is unknown."""
    s = Sim(enabled=False, edges=EDGES, xw_u=None)
    _drive(s, 1.0)
    assert s.m.status().crosswalk.reason == "camera_crosswalk_unadmittable"


def test_crosswalk_bound_over_the_config_bound_is_unadmittable():
    s = Sim(enabled=False, edges=EDGES, xw_u=0.059)                # over crosswalk_max_uncertainty_m 0.058
    _drive(s, 1.0)
    assert s.m.status().crosswalk.reason == "camera_crosswalk_unadmittable"


def test_field_like_frames_are_never_null():
    """9dfk today: lane lateral bound 0.024 m (> D-491 0.015) with a 0.024 m along-track bound."""
    s = Sim(enabled=False, edges=EDGES, xw_u=0.024, lat_u=0.024)
    states = []
    for _ in range(60):
        _drive(s, 0.02)
        states.append(_state(s))
    assert None not in states


def _passed(xw_u):
    """Drive past a zone until the back-off reach is 0.03 m beyond its far edge plus the small-bound margin."""
    s = Sim(enabled=False, edges=EDGES, xw_u=xw_u, crosswalk_max_uncertainty_m=0.2)
    _drive(s, 0.40)
    s.frame(crosswalk=(s.x + NEAR, s.x + FAR))
    far = s.x + FAR
    reach = (B.rear_x_m * -1 + 0.08 + B.half_width_m) # > hypot(rear + back, half width)
    while s.x < far + reach + 0.03 + 0.05 * FAR + 0.005 + 0.05 * 0.6:
        s.frame()
    return _state(s)


def test_zone_margin_grows_with_the_crosswalk_bound():
    assert _passed(0.005) is None
    assert _passed(0.10) == "inside"
