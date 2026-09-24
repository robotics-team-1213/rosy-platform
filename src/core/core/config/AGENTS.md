<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# config

## Purpose

Default robot config, Pinky Pro hardware profile, and static capability YAML. Installed to `share/core/config`. Local override is `~/.rosy/rosy.yaml` (not in this folder).

## Key Files

| File | Description |
|------|-------------|
| `rosy_default.yaml` | CFG-001 defaults: robot id, API port 8080, `auth.tokens: []` and `auth.pairing` lifetimes (D-193), safety/battery curve, power, navigation and the opt-in readiness gate |
| `rosy_dev_auth.yaml` | Shared dev tokens (`rosy-dev-admin`/`operator`/`viewer`). Merged by `load_config` only with `ROSY_DEV_AUTH=1` and never in device mode (D-193 7) |
| `profile.pinky_pro.yaml` | HWA-001 Pinky Pro profile (model, max velocities, geometry) |
| `capabilities.yaml` | CAP-001 static flags (D-11); must match the profile (HWA-003) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `rosy_default.yaml` carries **no** tokens (fail closed, D-193 7). Dev and sim opt in with `ROSY_DEV_AUTH=1`; host tests merge `rosy_dev_auth.yaml` themselves (`core_client` does). A device (`ROSY_DEPLOYMENT=device`) refuses the dev digests and plaintext entries wherever they come from.
- Battery curve is 2S Li-ion OCV. Invalid `battery_curve` must not prevent boot (`services._battery_config` falls back).
- `capabilities.yaml` currently has `docking.supported: false` for Pinky Pro. Pi lite overlay may also set `slam: false`.
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
