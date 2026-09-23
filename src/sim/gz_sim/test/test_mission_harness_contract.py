"""ROS-free checks for mission_harness.py (lane-network mission stage 3:
undock -> tour -> park in Gazebo), in the style of the coverage harness
tests: the script needs rclpy and ros2 launch to run, but its plan, its
mission loop (driven here by a fake CORE + Gazebo) and its scoring must
import and run on a host."""

import importlib.util
import io
import json
import math
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mission_harness.py"
LAUNCH = ROOT / "launch" / "map_v2_fleet_lane.launch.py"
GRAPH_PATH = ROOT.parents[1] / "apps" / "control" / "map" / "map_v2_fleet" / "lane_graph.yaml"
CMAKE = ROOT / "CMakeLists.txt"
SPOT = (-1.0, 0.0, 0.0)


def _mod():
    spec = importlib.util.spec_from_file_location("mission_harness", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _source():
    return SCRIPT.read_text(encoding="utf-8")


def _run_source():
    return _source().split("def run_mission(", 1)[1].split("\ndef main(", 1)[0]


@pytest.fixture(scope="module")
def graph():
    return yaml.safe_load(GRAPH_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def plan(graph):
    return _mod().mission_plan(graph)


@pytest.fixture(scope="module")
def tour_track(graph, plan):
    """The tour's centreline, 1 cm apart, from the entry back to it."""
    import junction_score
    keys, _, start, _ = plan
    path, arc, starts = junction_score.route_path(graph, keys)
    first = junction_score.directed_points(graph, keys[0])
    s0, _ = junction_score._nearest_on_path(first, junction_score._arc_length(first), start[:2])
    track = []
    for k in range(int(starts[-2] / 0.01) + 1):
        s = s0 + 0.01 * k
        i = min(int(arc.searchsorted(s, side="right")) - 1, len(path) - 2)
        d = path[i + 1] - path[i]
        p = path[i] + d / max(float((d @ d) ** 0.5), 1e-12) * (s - arc[i])
        track.append((float(p[0]), float(p[1]), math.atan2(d[1], d[0])))
    return track + [tuple(start)]


class FakeMission:
    """CORE's API and Gazebo's /odom. Each spin() is 0.1 s of wall clock
    and 0.2 s of simulation. Docking takes `dock_s` of simulation to finish
    (DOCKED, or `park_outcome` for the second dock), undock `undock_s`
    (ending on the tour start); CAMERA_LINE walks `tour` `per_spin` samples
    per spin; the second dock ends on `park_pose`."""

    def __init__(self, tour, *, park_pose=SPOT, park_outcome="DOCKED", line_state="TRACKING",
                 lost_at_index=None, confirm_status=200, undock_s=4.0, dock_s=2.0, park_s=10.0,
                 per_spin=5):
        self.tour, self.park_pose, self.park_outcome = tour, park_pose, park_outcome
        self.line_state, self.lost_at_index = line_state, lost_at_index
        self.confirm_status, self.undock_s, self.dock_s, self.park_s = \
            confirm_status, undock_s, dock_s, park_s
        self.per_spin = per_spin
        self.track, self.stamps = [], []
        self.wall, self.sim = 0.0, 0.0
        self.pose = SPOT
        self.docking = "UNDOCKED"
        self.pending = None           # (state when done, sim time, pose then)
        self.line = "OFF"
        self.tour_index = 0
        self.calls = []

    # rclpy + Gazebo
    def spin(self):
        self.wall += 0.1
        self.sim += 0.2
        if self.pending and self.sim >= self.pending[1]:
            self.docking, _, pose = self.pending
            self.pose = pose if pose is not None else self.pose
            self.pending = None
        if self.line == "CAMERA_LINE" and self.tour_index < len(self.tour):
            for _ in range(self.per_spin):
                if self.tour_index < len(self.tour):
                    self.pose = self.tour[self.tour_index]
                    self.tour_index += 1
                    self.track.append(self.pose)
                    self.stamps.append(self.sim)
            return
        # Otherwise the robot stands and /odom keeps coming.
        self.track.append(self.pose)
        self.stamps.append(self.sim)

    def monotonic(self):
        return self.wall

    # CoreApi
    def dock(self):
        self.calls.append("dock")
        if self.docking == "UNDOCKED" and self.pose == SPOT:
            if self.confirm_status != 200:
                return self.confirm_status, {"error": "CAPABILITY_NOT_SUPPORTED"}
            self.docking = "DOCKING"
            self.pending = ("DOCKED", self.sim + self.dock_s, None)
        else:
            self.docking = "DOCKING"
            self.pending = (self.park_outcome, self.sim + self.park_s, self.park_pose)
        return 200, {"state": self.docking}

    def undock(self):
        self.calls.append("undock")
        self.docking = "UNDOCKING"
        self.pending = ("UNDOCKED", self.sim + self.undock_s, self.tour[0])
        return 200, {"state": self.docking}

    def set_line(self, mode):
        self.calls.append(mode)
        self.line = mode
        return {"mode": mode}

    def docking_status(self):
        return {"state": self.docking}

    def line_status(self):
        if self.lost_at_index is not None and self.tour_index >= self.lost_at_index:
            return {"state": "LOST"}
        return {"state": self.line_state if self.line == "CAMERA_LINE" else "OFF"}


def _record(graph, plan, fake, *, budgets=None, wall_cap_s=5000.0):
    mod = _mod()
    keys, _, _, length = plan
    log = io.StringIO()
    recorded = mod.record_mission(
        graph, keys, fake.track, fake.stamps, spin=fake.spin, api=fake,
        monotonic=fake.monotonic, status_log=log,
        budgets_s=budgets or mod.budgets(length), wall_cap_s=wall_cap_s, status_period_s=1.0)
    records = [json.loads(line) for line in log.getvalue().splitlines()]
    return mod, recorded, records


def test_harness_imports_without_ros():
    mod = _mod()
    assert callable(mod.main) and callable(mod.run_mission)
    header = _source().split("def mission_plan(", 1)[0]
    for ros in ("import rclpy", "from rclpy", "from nav_msgs", "from std_msgs"):
        assert ros not in header, ros


def test_the_plan_starts_on_the_spot_and_tours_from_the_entry(graph, plan):
    keys, spot, tour_start, length = plan
    assert spot == pytest.approx(SPOT)
    assert keys[0] == keys[-1] == "west:f"
    assert math.dist(tour_start[:2], graph["parking"]["points"][0]) < 0.005
    assert tour_start[2] == pytest.approx(math.pi / 2, abs=0.01)
    assert length == pytest.approx(16.874, abs=0.01)


def test_budgets_are_simulation_time_per_phase(plan):
    mod = _mod()
    budgets = mod.budgets(plan[3])
    assert set(budgets) == set(mod.PHASES)
    import coverage_harness
    assert budgets["tour"] == coverage_harness.budget_s(plan[3])
    assert 600.0 < sum(budgets.values()) < 900.0
    assert "coverage_harness.WALL_CAP_FACTOR * total" in _source()


def test_one_launch_spawns_and_starts_the_route_on_the_spot(plan):
    mod = _mod()
    keys, spot, _, _ = plan
    args = mod.launch_args(keys, spot, "route_ab")
    x, y, yaw = spot
    assert f"spawn_x:={x}" in args and f"spawn_y:={y}" in args and f"spawn_yaw:={yaw}" in args
    assert f"route_start:=[{x}, {y}, {yaw}]" in args
    assert f"route:=[{', '.join(keys)}]" in args
    assert "dock_observer:=true" in args and "camera_lane_mode:=route_ab" in args
    launch = LAUNCH.read_text(encoding="utf-8")
    for arg in ("spawn_x", "spawn_y", "spawn_yaw", "camera_lane_mode", "debug_overlay",
                "route", "route_start", "dock_observer"):
        assert f'DeclareLaunchArgument("{arg}"' in launch, arg
    assert _run_source().count("subprocess.Popen(\n                [\"ros2\", \"launch\"") == 1


def test_the_whole_mission_parks_and_passes(graph, plan, tour_track):
    fake = FakeMission(tour_track, park_pose=(-1.004, 0.003, math.radians(1.0)))
    mod, recorded, records = _record(graph, plan, fake)
    assert recorded["reason"] == "parked"
    assert [p["name"] for p in recorded["phases"]] == ["confirm", "undock", "tour", "park"]
    assert [p["outcome"] for p in recorded["phases"]] == ["docked", "undocked", "reached", "docked"]
    # Line following is switched off before the dock that follows the tour.
    assert fake.calls == ["dock", "undock", "CAMERA_LINE", "OFF", "dock"]
    # The tour is anchored on its own first sample, not on the spawn.
    assert recorded["tour_track"][0] == pytest.approx(tour_track[0][:2])
    result = mod.score_mission(graph, plan[0], plan[1], fake.track, recorded)
    assert result["tour"]["pass"] and not result["lost"]
    assert result["park_error_m"] == pytest.approx(math.hypot(0.004, 0.003), abs=1e-4)
    assert result["park_dyaw_deg"] == pytest.approx(1.0, abs=0.01)
    assert result["pass"]
    # One status record per wall second, with the phase and both CORE statuses.
    assert {"sim", "phase", "line", "docking"} <= set(records[0])
    assert [r["phase"] for r in records if r["phase"]][0] == "confirm"
    assert any(r["phase"] == "tour" and r["line"] == {"state": "TRACKING"} for r in records)


def test_parked_outside_the_tolerance_fails(graph, plan, tour_track):
    for pose in [(-1.0 - 0.021, 0.0, 0.0), (-1.0, 0.0, math.radians(5.5))]:
        fake = FakeMission(tour_track, park_pose=pose)
        mod, recorded, _ = _record(graph, plan, fake)
        assert recorded["reason"] == "parked"
        assert not mod.score_mission(graph, plan[0], plan[1], fake.track, recorded)["pass"]


def test_a_lost_tour_ends_the_mission_without_docking(graph, plan, tour_track):
    fake = FakeMission(tour_track, lost_at_index=600)
    mod, recorded, _ = _record(graph, plan, fake)
    assert recorded["reason"] == "lost"
    assert recorded["phases"][-1] == pytest.approx(recorded["phases"][-1]) and \
        recorded["phases"][-1]["outcome"] == "lost"
    assert fake.calls == ["dock", "undock", "CAMERA_LINE"]
    result = mod.score_mission(graph, plan[0], plan[1], fake.track, recorded)
    assert result["lost"] and not result["pass"]


def test_a_brief_hold_during_the_tour_is_not_lost(graph, plan, tour_track):
    fake = FakeMission(tour_track, line_state="HOLD")
    _, recorded, _ = _record(graph, plan, fake)
    assert recorded["reason"] == "parked"


def test_a_failed_park_is_park_failed(graph, plan, tour_track):
    fake = FakeMission(tour_track, park_outcome="DOCK_FAILED")
    mod, recorded, _ = _record(graph, plan, fake)
    assert recorded["reason"] == "park_failed"
    assert not mod.score_mission(graph, plan[0], plan[1], fake.track, recorded)["pass"]


def test_a_refused_first_dock_stops_before_moving(graph, plan, tour_track):
    fake = FakeMission(tour_track, confirm_status=501)
    _, recorded, _ = _record(graph, plan, fake)
    assert recorded["reason"] == "confirm_failed"
    assert fake.calls == ["dock"]


def test_each_phase_is_bounded_in_simulation_time(graph, plan, tour_track):
    mod = _mod()
    budgets = dict(mod.budgets(plan[3]), undock=10.0)
    fake = FakeMission(tour_track, undock_s=1e9)
    _, recorded, _ = _record(graph, plan, fake, budgets=budgets)
    assert recorded["reason"] == "undock_timeout"
    undock = recorded["phases"][-1]
    assert 10.0 <= undock["sim_end"] - undock["sim_start"] < 10.0 + 0.2 + 1e-9
    fake = FakeMission(tour_track[:300])            # the tour never ends
    budgets = dict(mod.budgets(plan[3]), tour=40.0)
    _, recorded, _ = _record(graph, plan, fake, budgets=budgets)
    assert recorded["reason"] == "tour_timeout" and fake.calls[-1] == "OFF"


def test_a_stalled_simulation_hits_the_wall_cap(graph, plan, tour_track):
    fake = FakeMission(tour_track)
    fake.spin = lambda: setattr(fake, "wall", fake.wall + 0.1)
    _, recorded, _ = _record(graph, plan, fake, wall_cap_s=20.0)
    assert recorded["reason"] == "no_odometry"


def test_park_error_is_against_the_spot():
    mod = _mod()
    dx, dy, dyaw, position = mod.park_error((-0.99, -0.02, math.radians(-3)), SPOT)
    assert (dx, dy) == pytest.approx((0.01, -0.02))
    assert dyaw == pytest.approx(math.radians(-3))
    assert position == pytest.approx(math.hypot(0.01, 0.02))
    assert mod.PARK_POSITION_TOLERANCE_M == 0.020
    assert mod.PARK_HEADING_TOLERANCE_RAD == pytest.approx(math.radians(5.0))


def test_reuses_the_harness_readiness_cleanup_and_evidence():
    source = _run_source()
    assert "junction_harness.wait_ready(node, rclpy, boot_deadline)" in source
    assert "boot_deadline = time.monotonic() + junction_harness.BOOT_S" in source
    assert "junction_harness._kill_leftover_processes(out_dir, domain)" in source
    assert 'return {"pass": False, "reason": "boot_timeout"}' in source
    assert "clock_offset = junction_harness.wall_clock_offset()" in source
    assert 'result["clock_step_s"] = step' in source
    assert '(out_dir / "core_status.jsonl").open("w")' in source
    assert '(out_dir / "track.json").write_text' in source
    assert 'Path(__file__).with_name("record_debug.py")' in source
    assert "except Exception as exc" in source
    assert "score_mission(graph, keys, spot, track, recorded)" in source
    finally_source = source.split("finally:", 1)[1]
    order = [finally_source.index(text) for text in (
        "os.killpg(launch.pid, signal.SIGINT)", "rclpy_module.shutdown()",
        "recorder.send_signal(signal.SIGINT)",
        "recorder.wait(timeout=junction_harness.RECORDER_STOP_TIMEOUT_S)", "recorder.kill()")]
    assert order == sorted(order)


def test_cli_dry_run_prints_the_plan_and_runs_nothing(tmp_path, capsys):
    mod = _mod()
    assert mod.main(["--out", str(tmp_path / "x"), "--graph", str(GRAPH_PATH),
                     "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out.splitlines()[0])
    assert plan["spot"] == pytest.approx(list(SPOT))
    assert "dock_observer:=true" in plan["launch"]
    assert not (tmp_path / "x").exists()


def test_the_script_is_installed_beside_the_other_harnesses():
    cmake = CMAKE.read_text(encoding="utf-8")
    assert "scripts/mission_harness.py" in cmake
    assert cmake.index("scripts/coverage_harness.py") < cmake.index("scripts/mission_harness.py")
