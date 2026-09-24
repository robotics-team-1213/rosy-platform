<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# pinky_pro

## Purpose

Pinky Pro robot composition (D-196). Config only: the HWA-001 profile and CAP-001 capabilities CORE loads when `robot.model` is `pinky_pro` (the default). Installed to `share/pinky_pro/config`.

## Key Files

| File | Description |
|------|-------------|
| `config/profile.yaml` | HWA-001 Pinky Pro profile (model, max velocities, geometry, hardware mapping) |
| `config/capabilities.yaml` | CAP-001 static flags (D-11); must match the profile (HWA-003) |
| `package.xml` / `CMakeLists.txt` | ament_cmake; installs `config/` only |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `config/` | `profile.yaml`, `capabilities.yaml` |
| `test/` | `test_robot_package.py` (profile/capability agreement) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Change `profile.yaml` and `capabilities.yaml` together: the advertised navigation limits are the profile's (HWA-003). `docking.supported` is `false` for Pinky Pro — keep the capability checks.
- The per-mode files the robot actually advertises, `deploy/robot/config/{profile,capabilities}.{core,motor,hardware}.yaml`, are still owned by deploy and mounted at `/etc/rosy/*.yaml`, which wins over this package. Moving them here is follow-up work.
- No code here. Do not add Python or launch logic until the D-196 P6 assembly step.

### Testing Requirements

```bash
python -m pytest src/robots/pinky_pro/test -q
python -m pytest src/core/core/test src/core/core_common/test -q   # CORE reads this package via the source-tree fallback
```

## Dependencies

### Internal

- Read by `core` (`core_common.profile.robot_config_dir("pinky_pro")`); listed in `deploy/image/required-ros-packages.txt`

### External

- ament_cmake

<!-- MANUAL: -->
