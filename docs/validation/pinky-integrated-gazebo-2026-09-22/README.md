# Pinky Pro integrated Gazebo acceptance — 2026-09-22

## Verdict

`ROS-SIM: PASS` for one run-bound mapping, camera perception, and Nav2
acceptance execution. The physical Pinky Pro remains `NOT_TESTED`.

The run used the unchanged measured 16-wall world and a conservative circular
Pinky envelope: 0.172 m diameter plus 0.010 m required body clearance. CORE
was the sole final `cmd_vel` publisher throughout the run.

## Reproduction

From a ROS 2 Jazzy Linux environment with the workspace installed:

```bash
export ROS_DOMAIN_ID=212
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
ros2 launch gz_sim pinky_integrated_acceptance.launch.py \
  run_id:=20260922T_pinky_integrated_05 \
  output_path:=/tmp/pinky-integrated/result.json \
  timeout_wall_s:=1800 \
  gazebo_gui:=false \
  camera_update_rate:=2
```

The acceptance result is the run-bound JSON, not the launch process exit code.
On this WSL/Gazebo 8.11 host, Gazebo's child server did not exit within the
launch service's five-second SIGINT grace period and launch reported a teardown
error after the collector had atomically written a passing terminal result.

## Observed result

| Gate | Result |
|---|---:|
| Mapping route | 52/52, 14.1411 m before Nav2 |
| Full recorded trajectory | 14.51684 m |
| Collision | false |
| Minimum body clearance | 0.022132 m (required 0.010 m) |
| Robot-reachable map | 0% unknown, occupied, or outside raster |
| Gazebo camera | 584 frames at 320 x 180 |
| White lane while moving | detected, confidence 1.0 |
| Road semantics | lane, stop line, crosswalk detected |
| Nav2 goal | `SUCCEEDED`, 0.029071 m position error |
| Final command | `[0.0, 0.0]`, stable |
| Final `cmd_vel` publishers | `/core` only |

`result.json` records `passed: true` and every integrated safety/evidence gate
as true. Its source hashes bind the result to the exact world and wall geometry.

## Boundaries

- Full-raster wall fidelity remains `HOLD_FULL_RASTER_FIDELITY`: minimum wall
  surface recall was 85.0365%, below the separate 98% research target. This is
  not substituted for the robot-reachable configuration-space gate, which
  passed with complete known free space.
- The camera result covers the implemented white lane, stop line, and crosswalk
  semantics. It does not claim general object recognition.
- This simulation does not prove physical wheel slip, braking distance, camera
  mounting/calibration, lighting robustness, or real-device emergency-stop
  behavior. Those require a supervised physical Pinky Pro run.

## Evidence

- [`result.json`](result.json) — authoritative terminal result for
  `20260922T_pinky_integrated_05`.
