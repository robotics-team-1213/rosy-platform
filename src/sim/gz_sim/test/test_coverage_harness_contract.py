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
GRAPH_PATH = ROOT.parents[1] / "runtime" / "sensing" / "map" / "map_v2_fleet" / "lane_graph.yaml"
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
    assert "score_tour(graph, keys, track, pose[:2], reason)" in source
    assert "record_tour(" in source
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
    assert "junction_harness._api_get(junction_harness.STATUS_API" in source
    # The stall is a diagnostic in results.json, read off the lease the loop fed.
    assert "lease=lease" in source
    assert 'result["longest_stall_s"] = round(lease.longest_stall_s, 2)' in source


def test_an_error_is_a_recorded_reason_never_raised():
    source = _run_tour_source()
    assert "except Exception as exc" in source
    assert '"reason": f"error:{type(exc).__name__}"' in source


# --- the recording loop (record_tour) with fakes, and its scoring -------------

class FakeSim:
    """Stands in for rclpy + Gazebo + CORE's API: each spin() is 0.1 s of
    wall clock and delivers `per_spin` odometry samples (dt_s of simulation
    time each) from `samples`; once they run out the simulation still runs
    (stamps advance, the robot stands on its last point), or with
    `stall_clock` it stops (no odometry at all). status() is
    `status_at(sim_s)`."""

    def __init__(self, samples, status_at=lambda sim: {"state": "TRACKING"},
                 per_spin=1, dt_s=0.2, stall_clock=False):
        self.samples, self.status_at = list(samples), status_at
        self.per_spin, self.dt_s, self.stall_clock = per_spin, dt_s, stall_clock
        self.track, self.stamps, self.wall, self.sim, self.fed = [], [], 0.0, 0.0, 0

    def spin(self):
        self.wall += 0.1
        for _ in range(self.per_spin):
            if self.fed < len(self.samples):
                point = self.samples[self.fed]
                self.fed += 1
            elif self.stall_clock or not self.track:
                return
            else:
                point = self.track[-1]
            self.sim += self.dt_s
            self.track.append(point)
            self.stamps.append(self.sim)

    def monotonic(self):
        return self.wall

    def status(self):
        return self.status_at(self.stamps[-1] if self.stamps else None)


def _record(graph, sim, *, sim_budget_s=600.0, wall_cap_s=2400.0):
    import io
    import json
    mod = _mod()
    keys, _, _ = mod.tour_plan(graph)
    log = io.StringIO()
    reason, sim_start = mod.record_tour(
        graph, keys, sim.track, sim.stamps, spin=sim.spin, status=sim.status,
        monotonic=sim.monotonic, status_log=log, sim_budget_s=sim_budget_s,
        wall_cap_s=wall_cap_s, status_period_s=1.0)
    records = [json.loads(line) for line in log.getvalue().splitlines()]
    return mod, keys, reason, sim_start, records


@pytest.fixture(scope="module")
def centreline(graph):
    keys, pose, _ = _mod().tour_plan(graph)
    return _centreline_track(graph, keys, pose[:2])


def test_the_loop_stops_when_the_tour_reaches_its_end_and_cuts_the_track(graph, centreline):
    """Three odometry samples per spin, so the spin that reaches the end
    also delivers samples past it: they are cut. The recorded track then
    scores pass with reason "reached"."""
    beyond = centreline[1:40]        # the robot carries on past the end
    sim = FakeSim(centreline + beyond, per_spin=3)
    mod, keys, reason, sim_start, records = _record(graph, sim)
    assert reason == "reached"
    assert sim_start == pytest.approx(0.6)
    assert len(sim.track) < sim.fed
    progress = mod.Progress(graph, keys, sim.track[0])
    assert [progress.update(p) for p in sim.track].index(True) == len(sim.track) - 1
    result = mod.score_tour(graph, keys, sim.track, sim.track[0], reason)
    assert result["pass"] and not result["lost"], result
    # One core_status record per wall second, stamped with the sim time.
    assert len(records) == pytest.approx(sim.wall, abs=1.0)
    assert all(r["status"] == {"state": "TRACKING"} for r in records)
    stamps = [r["sim"] for r in records]
    assert stamps == sorted(stamps)


def test_the_loop_stops_on_the_simulation_budget(graph, centreline):
    sim = FakeSim(centreline[:300], status_at=lambda sim: None)
    mod, keys, reason, sim_start, _ = _record(graph, sim, sim_budget_s=120.0)
    assert reason == "timeout"
    assert 120.0 <= sim.stamps[-1] - sim_start < 120.0 + 0.2 + 1e-9
    result = mod.score_tour(graph, keys, sim.track, sim.track[0], reason)
    assert not result["pass"] and result["missing"]


def test_the_loop_stops_on_the_wall_clock_cap(graph):
    sim = FakeSim([], status_at=lambda sim: None, stall_clock=True)
    _, _, reason, sim_start, _ = _record(graph, sim, wall_cap_s=30.0)
    assert reason == "wall_cap" and sim_start is None
    assert sim.wall == pytest.approx(30.0, abs=0.11)


def test_a_lost_core_lease_ends_the_tour_as_lost(graph, centreline):
    sim = FakeSim(centreline, status_at=lambda sim: {"state": "LOST" if sim >= 40.0
                                                     else "TRACKING"})
    mod, keys, reason, _, records = _record(graph, sim)
    assert reason == "lost"
    assert records[-1]["status"]["state"] == "LOST" and records[-1]["sim"] >= 40.0
    assert all(r["status"]["state"] == "TRACKING" for r in records[:-1])
    result = mod.score_tour(graph, keys, sim.track, sim.track[0], reason)
    assert result["lost"] and not result["pass"]


def test_a_long_hold_is_a_diagnostic_never_lost(graph, centreline):
    """CORE latches LOST until set_mode, so only LOST ends the tour. A long
    HOLD stretch is recorded (longest_stall_s) and the tour carries on."""
    def held(start, length):
        return lambda sim: {"state": "HOLD" if start <= sim < start + length
                            else "TRACKING"}
    mod = _mod()
    lease = mod.CoreLease()
    sim = FakeSim(centreline, status_at=held(40.0, 30.0))
    keys, _, _ = mod.tour_plan(graph)
    import io
    reason, _ = mod.record_tour(
        graph, keys, sim.track, sim.stamps, spin=sim.spin, status=sim.status,
        monotonic=sim.monotonic, status_log=io.StringIO(), sim_budget_s=600.0,
        wall_cap_s=2400.0, status_period_s=1.0, lease=lease)
    assert reason == "reached"
    assert not lease.lost
    assert 28.0 <= lease.longest_stall_s < 30.0


def test_brief_holds_aliased_at_a_high_real_time_factor_are_not_lost(graph, centreline):
    """At RTF 4 one wall-second sample spans 4 s of simulation. Brief 0.2 s
    HOLDs that each happen to land on a sample look like a 12 s stall; CORE
    never lost the line, and neither does the lease."""
    samples = []

    def aliased(sim):
        # Samples 10-13 each land on a brief 0.2 s HOLD; CORE tracks between.
        samples.append(sim)
        return {"state": "HOLD" if 10 <= len(samples) <= 13 else "TRACKING"}
    sim = FakeSim(centreline, status_at=aliased, per_spin=2)   # 4 s sim per wall second
    mod, _, reason, _, records = _record(graph, sim)
    held = [r["sim"] for r in records if r["status"]["state"] == "HOLD"]
    assert len(held) >= 3 and held[-1] - held[0] > 3.0
    assert reason == "reached"


def test_the_core_lease_skips_samples_that_say_nothing():
    lease = _mod().CoreLease()
    assert not lease.update(10.0, {"state": "WAITING"})
    assert not lease.update(12.0, None)                   # API down: no evidence
    assert not lease.update(None, {"state": "HOLD"})      # no odometry yet
    assert not lease.update(13.0, {"state": "HOLD"})
    assert not lease.update(20.0, {"state": "HOLD"})      # a long HOLD is not LOST
    assert lease.stall_s == pytest.approx(10.0)
    assert lease.update(21.0, {"state": "LOST"})
    assert lease.update(22.0, {"state": "TRACKING"})      # latched


def test_an_api_outage_inside_a_stall_neither_ends_nor_extends_it():
    lease = _mod().CoreLease()
    assert not lease.update(10.0, {"state": "HOLD"})
    assert not lease.update(11.0, None)
    assert not lease.update(12.0, None)
    assert lease.stall_s == pytest.approx(0.0)            # outage adds nothing
    assert not lease.update(13.0, {"state": "WAITING"})
    assert lease.stall_s == pytest.approx(3.0)            # same stall, from 10.0
    assert not lease.update(14.0, {"state": "TRACKING"})
    assert lease.stall_s == 0.0 and lease.longest_stall_s == pytest.approx(3.0)
    assert lease.update(15.0, {"state": "LOST"})


def test_only_a_reached_tour_passes(graph, centreline):
    mod = _mod()
    keys, _, _ = mod.tour_plan(graph)
    for reason in ("reached", "timeout", "wall_cap", "lost"):
        result = mod.score_tour(graph, keys, centreline, centreline[0], reason)
        assert result["pass"] is (reason == "reached"), reason
        assert result["lost"] is (reason == "lost") and result["reason"] == reason
    assert mod.score_tour(graph, keys, [], centreline[0], "wall_cap")["progress_m"] == 0.0


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
