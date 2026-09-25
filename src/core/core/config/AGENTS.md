<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# config

## Purpose

Default robot config. Installed to `share/core/config`. Local override is `~/.rosy/rosy.yaml` (not in this folder). The robot profile and capabilities now live in `src/products/<model>/config/` (D-196); `robot.model` (default `pinky_pro`, env `ROSY_ROBOT`) picks the package.

## Key Files

| File | Description |
|------|-------------|
| `rosy_default.yaml` | CFG-001 defaults: robot id, `robot.model` (D-196), API port 8080, `auth.tokens: []` and `auth.pairing` lifetimes (D-193), safety/battery curve, power, navigation and the opt-in readiness gate |
| `rosy_dev_auth.yaml` | Shared dev tokens (`rosy-dev-admin`/`operator`/`viewer`). Merged by `load_config` only with `ROSY_DEV_AUTH=1` and never in device mode (D-193 7) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `rosy_default.yaml` carries **no** tokens (fail closed, D-193 7). Dev and sim opt in with `ROSY_DEV_AUTH=1`; host tests merge `rosy_dev_auth.yaml` themselves (`core_client` does). A device (`ROSY_DEPLOYMENT=device`) refuses the dev digests and plaintext entries wherever they come from.
- Battery curve is 2S Li-ion OCV. Invalid `battery_curve` must not prevent boot (`services._battery_config` falls back).
- Profile and capabilities are not here: see `src/products/pinky_pro/config/` (D-196). Pinky Pro `capabilities.yaml` has `docking.supported: false`.
- A hand-written overlay with a relative `profile:`/`capabilities:` name now resolves inside `share/<robot.model>/config/` (the old `profile.pinky_pro.yaml` is now `profile.yaml` there). Use absolute paths or omit the keys.
- New safety keys need matching fields in `BatteryConfig` / `PowerConfig` with defaults.

### Testing Requirements

`src/core/core/test/test_runtime_config.py`, `test_battery.py`, `test_power.py`.

### Common Patterns

Deep-merge; missing keys keep dataclass defaults. Runtime settings (SAF-004 limits) write only the overlay via `patch_local_config` — never `rosy_default.yaml`.

## Dependencies

### Internal

- Loaded by `core.config.load_config` and `RosyCoreNode`

### External

- PyYAML

<!-- MANUAL: -->
