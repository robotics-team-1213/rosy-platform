
# core_common

**Parent context:** `../AGENTS.md`

## Purpose

The importable Python package of the `core_common` module: config loading, identity, hardware profile, capability checks, shared stdlib utilities, and the ROS-free concept domain (`domain/`). Wire schemas live in `protocol/` (own AGENTS.md, D-766 size unit). Nothing here imports rclpy or a workspace package.

`observation.py` (D-667) owns immutable observation references and pure D-665 camera/anchor input validity. World compatibility imports and offline learning consume the same objects; valid metadata does not prove physical calibration or authorize driving.

`domain/` holds ROS-free snapshots, "not a second runtime": `adapters.py` is a YAML-only adapter registry (CORE must not import `omx_adapter`); `tasks.py` maps `TaskKind` atomic REST actions to capability flags (not a workflow engine); `command_mapping.py` says where an external call lands after CORE (D-74).

## For AI Agents

### Working In This Directory

- Leaf of the core chain: import only stdlib, pydantic/yaml, and sibling modules. A new import of another workspace package fails the architecture test.
- Modules shared with root-side or PC tools (`robot_state`, `calibration_store`, `device_poll`, `perception_model`) must stay stdlib only; `camera_quality` uses numpy only inside `frame_quality` (`deploy/robot/omx/camera_quality.py` is a shim); `discover.py` (mDNS, D-354) is optional,
- never required.
- `config.py` layers defaults, robot `core.yaml`, `~/.rosy/rosy.yaml`, `ROSY_CONFIG`; the dev-auth overlay applies only with `ROSY_DEV_AUTH=1` outside device mode. It is the single place defaults are resolved: do not hardcode robot geometry elsewhere (URDF is nominal, calibration refines).
- `rmw.py` selects CycloneDDS before `rclpy.init` and does not import rclpy. `calibration_store.py` is append-only status events (D-47). `startup_profile.py` process selection never grants motion readiness. `intent.py` never takes ROS topic names.
- `perception_model.py` is re-exported by `perception_runtime.perception.learned.manifest`.
- Changing a wire shape belongs in `protocol/` together with the API reference (D-18), not here.
- Package tier, coupling and 600-line budget: D-168. Docstrings mix Korean and English; keep each module's existing language.
- Dataclasses and enums for snapshots, pure functions for decisions, explicit error classes (`CapabilityError`).

### Testing Requirements

```bash
python -m pytest contracts/foundation/test -q
```

`test/architecture/test_module_structure.py` enforces the structure rules.
