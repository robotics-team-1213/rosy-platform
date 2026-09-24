<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# config

## Purpose

Explicit opt-in YAML for the optional BNO055 node. The default Rosy OS compose path does not load this file.

## Key Files

| File | Description |
|------|-------------|
| `bno055.yaml` | Driver parameters; `reset_on_start: false` unless a commissioning record requires a sensor reset |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Keep `reset_on_start: false` by default. SYS_TRIGGER reset is opt-in.
- Do not add this profile to default bringup until ARM64 sensor and localization gates pass.

### Testing Requirements

Package-contract tests in `../test/` assert the default reset policy. Live BNO055 is not this folder.

### Common Patterns

Launch arguments override YAML. Reset is the dangerous knob.

## Dependencies

### Internal

- `../launch/bno055.launch.py`, `../src/main_node.cpp`

### External

None.

<!-- MANUAL: -->
