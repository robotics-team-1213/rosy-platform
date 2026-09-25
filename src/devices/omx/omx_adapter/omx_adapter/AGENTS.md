<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# omx_adapter (Python package)

## Purpose

Pure profile validation and a CLI that prints the `ros2_control` contract as JSON. No serial, no joint-state publisher, no `cmd_vel`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `profile.py` | `OmxAdapterProfile`: model aliases, joint/frame checks, `ros2_control_contract()` / `capability_enabled` |
| `cli.py` | YAML path → profile → JSON stdout for commissioning and CI |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Disabled + empty model is valid and **not capable**. Contract is `{}`.
- Enabled profile requires a known model alias, driver package, hardware plugin, ≥4 unique joint names, frames, and finite positive `update_rate_hz`.
- Do not open hardware from `cli.py`. It is a validator.

### Testing Requirements

```bash
python3 -m pytest src/devices/omx/omx_adapter/test/test_omx_profile.py -v
```

### Common Patterns

`from_mapping` accepts either an `omx:` document or a flat mapping. Frozen dataclass.

## Dependencies

### Internal

- Config example: `../config/omx.disabled.yaml`

### External

- PyYAML in the CLI only

<!-- MANUAL: -->
