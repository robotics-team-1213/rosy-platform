<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# core_common

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

The importable Python package of the `core_common` module: config loading, identity, hardware profile, capability checks, shared stdlib utilities, and the ROS-free concept domain (`domain/`). Wire schemas live in `protocol/` (own AGENTS.md). Nothing here imports rclpy or a workspace package.

## Key Files

| File | Description |
|------|-------------|
| `config.py` | Layered YAML config (defaults, robot `core.yaml`, `~/.rosy/rosy.yaml`, `ROSY_CONFIG`); dev-auth overlay only with `ROSY_DEV_AUTH=1` outside device mode |
| `identity.py` | Robot id pattern and `SOFTWARE_VERSION` (IDN-001~003) |
| `profile.py` | Robot Profile loader (HWA-001); `DEFAULT_ROBOT` names the robot package |
| `capability.py` | `Capability` flags and `CapabilityError` (CAP-001~003) |
| `rmw.py` | CycloneDDS selection applied before `rclpy.init`; does not import rclpy |
| `calibration_store.py` | Per-robot immutable calibration records plus append-only status events; stdlib only (D-47) |
| `robot_state.py` | One five-state robot state for buzzer, lamp, LCD, dashboard (D-260); stdlib only, also loaded by the boot display |
| `device_poll.py` | Shared HTTP polling with a unified failure vocabulary (D-352/353); stdlib only |
| `discover.py` | mDNS/DNS-SD discovery with zeroconf, avahi, dns-sd fallbacks (D-354); optional, never required |
| `intent.py` | Translates operator intent into robot tasks or site commands; never takes ROS topic names |
| `succession.py` | Deterministic leader choice from roster plus dead set, so two robots cannot appoint two leaders |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `protocol/` | Wire schemas, evidence and pairing vectors (see `protocol/AGENTS.md`) |
| `domain/` | Concept snapshot types, covered below |

### domain/

ROS-free snapshots, "not a second runtime". `model.py` (Node/Device/Component/Asset, `DeviceState`), `capabilities.py` (CAP-001 flags to concept descriptor ids; false flags omitted), `tasks.py` (`TaskKind` atomic REST actions mapped to capability flags, not a workflow engine), `command_mapping.py` (where an external call lands after CORE, D-74), `adapters.py` (YAML-only adapter registry; CORE must not import `omx_adapter`).

## For AI Agents

### Working In This Directory

- Leaf of the core chain: import only stdlib, pydantic/yaml, and sibling modules. A new import of another workspace package fails the architecture test.
- Modules shared with root-side or PC tools (`robot_state`, `calibration_store`, `device_poll`) must stay stdlib only.
- Changing a wire shape belongs in `protocol/` together with the API reference (D-18), not here.
- Package tier, coupling and 600-line budget: D-168. Docstrings mix Korean and English; keep each module's existing language.

### Testing Requirements

```bash
python -m pytest contracts/foundation/test -q
```

Covers `calibration_store`, `robot_state`, robot selection and core-layer rules, plus protocol vectors. `test/architecture/test_module_structure.py` enforces the structure rules.

### Common Patterns

Dataclasses and enums for snapshots, pure functions for decisions, explicit error classes (`CapabilityError`). Config merging is the single place defaults are resolved: do not hardcode robot geometry elsewhere (URDF is nominal, calibration refines).

## Dependencies

### Internal

None (leaf). Consumed by `core`, the sensing nodes, bringup, fleet, and PC tools.

### External

PyYAML, pydantic (in `protocol/`); optional `zeroconf`.

<!-- MANUAL: -->
