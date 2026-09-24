<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# robots

## Purpose

One robot = one package (D-196). A robot package carries configuration only: the HWA-001 profile and CAP-001 capabilities CORE loads, and later the URDF assembly and launch that compose `devices/` packages. No Python or C++ code lives here.

## Key Files

None at this level. Each package directory has its own `AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `pinky_pro/` | Pinky Pro: `config/profile.yaml` + `config/capabilities.yaml` (see `pinky_pro/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Package name = directory name (`src/robots/<name>/`, `package.xml` `<name>` the same). The name is what `ROSY_ROBOT=<name>` / `robot.model` selects; it must match `[a-z][a-z0-9_]*`.
- CORE finds `share/<name>/config/{profile,capabilities}.yaml` at runtime (`core_common.profile.robot_config_dir`); a host checkout falls back to `src/robots/<name>/config/`. Absolute `profile:` / `capabilities:` paths in the config overlay (`/etc/rosy/*.yaml`) still win.
- core does **not** declare a dependency on robot packages (dynamic lookup, the same kind of coupling as D-126 `sensor_provider`). The image ships them by listing them in `deploy/image/required-ros-packages.txt` (and `deploy/image/inputs.lock.yaml`).
- Direction (D-196 P4 rows): `robots` → core contracts (`interfaces`, `core_common`, `web_common`) and `devices` only. Never `apps`, `navigation`, or `core` runtime.
- `pinky` literals belong here and in `src/devices/pinky_pro/` (D-196 residence rule, `test/test_robot_literals.py`).
- Every package needs `AGENTS.md`, its own `test/test_*.py`, and a `tools/harness/harness.yaml` module with `progress.md` / `logs.md` (D-168, D-61).

### Testing Requirements

```bash
python -m pytest src/robots -q
```

## Dependencies

### Internal

- Consumed by `core` (`core_common.profile.robot_config_dir`, `core/node.py`)

### External

- ament_cmake (install only)

<!-- MANUAL: -->
