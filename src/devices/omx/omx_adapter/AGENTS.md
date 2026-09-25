<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# omx_adapter

## Purpose

ROS-native OMX profile boundary. Validates a model-neutral YAML profile and emits the standard `ros2_control` / MoveIt controller contract (joint-state broadcaster + `JointTrajectoryController`). It must not open a serial port, publish base `cmd_vel`, bypass CORE safety, or advertise an arm capability while the OMX model, driver, mount, power, hand-eye calibration, payload, and recovery procedure are unaccepted.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; `exec_depend` on PyYAML |
| `setup.py` / `setup.cfg` | Package install; console script `omx_adapter` |
| `README.md` | Disabled-by-default contract; empty JSON from the disabled profile is expected |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `omx_adapter/` | `profile.py` + CLI validator (see `omx_adapter/AGENTS.md`) |
| `config/` | Device manifest only. The disabled arm profile is `src/products/omx` |
| `test/` | ROS-free profile/CLI tests (see `test/AGENTS.md`) |
| `resource/` | ament index marker `omx_adapter` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Keep vendor transport behind this profile. Do not add a fake hardware plugin or joint-state publisher "so MoveIt has something to talk to."
- Model aliases in `profile.py` (`omx-f` / `omx-ai` / `openmanipulator-x`) are names only until a measured driver is selected.
- A non-empty `ros2_control_contract()` is not physical acceptance.

### Testing Requirements

```bash
python3 -m pytest src/devices/omx/omx_adapter/test/test_omx_profile.py -v
python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml
```

The CLI on the disabled profile must print `{}`.

### Common Patterns

`OmxAdapterProfile.from_mapping(...)` is pure. CLI is YAML → profile → JSON stdout.

## Dependencies

### Internal

- Must not publish operational `cmd_vel`. CORE owns the robot command path.

### External

- PyYAML (CLI). No Dynamixel SDK / serial I/O in this package yet.

<!-- MANUAL: -->
