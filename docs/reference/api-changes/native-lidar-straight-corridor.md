---
surface: core
kind: additive
slug: native-lidar-straight-corridor
date: 2026-11-26
title: Read-only straight LiDAR corridor observation
---
Viewer GET /api/v1/sensors/lidar/corridor accepts direction (forward or reverse) and distance_m greater than zero and at most 0.03 m. Returns observed_clear, blocked or unknown for the required beams of one body-frame scan plane with native scan and receipt timestamps. Fleet peer identity, site-route clearance and motion require their respective owners.

The receipt names the robot, direction and requested distance in metres, the scan frame,
the ROS source timestamp in nanoseconds, and the CORE receipt/check times in Unix seconds.
The source and receipt fields are null when unavailable. The required and observed beam counts
describe the scan-plane leading strip. Both directions include the configured tray footprint.
An unknown native beam, a hardware near-range blind band, a masking or occluding object, stale
source data, and an unrecognized frame prevent a positive observation. Other heights and motion
after this scan are outside the observation.
