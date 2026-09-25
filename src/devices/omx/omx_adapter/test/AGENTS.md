<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# test

## Purpose

ROS-free tests for OMX profile normalization and the standard controller-name contract. Must not open serial devices or claim physical OMX availability.

## Key Files

| File | Description |
|------|-------------|
| `test_omx_profile.py` | Disabled profile is valid but not capable; enabled profile emits joint-state broadcaster + JointTrajectoryController names |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Keep these tests hardware-free. A test that talks to `/dev` or Dynamixel is out of scope for this package.
- Empty contract from the disabled profile is the expected commissioning result.

### Testing Requirements

```bash
python3 -m pytest src/devices/omx/omx_adapter/test/test_omx_profile.py -v
```

### Common Patterns

`OmxAdapterProfile.from_mapping({...})` then assert on `capability_enabled` and `ros2_control_contract()`.

## Dependencies

### Internal

- `omx_adapter.profile`, `omx_adapter.cli`

### External

- pytest

<!-- MANUAL: -->
