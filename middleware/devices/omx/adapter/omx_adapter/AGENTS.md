<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# omx_adapter (Python package)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Disabled-by-default profile validation plus optional ROS action and camera adapters. No fake joint-state publisher or `cmd_vel`. The only serial access is `real/dynamixel_port.py` with its `real/dynamixel_bus.py` (D-858 S1), which nothing composes yet.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `profile.py` | `OmxAdapterProfile`: model aliases, joint/frame checks, `ros2_control_contract()` / `capability_enabled` |
| `cli.py` | YAML path → profile → JSON stdout for commissioning and CI |
| `pilot_sim_runtime.py` | SIM-only Pilot facade over the single owner: jog/gripper goals, readback snapshot, `rosy.controls/1`, admission = cell profile within URDF (D-390, D-411) |
| `real/dynamixel_port.py` | D-858 S1 real Dynamixel `LocalActionPort`: startup HOLD, stop latch holding in place, rearm through the `local_stop` fence, RAM-only writes, joint/velocity limits from `ArmCommandConfig`, tracking/fault/arrival/empty-grasp HOLD, §4 motion gate, per-instance bus claim. Safety-tagged. Not wired into an owner until S4 |
| `real/dynamixel_bus.py` | D-858 S1 bus layer for `dynamixel_port.py`: register addresses, RAM-only write list, OMX-F IDs, per-instance/per-device writer claim, exclusive `SdkBus`. Safety-tagged |
| `real/dynamixel_gates.py` | D-858 S1/S3 §4 motion-gate evidence (`MotionEvidence`: V-016 stop bounds, record and config revision binding), tracking bounds, grasp-check spec. Safety-tagged |
| `real/commissioning_record.py` | D-858 S3 per-arm commissioning record: atomic save, history, content-hash revision; `load_motion_evidence` is the only `MotionEvidence` source; `gate_status` for the read-only viewer. Reuses `hardware_profile.py` validators. Safety-tagged |
| `real/dynamixel_stop_test.py` | D-858 S3 V-016 timed stop test on the port (measurement mode) and its CLI; real runs are a person's (KAN-30), tests use `--dry-run` and a fake bus. Safety-tagged |
| `pilot_sim_gripper.py` | D-411 C pure gripper state (`open`/`closed`/`holding`/`moving`/`unknown`); position evidence only, not grip force |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `real/` | D-858 real arm path (Dynamixel port, bus, motion gate, commissioning record, stop test); its own D-766 size unit |

## For AI Agents

### Working In This Directory

- Disabled + selected `omx_ai` model and empty measured joint map is valid and **not capable**. Contract is `{}`.
- Enabled profile requires a known model alias, driver package, hardware plugin, ≥4 unique joint names, frames, and finite positive `update_rate_hz`.
- Do not open hardware from `cli.py`. It is a validator.
- `real/dynamixel_bus.py` imports `serial`/`dynamixel_sdk` only inside `SdkBus`. Keep the module importable without them; tests use a fake bus. Do not add another serial writer for the same arm (D-858 §3).

### Testing Requirements

```bash
python3 -m pytest middleware/devices/omx/adapter/test/test_omx_profile.py -v
```

### Common Patterns

`from_mapping` accepts either an `omx:` document or a flat mapping. Frozen dataclass.

## Dependencies

### Internal

- Config example: `middleware/devices/omx/profile/config/omx.disabled.yaml`

### External

- PyYAML in the CLI only

<!-- MANUAL: -->
