# map_v2_fleet Gazebo ROS-SIM result (2026-09-22)

**Evidence class: ROS-SIM only. DEVICE / FIELD: NOT RUN.**

## Setup

- Source: `src/apps/control/map/map_v2_fleet/260919 MAP FILE.STL`, sha256 `cabf17a84175da8be1ef7562054ec598971bbb9378810acb8cee3f686fe1f92b`
- Branch `feat/map-v2-fleet-world`, run commit `29c42bc`
- WSL Ubuntu, ROS 2 Jazzy, Gazebo Sim 8.11. Isolated colcon layout (`--symlink-install`) in `~/rosy_mapv2_ws`. This layout also checks the `extra_resource_path` mesh fix.
- `ros2 launch gz_sim map_v2_fleet_lane.launch.py`, headless, `ROS_DOMAIN_ID=57`
- Spawn (-1.26955, 0.24255), yaw -pi/2. This is the centre of the left lane.
- Camera 320x180 at a 5 Hz request, tilt 25 deg. `line_observer_node` bright threshold 220.

## Runs

| Run | Change | Result |
|---|---|---|
| `161132` | threshold 180 | Camera 4.4 Hz. The frame renders correctly: lanes and the crosswalk ahead (`map/map_v2_fleet/review/camera_start_161132.png`). Line `visible: false` on every frame. The robot body fills rows 139-179 at grey 218, so 42% of the band is bright, and the frame is rejected as washed out (> 0.40). **Fail-closed held: 0 non-zero `/cmd_vel`.** |
| `161508` | threshold 220 | Line visible, error -0.03, confidence 0.886. CORE `TRACKING` at linear 0.065 m/s, but `/cmd_vel` stayed at zero. Cause: the borrowed `semantic_road_core.yaml` sets the traffic policy to ENFORCED, which holds with `no_road_evidence`, and no road observer runs here. |
| `161917` | own overlay `map_v2_fleet_core.yaml`, traffic policy DISABLED | 60 s drive through CORE: 2.351 m path, 1,834 non-zero `/cmd_vel`, 197/197 observations visible. Mode OFF gave a final `/cmd_vel` of exactly 0. |

Grey levels measured in run 161132: floor 109, robot body 218, lane paint 224-228.

Every run had **one** `/cmd_vel` publisher, `core`. The other endpoint is the Gazebo `parameter_bridge` subscriber.

## Finding: single-line tracking, not lane keeping

`trajectory_161917.png` plots the run over the track: green marks the start, blue the end, red the path. The robot left the lane centre, moved onto the right-hand boundary line (the inner rectangle's edge), and completed one loop along that single line. The loop closed within 0.099 m.

The cause is structural. `detect_lane_error` (`control/sensing/lane.py`) steers to the centroid of all bright pixels. It was designed for **one line on the floor**. The 260919 track bounds each ~160 mm lane with **two** lines, and the centroid locks onto whichever line dominates the band.

| Gate | Verdict |
|---|---|
| STL -> world, mesh loads in the isolated layout | PASS |
| Camera renders the lane paint | PASS |
| Line evidence -> CORE -> sole final `/cmd_vel` publisher | PASS |
| No evidence -> zero command (fail-closed) | PASS (run 161132) |
| Mode OFF -> final zero | PASS |
| Stays in the lane centre | **FAIL: follows a single boundary line** |
| Roundabout, S-curve, crosswalk semantics | NOT RUN |

Raw logs (`odom_drive.csv`, `line_obs.txt`, `cmd_vel.csv`) are outside Git, in WSL `/rosy_mapv2_ws/evidence/20260922T_map_v2_fleet_<run>/`.
