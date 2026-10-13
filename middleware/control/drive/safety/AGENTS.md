# safety

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Flat Drive safety limits installed as `control.control.*`, plus the legacy comparison node in `adapter/` installed as `control.safety`. These modules can withhold or reduce a candidate. They do not publish the operational final `/cmd_vel`. CORE remains that writer.

## Key Files

| File | Description |
|------|-------------|
| `actuation.py` | Prepares one final calibrated candidate before sweep and hardware publication |
| `adaptive_speed.py` | Measured-envelope speed limiter. It can reduce authority, never create it |
| `command_gate.py` | Semantic command restrictions shared by the legacy node and CORE adapters |
| `configured_operation.py` | Parameter operation is live permission, never calibration evidence |
| `floor_evidence.py` | D-468 current IR floor observation. Saturation is unknown, not a cliff |
| `footprint_guard.py` | Straight-line clearance from observed points to a verified chassis box |
| `footprint_sweep.py` | Finite-command bounds for a trusted convex chassis footprint |
| `lidar_guard.py` | Fail-closed lidar bumper decisions, with no ROS and no smoothing |
| `motion_sweep.py` | Conservative finite-command sweep for an explicitly commissioned simulation |
| `obstacle_risk.py` | Short-horizon relative collision evidence. Never motor authority |
| `policy_handoff.py` | Bounded in-process handoff from absorbed sensing to CORE policy |
| `rotation_clearance.py` | Conservative body bound when exact pivot coverage is unavailable |
| `rotation_envelope.py` | Sensor-evidenced pivot envelope. Does not infer unseen chassis geometry |
| `safety_profile.py` | Effective safety limits with a stable revision |
| `space_speed.py` | Gap-based speed reduction, not a measured braking model |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `adapter/` | Legacy safety node (`control.safety`): bumper, hazard, gate, scale (see `adapter/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A limiter or gate may only refuse or shrink a candidate. Do not add a publisher, a mode, or an automatic recovery start here.
- Keep the legacy final publisher inside `adapter/` inactive beside CORE.
- Sensor geometry and evidence freshness stay distinct from command restriction.

### Testing Requirements

Matching tests live in `middleware/perception/test/test_<module>.py`. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`. Do not run pytest on this laptop (D-584).

### Common Patterns

One subject per module. Docstrings say what the module refuses to decide. No ROS imports in the flat modules.

## Dependencies

### Internal

- `adapter/` consumes the classified state these modules produce.
- Candidates return to CORE arbitration in `middleware/core/services`.

### External

- Python standard library and numpy. The flat modules do not import ROS.

## Manual Notes
