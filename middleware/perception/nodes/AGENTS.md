<!-- Parent: ../AGENTS.md -->

# nodes/ (ROS composition)

**Parent context:** `../AGENTS.md`

## Purpose
ROS composition modules installed in the existing `control` package: sensor provider, calibration transport/storage, observation payloads, operator adapters. D-630/D-649/D-747 moved the sensor, vision, Drive and location/graph-health/snapshot/line-observation/object-evidence implementations to their holders; filenames in this folder's docs and launch files are preserved installed identities, not all source files here. Holder mapping: `../control/_source_layout.py`. Guides: [platform folders](../../../docs/reference/platform-folder-responsibilities.md), [distribution](../AGENTS.md), [import facades](../control/AGENTS.md).

The five directories in `../control/` (`control`, `sensing`, `planning`, `safety`, `wander`) are source initializer facades preserving `control.*` identities; their initializers are active import/build contracts and hold no algorithm copies. `../setup.py` installs one copy under each identity; the sdist includes the declared Drive source snapshot.

## For AI Agents

### Working In This Directory
- Sensor/provider/observation composition stays here; the four legacy Drive entry modules (`control_node`, `goal_node`, `wander_node`, `safety_node`) live in `middleware/drive/runtime`. New pure sensor, vision or Drive decisions go in their canonical holder;
- preserve `control.*` imports and monkeypatch identity.
- Keep the existing `setup.py` entry points, executor selector and `KeyboardInterrupt`-safe shutdown shape.
- Shutdown stays with the actual adapter (`middleware/drive/tracking/wander/node.py:stop_motors`). CORE remains the operational final `/cmd_vel` authority; this layout does not activate the legacy writer.
- `ir_overlay.py` (D-344 §12) validates `/etc/rosy/ir_calibration.yaml` and the operator override overlay `/etc/rosy/line_observer_overrides.yaml` (allowlisted camera lane keys, layered last); malformed files are skipped with a reason, never handed to the node.
- `line_observer_overrides.py` writes/removes it and restarts only `rosy-camera`.
- `/camera/cliff` is always false: a monocular camera cannot separate a dark wall from a dark hole, so floor IR owns that decision.
- `dock_observer_node.py` owns no motion. Only the Gazebo camera (`camera_geometry_source` GAZEBO under `use_sim_time`) may use the declared height/pitch/hfov/offset; any other source fails closed.
- Calibration: parameter acknowledgement does not prove policy adoption; bound records validate device/generation context. `route_a`/`route_b`/`route_ab` fail closed without `lane_graph_path`/`route`/`route_start`.
- `loc_assist_node` publishes `initialpose` only for an accepted decision; off on the device (`enable_loc_assist`).
- Docstring convention: `"""Subject: <one concern>. …"""`, one subject per module/mixin. English comments/logs.

### Testing Requirements
- ROS-free adapter characterization, executor/QoS scans and pure composition modules are covered by `../test/`; ROS transport behavior needs separate Jazzy evidence.
- `../test/test_responsibility_layout.py` checks source holders, isolated sdist/wheel installation, provider identity, unique module copies and map bytes. Run pytest through the committed-HEAD remote runner from the repository root (D-584).

<!-- MANUAL: -->
