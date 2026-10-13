# middleware

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11

## Purpose

On-robot middleware. CORE (the external API and the only final `/cmd_vel` publisher), device apps, board drivers, perception, robot UI, plus the ROS-free skill and local-execution wheels. A child `AGENTS.md` is the package guide. This file is only the map.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | Gateway, events, services and web API (see `core/AGENTS.md`) |
| `drive/` | Drive planning/tracking/recovery/calibration/safety source holders, including Nav2; existing `control.*` and `navigation` package identities (see `drive/AGENTS.md`, D-630) |
| `devices/` | Pinky and OMX hardware-family assembly, profiles and adapters (see `devices/AGENTS.md`, D-626) |
| `drivers/` | Board drivers: IMU, ADC, lamp, LED (see `drivers/AGENTS.md`) |
| `perception/` | ROS `control` distribution: sensors/vision implementations, node composition and thin import facades; no second operational final command publisher (see `perception/AGENTS.md`) |
| `ui/` | Robot face, Pilot, and the CORE dashboard (see `ui/AGENTS.md`) |
| `skills/` | ROS-free Skill wheels (see `skills/AGENTS.md`) |
| `execution/` | Local execution evidence wheel. Not `operations/execution` (see `execution/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- `middleware/core/gateway` is the external API. Do not add a second public command path in a sibling package.
- Perception may publish sensor evidence. It must not publish the operational `/cmd_vel`.
- CORE internal Drive composition lives in `core/gateway/core/drive`; common power/battery composition lives in `core/gateway/core/system/power.py`. Device Drive algorithms and OMX Arm authority remain separate owners.
- See [platform-folder-responsibilities.md](../docs/reference/platform-folder-responsibilities.md) for all current manifest roots and the namespace/semantic-depth distinction.
- New ROS packages follow `tools/harness/platform_parts.yaml` and need `AGENTS.md`, `progress.md`, `logs.md`, and `index.md` when they are harness modules.

### Testing Requirements

Run the suite named in the child `AGENTS.md`. Gateway and perception both ship `test_battery.py`, so those two suites stay in separate pytest invocations.

### Common Patterns

ament Python uses `setup.py` and `package.xml`. Wheels use `pyproject.toml` and `COLCON_IGNORE`.

## Dependencies

### Internal

- Contracts in `contracts/foundation` and `contracts/ros_idl`.
- Deploy units in `deploy/robot/pinky_pro/native`.

### External

- ROS 2 Jazzy for the ament packages. Wheels stay ROS-free unless their own file says otherwise.

## Manual Notes
