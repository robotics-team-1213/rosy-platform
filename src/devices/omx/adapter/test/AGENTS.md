<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# test

## Purpose

ROS-free tests for OMX profile normalization and the standard controller-name contract. Must not open serial devices or claim physical OMX availability.

## Key Files

| File | Description |
|------|-------------|
| `test_omx_profile.py` | Disabled profile is valid but not capable; enabled profile emits joint-state broadcaster + JointTrajectoryController names |
| `test_omx_command_owner.py` | ROS-free single-writer, identity, freshness, bounds, timeout/HOLD, and explicit recovery policy |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Keep these tests hardware-free. A test that talks to `/dev` or Dynamixel is out of scope for this package.
- Empty contract from the disabled profile is the expected commissioning result.
- Command-owner policy tests do not exercise a ROS action server, vendor driver, real stop, or physical recovery.

### Testing Requirements

```bash
python3 -m pytest src/devices/omx/adapter/test/ -v
```

### Common Patterns

`OmxAdapterProfile.from_mapping({...})` then assert on `capability_enabled` and `ros2_control_contract()`. For command policy, use fake in-memory action ports only.

## Dependencies

### Internal

- `omx_adapter.profile`, `omx_adapter.cli`

### External

- pytest

<!-- MANUAL: -->
