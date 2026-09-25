<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# omx

## Purpose

OMX arm composition (D-232). Config only: the disabled profile the adapter validates. Installed to `share/omx/config`. `omx-f` and `omx-ai` are model names in that file, not packages.

## Key Files

| File | Description |
|------|-------------|
| `config/omx.disabled.yaml` | Arm disabled until model, driver, mount, and payload are measured |
| `package.xml` / `CMakeLists.txt` | ament_cmake; installs `config/` only |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `config/` | `omx.disabled.yaml` |
| `test/` | `test_omx_package.py` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Do not put adapter code or a launch file here. The validator stays in `src/devices/omx/adapter`.
- Do not fill in a fake `hardware_plugin`. Selecting `omx-f` or `omx-ai` waits on a measured driver.

### Testing Requirements

```bash
python -m pytest src/products/omx/test -q
python -m omx_adapter.cli src/products/omx/config/omx.disabled.yaml
```

The CLI on this file must print `{}`.

## Dependencies

### Internal

- Read by `omx_adapter` as a YAML path. The device manifest stays in the adapter package.

### External

- ament_cmake

<!-- MANUAL: -->
