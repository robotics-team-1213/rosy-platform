"""ROS-free source-contract checks for junction_harness.py: it is a ROS
script (rclpy, ros2 launch) that cannot run on this Windows host, but its
scenario/scoring logic must stay importable here, and its launch arguments
must match what map_v2_fleet_lane.launch.py declares."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "launch" / "map_v2_fleet_lane.launch.py"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "junction_harness", ROOT / "scripts" / "junction_harness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_harness_imports_without_ros():
    """rclpy is not installed on this host; a module-level `import rclpy`
    would make this fail. Guarding it inside run_one() keeps the module,
    its CLI, and junction_score-based logic importable and testable here."""
    mod = _mod()
    assert mod.TIMEOUT_S > 0 and mod.BOOT_S > 0
    assert callable(mod.main)


def test_ros_imports_are_deferred_out_of_module_scope():
    """`wait_ready` (used from run_one) also imports ROS message/QoS types;
    `_api_ok` is the first function defined and is ROS-free, so splitting
    there captures every module-scope import, not just the ones before
    run_one."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    header = source.split("def _api_ok(", 1)[0]
    assert "import rclpy" not in header
    assert "from nav_msgs" not in header
    assert "from rclpy" not in header
    assert "from std_msgs" not in header


def test_harness_drives_the_scenarios_and_scoring_from_junction_score():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert "junction_score.scenarios(graph)" in source
    assert "junction_score.score(graph, scenario, track" in source


def test_cli_takes_mode_out_graph_only_and_domain():
    """main() builds its own parser; --help exits 0 (argparse's own exit)
    rather than raising, which is enough to prove every flag registers."""
    mod = _mod()
    try:
        mod.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("--help should exit")


def test_launch_arguments_the_harness_passes_are_declared_by_the_launch_file():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    launch = LAUNCH.read_text(encoding="utf-8")
    for arg in ("spawn_x", "spawn_y", "spawn_yaw", "camera_lane_mode", "debug_overlay"):
        assert f"{arg}:=" in source, arg
        assert f'DeclareLaunchArgument("{arg}"' in launch, arg


def test_route_a_and_route_b_pass_the_scenarios_route_and_start_to_the_launch():
    """Task 6: route_a/route_b need lane_graph_path/route/route_start built
    from the scenario's [into, out] and start pose, encoded as the YAML
    flow-list string the launch file's ParameterValue(value_type=List[...])
    parses (route_camera.py/route_map.py both take `keys=[into, out]`)."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    launch = LAUNCH.read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    assert 'if mode in ("route_a", "route_b") else []' in run_one_source
    assert "route:=[{scenario['into']}, {scenario['out']}]" in run_one_source
    assert "route_start:=[{x}, {y}, {yaw}]" in run_one_source
    for arg in ("route", "route_start"):
        assert f'DeclareLaunchArgument("{arg}"' in launch, arg


def test_harness_finds_record_debug_installed_beside_itself():
    """In an installed ament package, scripts land in lib/gz_sim/ side by
    side; with_name resolves at that installed location, not the source
    tree, so this stays correct after colcon install."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert 'Path(__file__).with_name("record_debug.py")' in source


def test_readiness_poll_replaces_the_blind_sleep_with_a_bounded_wait():
    """BOOT_S is the poll's upper bound, not a fixed sleep; a bare
    `time.sleep(BOOT_S)` would defeat the point of polling."""
    mod = _mod()
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert mod.BOOT_S > 0
    assert "time.sleep(BOOT_S)" not in source
    assert "boot_deadline = time.monotonic() + BOOT_S" in source
    assert "wait_ready(node, rclpy, boot_deadline)" in source


def test_readiness_poll_checks_the_status_api_with_the_viewer_token():
    mod = _mod()
    assert mod.STATUS_API == "http://127.0.0.1:8080/api/v1/line-follow"
    assert mod.VIEWER == {"Authorization": "Bearer rosy-dev-viewer"}
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert "_api_ok(STATUS_API, VIEWER)" in source


def test_readiness_poll_waits_for_odom_and_line_observation():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    wait_ready_source = source.split("def wait_ready(", 1)[1].split("\ndef ", 1)[0]
    assert 'create_subscription(Odometry, "odom"' in wait_ready_source
    assert 'create_subscription(String, "line/observation"' in wait_ready_source
    assert 'seen["odom"] and seen["line"]' in wait_ready_source


def test_boot_timeout_is_recorded_as_a_failed_result_not_raised():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert 'return {"pass": False, "reason": "boot_timeout"}' in source
    assert "if not wait_ready(node, rclpy, boot_deadline):" in source


def test_set_mode_retries_a_refused_connection():
    mod = _mod()
    assert mod.SET_MODE_RETRIES > 1
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    set_mode_source = source.split("def set_mode(", 1)[1].split("\ndef ", 1)[0]
    assert "for attempt in range(SET_MODE_RETRIES):" in set_mode_source
    assert "time.sleep(SET_MODE_RETRY_DELAY_S)" in set_mode_source


def test_every_scenario_records_one_of_the_defined_reasons():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert '"reason": "boot_timeout"' in source
    assert 'reached, reason = True, "reached"' in source
    assert 'reason = "timeout"' in source
    assert 'reached, reason = False, "wall_cap"' in source
    assert 'result["reason"] = reason' in source
    assert '"reason": f"error:{type(exc).__name__}"' in source


def test_scenario_exceptions_are_caught_so_one_failure_does_not_abort_the_run():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    assert "except Exception as exc" in run_one_source
    # main()'s loop calls run_one() directly with no try of its own: the
    # catch-and-record behaviour must live inside run_one() itself, not
    # rely on the caller to protect the loop.
    main_source = source.split("def main(", 1)[1]
    assert "try:" not in main_source


def test_launch_group_is_stopped_before_the_recorder_is_joined():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    kill_at = run_one_source.index("os.killpg(launch.pid, signal.SIGINT)")
    join_at = run_one_source.index("recorder.wait(timeout=RECORDER_STOP_TIMEOUT_S)")
    assert kill_at < join_at


def test_launch_group_is_stopped_before_rclpy_shutdown():
    """The launch group (Gazebo, bridge, nodes) should start winding down
    before this process tears down its own rclpy context, not after."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    finally_source = run_one_source.split("finally:", 1)[1]
    kill_at = finally_source.index("os.killpg(launch.pid, signal.SIGINT)")
    shutdown_at = finally_source.index("rclpy_module.shutdown()")
    assert kill_at < shutdown_at


def test_recorder_is_sent_sigint_before_being_killed():
    """record_debug.py finalises overlay.mp4's moov atom in a `finally`
    block when it's interrupted (SIGINT -> KeyboardInterrupt); SIGKILL gives
    it no chance to run that block, so overlay.mp4 has no moov atom -- an
    unplayable file. SIGINT must be tried, and joined, before any kill."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    finally_source = run_one_source.split("finally:", 1)[1]
    sigint_at = finally_source.index("recorder.send_signal(signal.SIGINT)")
    wait_at = finally_source.index("recorder.wait(timeout=RECORDER_STOP_TIMEOUT_S)")
    kill_at = finally_source.index("recorder.kill()")
    assert sigint_at < wait_at < kill_at
    # the kill is only reached from the TimeoutExpired branch of that wait
    assert "except subprocess.TimeoutExpired:" in finally_source[wait_at:kill_at]


def test_leftover_processes_from_this_scenario_are_checked_and_killed_narrowly():
    """Scoped by this scenario's own ROS_DOMAIN_ID, read from
    /proc/<pid>/environ -- not a bare pattern match, which would also kill
    an unrelated domain, user, or developer's own Gazebo run on the box."""
    mod = _mod()
    assert mod.LEFTOVER_PATTERNS == (
        'gz sim .*map_v2_fleet.world', "map_v2_fleet_lane.launch.py")
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert "_kill_leftover_processes(out_dir, domain)" in source
    kill_source = source.split("def _kill_leftover_processes(", 1)[1].split("\ndef ", 1)[0]
    assert '["pgrep", "-f", pattern]' in kill_source
    assert 'needle = f"ROS_DOMAIN_ID={domain}".encode()' in kill_source
    assert 'Path(f"/proc/{pid}/environ")' in kill_source
    assert "needle in environ.split" in kill_source
    assert '["kill", "-9", *matched]' in kill_source
    assert "log_lines.append" in kill_source


def test_leftover_process_cleanup_is_linux_only_and_skips_gracefully_elsewhere():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    kill_source = source.split("def _kill_leftover_processes(", 1)[1].split("\ndef ", 1)[0]
    assert 'sys.platform.startswith("linux")' in kill_source
    skip_branch = kill_source.split('if not sys.platform.startswith("linux"):', 1)[1].split(
        "\n\n", 1)[0]
    assert "return" in skip_branch
    assert "_append_log" in skip_branch


def test_launch_popen_is_inside_the_try_so_a_missing_ros2_does_not_abort_main():
    """A missing `ros2` binary raises OSError/FileNotFoundError from Popen;
    that must become an error-tagged result for this one scenario, not an
    uncaught exception escaping run_one() and aborting the rest of main()'s
    loop."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    try_at = run_one_source.index("try:")
    popen_at = run_one_source.index('subprocess.Popen(\n                ["ros2", "launch"')
    assert try_at < popen_at
    except_source = run_one_source.split("except OSError as exc:", 1)[1].split("\n\n", 1)[0]
    assert '"reason": f"error:{type(exc).__name__}"' in except_source


def test_launch_log_file_is_closed_in_the_finally_block():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    assert 'log_file = (out_dir / "launch.log").open("w")' in run_one_source
    finally_source = run_one_source.split("finally:", 1)[1]
    assert "log_file.close()" in finally_source


def test_killpg_is_guarded_by_launch_is_not_none():
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    run_one_source = source.split("def run_one(", 1)[1].split("\ndef main(", 1)[0]
    finally_source = run_one_source.split("finally:", 1)[1]
    assert "if launch is not None:" in finally_source
    # the killpg call itself must be textually inside that guarded block,
    # not merely preceded by the guard somewhere earlier in the function
    guarded = finally_source.split("if launch is not None:", 1)[1]
    next_top_level_if = guarded.split("\n        if ", 1)[0]
    assert "os.killpg(launch.pid, signal.SIGINT)" in next_top_level_if


def test_scenario_budget_is_simulation_time_with_a_wall_cap():
    """A loaded host slows Gazebo: a wall-clock budget made slow-but-correct
    runs time out (route_b smoke 2026-09-23, 1.1 Hz camera at load 22). The
    budget runs on odom header stamps; wall time is only a backstop, and the
    real-time factor is recorded so load is visible in the results."""
    source = (ROOT / "scripts" / "junction_harness.py").read_text(encoding="utf-8")
    assert "stamps[-1] - sim_start >= TIMEOUT_S" in source
    assert "WALL_CAP_S = " in source
    assert 'result["real_time_factor"]' in source
    assert 'result["sim_s"]' in source and 'result["wall_s"]' in source
