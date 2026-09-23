<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-14 -->

# gz_sim

## Purpose

Gazebo simulation: worlds, models, ros_gz bridge params, lamp plugin, and `gz_multi.launch.py` for N namespaced robots (`rosy_01` …).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_cmake; ros_gz, gz_ros2_control |
| `CMakeLists.txt` | Installs launch, worlds, models, params, plugins. **`return()` on aarch64** — do not "fix" that skip |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `launch/` | `gz_multi.launch.py`, `launch_sim.launch.xml` (see `launch/AGENTS.md`) |
| `worlds/` | `rosy_factory.world`, `rosy_map.world`, `empty.world`, `default.sdf` (see `worlds/AGENTS.md`) |
| `models/` | Robot/shelf meshes and SDF (see `models/AGENTS.md`) |
| `params/` | `rosy_bridge.yaml` ros_gz topic maps |
| `plugins/` | `gz_lamp_control_plugin.cpp/.hpp` |
| `scripts/` | Swarm formation bench (no rclpy; uses `fleet`) (see `scripts/AGENTS.md`) |
| `test/` | `gz_multi.launch.py` identity/port contracts (see `test/AGENTS.md`) |

## For AI Agents

### Working In This Directory

Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.

```bash
ros2 launch gz_sim gz_multi.launch.py robots:=2
ros2 launch gz_sim gz_multi.launch.py robots:=3 mode:=slam headless:=true
```

- One Gazebo server; per-robot RSP, spawn, and ros_gz bridge with namespaced `cmd_vel`.
- Do not assume mapper `scan_topic` is namespaced — override per robot if needed.
- `CMakeLists.txt` exits on aarch64. Pi images do not ship Gazebo.

### Testing Requirements

Launch-level. CI flake8 includes `gz_sim/launch`.

### Common Patterns

`PushRosNamespace` + `frame_prefix`. Mode `nav` vs `slam`.

## Dependencies

### Internal

- `description`, `navigation` launches

### External

- Gazebo / ros_gz, gz_ros2_control

<!-- MANUAL: -->
