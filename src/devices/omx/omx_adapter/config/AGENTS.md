<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# config

## Purpose

Device manifest for the OMX adapter. The disabled arm profile lives in `src/products/omx`.

## Key Files

| File | Description |
|------|-------------|
| `adapter.manifest.yaml` | Device id `rosy.device.omx`, type manipulator, disabled |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not fill in a fake `hardware_plugin` so the stack looks enabled.
- Selecting `omx-f` / `omx-ai` / `openmanipulator-x` is a measured-hardware decision, not a YAML tidy-up.
- CLI: `python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml` must print `{}`.

### Testing Requirements

`../test/test_omx_profile.py` loads mappings equivalent to this file.

### Common Patterns

Top-level `omx:` map consumed by `OmxAdapterProfile.from_mapping`.

## Dependencies

### Internal

- `../omx_adapter/profile.py`

### External

None.

<!-- MANUAL: -->
