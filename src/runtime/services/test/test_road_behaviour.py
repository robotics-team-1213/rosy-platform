"""D-384 decisions 2 and 4: road-behaviour state machine (ROS-free, deterministic).

A library CORE traffic_policy/line_follow may import (D-2, D-151): it returns a speed
cap and a branch choice, never a command.
"""

import dataclasses
import inspect
from pathlib import Path

import pytest

from core_features.line_follow.model import LineFollowConfig
from core_features.road_behaviour import (
    EVENT_OBSTACLE_HOLD,
    BehaviourInputs,
    BehaviourMemory,
    BehaviourOutput,
    BehaviourParams,
    BehaviourState as S,
    CorridorObstacle,
    JunctionAhead,
    JunctionRobot,
    LeadRobot,
    RoadBehaviour,
    RoadLevel,
    RoadStateSample,
    Stamped,
    TurnProgress,
    choose_branch,
    render_transition_table_markdown,
    required_inputs,
    step_behaviour,
    transition_table,
)
import core_features.road_behaviour.machine as machine_module

PD = BehaviourParams()                               # default: junction logic off
P = BehaviourParams(junction_logic_enabled=True)     # junction states under test
ALL_BRANCHES = frozenset({"left", "straight", "right"})
DOC = (Path(__file__).resolve().parents[4] / "docs" / "plans"
       / "2026-10-01-road-behaviour-transition-table.md")
JN = JunctionAhead(distance_m=0.5, junction_id="J1", branches=ALL_BRANCHES)


def fresh(value, now):
    return Stamped(value, now)


def inputs(now=10.0, *, level=RoadLevel.TRACK, obstacles=(), lead=None, junction=None,
           stop_line=None, route=None, pedestrian=False, robots=(), grant=None, turn=None,
           core_cap=None, omit=()):
    """Every input fresh at `now`; `omit` removes named inputs (unknown)."""
    fields = dict(
        road_state=fresh(RoadStateSample(level, 0.0, 0.0), now),
        obstacles=fresh(tuple(obstacles), now),
        lead=None if lead is None else fresh(lead, now),
        junction=fresh(junction, now),
        stop_line_distance=None if stop_line is None else fresh(stop_line, now),
        route_direction=None if route is None else fresh(route, now),
        pedestrian_at_crosswalk=None if pedestrian is None else fresh(pedestrian, now),
        other_robots=fresh(tuple(robots), now),
        fleet_grant=None if grant is None else fresh(grant, now),
        turn=None if turn is None else fresh(turn, now),
    )
    for name in omit:
        fields[name] = None
    return BehaviourInputs(now=now, core_speed_cap_mps=core_cap, **fields)


def at(state, now=10.0, **extra):
    base = dict(state=state, entered_at=now, arrived_at=None, path_choice=None,
                blocked_since=None, blocked_reported=False)
    base.update(extra)
    return BehaviourMemory(**base)


def run(memory, inp, params=P):
    return step_behaviour(memory, inp, params)


def static(range_m):
    return CorridorObstacle(range_m=range_m, bearing_rad=0.0, closing_speed_mps=0.0,
                            is_moving=False)


def moving(range_m, closing=0.0):
    return CorridorObstacle(range_m=range_m, bearing_rad=0.0, closing_speed_mps=closing,
                            is_moving=True)


def robot(rid="R2", arrival=9.0, side="left", inside=False, intent=None, width=None):
    return JunctionRobot(robot_id=rid, arrival_time=arrival, relative_side=side,
                         in_intersection=inside, intended_direction=intent, road_width_m=width)


TURN = TurnProgress(travelled_m=0.1, arc_length_m=0.5, target_lane_acquired=False)


# --- params -----------------------------------------------------------------------------

def test_params_match_adr_numbers_at_operating_point():
    assert (PD.v_cruise, PD.d0, PD.tau, PD.d_jn, PD.v_app) == (0.08, 0.25, 1.5, 0.6, 0.05)
    assert (PD.d_stop_min, PD.d_stop_max, PD.t_stop, PD.v_creep, PD.t_clear, PD.t_tie,
            PD.t_stale, PD.arc_timeout_factor) == (0.15, 0.22, 1.0, 0.03, 1.0, 0.5, 0.3, 1.3)
    assert 0.03 <= PD.v_creep <= PD.v_app <= PD.v_cruise <= 0.08
    assert PD.corridor_length_m == pytest.approx(0.25 + 1.5 * 0.08)
    assert PD.junction_logic_enabled is False


def test_escalation_matches_line_follow_config():
    assert PD.obstacle_escalate_s == LineFollowConfig().obstacle_escalate_s == 5.0
    assert EVENT_OBSTACLE_HOLD == "nav.line_obstacle_hold"


def test_params_reject_time_gap_below_iso_minimum():
    with pytest.raises(ValueError):
        BehaviourParams(tau=0.79)
    BehaviourParams(tau=0.8)


@pytest.mark.parametrize("bad", [dict(d_stop_min=0.25), dict(v_creep=0.06),
                                 dict(v_cruise=float("nan")), dict(slow_factor=0.0)])
def test_params_reject_inconsistent_values(bad):
    with pytest.raises(ValueError):
        BehaviourParams(**bad)


# --- CORE cap --------------------------------------------------------------------------

@pytest.mark.parametrize("core_cap,cap", [(None, 0.08), (0.05, 0.05), (0.2, 0.08), (0.0, 0.0),
                                          (-1.0, 0.0)])
def test_speed_cap_never_exceeds_core_cap(core_cap, cap):
    _, out = run(at(S.LANE_FOLLOW), inputs(core_cap=core_cap), PD)
    assert out.speed_cap_mps == pytest.approx(cap)


# --- stale / missing inputs -> FAULT ------------------------------------------------------

@pytest.mark.parametrize("name", ["road_state", "obstacles"])
def test_lane_follow_missing_required_input_faults(name):
    _, out = run(at(S.LANE_FOLLOW), inputs(omit=(name,)), PD)
    assert out.state is S.FAULT and out.speed_cap_mps == 0.0
    assert name in out.reason


def test_junction_input_required_only_when_junction_logic_enabled():
    _, out = run(at(S.LANE_FOLLOW), inputs(omit=("junction",)), PD)
    assert out.state is S.LANE_FOLLOW
    _, out = run(at(S.LANE_FOLLOW), inputs(omit=("junction",)), P)
    assert out.state is S.FAULT and "junction" in out.reason


def test_stale_boundary_is_inclusive_at_t_stale():
    params = BehaviourParams(t_stale=0.25)        # binary-exact boundary: 10.0 - 9.75
    base = inputs(10.0)
    ok = dataclasses.replace(base, road_state=Stamped(base.road_state.value, 9.75))
    assert run(at(S.LANE_FOLLOW), ok, params)[1].state is S.LANE_FOLLOW
    bad = dataclasses.replace(base, road_state=Stamped(base.road_state.value, 9.7499))
    _, out = run(at(S.LANE_FOLLOW), bad, params)
    assert out.state is S.FAULT and out.speed_cap_mps == 0.0


def test_future_stamp_is_stale():
    bad = dataclasses.replace(inputs(10.0), obstacles=Stamped((), 10.1))
    assert run(at(S.LANE_FOLLOW), bad)[1].state is S.FAULT


def test_required_inputs_are_listed_for_every_state():
    for state in S:
        assert isinstance(required_inputs(state, True), tuple)
    assert required_inputs(S.FAULT, True) == ()
    assert "junction" not in required_inputs(S.LANE_FOLLOW, False)
    assert "stop_line_distance" in required_inputs(S.APPROACH, True)
    assert "pedestrian_at_crosswalk" in required_inputs(S.YIELD_CHECK, True)
    assert "turn" in required_inputs(S.CROSS, True)
    assert "road_state" not in required_inputs(S.CROSS, True)


@pytest.mark.parametrize("state", [s for s in S if s is not S.FAULT])
def test_every_state_faults_on_its_missing_required_inputs(state):
    for name in required_inputs(state, True):
        _, out = run(at(state, arrived_at=10.0, path_choice="right"),
                     inputs(junction=JN, stop_line=0.5, turn=TURN, omit=(name,)))
        assert out.state is S.FAULT and out.speed_cap_mps == 0.0, (state, name)


def test_fault_stays_until_lane_inputs_fresh_and_track():
    assert run(at(S.FAULT), inputs(level=RoadLevel.COAST))[1].state is S.FAULT
    assert run(at(S.FAULT), inputs(omit=("obstacles",)))[1].state is S.FAULT
    _, out = run(at(S.FAULT), inputs(level=RoadLevel.TRACK), PD)
    assert out.state is S.LANE_FOLLOW and out.speed_cap_mps == PD.v_cruise


def test_fault_clears_junction_memory():
    mem, _ = run(at(S.CREEP, arrived_at=9.0, path_choice="left"),
                 inputs(junction=JN, omit=("other_robots",)))
    assert mem.state is S.FAULT and mem.path_choice is None and mem.arrived_at is None


# --- road_state levels --------------------------------------------------------------------

@pytest.mark.parametrize("level,cap", [
    (RoadLevel.TRACK, 0.08), (RoadLevel.COAST, 0.08), (RoadLevel.SLOW, 0.04),
    (RoadLevel.STOP, 0.0), ("SLOW", 0.04)])
def test_road_level_caps_speed(level, cap):
    _, out = run(at(S.LANE_FOLLOW), inputs(level=level), PD)
    assert out.state is S.LANE_FOLLOW
    assert out.speed_cap_mps == pytest.approx(cap)


def test_unknown_road_level_faults():
    _, out = run(at(S.LANE_FOLLOW), inputs(level="LOST"), PD)
    assert out.state is S.FAULT


# --- corridor obstacles -------------------------------------------------------------------

def test_static_obstacle_in_corridor_holds():
    _, out = run(at(S.LANE_FOLLOW), inputs(obstacles=[static(0.37)]), PD)
    assert out.state is S.HOLD and out.speed_cap_mps == 0.0 and out.path_choice is None


def test_static_obstacle_beyond_corridor_ignored():
    assert run(at(S.LANE_FOLLOW), inputs(obstacles=[static(0.38)]), PD)[1].state is S.LANE_FOLLOW


def test_hold_release_has_hysteresis():
    assert run(at(S.HOLD), inputs(obstacles=[static(0.41)]), PD)[1].state is S.HOLD
    _, out = run(at(S.HOLD), inputs(obstacles=[static(0.43)]), PD)
    assert out.state is S.LANE_FOLLOW and out.speed_cap_mps == PD.v_cruise


def test_moving_lead_follows_with_gap_policy():
    _, out = run(at(S.LANE_FOLLOW), inputs(obstacles=[moving(0.31)]), PD)
    assert out.state is S.FOLLOW
    assert out.speed_cap_mps == pytest.approx((0.31 - 0.25) / 1.5)


def test_follow_cap_is_zero_inside_d0_and_capped_at_cruise():
    _, out = run(at(S.FOLLOW), inputs(obstacles=[moving(0.20)]), PD)
    assert out.state is S.FOLLOW and out.speed_cap_mps == 0.0
    _, out = run(at(S.FOLLOW), inputs(obstacles=[moving(0.37)]), PD)
    assert out.speed_cap_mps == pytest.approx(0.08)


def test_follow_ends_when_lead_leaves_corridor():
    assert run(at(S.FOLLOW), inputs(obstacles=[moving(0.5)]), PD)[1].state is S.LANE_FOLLOW


def test_lead_robot_input_counts_as_moving_lead():
    _, out = run(at(S.LANE_FOLLOW), inputs(lead=LeadRobot(gap_m=0.34, speed_mps=0.05)), PD)
    assert out.state is S.FOLLOW and out.speed_cap_mps == pytest.approx(0.06)


def test_stopped_lead_robot_holds():
    _, out = run(at(S.LANE_FOLLOW), inputs(lead=LeadRobot(gap_m=0.34, speed_mps=0.0)), PD)
    assert out.state is S.HOLD


def test_oncoming_mover_holds_instead_of_following():
    _, out = run(at(S.LANE_FOLLOW), inputs(obstacles=[moving(0.35, closing=0.2)]), PD)
    assert out.state is S.HOLD and out.speed_cap_mps == 0.0


def test_lead_stops_moving_follow_becomes_hold():
    assert run(at(S.FOLLOW), inputs(obstacles=[static(0.3)]), PD)[1].state is S.HOLD


def test_obstacle_never_overtakes():
    mem = at(S.LANE_FOLLOW)
    for k in range(200):
        mem, out = run(mem, inputs(10.0 + k * 0.1, obstacles=[static(0.3)]), PD)
        assert (out.state, out.path_choice, out.speed_cap_mps) == (S.HOLD, None, 0.0)


# --- obstacle escalation (line_follow semantics) ------------------------------------------

def test_obstacle_hold_escalates_exactly_once():
    mem, events = at(S.LANE_FOLLOW), []
    for k in range(300):
        mem, out = run(mem, inputs(10.0 + k * 0.1, obstacles=[static(0.3)]), PD)
        events.extend((10.0 + k * 0.1, e) for e in out.events)
    assert [e for _, e in events] == [EVENT_OBSTACLE_HOLD]
    assert events[0][0] >= 15.0 - 1e-9


def test_obstacle_hold_escalates_at_exactly_escalate_s():
    mem, _ = run(at(S.LANE_FOLLOW), inputs(10.0, obstacles=[static(0.3)]), PD)
    mem, out = run(mem, inputs(14.99, obstacles=[static(0.3)]), PD)
    assert out.events == ()
    mem, out = run(mem, inputs(15.0, obstacles=[static(0.3)]), PD)
    assert out.events == (EVENT_OBSTACLE_HOLD,)


def test_obstacle_hold_rearms_after_clear():
    mem, _ = run(at(S.LANE_FOLLOW), inputs(10.0, obstacles=[static(0.3)]), PD)
    mem, out = run(mem, inputs(15.5, obstacles=[static(0.3)]), PD)
    assert out.events == (EVENT_OBSTACLE_HOLD,)
    mem, out = run(mem, inputs(16.0), PD)
    assert out.state is S.LANE_FOLLOW and mem.blocked_since is None
    mem, _ = run(mem, inputs(17.0, obstacles=[static(0.3)]), PD)
    mem, out = run(mem, inputs(22.5, obstacles=[static(0.3)]), PD)
    assert out.events == (EVENT_OBSTACLE_HOLD,)


def test_pedestrian_wait_never_escalates():
    mem = at(S.YIELD_CHECK, arrived_at=0.0)
    for k in range(300):
        mem, out = run(mem, inputs(10.0 + k * 0.1, junction=JN, pedestrian=True))
        assert out.events == ()


# --- junction gating (logic off by default) -----------------------------------------------

def test_junction_logic_off_detected_junction_holds_unsupported():
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=JN, stop_line=0.5, route="right"), PD)
    assert out.state is S.HOLD and out.speed_cap_mps == 0.0
    assert out.reason == "junction_unsupported" and out.path_choice is None


def test_junction_logic_off_far_junction_keeps_lane():
    jn = dataclasses.replace(JN, distance_m=0.61)
    assert run(at(S.LANE_FOLLOW), inputs(junction=jn), PD)[1].state is S.LANE_FOLLOW


def test_junction_unsupported_hold_clears_when_junction_gone():
    assert run(at(S.HOLD), inputs(junction=None), PD)[1].state is S.LANE_FOLLOW


def test_junction_logic_off_never_enters_junction_states_from_memory():
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inputs(junction=JN), PD)
    assert out.state is S.HOLD and out.reason == "junction_unsupported"


def test_junction_logic_on_without_stop_line_holds_unsupported():
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=JN), P)
    assert out.state is S.HOLD and out.reason == "junction_unsupported"


def test_junction_unsupported_is_not_an_obstacle_escalation():
    mem = at(S.LANE_FOLLOW)
    for k in range(100):
        mem, out = run(mem, inputs(10.0 + k * 0.1, junction=JN), PD)
        assert out.events == ()


# --- junction: approach and stop (logic on) -----------------------------------------------

def test_junction_beyond_d_jn_keeps_lane_follow():
    jn = dataclasses.replace(JN, distance_m=0.61)
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=jn, stop_line=0.8))
    assert out.state is S.LANE_FOLLOW and out.path_choice is None


def test_junction_at_d_jn_starts_approach_at_v_app():
    jn = dataclasses.replace(JN, distance_m=0.6)
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=jn, stop_line=0.6))
    assert out.state is S.APPROACH and out.speed_cap_mps == pytest.approx(0.05)


def test_static_obstacle_beats_junction_approach():
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=JN, stop_line=0.5, obstacles=[static(0.3)]))
    assert out.state is S.HOLD and out.reason == "obstacle_ahead"


def test_hold_clears_into_approach_when_junction_close():
    assert run(at(S.HOLD), inputs(junction=JN, stop_line=0.5))[1].state is S.APPROACH


def test_approach_follows_moving_lead_below_v_app():
    _, out = run(at(S.APPROACH), inputs(junction=JN, stop_line=0.5, obstacles=[moving(0.28)]))
    assert out.state is S.APPROACH and out.speed_cap_mps == pytest.approx(0.02)


def test_approach_static_obstacle_stops_and_counts_hold():
    mem, out = run(at(S.APPROACH), inputs(junction=JN, stop_line=0.5, obstacles=[static(0.3)]))
    assert out.state is S.APPROACH and out.speed_cap_mps == 0.0
    assert mem.blocked_since == 10.0


def test_approach_continues_above_stop_window():
    assert run(at(S.APPROACH), inputs(junction=JN, stop_line=0.2201))[1].state is S.APPROACH


def test_approach_stops_at_window_upper_edge():
    mem, out = run(at(S.APPROACH), inputs(junction=JN, stop_line=0.22))
    assert out.state is S.STOP_AT_LINE and out.speed_cap_mps == 0.0
    assert mem.arrived_at == 10.0 and out.events == ()


def test_approach_overshoot_below_window_stops_with_event():
    _, out = run(at(S.APPROACH), inputs(junction=JN, stop_line=0.149))
    assert out.state is S.STOP_AT_LINE and out.events == ("nav.road_stop_line_overshoot",)


def test_approach_junction_gone_returns_to_lane():
    assert run(at(S.APPROACH), inputs(junction=None, stop_line=0.5))[1].state is S.LANE_FOLLOW


def test_every_junction_is_all_way_stop_even_with_grant_and_no_traffic():
    _, out = run(at(S.APPROACH), inputs(junction=JN, stop_line=0.2, grant=True))
    assert out.state is S.STOP_AT_LINE and out.speed_cap_mps == 0.0


def test_stop_at_line_waits_t_stop():
    mem = at(S.STOP_AT_LINE, now=10.0, arrived_at=10.0)
    _, out = run(mem, inputs(10.99, junction=JN))
    assert out.state is S.STOP_AT_LINE and out.speed_cap_mps == 0.0
    _, out = run(mem, inputs(11.0, junction=JN))
    assert out.state is S.YIELD_CHECK and out.speed_cap_mps == 0.0


def test_junction_lost_mid_stop_faults():
    _, out = run(at(S.STOP_AT_LINE, arrived_at=10.0), inputs(10.5, junction=None))
    assert out.state is S.FAULT


# --- branch choice ------------------------------------------------------------------------

def test_branch_route_wins():
    assert choose_branch("left", ALL_BRANCHES) == ("left", "route")


def test_branch_no_route_prefers_right():
    assert choose_branch(None, ALL_BRANCHES) == ("right", "keep_right")


def test_branch_right_unavailable_prefers_straight_then_left():
    assert choose_branch(None, frozenset({"left", "straight"})) == ("straight", "no_right_straight")
    assert choose_branch(None, frozenset({"left"})) == ("left", "only_left")


def test_branch_none_available_holds():
    assert choose_branch(None, frozenset()) == (None, "no_branch")


def test_branch_route_unavailable_holds_not_guesses():
    assert choose_branch("left", frozenset({"right"})) == (None, "route_branch_unavailable")


def test_junction_no_route_goes_right():
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inputs(junction=JN))
    assert out.path_choice == "right" and out.state is S.CREEP


def test_junction_right_unavailable_goes_straight():
    jn = dataclasses.replace(JN, branches=frozenset({"left", "straight"}))
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inputs(junction=jn))
    assert out.path_choice == "straight" and out.state is S.CREEP


def test_junction_without_branch_waits():
    jn = dataclasses.replace(JN, branches=frozenset())
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inputs(junction=jn))
    assert out.state is S.YIELD_CHECK and out.speed_cap_mps == 0.0
    assert out.path_choice is None and out.reason == "no_branch"


def test_stale_route_waits_instead_of_defaulting_right():
    inp = dataclasses.replace(inputs(10.0, junction=JN), route_direction=Stamped("left", 9.0))
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inp)
    assert out.state is S.YIELD_CHECK and out.path_choice is None and out.reason == "route_stale"


def test_path_choice_shown_from_approach():
    _, out = run(at(S.LANE_FOLLOW), inputs(junction=JN, stop_line=0.5, route="left"))
    assert out.state is S.APPROACH and out.path_choice == "left"


# --- right of way (§26) -------------------------------------------------------------------

def yield_step(robots, route=None, arrived=9.0, grant=None, junction=JN, pedestrian=False,
               obstacles=()):
    return run(at(S.YIELD_CHECK, arrived_at=arrived),
               inputs(junction=junction, robots=robots, route=route, grant=grant,
                      pedestrian=pedestrian, obstacles=obstacles))


def test_robot_already_in_intersection_waits():
    _, out = yield_step([robot(arrival=20.0, inside=True)])
    assert out.state is S.YIELD_CHECK and out.reason == "yield:R2:in_intersection"


def test_simultaneous_arrival_yields_to_right():
    _, out = yield_step([robot(arrival=9.5, side="right")])
    assert out.state is S.YIELD_CHECK and out.reason == "yield:R2:right_hand"


def test_simultaneous_arrival_robot_on_left_yields_to_me():
    assert yield_step([robot(arrival=9.5, side="left")])[1].state is S.CREEP


def test_tie_window_boundary():
    assert yield_step([robot(arrival=9.5, side="right")])[1].state is S.YIELD_CHECK
    assert yield_step([robot(arrival=9.5001, side="right")])[1].state is S.CREEP


def test_earlier_arrival_goes_first():
    _, out = yield_step([robot(arrival=8.4, side="left")])
    assert out.reason == "yield:R2:arrived_first"


def test_wider_road_has_priority_when_known():
    jn = dataclasses.replace(JN, road_width_m=0.3)
    _, out = yield_step([robot(arrival=9.9, side="left", width=0.5)], junction=jn)
    assert out.reason == "yield:R2:wider_road"
    assert yield_step([robot(arrival=8.0, side="right", width=0.2)], junction=jn)[1].state is S.CREEP


def test_left_turn_yields_to_opposite_straight_or_unknown():
    _, out = yield_step([robot(arrival=9.2, side="opposite", intent="straight")], route="left")
    assert out.reason == "yield:R2:left_turn_yields"
    assert yield_step([robot(arrival=9.2, side="opposite")], route="left")[1].state is S.YIELD_CHECK


def test_opposite_left_turns_do_not_conflict():
    _, out = yield_step([robot(arrival=9.2, side="opposite", intent="left")], route="left")
    assert out.state is S.CREEP


def test_straight_does_not_yield_to_opposite():
    _, out = yield_step([robot(arrival=9.2, side="opposite", intent="straight")], route="straight")
    assert out.state is S.CREEP


# --- pedestrian (§27) ---------------------------------------------------------------------

def test_pedestrian_stops_and_is_never_timed_out():
    mem = at(S.YIELD_CHECK, arrived_at=0.0)
    for k in range(1000):
        mem, out = run(mem, inputs(10.0 + k, junction=JN, pedestrian=True, grant=True))
        assert (out.state, out.speed_cap_mps, out.reason) == (
            S.YIELD_CHECK, 0.0, "pedestrian_at_crosswalk")


def test_pedestrian_stops_lane_follow_too():
    _, out = run(at(S.LANE_FOLLOW), inputs(pedestrian=True), PD)
    assert out.speed_cap_mps == 0.0 and out.reason == "pedestrian_at_crosswalk"


def test_pedestrian_during_creep_returns_to_yield_check():
    _, out = run(at(S.CREEP, arrived_at=9.0), inputs(junction=JN, pedestrian=True))
    assert out.state is S.YIELD_CHECK and out.speed_cap_mps == 0.0


def test_pedestrian_during_cross_stops_in_place():
    _, out = run(at(S.CROSS, path_choice="right"), inputs(pedestrian=True, turn=TURN))
    assert out.state is S.CROSS and out.speed_cap_mps == 0.0


# --- Fleet grant --------------------------------------------------------------------------

def test_fleet_grant_true_overrides_local_ordering():
    assert yield_step([robot(arrival=9.5, side="right")], grant=True)[1].state is S.CREEP


def test_fleet_grant_false_overrides_local_go():
    _, out = yield_step([], grant=False)
    assert out.state is S.YIELD_CHECK and out.reason == "fleet_grant_wait"


def test_fleet_grant_never_overrides_obstacle_or_pedestrian_or_occupied():
    assert yield_step([], grant=True, pedestrian=True)[1].state is S.YIELD_CHECK
    _, out = yield_step([], grant=True, obstacles=[static(0.3)])
    assert out.state is S.YIELD_CHECK and out.reason == "obstacle_ahead"
    assert yield_step([robot(inside=True)], grant=True)[1].state is S.YIELD_CHECK


def test_stale_fleet_grant_waits():
    inp = dataclasses.replace(inputs(10.0, junction=JN), fleet_grant=Stamped(True, 9.0))
    _, out = run(at(S.YIELD_CHECK, arrived_at=9.0), inp)
    assert out.state is S.YIELD_CHECK and out.reason == "fleet_grant_stale"


# --- creep and cross ----------------------------------------------------------------------

def test_creep_speed_and_clearance_time():
    mem = at(S.CREEP, now=10.0, arrived_at=9.0, path_choice="right")
    _, out = run(mem, inputs(10.99, junction=JN))
    assert out.state is S.CREEP and out.speed_cap_mps == pytest.approx(0.03)
    mem2, out = run(mem, inputs(11.0, junction=JN))
    assert out.state is S.CROSS and mem2.path_choice == "right"


def test_creep_robot_enters_intersection_returns_to_yield():
    _, out = run(at(S.CREEP, arrived_at=9.0), inputs(junction=JN, robots=[robot(inside=True)]))
    assert out.state is S.YIELD_CHECK


def test_cross_speed_and_exit_on_target_lane():
    _, out = run(at(S.CROSS, path_choice="left"), inputs(turn=TURN))
    assert out.state is S.CROSS and out.path_choice == "left"
    assert out.speed_cap_mps == pytest.approx(P.v_cross)
    done = dataclasses.replace(TURN, target_lane_acquired=True)
    mem, out = run(at(S.CROSS, path_choice="left"), inputs(turn=done))
    assert out.state is S.LANE_FOLLOW and mem.path_choice is None


def test_cross_ignores_road_state_level():
    _, out = run(at(S.CROSS, path_choice="left"),
                 inputs(level=RoadLevel.STOP, turn=TURN, omit=("junction",)))
    assert out.state is S.CROSS and out.speed_cap_mps > 0


def test_cross_arc_timeout_boundary():
    turn = dataclasses.replace(TURN, travelled_m=0.65)
    assert run(at(S.CROSS, path_choice="left"), inputs(turn=turn))[1].state is S.CROSS
    late = dataclasses.replace(TURN, travelled_m=0.6501)
    _, out = run(at(S.CROSS, path_choice="left"), inputs(turn=late))
    assert out.state is S.FAULT and out.speed_cap_mps == 0.0
    assert out.events == ("nav.road_turn_timeout",)


def test_cross_static_obstacle_stops_without_overtaking():
    _, out = run(at(S.CROSS, path_choice="left"), inputs(turn=TURN, obstacles=[static(0.3)]))
    assert (out.state, out.speed_cap_mps, out.path_choice) == (S.CROSS, 0.0, "left")


# --- whole run, determinism, output contract ----------------------------------------------

def _scenario():
    frames, t = [], 0.0
    for dist in (1.0, 0.8, 0.6, 0.4, 0.3, 0.2):
        frames.append(inputs(t, junction=dataclasses.replace(JN, distance_m=dist), stop_line=dist))
        t += 0.25
    for _ in range(12):
        frames.append(inputs(t, junction=dataclasses.replace(JN, distance_m=0.2), stop_line=0.2,
                             turn=TURN))
        t += 0.25
    frames.append(inputs(t, turn=TURN))
    frames.append(inputs(t + 0.25, turn=dataclasses.replace(TURN, target_lane_acquired=True)))
    return frames


def test_full_junction_sequence():
    machine = RoadBehaviour(P)
    order = []
    for frame in _scenario():
        state = machine.step(frame).state
        if not order or order[-1] is not state:
            order.append(state)
    assert order == [S.LANE_FOLLOW, S.APPROACH, S.STOP_AT_LINE, S.YIELD_CHECK, S.CREEP,
                     S.CROSS, S.LANE_FOLLOW]


def test_full_sequence_with_junction_logic_off_holds_at_junction():
    machine = RoadBehaviour()
    states = {machine.step(frame).state for frame in _scenario()[:6]}
    assert states == {S.LANE_FOLLOW, S.HOLD}


def test_determinism_same_inputs_same_outputs():
    a, b = RoadBehaviour(P), RoadBehaviour(P)
    assert [a.step(f) for f in _scenario()] == [b.step(f) for f in _scenario()]
    mem = BehaviourMemory()
    assert run(mem, _scenario()[0]) == run(mem, _scenario()[0])


def test_output_never_contains_velocity_commands():
    names = {f.name for f in dataclasses.fields(BehaviourOutput)}
    assert names == {"state", "speed_cap_mps", "path_choice", "reason", "events"}
    for out in (RoadBehaviour(P).step(f) for f in _scenario()):
        assert 0.0 <= out.speed_cap_mps <= P.v_cruise


def test_module_is_ros_free_and_does_not_import_control():
    source = inspect.getsource(machine_module)
    for word in ("rclpy", "cmd_vel", "geometry_msgs", "import control", "from control"):
        assert word not in source
    assert "D-2" in machine_module.__doc__ and "D-151" in machine_module.__doc__


# --- transition table and plan doc --------------------------------------------------------

def test_transition_table_covers_every_state():
    rows = transition_table()
    assert {r.source for r in rows} == set(S)
    assert {r.target for r in rows} == set(S)


def test_plan_doc_matches_transition_table():
    assert render_transition_table_markdown() in DOC.read_text(encoding="utf-8")
