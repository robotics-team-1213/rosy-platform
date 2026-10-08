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

## What the operator should do now

1. **Keep both robots stopped.** Leave E-Stop access clear and keep people and loose cable out of the intended lane. Keep the site PC and ceiling camera on.
2. **Prepare the physical markers.** `X:/DevTemp/lane-choice-20261008/aruco-provisional.pdf` contains proposed `DICT_4X4_50` IDs 30–33 for four fixed map points and ID 7 for `rosy_26`. Print at **100%** and measure the printed squares (120 mm map, 60 mm robot). The PDF is a preparation artifact; these IDs are not yet in the installed site configuration. Place the four fixed markers flat, fully visible to the ceiling camera and outside the robot path. Put ID 7 flat on `rosy_26` without covering its camera, vents, controls, or cable. Record which ID is where and the robot marker's orientation. The map origin is the inner-track centre, +x right and +y up; use surveyed map metres for the four fixed marker centres. Do not infer the coordinates from image corners alone.
3. **Send the marker placement photo and measured positions.** I can then update the site marker configuration using those surveyed points, verify fresh detections and authenticated sightings, and require Fleet `LOCALIZED` map pose. I will check live IR, keep-mode and motion evidence before asking CORE for `junction_turn:true` through its normal gate.

The physical branch run stays HOLD until those gates pass and the wrong-way simulation case is resolved. A marker detection or a healthy service by itself is not field acceptance.
