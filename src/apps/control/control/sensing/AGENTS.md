<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-24 -->

# sensing/ (raw data → robot-frame geometry)

## Purpose
Pure logic (no ROS) turning raw sensor data into robot-frame geometry one subject per module: scan geometry, filtering, footprint, camera classification. Consumed by safety, wander, calib, and the web/LCD stack.

## Key Files
| File | Description |
|------|-------------|
| `lidar.py` | C1 scan geometry — the one heading everyone shares. `NOSE_YAW = π + 10°` (scan 0° is the rear); every heading through `robot_yaw()`/`wrap_pi()`. Sector ranges use a 10th percentile (`scan_pctl`); `is_robot_scan()` rejects remote gazebo scans (beam count + range_max + wall-clock stamp) unless an isolated rig called `enable_simulation_scans()`; frontier/straight-route finders feed `/safety/frontier_*`, `/safety/route_*` |
| `filt.py` | Median + 1st-order low-pass filters for jumpy sensors |
| `body.py` | Robot circumradius from URDF (calib param wins if sane); `ignore_m` drops chassis hits; `turn_clear_m` for spin clearance |
| `camera.py` | HSV floor/void/obstacle classification (`classify_frame`) behind `camera_detect_node` |
| `camera_worker.py` | ROS-free frame validation, rotation, drop/latency accounting and profile telemetry |
| `lane_boundaries.py` | Both lane boundaries, centre-line following with a fallback ladder |
| `lane_route.py` | Route model shared by the junction prototypes: directed `lane_graph` segments, progress along them, distance to the next node, exit tangent |
| `lane_coverage.py` | All-lane coverage tour over `lane_graph` (lane-network mission stage 2) |
| `lane_debug.py` | Four-panel picture of one lane-following decision (debug overlay) |
| `paint_localizer.py` | Prototype B pose: particle filter over the checked-in paint map |
| `route_camera.py` | Prototype A: camera lane keeping with route-driven junction manoeuvres |
| `route_map.py` | Prototype B steering: the planned route pursued from the paint pose |
| `route_hybrid.py` | `route_ab`: prototype B's pose steering prototype A's camera-first logic |
| `dock_tag.py` | ArUco dock tag → relative pose; optional `CameraMount` gives base_link pose and tag yaw. Picks the ArUco API by `hasattr` (OpenCV 4.6 on the device, 4.7+ on hosts) |
| `dock_observer.py` | One camera frame → one `dock/observation` wire payload |

## For AI Agents

### Working In This Directory
- The nose-yaw trap: any new use of scan angles must go through `robot_yaw()`/`wrap_pi()` — scan angle 0 is the **rear**, nose ≈ 190°.
- Keep modules ROS-free; callbacks and publishers belong to the nodes.
- No-echo conventions: lidar beyond 8 m is the trust horizon, US beyond `US_NOSE_MAX_M` (0.80) is noise — defined once in `control/modes.py`, don't restate them here.

### Testing Requirements
- `python3 -m pytest test/test_lidar*.py test/test_body.py test/test_filt.py -q` (whichever apply).
- Geometry fixes need a boundary test (e.g., nose-yaw wrap at ±π).

### Common Patterns
- One subject per module, `"""Subject: …"""` docstring, hardware-limit comments in English.

## Dependencies

### Internal
- `control/modes.py` owns the shared distance cutoffs; safety/wander/calib consume this geometry.

### External
- `math`, `numpy` only.

<!-- MANUAL: -->
