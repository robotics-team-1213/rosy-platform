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

## Supervised device preflight — 22:16 KST

The D-512 `tools/device_test/run.py --preflight-only` check against `rosy_26` succeeded. It confirmed SSH hostname `rosy-pinky-9dfk`, CORE robot ID `rosy_26`, `IDLE`, battery 100%, and `localization: null`; it captured a new site overhead JPEG, robot front JPEG, and LiDAR body-gap advisory. This used the existing D-476 bridge plan for its read-only preflight only; it did **not** execute that bridge plan or a lane choice. Raw evidence, frame digests, the camera-verdict template, and the preflight summary are under `X:/DevTemp/lane-choice-20261008/device-preflight/`.

The overhead frame showed two robots and cables, but did not establish which image target matched `rosy_26` or prove its turning path clear. The robot front frame showed a right-lane prediction with unclassified regions, not a confirmed junction. A documented non-motion `POST /host/lamp/identify` returned 200 `pending_visual_confirmation` for `rosy_26`; subsequent overhead frames did not visibly confirm the blink, so image identity remains unconfirmed. Fleet still reported `UNKNOWN` map pose and `junction_turn: false` for both robots. **No wheel motion or junction instruction was sent.** The physical lane-choice test remains **HOLD** at camera identity/path clearance and the junction admission gate.

## Image identity follow-up — 22:37 KST

After the operator asked the agent to resolve identity from the cameras, both robot front frames and another overhead sequence were captured. The documented `POST /host/hardware/test {device:"lamp"}` on authenticated `rosy_26` returned a request ID. In the overhead sequence, the upper-left robot gained a visible red light and its red-pixel count in the robot crop rose from 17 before the request to 87–106 during the request; the lower-right and upper-edge robot crops remained at zero red pixels. This is strong correlation that the **upper-left chassis is `rosy_26`**, but the hardware result reported `failed` because `lamp_selftest` did not finish within 10 seconds. It is therefore not a completed lamp acceptance or a Fleet-trusted identity. The hardware test service was inactive afterward, with `rosy-face` and CORE active and no `lamp_selftest` process. The upper-left light remained red in a later frame; its meaning was not established by this check.

The later overhead frame showed a third robot at the top edge and a person beside the upper-left part of the track. `rosy_26` remained `IDLE`, line-follow `OFF`, E-Stop clear, velocity zero. Fleet still reported both map poses `UNKNOWN` and the installed camera calibration `display-only`; its odom future refusal had cleared to zero, which did not supply a map anchor. The visible cable/track area and junction gate still do not admit a lane-choice drive. No wheel motion, line-follow activation, or junction instruction was sent.
