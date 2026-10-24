<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# omx_adapter (Python package)

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-19

## Purpose

Disabled-by-default profile validation plus optional ROS action and camera adapters. No fake joint-state publisher or `cmd_vel`. The only serial access is `real/dynamixel_port.py` with its `real/dynamixel_bus.py` (D-858 S1), which nothing composes yet.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `profile.py` | `OmxAdapterProfile`: model aliases, joint/frame checks, `ros2_control_contract()` / `capability_enabled` |
| `cli.py` | YAML path → profile → JSON stdout for commissioning and CI |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `pilot_sim/` | SIM-only Pilot owner, own D-766 size unit (see `pilot_sim/AGENTS.md`) |

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
