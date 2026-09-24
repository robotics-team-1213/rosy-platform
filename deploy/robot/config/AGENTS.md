<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# config

## Purpose

Pinky Pro board overlays mounted into `rosy-core`. `ROSY_RUNTIME_MODE` selects `core`, `motor`, or `hardware`. `board.yaml` catalogs slices (`required: [core]`) and presets that map onto those modes. The full in-tree `src/robots/pinky_pro/config/capabilities.yaml` (D-196) is the Pinky source profile; these files are what the robot actually advertises.

## Key Files

| File | Description |
|------|-------------|
| `profile.core.yaml` / `capabilities.core.yaml` | Dashboard only: no teleop, no lidar |
| `profile.motor.yaml` / `capabilities.motor.yaml` | Dynamixel teleop, encoder only |
| `profile.hardware.yaml` / `capabilities.hardware.yaml` | Motor + RPLidar + localized Nav2 goal/return-home; slam false |
| `capabilities.hardware-mapping.yaml` | Hardware SLAM overlay selected only by `ROSY_NAVIGATION_BACKEND=slam`; slam true, navigation false |
| `motion_profiles.yaml` | Measured base/arm/payload states; defaults to unmeasured `unknown` |
| `board.yaml` | Modes, aliases (`pi5-lite` → `hardware`), `slices` (`required: [core]`; available motor/io/nav/vision/omx/ai), and `presets` (`core` / `motor` / `hardware`) |
| `resolve-mode.sh` | Maps aliases and `--slices` sets onto catalog modes; overlay YAML exists only for catalog modes |
| `rosy.pi5.example.yaml` | Example `ROSY_CONFIG` for the device; hardware readiness gate is required |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Compose bind-mounts profile/capabilities over `/etc/rosy/`. Keep keys aligned with `src/core/core/config/` schemas.
- Overlay YAML exists only for `core` / `motor` / `hardware`. Do not copy YAML for aliases.
- Presets: `core` → `[core]`; `motor` → `[core, motor]`; `hardware` → `[core, motor, io, nav]`. vision/omx/ai are catalog-only (`enabled: false`); do not add overlay YAML or compose services for them.
- Do not enable slam/swarm unless the hardware image actually launches those stacks. D-144 permits slam only through the dedicated hardware-mapping overlay; the normal hardware overlay remains localization-only.

### Testing Requirements

Covered by `test/test_robot_runtime.py` and `src/core/core/test/test_runtime_config.py`.

### Common Patterns

YAML only; no code.

## Dependencies

### Internal

- `src/core/core/config/rosy_default.yaml` structure
- `deploy/robot/compose.yaml` volume mounts

### External

None.

<!-- MANUAL: -->
