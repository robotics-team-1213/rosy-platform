"""D-531: route context narrows camera choices without carrying a drive command."""
from core_features.line_follow.route_context import route_context
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig
from test_lane_arc import ArcRig, SEGMENT


def _junction(**changes):
    value = dict(seq=4, state="armed", action="straight", place_id="SE",
                 map_id="track-v1", expires_at=20.0, pivot=0.1,
                 lane_turn=0.0, window=dict(key=(2, "odom"), odometer=1.0,
                                            expect_in=0.5, tol=0.05),
                 exit_segment=None)
    value.update(changes)
    return value


def test_junction_window_moves_with_signed_odom_and_expires():
    result = route_context(_junction(), None, mono_now=10.0, ros_now=100.0,
                           odom_key=(2, "odom"), odometer=1.2)
    assert result.message() == dict(v=1, seq=4, place_id="SE", map_id="track-v1",
                                    stamp_s=100.0, valid_until_s=100.5,
                                    kind="junction", ahead_m=(0.15, 0.25), lane_turn_deg=0.0)
    assert route_context(_junction(), None, mono_now=20.0, ros_now=100.0,
                         odom_key=(2, "odom"), odometer=1.2) is None
    assert route_context(_junction(), None, mono_now=10.0, ros_now=100.0,
                         odom_key=(3, "odom"), odometer=1.2) is None


def test_running_arc_outlives_completed_junction_but_requires_its_odom_key():
    arc = dict(state="running", instruction_seq=4, **{"from": "SE"},
               map_id="track-v1", k=3.0, deadline=11.0, key=(2, "odom"))
    result = route_context(None, arc, mono_now=10.8, ros_now=100.0,
                           odom_key=(2, "odom"), odometer=1.2)
    assert result.message() == dict(v=1, seq=4, place_id="SE", map_id="track-v1",
                                    stamp_s=100.0, valid_until_s=100.2,
                                    kind="ring", curvature_1pm=3.0)
    assert route_context(None, arc, mono_now=10.8, ros_now=100.0,
                         odom_key=(3, "odom"), odometer=1.2) is None
    assert route_context(None, arc, mono_now=11.0, ros_now=100.0,
                         odom_key=(2, "odom"), odometer=1.2) is None


def test_outgoing_ring_curvature_is_not_sent_on_approach_before_arc_opens():
    context = route_context(_junction(exit_segment={"curvature_1pm": 3.0}), None,
                            mono_now=10., ros_now=100., odom_key=(2, "odom"), odometer=1.2)
    assert context.kind == "junction"
    assert context.curvature_1pm is None


def test_off_or_unmapped_instruction_never_yields_a_context():
    assert route_context(_junction(), None, mono_now=10.0, ros_now=100.0,
                         odom_key=(2, "odom"), odometer=1.2, mode="OFF") is None
    assert route_context(_junction(map_id=None), None, mono_now=10.0, ros_now=100.0,
                         odom_key=(2, "odom"), odometer=1.2) is None


def test_bend_pass_and_reacquisition_keep_a_phase_after_approach_window():
    bend = _junction(action="bend", bend_in=0.3, tol=0.05, turn_deg=63.0,
                     window=None, travel=0.9)
    for phase in ("bending", "reacquiring"):
        context = route_context(dict(bend, state=phase), None, mono_now=10.0, ros_now=100.0,
                                odom_key=(2, "odom"), odometer=1.2)
        assert context.kind == "bend" and context.bend_phase == phase
        assert context.ahead_m is None


def test_manager_publishes_only_when_enabled_and_with_fresh_matching_pose():
    class Bus:
        def publish(self, *args, **kwargs):
            pass

    enabled = LineFollowManager(Bus(), clock=lambda: 10.,
                                config=LineFollowConfig(route_context_enabled=True))
    disabled = LineFollowManager(Bus(), clock=lambda: 10.)
    for manager in (enabled, disabled):
        manager.set_mode("CAMERA_LINE")
        manager.observe_return_pose(stamp_ns=10_000_000_000, source_now_ns=10_000_000_000,
                                    frame="odom", x=0., y=0., yaw=0., received_at=10.)
        manager.set_junction("straight", "SE", 2., expect=dict(
            map_id="track-v1", expect_in_m=.5, expect_tol_m=.05,
            pivot_past_line_m=.1, lane_turn_deg=0.))
    assert enabled.route_context(ros_now=100., now=10.).kind == "junction"
    published = enabled.route_context(ros_now=100., now=10.)
    enabled.set_route_context_publication(published, 100.)
    assert enabled.status().route_context.seq == published.seq
    assert enabled.status().route_context_published_at_s == 100.
    enabled.set_route_context_publication(None, 100.1)
    assert enabled.status().route_context is None
    enabled.set_junction("straight", "NW", 2., expect=dict(
        map_id="track-v1", expect_in_m=.5, expect_tol_m=.05,
        pivot_past_line_m=.1, lane_turn_deg=0.))
    assert enabled.route_context(ros_now=100.1, now=10.).seq != published.seq
    assert disabled.route_context(ros_now=100., now=10.) is None
    assert enabled.route_context(ros_now=100., now=10.5) is None
    enabled.set_mode("OFF")
    assert enabled.route_context(ros_now=100., now=10.) is None


def test_open_arc_remembers_the_instruction_sequence_for_ring_context():
    rig = ArcRig(route_context_enabled=True)
    rig.step()
    with rig.m._lock:
        assert rig.m._open_arc(dict(seq=7, place_id="SW", action="left", map_id="lab-a",
                                    exit_segment=dict(SEGMENT)), rig.now) is None
    assert rig.m._arc["instruction_seq"] == 7
    context = rig.m.route_context(ros_now=100., now=rig.now)
    assert (context.kind, context.seq, context.curvature_1pm) == ("ring", 7, SEGMENT["curvature_1pm"])
