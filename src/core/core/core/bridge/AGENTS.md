<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# bridge

## Purpose

ROS-101: the only module allowed to import rclpy message types and talk to the ROS graph. Publishes the muxed `cmd_vel` at 50 Hz. Optional `slam_toolbox` must be imported inside try/except.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `ros_bridge.py` | 22 subs, 5 pubs, 4 service clients, 6 timers, the Nav2 action client and TF. Exact list pinned in `test/test_bridge_timers.py` — update both together |
| `translate.py` | ROS-free message → domain dict conversion. Imports no ROS type, so host pytest runs it |
| `goal_tracker.py` | ROS-free Nav2 goal generations: which result is current, what to cancel |
| `display.py` | ROS-free `display/info` decisions: address resolution and payload rounding (PWR-003) |
| `reconcile.py` | ROS-free change-detection latch. LED latches on a skipped call, LiDAR does not |
| `odometry.py` | ROS-free `travelled_m` — the only measure undocking has |
| `battery_policy.py` | ROS-free SAF-005/DNC-006 chain: what one voltage reading sets in motion, in order |
| `cmd_vel.py` | ROS-free 50 Hz `cmd_vel` cycle: select, readiness HOLD → zero, wheels, then power activity and the SAF-002 `safety.watchdog` announcement |
| `save_map.py` | ROS-free SaveMap reply handling: safe basenames under the configured map directory, `RESULT_SUCCESS = 0`, and the D-13 map id |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `SaveMap` name field is `std_msgs/String`, success code 0. Wrong types SIGABRT — CI guards this.
- Topics: `cmd_vel` out; `nav_cmd_vel` in from Nav2; `battery/voltage`; `us_sensor/range`; `batt_state`.
- LED and LiDAR start/stop are services, not CORE GPIO.
- Do not put policy here. Policy lives in command/safety/power; bridge only adapts.
- More than one Nav2 goal can be in flight (SWM-001 moving goal). Route every acceptance, result and cancel through `GoalTracker`: a preempted goal's late abort must not be read as the current goal's failure, and a cancel must reach every live handle.
- `_setup_diagnostics` registers exactly `{core, cpu, memory, disk, odom_topic}`. That set is the baseline any
  refactor of this file must reproduce — compare `GET /api/v1/diagnostics` key-for-key, not for non-emptiness. A dropped
  provider shows up as a missing key, never as an error.
- Costmaps: subscribe to `*_costmap/costmap_raw` only. Nav2 publishes the same grid on two topics —
  `costmap` is `nav_msgs/OccupancyGrid`, `costmap_raw` is `nav2_msgs/Costmap`. Four subscriptions used to
  exist; the two non-`_raw` ones read the wrong type, so they never matched and cost discovery for no data.
  Corroborated by `navigation/params/nav2_params.yaml`, which points Nav2's own consumers at `_raw`.
  *(Recorded here because the deletion shipped inside a commit about battery policy and is not reviewable
  from that commit's message.)*
- Message → dict conversion belongs in `translate.py`, not in a callback. A callback should read one line: translate, then hand the result to a service. Anything computed inline in `ros_bridge.py` cannot be tested on the host, and the source-grep tests that stand in for it pass on wrong values.

### Testing Requirements

Host pytest does not import `ros_bridge.py` (optional ROS). CI boot smoke + the SaveMap guard are what
*should* cover it — **but note they have not run on this branch**: `ci.yml` triggers on `push: [main]` and
`pull_request`, and this repository has no remote, so neither event can fire. Treat construction-time
correctness in this file as unverified until CI actually runs.
One exception, deliberately narrow — `test/test_bridge_timers.py` stubs `rclpy` in `sys.modules` to build
the bridge against a recording node and assert **what it registers**: six timers at fixed periods, seventeen
subscriptions with their callbacks and QoS, five publishers with QoS, four service clients, the action
client, the TF listener and both executor wirings. Structural only. It exists so the 3b adapter reshape
is gradable without a robot. Do not add semantic tests there and do not move the stub into `conftest.py` —
a stub asserts stub semantics, and its blast radius is meant to stay one file.
The ROS-free siblings are host-testable and carry real value assertions — `translate.py` (`test_bridge_translate.py`), `goal_tracker.py` (`test_goal_tracker.py`), `display.py` (`test_bridge_display.py`), `reconcile.py` (`test_bridge_reconcile.py`), `odometry.py` (`test_bridge_odometry.py`), `save_map.py` (`test_bridge_save_map.py`), `battery_policy.py` (`test_bridge_battery_policy.py`), `cmd_vel.py` (`test_cmd_vel_cycle.py` — the 50 Hz cycle order: wheels before the SAF-002 announcement). Duck-typed `SimpleNamespace` inputs, no rclpy. Extract a decision here rather than leaving it inline: this file is the one place host pytest cannot reach.

### Common Patterns

`frame_prefix` on TF frames. Hash map files for `map_id` (D-13).

Readiness subscriptions are intentional: lifecycle `transition_event` is the
source for AMCL, map server, controller and both costmaps; `motor/ready` is a
transient-local adapter lease. They feed the ROS-free
`navigation.readiness.NavigationReadinessGate` and do not create another
velocity path. Hardware mode remains HOLD until all required components report
active and the motor lease is refreshed.
The SLAM backend substitutes `slam_toolbox` lifecycle readiness for AMCL and
map-server readiness; the selected profile must never require both graphs.

## Dependencies

### Internal

- `CommandManager`, `NavigationManager`, `DiagnosticsCollector`, `power.battery.resolve_led`

### External

- rclpy, nav2_msgs, tf2_ros, slam_toolbox (optional), interfaces.SetLed

<!-- MANUAL: -->
