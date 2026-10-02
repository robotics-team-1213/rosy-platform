"""D-395 S2 bench (tools/sim/d395_s2_bench.py, d395_s2_summary.py): layouts, truth, pass bar."""

import importlib.util
import math
from pathlib import Path

SIM = Path(__file__).resolve().parents[1] / "tools" / "sim"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SIM / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bench = _load("d395_s2_bench")
summary = _load("d395_s2_summary")

A, B = (-1.26, 0.49, -math.pi / 2), (0.86, -0.52, math.pi)


def test_layout_q_spawn_drops_and_goals_are_valid():
    assert bench.scenario_problems(bench.SCENARIOS["q"]) == []


def test_overlap_and_wall_hugging_are_rejected_but_the_squares_are_not():
    assert bench.layout_problems([A, B], anchors=(0, 1)) == []     # square B is 0.105 m from its wall
    problems = bench.layout_problems([A, B, (-0.70, -0.20, 0.0), (-0.60, -0.10, 0.0)], anchors=(0, 1))
    assert any("r3-r4" in m for m in problems)
    problems = bench.layout_problems([A, B, (0.0, 0.55, 0.0)], anchors=(0, 1))
    assert any("r3 0.075 m from a wall" in m for m in problems)


def test_a_robot_whose_twin_lands_on_a_peer_is_rejected():
    # r4 sits near the twin of square A: r3's twin hypothesis places r1 (on A) onto r4 and r4 onto r1.
    problems = bench.layout_problems([A, B, (-0.50, -0.20, 0.0), (1.20, -0.42, 0.0)], anchors=(0, 1))
    assert "r3's twin gets peers support 0.67" in problems   # A and r4 swap
    # A robot on r3's own twin is harmless: r3 is no anchor for itself.
    assert not any("twin" in m for m in bench.layout_problems(
        [A, B, (-0.50, -0.20, 0.0), (0.50, 0.20, 0.0)], anchors=(0, 1)))


def test_an_off_slot_robot_needs_an_anchor_in_view():
    problems = bench.layout_problems([A, (1.10, -0.30, 0.0)], anchors=(0,))
    assert "r2 has no anchor in view" in problems


def test_peer_support_scores_truth_and_twin():
    truth, twin = bench.peer_support((-0.70, -0.20), [A, B], [A, B])
    assert (truth, twin) == (1.0, 0.0)
    # The twin of an observer next to the origin sees mirrored peers; one mirrored onto a peer counts.
    truth, twin = bench.peer_support((0.0, 0.0), [(0.5, 0.2), (-0.5, -0.2)], [(0.5, 0.2), (-0.5, -0.2)])
    assert (truth, twin) == (1.0, 1.0)


def test_the_s2b_stale_trap_is_armed_only_with_a_stale_anchor():
    sc = bench.SCENARIOS["q"]
    trap = bench.stale_trap(sc["spawn"], sc["pickup"])
    assert trap["rosy_01"][1] > 0.0          # r4's old pose as an anchor supports r1's twin
    assert trap["rosy_01"][0] < 1.0          # and costs the truth
    assert bench.scenario_problems(sc) == []   # with live anchors only, no twin support


def test_s2b_drops_follow_where_the_robots_stand():
    sc = bench.SCENARIOS["q"]
    after = bench.drop_layout(sc["spawn"], sc["pickup"])
    assert after[3][:2] == (-0.20, -0.25)      # r4 on the twin of its spawn
    # After the s2d legs r1 and r2 stand elsewhere; r4's drop follows r4.
    moved = [(-1.00, 0.40, math.pi), (0.95, -0.25, 0.0), sc["spawn"][2], (0.10, 0.20, 0.0)]
    assert bench.drop_layout(moved, sc["pickup"])[3][:2] == (-0.10, -0.20)
    assert bench.drop_problems(moved, sc["pickup"]) == []
    # One lifted robot leaves no stale anchor to trap anyone: flagged, not passed.
    far = {"robots": [3], "drops": ["twin"]}
    assert "stale-anchor trap disarmed" in bench.drop_problems(sc["spawn"], far)


POSE_V = """header {
  stamp {
    sec: 41
    nsec: 500000000
  }
  data {
    key: "frame_id"
    value: "map_v2_fleet"
  }
}
pose {
  name: "rosy_01"
  id: 9
  position {
    x: -1.26
    y: 0.49
    z: 0.0499
  }
  orientation {
    z: -0.70710678
    w: 0.70710678
  }
}
pose {
  name: "base_link"
  id: 10
  position {
    x: 0.3
  }
  orientation {
    w: 1
  }
}
pose {
  name: "rosy_02"
  id: 30
  position {
    y: -0.52
  }
}
"""


def test_parse_pose_v_reads_wanted_models_with_omitted_zero_fields():
    poses = bench.parse_pose_v(POSE_V, {"rosy_01", "rosy_02", "rosy_03"})
    assert set(poses) == {"rosy_01", "rosy_02"}
    x, y, yaw = poses["rosy_01"]
    assert (x, y) == (-1.26, 0.49) and math.isclose(yaw, -math.pi / 2, abs_tol=1e-6)
    assert poses["rosy_02"] == (0.0, -0.52, 0.0)
    assert bench.parse_pose_v("", {"rosy_01"}) == {}


def test_min_pairwise_groups_rounds_and_counts_collisions():
    trail = [(1.0, "rosy_01", 0.0, 0.0, 0.0), (1.0, "rosy_02", 0.5, 0.0, 0.0), (1.0, "rosy_03", 0.0, 0.9, 0.0),
             (2.0, "rosy_01", 0.0, 0.0, 0.0), (2.0, "rosy_02", 0.2, 0.0, 0.0),
             (3.0, "rosy_01", 0.0, 0.0, 0.0)]                        # a lone sample is no round
    hit = bench.min_pairwise(trail)
    assert hit["min_m"] == 0.2 and hit["pair"] == ["rosy_01", "rosy_02"] and hit["t"] == 2.0
    assert hit["below"] == 1 and hit["rounds"] == 3
    assert bench.min_pairwise(trail, until=1.5)["min_m"] == 0.5
    assert bench.min_pairwise([])["min_m"] is None


def _run(**phases):
    ok = {"ok": True, "mirror": False, "err_xy_m": 0.004, "err_yaw_deg": 0.5}
    clock = [(0.0, 0.0, 0.1), (100.0, 10.0, 0.1), (1000.0, 100.0, 0.1)]
    trail = [(t, f"rosy_0{i}", float(i), 0.0, 0.0) for t in (10.0, 20.0) for i in (1, 2, 3, 4)]
    return {"clock": clock, "trail": trail, "events": [],
            "phases": {"power_on": {"done": True, **{f"rosy_0{i}": ok for i in (1, 2, 3, 4)}}, **phases}}


def test_the_bar_passes_a_clean_power_on_and_flags_a_collision():
    assert summary.bar(_run(), []) == {"s2a": (True, [])}
    run = _run()
    run["trail"] += [(30.0, "rosy_01", 0.0, 0.0, 0.0), (30.0, "rosy_02", 0.1, 0.0, 0.0)]
    passed, why = summary.bar(run, [])["s2a"]
    assert not passed and why[0].startswith("collision: ['rosy_01', 'rosy_02'] 0.1 m")


def test_the_bar_judges_mirror_latency_in_sim_seconds_and_accusations():
    ok = {"ok": True, "mirror": False, "err_xy_m": 0.004, "err_yaw_deg": 0.5}
    mirror = {"target": "rosy_04", "t_pub_start": 50.0, "t_injected": 100.0, "target_left": (200.0, "rosy_04", "SUSPECT", "fleet_monitor"),
              "accused": [], "done": True, **{f"rosy_0{i}": ok for i in (1, 2, 3, 4)}}
    assert summary.bar(_run(mirror=mirror), [])["s2c"] == (True, [])
    slow = dict(mirror, target_left=(400.0, "rosy_04", "SUSPECT", "fleet_monitor"))      # 30 sim s
    assert "detected after 30.0 sim s" in summary.bar(_run(mirror=slow), [])["s2c"][1][0]
    accused = dict(mirror, accused=[(210.0, "rosy_03", "SUSPECT", "fleet_monitor")])
    assert summary.bar(_run(mirror=accused), [])["s2c"][1] == ["accused ['rosy_03']"]


def test_the_bar_counts_mirror_and_human_decisions_against_every_scenario():
    run = _run(pickup2={"done": True, "others_left_localized": []})
    run["events"] = [{"event": {"type": "localization.result", "data": {"source": "human", "accepted": True}}}]
    for passed, why in summary.bar(run, [("rosy_01", "r1", "[]", {"ok": False, "mirror": True})]).values():
        assert not passed and "1 human decisions" in why and "1 mirror decisions" in why


def test_fleet_log_lines_are_parsed(tmp_path):
    (tmp_path / "fleet.log").write_text(
        "2026-10-02 21:00:01,000 fleet.localization INFO localization: rosy_04 ladder rotate: rotate_in_place "
        "sent (held ['rosy_01', 'rosy_02'])\n"
        "2026-10-02 21:00:09,000 fleet.localization WARNING localization: rosy_04 observed > 0.30 m / 30 deg "
        "off in 2 reports; suspect\n"
        "2026-10-02 21:00:08,000 fleet.localization WARNING localization: rosy_04 pose jumped while LOCALIZED: "
        "no longer an anchor\n", encoding="utf-8")
    logs = summary.fleet_log(tmp_path)
    assert logs["ladder"] == [("rosy_04", "rotate", "rotate_in_place", "['rosy_01', 'rosy_02']")]
    assert logs["suspects"] == ["rosy_04"] and logs["jumped"] == ["rosy_04"]


def test_s2d_fails_without_homing_or_without_a_record():
    legs = {"rosy_01": [{"leg": 0, "off_goal_m": 0.05}], "rosy_02": [{"leg": 0, "off_goal_m": 0.04}]}
    traffic = {"started": 10.0, "homer_at_start": {"state": "CANDIDATES"}, "legs": legs,
               "planned": {"rosy_01": 1, "rosy_02": 1}}
    assert summary.bar(_run(traffic=traffic), [])["s2d"] == (True, [])
    early = dict(traffic, homer_at_start={"state": "LOCALIZED"})
    assert "no homing in traffic" in summary.bar(_run(traffic=early), [])["s2d"][1][0]
    bay = dict(traffic, legs={"rosy_01": [{"leg": 0, "off_goal_m": 0.6}], "rosy_02": legs["rosy_02"]})
    assert summary.bar(_run(traffic=bay), [])["s2d"][1] == ["legs counted away from their goal [('rosy_01', 0.6)]"]
    missing = _run()
    missing["args"] = {"traffic": True}
    assert summary.bar(missing, [])["s2d"] == (False, ["traffic requested, phase not recorded"])
