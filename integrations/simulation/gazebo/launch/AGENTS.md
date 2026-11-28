
# launch

**Parent context:** `../AGENTS.md`

## Purpose

Gazebo multi-robot and single-sim launches.

## Key Files

| File | Description |
|------|-------------|
| `launch_sim.launch.xml` | Older single-sim XML |
| `map_v2_fleet_multi_real.launch.py` | Two camera robots on map_v2_fleet for a runner-owned `run_spec` (D-676): gz_multi COREs, bridge, line/road observers, IR floor rays (`sim_ir_floor.py`, `gz_multi_parts.SIM_IR_CALIBRATION`). Empty `learned_lane_pointer` = denoise paint. Driven by `tools/sim/fleet_trips.py` |

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
