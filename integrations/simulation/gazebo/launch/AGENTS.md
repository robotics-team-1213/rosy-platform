<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# launch

## Purpose

Gazebo multi-robot and single-sim launches.

## Key Files

| File | Description |
|------|-------------|
| `gz_multi.launch.py` | N robots `rosy_01..NN`; args `robots`, `mode` (nav/slam), `headless` |
| `launch_sim.launch.xml` | Older single-sim XML |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

CI flake8 includes this Python launch (max line 120). Per-robot ros_gz bridge maps namespaced `cmd_vel`.

### Testing Requirements

Manual launch. flake8 in CI.

### Common Patterns

`OpaqueFunction` to stamp N groups; include `navigation` gz bringup.

## Dependencies

### Internal

- `description`, `navigation`, `../worlds`, `../params/rosy_bridge.yaml`

### External

- ros_gz, Gazebo

<!-- MANUAL: -->
