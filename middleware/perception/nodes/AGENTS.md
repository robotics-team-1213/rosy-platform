<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-06 | Updated: 2026-09-24 -->

# nodes/ (ROS composition)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose
This folder supplies ROS composition modules installed in the existing `control` Python package: the sensor provider, calibration transport/storage, observation payloads and operator adapters. D-630 moved the sensor and vision implementations to `middleware/perception/sensors/sensing` and `middleware/perception/front_camera/perception`, and the Drive implementations to `middleware/drive/`.

Five compatibility package directories in `../control/` preserve `control.control`, `control.sensing`, `control.planning`, `control.safety` and `control.wander`. Their initializers are active source import/build contracts. The pure `control.control.*` modules have one canonical source across Drive motion limits, tracking, recovery and calibration; their installed import names remain unchanged. See the [current platform folder guide](../../../docs/reference/platform-folder-responsibilities.md) and [distribution guide](../AGENTS.md).

D-649 additionally moves the actual `control_node`, `goal_node`, `wander_node` and `safety_node` entry modules to `middleware/drive/runtime`; the names below refer to their installed identities. This folder retains sensor/provider/observation composition, general calibration storage and observer adapters. The five initializer directories in `../control/` contain no algorithm copies.

D-747 moves location assist/status to `../localization`, graph health to `../graph_health`, snapshot triggers to `../snapshots`, line observation to `../sensors/line_observation`, and object evidence to `../front_camera/object_observation`. Dedicated adapters live with their judgments. The filenames below describe preserved installed identities; they are not all source files in this folder. Calibration command/storage, recording process/file IO, provider/executor/TF/web composition live here after S3.

## Key Files
| File | Description |
|------|-------------|
| `../control/_source_layout.py` | Static canonical holder mapping; `CONTROL_ROOTS` selects composition modules for the installed `control` package. The four package facades load their canonical source package, while `control.control` adds only the four declared Drive module roots to its package path |
| `wander_node.py` | Entry wrapper — re-exports `WanderNode`/`main` from `wander/` |
| `safety_node.py` | Entry wrapper for the safety gate node |
| `calib_node.py` | Relative `calib/step` FSM; saves one explicitly configured calibration file and requests safety parameters. Bound records validate device/generation context. Parameter acknowledgement does not prove policy adoption |
| `ir_overlay.py` | D-344 §12: validates the optional `/etc/rosy/ir_calibration.yaml` observer overlay for `camera_preview.launch.py`; malformed files are skipped with a reason, never handed to the node. Addendum 2026-10-03: also the operator override overlay `/etc/rosy/line_observer_overrides.yaml` (allowlisted camera lane keys, layered last) |
| `line_observer_overrides.py` | D-344 §12 addendum 2026-10-03: console script that writes/removes `/etc/rosy/line_observer_overrides.yaml` (bench keep/NOMINAL) and restarts only `rosy-camera`; replaces editing the release's `line_follow.yaml`, which every update drops; source in `../sensors/line_observation` beside the `ir_overlay.py` reader (D-766) |
| `calibration_record.py` / `calibration_storage.py` / `calibration_lock.py` | Versioned context/digest envelope, fixed runtime path, revision checks and locked atomic save; verified runtime consumer and authenticated identity source remain pending |
| `camera_power.py` | D-440 `CameraPowerMixin` for `camera_detect_node`: follows CORE's latched `power/devices` board (pause capture → `camera/blocked` true, reduced = one tick in four via the ROS-free `camera_power_gate.py`), restarts with a fresh lock and warmup, reports `power/device_ready` |
| `camera_detect_node.py` | OV5647 capture (BGR8, rotated 180°) through `control.sensing.perception.camera_worker`, controls, classifier and policy; canonical source is in `../front_camera/perception`. Publishes `/camera/blocked|side|observation|telemetry|controls`. `/camera/cliff` is always false: a monocular camera cannot separate a dark wall from a dark hole, so floor IR owns that decision |
| `control_node.py` | odom-P straight/rotate controller driven by `/goal_distance`, `/goal_rotate` |
| `goal_node.py` | Map point-to-go: `/map`+TF → `/goal_point`, `/route`; thin I/O over `planning.GoalBrain`; advisory only, never touches `/cmd_vel_raw` |
| `watch_node.py` | Graph health: required nodes, exclusive topic ownership, foreign-node detection → `/robot/ok|health|interrupt` |
| `watch.py` | Pure graph-inspect logic (ROS-free), covered by `test_watch.py` |
| `line_observer_node.py` | Normalised white-line evidence from IR reflectance or camera frames; `route_followers.py` composes the `control.sensing.perception.route_*` followers from `../front_camera/perception`. `route_a`/`route_b`/`route_ab` fail closed without `lane_graph_path`/`route`/`route_start`; `line/debug` is an optional overlay |
| `loc_assist.py` | D-395 P2-3 ROS-free `LocAssist` core: search timing, `localization/state`/`candidates`/`result` payloads, per-source injection covariance; `search`, `pooled_grid`, `lane_rules_near` |
| `loc_assist_node.py` | D-395 P2-3 ROS adapter for `LocAssist`; `initialpose` only for an accepted decision. Off on the device (`enable_loc_assist`), on in gz_multi nav |
| `dock_observer_node.py` | Camera frames → `dock/observation` via `sensing/dock_observer`; owns no motion. Only the Gazebo camera (`camera_geometry_source` GAZEBO under `use_sim_time`) may use the declared height/pitch/hfov/offset; any other source fails closed (every frame publishes not-visible) |

## Related import facades
| Directory | Purpose |
|-----------|---------|
| `../control/control/` | Initializer for the preserved `control.control` identity; pure modules live in Drive motion limits/tracking/recovery/calibration (see [import compatibility guide](../control/AGENTS.md)) |
| `../control/planning/` | Source initializer facade for `middleware/drive/planning/grid`; installed as `control.planning` |
| `../control/safety/` | Source initializer facade for `middleware/drive/motion_limits/adapter`; installed as `control.safety` |
| `../control/sensing/` | Source initializer facade for `middleware/perception/sensors/sensing`; its `control.sensing.perception` child lives in `middleware/perception/front_camera/perception` |
| `../control/wander/` | Source initializer facade for `middleware/drive/tracking/wander`; installed as `control.wander` |

`../setup.py` uses ordinary `package_dir` mappings for the moved subpackages and a narrow build step for the flat `control.control` modules. It installs one copy under each existing identity. The self-contained sdist includes the declared Drive source snapshot; the wheel contains the installed packages and the unchanged `share/control` resources.

## For AI Agents

### Working In This Directory
- Sensor/provider/observation composition stays here; the four legacy Drive entry modules live in Drive runtime. New pure sensor, vision or Drive decisions belong in their canonical holder; preserve existing `control.*` imports and monkeypatch identity.
- Keep the existing `setup.py` entry points, executor selector and `KeyboardInterrupt`-safe shutdown shape.
- Shutdown behavior remains with the actual adapter (`middleware/drive/tracking/wander/node.py:stop_motors`). CORE remains the operational final `/cmd_vel` authority; the legacy writer is not activated by this folder layout.

### Testing Requirements
- ROS-free adapter characterization, executor/QoS scans and pure composition modules such as `../graph_health/watch.py` are covered by `../test/`; ROS transport behavior needs separate Jazzy evidence.
- `../test/test_responsibility_layout.py` checks source holders, isolated sdist/wheel installation, provider identity, unique module copies and map bytes. Run pytest through the committed-HEAD remote runner from the repository root (D-584).

### Common Patterns
- Docstring convention: `"""Subject: <one concern>. …"""` — one subject per module/mixin.
- English comments/logs; explain *why* against hardware limits.

## Dependencies

### Internal
- `../config/` and `../launch/` retain parameter, provider and ROS package-share ownership; `robot.yaml` is loaded before per-node overrides. Canonical sensor/vision/Drive source holders are mapped by `../control/_source_layout.py`.

### External
- `rclpy`, `std_msgs`, `geometry_msgs`, `nav_msgs`, `sensor_msgs`, `picamera2` (camera node), `tf_transformations`.

<!-- MANUAL: -->
