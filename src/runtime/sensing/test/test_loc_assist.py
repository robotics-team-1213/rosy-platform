"""D-395 P2-3: the robot-side LocAssist core between ROS and the pure localization logic.

Contract: docs/plans/2026-10-01-d395-phase2-interfaces.md section 1. The node only
does ROS I/O; every decision about what to publish and when is made here.
"""
import itertools
import math

import numpy as np
import pytest
from core_common.protocol.localization import CandidateReport, LocalizationStatus

from control.loc_assist import (COVARIANCE, LocAssist, lane_rules_near, pooled_grid, search)
from control.sensing.loc_candidates import PoseCandidate
from loc_world import MOUNT, SQUARES, field, scan

ODOM = (0., 0., 0.)
TRUTH = PoseCandidate(-1.26, .49, -math.pi / 2, .97, 'slot:A')
MIRROR = PoseCandidate(1.26, -.49, math.pi / 2, .97, 'global')


def core(**kwargs):
    ids = itertools.count(1)
    return LocAssist(lambda: f"r-{next(ids)}", **kwargs)


def kinds(out, kind):
    return [payload for k, payload in out if k == kind]


def one(out, kind):
    found = kinds(out, kind)
    assert len(found) == 1, (kind, out)
    return found[0]


def candidates_ready(a, now=1.):
    assert a.search_due(now, ODOM)
    a.search_started(now, ODOM)
    return a.search_finished(now, ODOM, [TRUTH, MIRROR], unmapped=[(.3, .1)])


def decision(request_id, received_s, **fields):
    body = {"request_id": request_id, "source": "candidate", "candidate_index": 0, "cues": ["slot"]}
    body.update(fields)
    return {"decision": body, "received_s": received_s}


def hold(a, start, until, fit=.95, dt=.1):
    out, t = [], start
    while t <= until + 1e-9:
        out += a.on_fit(t, fit)
        t = round(t + dt, 6)
    return out


def test_power_on_is_unknown_without_a_map_pose_and_asks_for_a_search():
    a = core()
    state = one(a.tick(0.), 'state')
    status = LocalizationStatus.model_validate(state['status'])
    assert status.state.value == 'UNKNOWN' and status.pose_frame.value == 'odom'
    assert state['pose'] is None and state['stamp'] == 0.
    assert a.search_due(0., ODOM)


def test_the_amcl_pose_is_reported_in_the_map_frame():
    a = core()
    a.on_amcl_pose((1., 2., .5))
    state = one(a.tick(0.), 'state')
    assert state['status']['pose_frame'] == 'map'
    assert state['pose'] == {'x': 1., 'y': 2., 'yaw': .5}


def test_candidates_are_a_valid_report_and_move_the_state_to_candidates():
    a = core()
    out = candidates_ready(a)
    report = one(out, 'candidates')
    full = CandidateReport.model_validate({**report, 'robot_id': 'rosy_01'})
    assert full.request_id == 'r-1' and len(full.candidates) == 2
    assert full.unmapped_objects[0].x == .3 and full.stamp == 1. and not full.pickup
    assert one(out, 'state')['status']['state'] == 'CANDIDATES'
    assert one(out, 'state')['status']['request_id'] == 'r-1'


def test_candidates_are_re_reported_every_two_seconds_with_a_new_stamp():
    a = core()
    candidates_ready(a, now=1.)
    assert kinds(a.tick(2.9), 'candidates') == []
    again = one(a.tick(3.), 'candidates')
    assert again['request_id'] == 'r-1' and again['stamp'] == 3.
    assert kinds(a.tick(4.), 'candidates') == []
    assert one(a.tick(5.), 'candidates')['stamp'] == 5.


def test_state_is_published_at_two_hertz_and_on_every_change():
    a = core()
    assert len(kinds(a.tick(0.), 'state')) == 1
    assert kinds(a.tick(.3), 'state') == []
    assert len(kinds(a.tick(.5), 'state')) == 1
    assert len(kinds(candidates_ready(a, now=.6), 'state')) == 1   # change, not cadence


def test_at_most_eight_candidates_are_reported():
    a = core()
    a.search_started(0., ODOM)
    many = [PoseCandidate(i * .3, 0., 0., .95, 'global') for i in range(11)]
    assert len(one(a.search_finished(0., ODOM, many), 'candidates')['candidates']) == 8


@pytest.mark.parametrize('source, fields', [
    ('candidate', {'candidate_index': 1}),
    ('human', {'candidate_index': None, 'pose': {'x': .1, 'y': .2, 'yaw': .3}, 'cues': []}),
    ('overhead', {'candidate_index': None, 'pose': {'x': .1, 'y': .2, 'yaw': .3}, 'cues': ['square', 'overhead']}),
    ('homing_ref', {'candidate_index': None, 'pose': {'x': .1, 'y': .2, 'yaw': .3}, 'cues': ['square']}),
])
def test_each_source_injects_with_its_own_covariance(source, fields):
    a = core()
    candidates_ready(a)
    inject = one(a.on_decision(1.5, decision('r-1', 1.5, source=source, **fields)), 'inject')
    assert (inject.xy_std, inject.yaw_std) == COVARIANCE[source]
    assert inject.source == source and inject.request_id == 'r-1'
    if source == 'candidate':
        assert inject.pose == (MIRROR.x, MIRROR.y, MIRROR.yaw)
    else:
        assert inject.pose == (.1, .2, .3)


def test_covariance_table_matches_the_contract():
    assert COVARIANCE == {'candidate': (.05, .1), 'human': (.15, .3),
                          'overhead': (.10, .2), 'homing_ref': (.05, .1)}


def test_decision_inject_three_seconds_then_localized():
    a = core()
    candidates_ready(a)
    out = a.on_decision(2., decision('r-1', 2.))
    assert one(out, 'inject').pose == (TRUTH.x, TRUTH.y, TRUTH.yaw)
    assert kinds(out, 'result') == []          # the result waits for the 3 s check
    assert not a.search_due(10., (1., 0., 0.))  # nothing searches over a running check
    early = hold(a, 2.1, 5.4)
    assert kinds(early, 'result') == []
    done = hold(a, 5.5, 5.6)
    result = one(done, 'result')
    assert result == {'request_id': 'r-1', 'accepted': True, 'reason': None, 'state': 'LOCALIZED'}
    state = one(done, 'state')
    assert state['status']['state'] == 'LOCALIZED'
    assert set(state) == {'status', 'pose', 'stamp'}   # contract §1; CORE cancels Nav2 itself
    assert kinds(a.tick(8.), 'candidates') == []


def test_a_rejected_decision_answers_at_once_with_the_reason():
    a = core()
    candidates_ready(a)
    out = a.on_decision(2., decision('old-7', 2.))
    assert one(out, 'result') == {'request_id': 'old-7', 'accepted': False,
                                  'reason': 'stale_request', 'state': 'CANDIDATES'}
    assert kinds(out, 'inject') == []


def test_the_ttl_counts_from_cores_receipt_time():
    a = core()
    candidates_ready(a)
    out = a.on_decision(8., decision('r-1', 2.))
    assert one(out, 'result')['reason'] == 'expired'


def test_a_malformed_decision_is_rejected_not_raised():
    a = core()
    candidates_ready(a)
    out = a.on_decision(2., {"decision": {"request_id": "r-1", "source": "candidate"}, "received_s": 2.})
    assert one(out, 'result') == {'request_id': 'r-1', 'accepted': False, 'reason': 'bad_decision',
                                  'state': 'CANDIDATES'}
    assert one(a.on_decision(2., {"nonsense": 1}), 'result')['request_id'] == ''


def test_a_failed_check_is_suspect_with_a_result_and_searches_again():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    hold(a, 2.1, 2.5)
    out = a.on_fit(2.6, .4)
    assert one(out, 'result') == {'request_id': 'r-1', 'accepted': False,
                                  'reason': 'inject_rejected', 'state': 'SUSPECT'}
    assert one(out, 'state')['status']['reason'] == 'inject_rejected'
    assert a.search_due(2.7, ODOM)


def test_a_scan_gap_during_the_check_fails_it_on_the_tick():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    assert one(a.tick(2.7), 'result')['reason'] == 'inject_rejected'


def test_fleet_suspect_moves_localized_to_suspect_and_searches():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    hold(a, 2.1, 5.6)
    out = a.on_suspect(6., {"reason": "fleet_monitor"})
    status = one(out, 'state')['status']
    assert status['state'] == 'SUSPECT' and status['reason'] == 'fleet_monitor'
    assert a.search_due(6.1, ODOM)


def test_pickup_suspects_waits_for_the_set_down_and_marks_the_report():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    hold(a, 2.1, 5.6)
    out = a.on_pickup(6., True)
    assert one(out, 'state')['status']['reason'] == 'pickup'
    assert not a.search_due(7., ODOM)
    a.on_pickup(8., False)
    assert a.search_due(8., ODOM)
    a.search_started(8., ODOM)
    assert one(a.search_finished(9., ODOM, [TRUTH, MIRROR]), 'candidates')['pickup'] is True


def test_a_pickup_during_the_check_ends_it_with_a_result():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    out = a.on_pickup(2.3, True)
    assert one(out, 'result') == {'request_id': 'r-1', 'accepted': False,
                                  'reason': 'pickup', 'state': 'SUSPECT'}


def test_a_search_over_a_moving_robot_is_discarded_and_retried():
    a = core()
    a.search_started(0., ODOM)
    assert a.search_finished(1., (.02, 0., 0.), [TRUTH, MIRROR]) == []
    assert a.search_due(1., (.02, 0., 0.))


def test_candidates_are_searched_again_only_after_a_move_and_the_retry_interval():
    a = core(retry_s=5.)
    candidates_ready(a, now=1.)
    assert not a.search_due(3., ODOM)
    assert not a.search_due(3., (.2, 0., 0.))       # moved, but within retry_s
    assert not a.search_due(7., ODOM)               # due by time, but did not move
    assert a.search_due(7., (.2, 0., 0.))


def test_an_empty_search_stays_unknown_and_retries_after_the_interval():
    a = core(retry_s=5.)
    a.search_started(0., ODOM)
    assert kinds(a.search_finished(.5, ODOM, []), 'candidates') == []
    assert not a.search_due(3., ODOM)
    assert a.search_due(5.5, ODOM)


def test_a_search_finishing_over_a_human_decision_is_dropped():
    a = core()
    candidates_ready(a)
    a.search_started(1.5, ODOM)
    a.on_decision(2., decision('r-1', 2.))
    assert a.search_finished(2.2, ODOM, [MIRROR]) == []
    assert a.machine.check is not None


def test_pooled_grid_keeps_walls_and_unknown_at_the_coarser_resolution():
    grid = np.zeros((8, 8), dtype=np.int8)
    grid[0, 0] = 100
    grid[5, 6] = -1
    pooled, resolution = pooled_grid(grid, .005, .02)
    assert resolution == .02 and pooled.shape == (2, 2)
    assert pooled[0, 0] == 100 and pooled[1, 1] == -1 and pooled[0, 1] == 0


def test_pooled_grid_leaves_a_coarse_map_alone():
    grid = np.zeros((3, 3), dtype=np.int8)
    pooled, resolution = pooled_grid(grid, .05, .02)
    assert resolution == .05 and pooled is grid


def test_lane_rules_are_found_beside_the_map_or_one_folder_up(tmp_path):
    maps = tmp_path / 'maps'
    maps.mkdir()
    (maps / 'm.yaml').write_text('image: m.pgm\n', encoding='utf-8')
    assert lane_rules_near(str(maps / 'm.yaml')) is None
    (tmp_path / 'lane_rules.yaml').write_text('{}\n', encoding='utf-8')
    assert lane_rules_near(str(maps / 'm.yaml')) == str(tmp_path / 'lane_rules.yaml')
    (maps / 'lane_rules.yaml').write_text('{}\n', encoding='utf-8')
    assert lane_rules_near(str(maps / 'm.yaml')) == str(maps / 'lane_rules.yaml')
    assert lane_rules_near('') is None


def test_search_on_the_fleet_map_finds_the_slot_pose_and_its_objects():
    truth = (-1.26, .49, -math.pi / 2)
    ranges, angles = scan(truth, peers=[(-.9, -.509)])
    found, objects, clear = search(field(), None, SQUARES, ranges, angles, .105, MOUNT)
    assert 1 <= len(found) <= 8 and clear is not None
    assert math.dist((found[0].x, found[0].y), truth[:2]) < .05
    assert found[0].origin == 'slot:A'
    assert all(len(o) == 2 for o in objects)
    again, _, same = search(field(), clear, SQUARES, ranges, angles, .105, MOUNT)
    assert same is clear and len(again) == len(found)


def test_peer_objects_come_from_the_full_scan_while_the_search_is_strided():
    """S1 finding 2: at scan_stride 4 a Pinky 2.35 m away is one beam (MIN_POINTS 2),
    seen 1 in 36 reports. The search stays strided; the objects use every beam."""
    truth, peer = (.86, -.52, math.pi), (-1.26, .49)        # the S1 (b) layout
    full = scan(truth, peers=[peer], beams=640)
    strided = full[0][::4], full[1][::4]
    _, objects, _ = search(field(), None, SQUARES, *strided, .105, MOUNT)
    assert objects == []                                    # the defect: one beam is no object
    found, objects, _ = search(field(), None, SQUARES, *strided, .105, MOUNT, object_scan=full)
    assert math.dist((found[0].x, found[0].y), truth[:2]) < .05
    assert len(objects) == 1
    c, s = math.cos(truth[2]), math.sin(truth[2])
    dx, dy = peer[0] - truth[0], peer[1] - truth[1]
    assert math.dist(objects[0], (c * dx + s * dy, -s * dx + c * dy)) < .08


def test_the_global_fine_stage_gets_the_full_scan(monkeypatch):
    """S1 re-run R3: the fine yaw stage runs on every beam, not the strided search scan."""
    import control.loc_assist as loc_assist
    seen = {}
    monkeypatch.setattr(loc_assist, 'global_candidates', lambda *a, **kw: seen.update(kw) or [])
    full = scan((-.7, .15, math.pi), beams=640)
    search(field(), None, SQUARES, full[0][::4], full[1][::4], .105, MOUNT, object_scan=full)
    assert seen['fine_scan'] is full


def test_returns_inside_the_robot_body_are_not_peer_objects():
    """Gazebo fix_a1: on square A every full-scan report carried an object 7 cm from
    base_link (a chassis/wall return the stride used to thin to one beam). No peer
    can be inside this robot's own radius."""
    truth = (-1.26, .49, -math.pi / 2)
    ranges, angles = scan(truth, beams=640)
    ranges = ranges.copy()
    ranges[200:206] = .07                                   # a self-hit cluster
    _, objects, _ = search(field(), None, SQUARES, ranges[::4], angles[::4], .105, MOUNT,
                           object_scan=(ranges, angles))
    assert objects == []


@pytest.mark.parametrize('pose', [(.86, -.52, math.pi), (-1.26, .49, math.pi / 2), (-.7, .15, math.pi)])
def test_the_full_scan_finds_no_objects_on_an_empty_track(pose):
    full = scan(pose, beams=640)
    _, objects, _ = search(field(), None, SQUARES, full[0][::4], full[1][::4], .105, MOUNT, object_scan=full)
    assert objects == []


def test_a_wider_scan_gap_survives_an_executor_stall_but_not_a_lost_lidar():
    """Node default max_gap_s 1.0: a 0.8 s stall right after the injection (WSL, a loaded Pi)
    must not fail a correct pose; a 10 Hz lidar still gives ~10 fits per second."""
    a = core(max_gap_s=1.)
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    assert kinds(a.tick(2.8), 'result') == []
    hold(a, 2.8, 4.0)
    assert one(a.tick(5.1), 'result')['reason'] == 'inject_rejected'   # 1.1 s silence


def test_the_machine_passes_the_gap_to_its_check():
    from control.sensing.loc_state import LocalizationStateMachine
    machine = LocalizationStateMachine(lambda: 'x', max_gap_s=1.)
    machine.offer([TRUTH], 0.)
    machine.decide('x', 0., candidate_index=0, cues=['slot'])
    assert machine.check.max_gap_s == 1.
    assert LocalizationStateMachine(lambda: 'y').__dict__['_check_args'].get('max_gap_s', .5) == .5


def test_paint_scores_ride_on_their_candidates():
    a = core()
    a.search_started(0., ODOM)
    report = one(a.search_finished(0., ODOM, [TRUTH, MIRROR], paint_scores=[.93, .02], evidence_s=0.), 'candidates')
    assert [c['paint_score'] for c in report['candidates']] == [.93, .02]


# --- review fixes (lane A review 2026-10-02) ----------------------------------------

def test_a_pickup_mid_search_discards_the_result_and_no_decision_injects():
    a = core()
    a.search_started(0., ODOM)
    a.on_pickup(.5, True)
    assert a.search_finished(1., ODOM, [TRUTH, MIRROR]) == []
    a.on_pickup(1.5, False)
    assert a.machine.request_id is None
    out = a.on_decision(2., decision('r-1', 2.))
    assert kinds(out, 'inject') == [] and one(out, 'result')['reason'] == 'stale_request'
    assert a.search_due(2., ODOM)                     # the set-down searches again


def test_a_search_spanning_a_whole_pickup_is_still_discarded():
    a = core()
    a.search_started(0., ODOM)
    a.on_pickup(.3, True)
    a.on_pickup(.6, False)
    assert a.search_finished(1., ODOM, [TRUTH, MIRROR]) == []


def test_decisions_while_held_are_rejected():
    a = core()
    candidates_ready(a)
    a.on_pickup(1.5, True)
    out = a.on_decision(2., decision('r-1', 2.))
    assert kinds(out, 'inject') == [] and one(out, 'result')['reason'] == 'held'


def test_no_re_report_while_the_check_runs():
    a = core()
    candidates_ready(a, now=1.)
    a.on_decision(1.5, decision('r-1', 1.5))
    out = []
    t = 1.6
    while t < 4.5:
        out += a.on_fit(t, .95) + a.tick(t)
        t = round(t + .1, 6)
    assert kinds(out, 'candidates') == []


def test_a_duplicate_of_the_pending_decision_gets_no_result():
    a = core()
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    assert a.on_decision(2.2, decision('r-1', 2.2)) == []
    done = hold(a, 2.1, 5.6)
    assert one(done, 'result')['accepted'] is True


@pytest.mark.parametrize('received', [None, 'nan', math.inf, 2.6])
def test_received_s_is_required_finite_and_not_from_the_future(received):
    a = core()
    candidates_ready(a)
    payload = decision('r-1', received)
    if received is None:
        del payload['received_s']
    elif received == 'nan':
        payload['received_s'] = math.nan
    out = a.on_decision(2., payload)
    assert kinds(out, 'inject') == [] and one(out, 'result')['reason'] == 'bad_receipt'


def test_received_s_slightly_ahead_is_clock_jitter_and_accepted():
    a = core()
    candidates_ready(a)
    assert kinds(a.on_decision(2., decision('r-1', 2.4)), 'inject')


def test_square_and_paint_evidence_older_than_the_search_is_dropped():
    sighting = type('S', (), {'bearing_rad': .1, 'range_m': .4, 'confidence': .9})()
    a = core()
    a.search_started(1., ODOM)
    old = one(a.search_finished(2., ODOM, [TRUTH, MIRROR], sightings=[sighting],
                                paint_scores=[.9, .1], evidence_s=.8), 'candidates')
    assert old['square_sightings'] == [] and [c['paint_score'] for c in old['candidates']] == [None, None]
    b = core()
    b.search_started(1., ODOM)
    new = one(b.search_finished(2., ODOM, [TRUTH, MIRROR], sightings=[sighting],
                                paint_scores=[.9, .1], evidence_s=1.2), 'candidates')
    assert len(new['square_sightings']) == 1 and new['candidates'][0]['paint_score'] == .9


def test_the_camera_is_wanted_only_outside_localized():
    a = core()
    assert a.camera_wanted
    candidates_ready(a)
    a.on_decision(2., decision('r-1', 2.))
    hold(a, 2.1, 5.6)
    assert not a.camera_wanted
    a.on_suspect(6., {'reason': 'fleet_monitor'})
    assert a.camera_wanted


# --- D-395 P2-7: CORE missions ---------------------------------------------------


def test_no_search_runs_while_a_core_mission_moves_the_robot():
    a = core()
    a.on_mission(0., {"kind": "rotate_in_place", "state": "running", "reason": None})
    assert not a.search_due(0., ODOM)                 # power-on wants one, but the robot is moving
    a.on_mission(1., {"kind": "rotate_in_place", "state": "done", "reason": "done"})
    assert a.search_due(1., ODOM)


def test_a_mission_end_searches_candidates_again_without_waiting_for_a_move():
    a = core()
    candidates_ready(a)
    assert not a.search_due(1.5, (.01, 0., 0.))       # CANDIDATES: neither moved nor waited
    a.on_mission(1.5, {"kind": "nudge_forward", "state": "running", "reason": None})
    a.on_mission(2., {"kind": "nudge_forward", "state": "aborted", "reason": "obstacle"})
    assert a.search_due(2., (.01, 0., 0.))            # fresh candidates after every mission end
    a.search_started(2., (.01, 0., 0.))
    a.search_finished(2.5, (.01, 0., 0.), [TRUTH, MIRROR])
    assert not a.search_due(3., (.01, 0., 0.))        # one search per end


def test_a_mission_message_without_a_known_state_is_ignored():
    a = core()
    candidates_ready(a)
    a.on_mission(2., {"state": "flying"})
    a.on_mission(2., "not a dict")
    assert not a.search_due(2., ODOM)


def test_a_decision_while_a_mission_runs_is_rejected_mission_running():
    """S1 re-run (F1 WSL run): Fleet decided while `rotate_in_place` still turned r2, so
    even the right pose fitted 0.18-0.39 and failed its check. No injection while moving."""
    a = core()
    candidates_ready(a)
    a.on_mission(1.5, {"kind": "rotate_in_place", "state": "running", "reason": None})
    out = a.on_decision(2., decision('r-1', 2.))
    assert one(out, 'result') == {'request_id': 'r-1', 'accepted': False,
                                  'reason': 'mission_running', 'state': 'CANDIDATES'}
    assert kinds(out, 'inject') == []


def test_a_mission_start_drops_the_open_request_and_its_report():
    a = core()
    candidates_ready(a)
    a.on_mission(1.5, {"kind": "rotate_in_place", "state": "running", "reason": None})
    state = one(a.tick(1.5), 'state')
    assert state['status']['state'] == 'CANDIDATES' and state['status']['request_id'] is None
    assert kinds(a.tick(9.), 'candidates') == []                  # no stale re-report meanwhile
    a.on_mission(10., {"kind": "rotate_in_place", "state": "done", "reason": "done"})
    reason = one(a.on_decision(10., decision('r-1', 10.)), 'result')['reason']
    assert reason == 'stale_request'                              # the old id never comes back
    assert a.search_due(10., ODOM)
    a.search_started(10., ODOM)
    fresh = one(a.search_finished(10.5, ODOM, [TRUTH, MIRROR]), 'candidates')
    assert fresh['request_id'] == 'r-2'
    assert kinds(a.on_decision(11., decision('r-2', 11.)), 'inject')


def test_a_lost_mission_end_stops_pausing_the_search_after_the_longest_mission():
    """CORE caps a mission at 120 s; a lost end message or a CORE restart must not pause
    the search forever: the pause lapses 10 s after that."""
    a = core()
    a.on_mission(0., {"kind": "lane_to_stopline", "state": "running", "reason": None})
    assert not a.search_due(130., ODOM)
    assert a.search_due(130.1, ODOM)
