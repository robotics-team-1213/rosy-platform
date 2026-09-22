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
| Stays in the lane centre (single-line mode) | **FAIL: follows a single boundary line**. Replaced by lane mode below |
| Roundabout, S-curve, crosswalk semantics | NOT RUN |

## Two-line lane mode (the user chose lane-centre keeping)

`detect_lane_centre` (`f96320f`, `052f2fa`) projects bright runs to floor metres with the declared Gazebo `GroundPlane`. In each row it pairs the two runs whose spacing is closest to the lane width (2 x 0.0925 m) and steers to their midpoint. With no ground model it returns None, so an uncalibrated Device camera never drives in this mode.

| Run | Change | Result |
|---|---|---|
| `163244` / `163611` | first lane detector | error 0.0 at the lane centre. Confidence fell 0.67 -> 0.33 near the crosswalk and CORE went LOST (min 0.35) after 7 cm. Causes: rows that cannot see a centred lane were counted, and crosswalk bars (parallel to travel) were paired as lane lines. |
| `164241` | width pairing + observable rows only | All 26 captured frames read conf 1.0 offline. Live, the crosswalk lit 48-54% of the band, above the 0.40 washed-out cut, so it went LOST. |
| `164757` | washed-out cut 0.75 (map_v2_fleet launch only) | **0.556 m along the lane centre through the crosswalk; x stayed within 1.0 mm of the centre** (-1.27057..-1.26955). Stopped fail-closed at y -0.41, where the inner block ends and the lane turns 90 deg (`trajectory_164757_lane.png`, `camera_corner_164757.png`). |

| Lane-mode gate | Verdict |
|---|---|
| Straight lane centre keeping | PASS (1 mm, run 164757) |
| Crosswalk bars inside the lane | PASS |
| 90 deg corner | **PASS** (run 184434, corner turning `e3b5eff`) |
| 45 deg bend toward the roundabout | HOLD in 'lane' mode; **PASS in edge_left** (below) |
| Sitting on a shared boundary line | HOLD: single frame ambiguous, needs lane memory across frames |

## Corner turning (the user chose to implement it)

`LaneCornerTracker` (`e3b5eff`) confirms an L-corner over 2 frames: a transverse line ahead plus one side line that ends, which marks the open side. The line observer then drives the odometry-measured distance to the junction centre and emits a full-lock error until the odom yaw has turned 75-105 deg and the new lane has been reacquired. Without odometry, or on a timeout or overshoot, it emits no lane, so CORE stops. CORE and its command law are unchanged, and CORE remains the only `/cmd_vel` publisher.

Run `184434` (`trajectory_184434_corner.png`):
- 1.142 m in total. Down the left lane and through the crosswalk, then a left turn at the bottom-left corner, then about 0.57 m east along the bottom corridor.
- In the turn it overshot 2.7 cm toward the outer line (y min -0.538). It then settled within 8 mm of the corridor centre (mean y -0.5037 vs -0.511).
- It stopped fail-closed at x -0.69, where both lines bend 45 deg toward the roundabout. That geometry is neither a straight lane nor an L-corner.

## Full lap: `edge_left` mode (the user chose bends and curves)

On the lap the robot started on, the line on its left is always the inner block's outline: its left and bottom edges, both chevron bends (about 65 deg), the concave arc that forms the roundabout's left side, and the top edge. `edge_left` (`5f17ed8`, `3a1b73b`, `49ca068`, in `control/sensing/lane_bev.py`) works as follows:
- It projects the thresholded frame to a 2.5 mm bird's-eye grid in base_link.
- It keeps the left boundary (and the right boundary of the same lane) as odometry-carried memory, re-seen within 0.40 m of travel or dropped.
- It follows the iso-line at h - lw/2 from the boundary with pure pursuit (lookahead 0.15-0.25 m), inverting CORE's command law so that CORE drives the computed curvature.
- With no supported lookahead point it outputs no lane, so CORE stops. `LaneCornerTracker` stays armed as a fallback.

| Run | Change | Result |
|---|---|---|
| `193728` | edge_left, threshold 220 | Never moved. Gazebo dims paint with range: 226 at 0.12 m, 214 at 0.44 m. The left line never seeded, so the run went LOST (fail-closed). |
| `194559` | threshold 180 (the bird's-eye view starts at 0.09 m, beyond the 218-grey body rows) | **Full lap: back within 2.9 mm of the start after 3.086 m of travel, heading -87.5 deg.** It then continued through most of a second lap: 5.96 m in total, 620/620 observations visible at confidence >= 0.35, still TRACKING when the window closed (`trajectory_194559_lap.png`). |
| `202739` | after review fix `4d3d811` (stale odom / memory age caps) | 1.335 m, still TRACKING when the window closed. The sim ran at half speed (camera 1.7 Hz, host load 9.5). Not a lap, not a failure. |
| `204552` | same, 420 s window | **Full lap again: back within 4.3 mm of the start after 3.059 m**, 609/609 observations visible. One transient `observation_stale` HOLD (age 0.424 s > 0.3 s, from slow sim frames) recovered on the next frame. |

Review fix `4d3d811`:
- Odom older than 0.3 s against the image stamp counts as no pose, so there is no lane output.
- Memory-only output is capped by the clock (`MEMORY_MAX_AGE_S` = 16.5 s, derived from 0.40 m at the slowest memory-only speed).
- Armed corners expire by time.
- The reviewer's frozen-odom repro, which previously drove for 600 s, now stops after 82 frames.

The 2.9 mm closure was re-measured independently from `odom_drive.csv`: the minimum distance to the start after 2 m of travel. Host suites: 1327 passed, 29 skipped.

| Lap gate | Verdict |
|---|---|
| Straights, crosswalk, both 90 deg corners, chevron bends, roundabout left arc | PASS (ROS-SIM) |
| Other routes (east S-curve loop, circling the island) | NOT SUPPORTED: left-edge following has no junction choice |
| Real Pinky: wheel-odom memory, lighting, camera calibration | NOT RUN (edge_left needs a ground model; only the Gazebo one exists) |

Raw logs (`odom_drive.csv`, `line_obs.txt`, `cmd_vel.csv`) are outside Git, in WSL `/rosy_mapv2_ws/evidence/20260922T_map_v2_fleet_<run>/`.
