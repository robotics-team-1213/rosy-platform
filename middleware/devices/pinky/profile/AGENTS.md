<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# pinky_pro

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Pinky Pro robot composition (D-196). Config only: the HWA-001 profile and CAP-001 capabilities CORE loads when `robot.model` is `pinky_pro` (the default). Installed to `share/pinky_pro/config`.

## Key Files

| File | Description |
|------|-------------|
| `config/profile.yaml` | HWA-001 Pinky Pro profile (model, max velocities, geometry, hardware mapping) |
| `config/capabilities.yaml` | CAP-001 static flags (D-11); must match the profile (HWA-003) |
| `config/deployment-binding.yaml` | Release-owned package model ID and normalized static configuration digests; CORE validates it in device mode |
| `config/core.yaml` | Robot-fact CORE config layer merged by `load_config` over `rosy_default.yaml`, under the local overlay (e.g. `line_follow.lidar_forward_deg: 180`) |
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
- Development Compose mode variants remain deploy-owned. Device-mode CORE requires this installed package's binding and canonical typed configuration; see `docs/deployment/deployment-tools.md` for coordinated updates and migration.
- Update the release-owned binding under source review when static configuration changes. Do not regenerate it from installed files; source/installed product-startup tests must reject stale digests.
- No code here. Do not add Python or launch logic until the D-196 P6 assembly step.

### Testing Requirements

```bash
python -m pytest middleware/devices/pinky/profile/test -q
python -m pytest middleware/core/gateway/test contracts/foundation/test -q   # CORE reads this package via the source-tree fallback
```

## Dependencies

### Internal

- Read by `core` (`core_common.profile.robot_config_dir("pinky_pro")`); listed in `deploy/robot/pinky_pro/image/required-ros-packages.txt`

### External

- ament_cmake

<!-- MANUAL: -->
