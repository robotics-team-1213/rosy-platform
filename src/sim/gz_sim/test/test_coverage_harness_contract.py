"""ROS-free source-contract checks for coverage_harness.py (mission plan
stage 2, the all-lane tour in Gazebo), in the style of
test_junction_harness_contract: the script needs rclpy and ros2 launch to
run, but its planning, progress and scoring logic must import here, and
its launch arguments must match map_v2_fleet_lane.launch.py."""

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "coverage_harness.py"
LAUNCH = ROOT / "launch" / "map_v2_fleet_lane.launch.py"
GRAPH_PATH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"
CMAKE = ROOT / "CMakeLists.txt"


def _mod():
    spec = importlib.util.spec_from_file_location("coverage_harness", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source():
    return SCRIPT.read_text(encoding="utf-8")


def _run_tour_source():
    return _source().split("def run_tour(", 1)[1].split("\ndef main(", 1)[0]


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load(GRAPH_PATH.read_text(encoding="utf-8"))


def test_harness_imports_without_ros():
    mod = _mod()
    assert callable(mod.main) and callable(mod.run_tour)
    header = _source().split("def tour_plan(", 1)[0]
    for ros in ("import rclpy", "from rclpy", "from nav_msgs", "from std_msgs"):
        assert ros not in header, ros


def test_the_tour_starts_and_ends_at_the_parking_junction(graph):
    keys, pose, length = _mod().tour_plan(graph)
    assert keys[0] == keys[-1] == "west:f"
    assert math.dist(pose[:2], graph["parking"]["points"][0]) < 0.005
    assert length == pytest.approx(16.874, abs=0.01)


def test_the_budget_is_simulation_time_sized_from_the_tour_length(graph):
    mod = _mod()
    _, _, length = mod.tour_plan(graph)
    budget = mod.budget_s(length)
    # Longer than the offline drive (339 s) with room for a slow Gazebo run,
    # and scaled from the length, not a fixed per-scenario timeout.
    assert budget == pytest.approx(length / (mod.BUDGET_SPEED_FRACTION * mod.CORE_CRUISE_M_S))
    assert 339.0 * 1.3 < budget < 1200.0
    assert mod.budget_s(0.5) == mod.MIN_BUDGET_S
    source = _run_tour_source()
    assert "stamps[-1] - sim_start >= sim_budget_s" in source
    assert "wall_deadline = wall_start + wall_cap_s" in source
    assert "WALL_CAP_FACTOR * sim_budget" in _source()


def test_one_launch_passes_the_whole_route_and_its_start(graph):
    mod = _mod()
    keys, pose, _ = mod.tour_plan(graph)
    args = mod.launch_args(keys, pose, "route_ab")
    assert "camera_lane_mode:=route_ab" in args and "debug_overlay:=true" in args
    assert f"route:=[{', '.join(keys)}]" in args
    assert f"route_start:=[{pose[0]}, {pose[1]}, {pose[2]}]" in args
    assert f"spawn_x:={pose[0]}" in args and f"spawn_yaw:={pose[2]}" in args
    launch = LAUNCH.read_text(encoding="utf-8")
    for arg in ("spawn_x", "spawn_y", "spawn_yaw", "camera_lane_mode", "debug_overlay",
                "route", "route_start"):
        assert f'DeclareLaunchArgument("{arg}"' in launch, arg
    # One launch for the whole tour, not one per segment.
    assert _run_tour_source().count("subprocess.Popen(\n                [\"ros2\", \"launch\"") == 1


def _centreline_track(graph, keys, start):
    import junction_score
    path, arc, starts = junction_score.route_path(graph, keys)
    first = junction_score.directed_points(graph, keys[0])
    s0, _ = junction_score._nearest_on_path(first, junction_score._arc_length(first), start)
    track = []
    for k in range(int(starts[-2] / 0.01) + 1):     # s0 .. the start again on the last key
        s = s0 + 0.01 * k
        i = min(int(arc.searchsorted(s, side="right")) - 1, len(path) - 2)
        d = path[i + 1] - path[i]
        track.append(tuple(path[i] + d / max(float((d @ d) ** 0.5), 1e-12) * (s - arc[i])))
    return track + [tuple(start)]


def test_progress_reaches_the_end_only_after_the_whole_tour(graph):
    """The tour's end point IS its start point: a plain distance-to-end
    check would stop at the first sample."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    mod = _mod()
    keys, pose, length = mod.tour_plan(graph)
    progress = mod.Progress(graph, keys, pose[:2])
    track = _centreline_track(graph, keys, pose[:2])
    done_at = next(k for k, p in enumerate(track) if progress.update(p))
    assert done_at >= len(track) - 3 and len(track) > 1600
    assert (progress.s - progress.start_s) == pytest.approx(length, abs=0.02)


def test_the_tour_is_scored_with_score_route_and_writes_the_evidence():
    source = _run_tour_source()
    assert "junction_score.score_route(graph, keys, track" in source
    assert '(out_dir / "track.json").write_text' in source
    assert '(args.out / "results.json").write_text' in _source()
    assert 'Path(__file__).with_name("record_debug.py")' in source


def test_reuses_junction_harness_readiness_mode_and_cleanup():
    source = _run_tour_source()
    assert "junction_harness.wait_ready(node, rclpy, boot_deadline)" in source
    assert "boot_deadline = time.monotonic() + junction_harness.BOOT_S" in source
    assert 'junction_harness.set_mode("CAMERA_LINE")' in source
    assert 'junction_harness.set_mode("OFF")' in source
    assert "junction_harness._kill_leftover_processes(out_dir, domain)" in source
    assert 'return {"pass": False, "reason": "boot_timeout"}' in source


def test_records_clock_step_and_core_status_like_junction_harness():
    source = _run_tour_source()
    assert "clock_offset = junction_harness.wall_clock_offset()" in source
    assert "junction_harness.clock_step_s(clock_offset, junction_harness.wall_clock_offset())" \
        in source
    assert 'result["clock_step_s"] = step' in source
    assert "junction_harness.CLOCK_STEP_TOLERANCE_S" in source
    assert '(out_dir / "core_status.jsonl").open("w")' in source
    assert "junction_harness.STATUS_SAMPLE_S" in source
    assert "junction_harness._api_get(junction_harness.STATUS_API" in source
    assert "status_log.close()" in source


def test_every_outcome_is_a_recorded_reason_never_raised():
    source = _run_tour_source()
    assert 'reached, reason = True, "reached"' in source
    assert 'reason = "timeout"' in source
    assert 'reached, reason = False, "wall_cap"' in source
    assert 'result["reason"] = reason' in source
    assert "except Exception as exc" in source
    assert '"reason": f"error:{type(exc).__name__}"' in source


def test_cleanup_order_matches_junction_harness():
    finally_source = _run_tour_source().split("finally:", 1)[1]
    kill = finally_source.index("os.killpg(launch.pid, signal.SIGINT)")
    shutdown = finally_source.index("rclpy_module.shutdown()")
    sigint = finally_source.index("recorder.send_signal(signal.SIGINT)")
    wait = finally_source.index("recorder.wait(timeout=junction_harness.RECORDER_STOP_TIMEOUT_S)")
    rkill = finally_source.index("recorder.kill()")
    assert kill < shutdown < sigint < wait < rkill
    assert "log_file.close()" in finally_source


def test_cli_dry_run_prints_the_plan_and_runs_nothing(tmp_path, capsys):
    mod = _mod()
    out = tmp_path / "tour"
    assert mod.main(["--graph", str(GRAPH_PATH), "--out", str(out), "--dry-run"]) == 0
    assert not out.exists()
    assert '"keys": ["west:f"' in capsys.readouterr().out


def test_the_script_is_installed_beside_junction_harness():
    cmake = CMAKE.read_text(encoding="utf-8")
    assert "scripts/coverage_harness.py" in cmake
    install = cmake.split("scripts/junction_harness.py", 1)[1].split(")", 1)[0]
    assert "scripts/coverage_harness.py" in install
