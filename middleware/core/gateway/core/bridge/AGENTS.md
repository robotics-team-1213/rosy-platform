
# bridge

**Parent context:** `../AGENTS.md`

## Purpose

ROS-101: the only module allowed to import rclpy message types and talk to the ROS graph. Publishes the muxed `cmd_vel` at 50 Hz. Optional `slam_toolbox` must be imported inside try/except.

`ros_bridge.py` registers 25 subs, 5 pubs, 4 service clients, 7 timers, the Nav2 action client and TF; the exact list is pinned in `test/test_bridge_timers.py` (update both together). The other modules are ROS-free siblings (`observation`, `translate`, `goal_tracker`, `cmd_vel`, `docking_executor`, ...) with host tests named `test_bridge_<module>.py`; `nav_goal.py` needs the ROS messages.

## For AI Agents

### Working In This Directory

- `SaveMap` name field is `std_msgs/String`, success code 0. Wrong types SIGABRT — CI guards this.
- LED and LiDAR start/stop are services, not CORE GPIO.
- Do not put policy here. Policy lives in command/safety/power; bridge only adapts.
- More than one Nav2 goal can be in flight (SWM-001). Route every acceptance, result and cancel through `GoalTracker`: a preempted goal's late abort must not be read as the current goal's failure, and a cancel must reach every live handle.
- `_setup_diagnostics` registers exactly `{core, cpu, memory, disk, odom_topic}`. Any refactor must reproduce it: compare `GET /api/v1/diagnostics` key-for-key (a dropped provider shows as a missing key, never an error).
- Costmaps: subscribe to `*_costmap/costmap_raw` only. `costmap` is `nav_msgs/OccupancyGrid`, `costmap_raw` is `nav2_msgs/Costmap`; the non-`_raw` subscriptions read the wrong type and never matched.
- Map QoS: the bridge takes `map` LATCHED (TRANSIENT_LOCAL both sides). Other consumers take it with sensor-data QoS deliberately; that split is intentional. A RELIABLE-only subscriber must never meet a BEST_EFFORT publisher: the pair never matches and reads as silence.
- Message → dict conversion belongs in `translate.py`; a decision (parse, validate, admit/reject, route) belongs in `observation.py` or the owning sibling (D-338). A callback takes the clock, calls the sibling, passes `warn`/publish through.
- Inline computation in `ros_bridge.py` is untestable on the host.
- Readiness subscriptions (lifecycle `transition_event` for AMCL, map server, controller, both costmaps; `motor/ready` lease) feed `navigation.readiness.NavigationReadinessGate`, not another velocity path.
- Hardware mode stays HOLD until all required components are active and the motor lease is fresh.
- The SLAM backend substitutes `slam_toolbox` readiness for AMCL/map-server; a profile must never require both.
- `frame_prefix` on TF frames; hash map files for `map_id` (D-13).

### Testing Requirements

Host pytest does not import `ros_bridge.py` (optional ROS). CI boot smoke and the SaveMap guard cover it; check the latest run (`gh run list`). A local `main` ahead of `origin/main` has no CI evidence.

Exception: `test/test_bridge_timers.py` stubs `rclpy` in `sys.modules` and asserts only what the bridge registers (structural). Add no semantic tests there and do not move the stub into `conftest.py`: a stub asserts stub semantics, so its blast radius stays one file. Extract decisions into ROS-free siblings with duck-typed `SimpleNamespace` tests instead.
