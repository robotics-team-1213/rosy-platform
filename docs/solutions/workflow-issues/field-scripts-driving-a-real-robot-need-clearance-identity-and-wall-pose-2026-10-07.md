---
title: Field scripts that drive a real robot need the shared clearance check, a confirmed identity, wall-based pose and a loop faster than the watchdog
date: 2026-10-07
category: workflow-issues
module: PC field scripts driving Pinky robots through CORE teleop (rosy-pinky-9dfk, 260919 track)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "an agent or a PC script sends POST /api/v1/teleop to a real robot"
  - "the robot is located or steered from the Rosy Cam overhead image"
  - "in-place turns on carpet are measured with wheel odometry"
  - "a command loop also polls sensors over HTTPS"
symptoms:
  - "a 0.6 m reverse at 0.03 m/s pushed 9dfk against the west wall (LiDAR rear 0.067 m, odom 0.59 m, overhead almost no motion)"
  - "a commanded 111 deg odom turn was about 30 deg on the floor; a 1.5 s turn at 0.25 rad/s gave 3.4 deg"
  - "teleop went out at about 3 Hz, below the 300 ms watchdog, so the robot stopped between commands"
  - "MODE_CONFLICT answers were ignored for 10 minutes while the script kept commanding"
tags: [field-safety, teleop, clearance, robot-body, rosy-cam, lidar-pose, watchdog, odometry, pinky]
---

# Field scripts that drive a real robot need the shared clearance check, a confirmed identity, wall-based pose and a loop faster than the watchdog

## Context

During the D-491 field session on 2026-10-07 an agent drove rosy-pinky-9dfk from PC scripts over the CORE API (motor runtime, release 2026.10.07-051) to check the crosswalk detector and calibrate the floor IR. Several separate mistakes stacked up:

- The script had no clearance check of its own. CORE's D-422 body stop covers line-follow only, not raw teleop, so nothing refused the reverse that touched the wall.
- The agent picked "9dfk" on the overhead image by appearance. It was another robot. 9dfk was across the track with its back to a wall.
- Odom yaw was trusted for in-place turns. On carpet the commanded and actual rotation differed several-fold, and once the odom reading jumped.
- Each command first fetched a LiDAR scan over a new TLS connection (about 1 s), so commands arrived slower than the 300 ms teleop watchdog (`teleop_timeout_ms: 300` in the Pinky profile).
- A cable lay across the robot. LiDAR does not see thin cables. The operator removed it.
- A YAML written for the robot on Windows used the default cp949 encoding and failed to load on the Pi.

## Guidance

1. **Guard every command with the shared body model, never a tool-local number.** Before each teleop, judge the motion with `core_common.robot_body` (`RobotBody.scan_view`, `translation_gap`, `stop_gap_m`, `rotation_clear_m`). The field guard used `dataclasses.replace(PINKY_PRO, lidar_forward_deg=<measured>, latency_s=0.65)` for the remote path. It refused the same reverse (gap 0.018 m < 0.033 m) that had touched the wall. No-return beams whose range_min end lies inside the body outline are self-occlusion, not obstacles; ends outside the body stay obstacles. D-500 (Proposed) moves this check into CORE's command intake so a script cannot skip it.
2. **Confirm identity before the first motion.** Command a few centimetres and check that the robot you are watching moved, or compare the robot camera's view with the overhead scene. The robot camera showing a roundabout ahead while "the robot" stood in a straight lane was the clue that came too late.
3. **Pose from the robot's own LiDAR against the arena walls, not from odom or overhead blobs.** The 260919 walls are an axis-aligned rectangle in the STL. The dominant straight runs of a scan give yaw modulo 90 deg (repeatable to 0.1 deg here), and wall distances give x and y (about 1 cm). Use the overhead position only to pick the 90-degree branch: the right branch put 9dfk within 2.5 cm of the overhead fix. Overhead wheel-blob tracking (D-375 lane-paint homography plus cyan wheels) gave a correct scale (axle 0.097 m vs 0.0971 m) but lost a wheel under the body once the robot rotated.
4. **Keep the command loop faster than the watchdog.** Use one kept-alive HTTPS connection per thread, run the clearance judgement on a background thread, send teleop every 0.1 s, and accept a judgement only if it is newer than the motion request (0.6 s bound here, covered by the 0.65 s latency in the stop gap). Wait for the first judgement before moving.
5. **Check every teleop response.** Treat `MODE_CONFLICT` as a stop: re-enter MANUAL once, loudly, and abort if it repeats. Abort when the measured pose does not progress for three steps.
6. **Look before moving.** Check the robot camera and the overhead image for cables, hands and thin objects the LiDAR cannot see, and ask the people on site when something is attached to the robot.
7. **Write robot files with an explicit encoding** (`encoding="ascii"` or `"utf-8"`) and validate them on the robot (`python3 -c 'import yaml; yaml.safe_load(...)'`) before restarting a service.
8. **Return the robot to IDLE in a `finally`.** Every script left 9dfk in IDLE even when it was killed, and the guard refused motion without fresh evidence.

## Why This Matters

Each item alone looked harmless at 0.02–0.03 m/s. Together they produced a wall contact, ten minutes of silent failure and two crossings in the wrong place, on a robot other sessions also use. The same pattern in `tools/calibration/run_calibration.py` (plain HTTP, a TLS handshake per request, a 0.4 s budget) blocked calibration of any TLS-required robot. The fix is pending on branch `fix/calibration-runner-tls`.

## When to Apply

- Any agent or bench script that moves a real robot outside CORE's own autonomous modes, until D-500's CORE intake check ships.
- Any procedure that turns in place on carpet and relies on the angle reached.

## Examples

Guard decisions at the wall, before and after moving away (robot-frame gaps from the shared body model, remote latency 0.65 s, 0.02 m/s):

```text
fwd gap 1.246 need 0.033 -> allowed
rev gap 0.018 need 0.033 -> REFUSED      (the reverse that touched the wall)
rot nearest 0.101 need 0.093 -> allowed
```

LiDAR-wall pose, two reads 1 s apart: `yaw -65.4 deg, x -1.035, y -0.241` and `-65.6 deg, -1.036, -0.240`.

## Related

- D-500 measured motion response and clearance budget (Proposed)
- D-422 / D-424 body-referenced stop and shared RobotBody
- `docs/solutions/workflow-issues/ir-line-calibration-by-guided-line-crossing-2026-10-07.md`
