---
title: Pinky simulated bay T guide needs an approach window
category: runtime-errors
problem_type: runtime_error
date: 2026-11-24
tags: [gazebo, pinky, camera-line, junction]
---

The C2 camera drive in the archived 261026 Gazebo world reported `no_boundary` before P2 despite visible magenta paint. At simulation times 28.2 to 29.4 seconds, the accepted forward fit shrank from 110 to 60 mm. Its far end was about 37–42 mm before the transverse fit. After the longitudinal fit disappeared the robot still saw the bar at about 203 mm ahead. The standard junction rules require a boundary that diverges or forks and therefore missed this T.

Use the isolated single-tape simulation mode to recognize the centered stem that terminates at a bar. The fit gap is bounded by the extractor's continuity allowance. A bar alone, a disconnected stem and a guide that continues past the bar do not authorize the classification. An initial implementation recognized P2 from 429 mm away and held close to the spawn. The 300 mm simulated approach window keeps that early sighting from initiating the wait.

Run `tools/sim/world_pinky_camera_drive.py --pink-centerline --expect-p2-hold` through the isolated remote simulation runner. Commit `241b7798b3` moved the model from y=0.470 to y=0.311 m, reported `junction_waiting` across three advancing odometry samples and kept both speeds at zero. Immobilized camera JPEGs at y=0.255 and y=0.219 m confirm the visual shape before and after the tracking failure. The run does not issue a turn request. Use the standard CORE approach and Fleet grant path to verify the next maneuver on registered geometry.
