<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-24 -->

# sensing/ (raw data → robot-frame geometry)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose
Pure logic (no ROS) for scan geometry, filtering, and footprint (D-229). Camera and lane evidence is `perception/`, not this package root. This package does not import `perception` and does not publish `cmd_vel`.

## Key Files
| File | Description |
|------|-------------|
| `lidar.py` | C1 scan geometry, the one shared heading: `NOSE_YAW = π` (D-397), sector ranges at 10th percentile (`scan_pctl`), frontier/straight-route finders feeding `/safety/frontier_*`, `/safety/route_*`. See rules for `robot_yaw()`/`wrap_pi()` and `is_robot_scan()` |
| `range_tilt.py` | `parse_us_range` (US Range → metres, None for no-echo/blind zone) and `roll_pitch` (quaternion → tilt). The safety adapters (bumper, hazard) and calibration both use these one copies |
| `filt.py` | Median + 1st-order low-pass filters for jumpy sensors |
| `body.py` | Robot circumradius from URDF (calib param wins if sane); `ignore_m` drops chassis hits; `turn_clear_m` for spin clearance |
| `perception/` | Camera and lane evidence. Import `control.sensing.perception`, not this package root. See `perception/AGENTS.md` |
| `dock_tag.py` | ArUco dock tag → relative pose; optional `CameraMount` gives base_link pose and tag yaw. Picks the ArUco API by `hasattr` (OpenCV 4.6 on the device, 4.7+ on hosts). Not perception |
| `dock_observer.py` | One camera frame → one `dock/observation` wire payload |
| `loc_candidates.py` | D-395 pose hypotheses: `global_candidates` (every distinct pose, mirror included), `slot_candidates` (reference square axis and axis+180), `merge`; base/sensor transforms through `Mount` |
| `loc_objects.py` | D-395 `unmapped_objects`: unexplained lidar returns as base_link objects (other robots); clusters wrap across the scan seam |
| `loc_verify.py` | D-395 `InjectionCheck`: 0.5 s settle + 3 s of fit ≥ 0.85; cannot reject a mirror on a symmetric map |
| `loc_state.py` | D-395 `LocalizationStateMachine` UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT; a decision needs a scan-asymmetric cue (or a human) and lapses 5 s after receipt; autonomy only when LOCALIZED |

## For AI Agents

### Working In This Directory
- The nose-yaw trap: any new use of scan angles must go through `robot_yaw()`/`wrap_pi()` — scan angle 0 is the **rear**, nose = 180° nominal (measured 181–182°).
- `lidar.py`: an accepted lidar_mount record refines `NOSE_YAW`. `is_robot_scan()` rejects remote gazebo scans (beam count + range_max + wall-clock stamp) unless an isolated rig called `enable_simulation_scans()`.
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
