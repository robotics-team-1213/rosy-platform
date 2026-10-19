<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-19 | Updated: 2026-10-19 -->

# pilot_sim

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-19

## Purpose

SIM-only OMX Pilot owner, moved out of the flat `omx_adapter` package as its own D-766 size unit (`test/architecture/size_units.txt`). Run with `python3 -m omx_adapter.pilot_sim.server`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `runtime.py` | SIM-only Pilot facade over the single owner: jog/gripper goals, readback snapshot, `rosy.controls/1`, admission = cell profile within URDF (D-390, D-411) |
| `gripper.py` | D-411 C pure gripper state (`open`/`closed`/`holding`/`moving`/`unknown`); position evidence only, not grip force |
| `api.py` | `create_pilot_sim_app`: FastAPI Pilot routes, pairing sessions, `PILOT_ASSETS` |
| `capture.py` | `PilotSimCapture`: demonstration recording on disk |
| `camera.py` | `PilotSimCamera`: ROS camera stream for the Pilot |
| `server.py` | ROS node + uvicorn entrypoint (port 8088, `shared/web/surfaces.yaml`) |

## For AI Agents

### Working In This Directory

- `../` modules (`command_owner`, `kinematics`, `ros_runtime`, ...) are imported with `..`; nothing outside this folder imports it relatively.
- `deploy/robot/omx/cell_sim_tools.py` `_ARM_OWNERS` matches the `pilot_sim.server` command line; keep it in step with a rename.
- `server.py` hashes `../*.py` and `pilot_sim/*.py` into `source_tree_sha256`; a new subfolder needs adding there.

### Testing Requirements

```bash
python3 -m pytest middleware/devices/omx/adapter/test -k pilot -q
```

<!-- MANUAL: -->
