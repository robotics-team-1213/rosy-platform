
# pinky_pro

**Parent context:** `../AGENTS.md`

## Purpose

Pinky Pro robot composition (D-196). Config only: the HWA-001 profile and CAP-001 capabilities CORE loads when `robot.model` is `pinky_pro` (the default). Installed to `share/pinky_pro/config`.

## Key Files

| File | Description |
|------|-------------|
| `config/capabilities.yaml` | CAP-001 static flags (D-11); must match the profile (HWA-003) |
| `package.xml` / `CMakeLists.txt` | ament_cmake; installs `config/` only |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `config/` | `profile.yaml`, `capabilities.yaml` |
| `test/` | `test_robot_package.py` (profile/capability agreement) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Change `profile.yaml` and `capabilities.yaml` together: the advertised navigation limits are the profile's (HWA-003). `docking.supported` is `true` for Pinky Pro since 2026-11-18 (D-1042 6, one-press pink-line bay docking) — keep the capability checks.
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
