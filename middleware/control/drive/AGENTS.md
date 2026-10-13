# drive

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

Base-control backends: `planning/{nav2,grid}`, `tracking/wander`, `safety/adapter`, and the flat modules in `safety/`, `tracking/`, `recovery/`, `calibration/`. The 50 flat modules keep their installed `control.control.*` identities; grid, wander and adapter retain `control.planning`, `control.wander`, `control.safety`. Static source mappings in `middleware/perception/setup.py` build them into the existing `control` distribution once.

`behaviors/` holds Base feature managers installed by `core_features` (D-649); `runtime/` holds the four legacy Drive entry modules installed by `control`. Sensor/vision observation nodes and shared calibration adapters remain in `middleware/perception/control`, with evidence in `middleware/perception/sensors/sensing` and `middleware/perception/vision/perception`. CORE common command arbitration and Safety stay in `middleware/core/services`; CORE-specific Drive composition lives in `middleware/core/gateway/core/drive`. See [the current folder responsibilities](../../../docs/reference/platform-folder-responsibilities.md).

Every backend submits a candidate to CORE. No operational final publisher, new mode or automatic recovery activation belongs in this holder. Curvature, clearance, pivot/reverse and bounded recovery must retain their own behavioral evidence.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `behaviors/` | Base feature managers installed by `core_features` (see `behaviors/AGENTS.md`) |
| `calibration/` | Stationary calibration evidence and bounded validation (see `calibration/AGENTS.md`) |
| `planning/` | Nav2 and grid planners (see `planning/AGENTS.md`) |
| `recovery/` | Bounded recovery proposals (see `recovery/AGENTS.md`) |
| `runtime/` | Legacy Drive entry modules installed by `control` (see `runtime/AGENTS.md`) |
| `safety/` | Flat `control.control` limits plus the `control.safety` adapter (see `safety/AGENTS.md`) |
| `tracking/` | Route following plus the `control.wander` adapter (see `tracking/AGENTS.md`) |

## Manual Notes
