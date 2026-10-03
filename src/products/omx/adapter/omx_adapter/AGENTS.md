<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# omx_adapter (Python package)

## Purpose

Disabled-by-default profile validation plus optional ROS action and camera adapters. No serial access, fake joint-state publisher, or `cmd_vel`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `profile.py` | `OmxAdapterProfile`: model aliases, joint/frame checks, `ros2_control_contract()` / `capability_enabled` |
| `cli.py` | YAML path → profile → JSON stdout for commissioning and CI |
| `pilot_sim_runtime.py` | SIM-only Pilot facade over the single owner: jog/gripper goals, readback snapshot, `rosy.controls/1`, admission = cell profile within URDF (D-390, D-411) |
| `pilot_sim_gripper.py` | D-411 C pure gripper state (`open`/`closed`/`holding`/`moving`/`unknown`); position evidence only, not grip force |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Disabled + selected `omx_ai` model and empty measured joint map is valid and **not capable**. Contract is `{}`.
- Enabled profile requires a known model alias, driver package, hardware plugin, ≥4 unique joint names, frames, and finite positive `update_rate_hz`.
- Do not open hardware from `cli.py`. It is a validator.

### Testing Requirements

```bash
python3 -m pytest src/products/omx/adapter/test/test_omx_profile.py -v
```

### Common Patterns

`from_mapping` accepts either an `omx:` document or a flat mapping. Frozen dataclass.

## Dependencies

### Internal

- Config example: `src/products/omx/profile/config/omx.disabled.yaml`

### External

- PyYAML in the CLI only

<!-- MANUAL: -->
