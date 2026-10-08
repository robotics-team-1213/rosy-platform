# Real Pinky lane-choice field review — 2026-10-08 21:00 KST

**Decision: HOLD.** This is a contemporaneous site and device readback, not a physical lane-choice run. No motion, junction instruction, E-Stop change, robot configuration change, or release was sent. Source checkout: `1a303f92e43612a457b7334d7465f94977640587`; this SHA identifies the review's source reference, not the installed robot or site images.

## What was observed

| Evidence tier | Readback at review | Limit |
|---|---|---|
| Site runtime | The site PC rebooted at 20:50:55 KST. The site stack was active and its loopback HTTPS health returned 200. Fleet and Vision served requests after reboot. | Service health does not prove a usable route or robot motion. |
| Device | Fleet listed `rosy_26` and `rosy_60` online. Earlier authenticated CORE reads found both IDLE, E-Stop clear, and line-follow OFF. | These are readbacks at their respective times, not an ongoing clearance certificate. |
| Ceiling camera | A fresh `ceiling_north` JPEG was obtained. OpenCV `DICT_4X4_50` found **zero marker IDs**. | The frame alone does not identify either robot or a clear drive path. |
| Installed Vision configuration | `corner_marker_ids: null`, `robot_markers: {}` for `ceiling_north`; the configured map is `map_v2_fleet`. | Vision requires four configured map markers and a robot marker in one frame to publish a robot sighting. |
| Fleet map pose | Both trip poses were `UNKNOWN`; after the reboot `odom_refused` was 0. The available overhead calibration is marked `display-only`. | There is no trusted sighting anchor for a trip. The display calibration is not motion authority. |
| Junction admission | Fleet advertised `junction_turn: false` for both robots and had no running trip. | A lane trip cannot pass the documented start gate while this remains false. |
| Earlier ROS-SIM | The recorded Fleet lane lap completed 0/20 runs and included wrong-way travel near a junction. | Simulation evidence; no physical run in this review. |

The raw field notes and captured images are under `X:/DevTemp/lane-choice-20261008/`. The ceiling frame SHA-256 is `ec3b4c60a58a497e635d80dd976292384d8b6dd6830b3b551b26388fd02da7dc`. Temporary robot login tokens were logged out and removed.

## Direct control follow-up — 21:08 KST

The operator clarified that the agent should control the robot for this test. The provisional marker PDF under `X:/DevTemp/lane-choice-20261008/` was neither printed nor installed and is not an operator action for this run.

Authenticated CORE readback from `rosy_26` at this follow-up: `mode: IDLE`, `safety.estop: false`, battery 100%, `line_follow.mode: OFF`, junction idle, motor drive ready, `localization: null`. A fresh front frame showed a left lane and unclassified regions; it did not show a confirmed junction or the clearance around the robot. Tailscale reported the site PC offline, and `tailscale ping` timed out. Therefore the agent could not obtain a fresh overhead frame to identify the robot and its cable/path. No motion or junction instruction was sent in this follow-up. The temporary CORE token was logged out after the read.

The intended next run is supervised direct CORE control of one identified robot, with the live overhead and front views, tether/path check, hold deadman, and stop available. Recheck the site link and a fresh camera verdict before starting. A Fleet lane trip still needs trusted map pose and junction admission; the current readback does not establish either. The physical lane-choice result remains **HOLD**.

## Site recovery check — 21:31 KST

Tailscale again reported the site PC online. Authenticated SSH found its Wi-Fi address had changed from the earlier readback; `rosy-site-stack` was active and loopback `/healthz` returned 200. A new `ceiling_north` frame showed both robots and cables. The frame does not establish which robot is `rosy_26`, and the intended turning path is not yet cleared by a camera verdict.

Fresh Fleet readback reported both robots online, no running trip, `map-pose.state: UNKNOWN` for each, and `odom_refused_reason: future`. The installed calibration remains `display-only`. Both advertised `junction_turn: false` (`rosy_26` advertised `junction_pivot: true`, which alone is not junction admission). The site connection is restored, but these readbacks do not clear a physical lane-choice run. No motion, junction instruction, or safety-state change was sent in this check.
