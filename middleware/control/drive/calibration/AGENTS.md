# calibration

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Stationary sensor checks and bounded calibration motion for Drive. A certificate records a completed run. It is not live permission to drive, and nothing here publishes `/cmd_vel`.

## Key Files

| File | Description |
|------|-------------|
| `calibration.py` | Stationary sensor-quality and bounded motion validation |
| `calibration_certificate.py` | Versioned evidence for reusing a completed calibration, never live health |
| `calibration_clearance.py` | Reserves actual motion travel against the safety gate's metric limits |
| `calibration_profile.py` | Atomic, expiring calibration evidence. Old split topics carry no authority |
| `calibration_relocation.py` | One straight observed-space relocation. Targets are hypotheses, not rotation permission |
| `calibration_return.py` | Optional straight return to the recorded pre-calibration odometry origin |
| `calibration_rotation_clearance.py` | Consumes the final gate's current rotation clearance |
| `calibration_rotation_handoff.py` | A translation lease cannot acknowledge the start of a rotation trial |
| `calibration_runtime.py` | Completed calibration evidence is independent of live operating permission |
| `calibration_tf.py` | TF evidence checks for bounded calibration recovery. No fabricated poses |
| `commissioning_certificate.py` | Fail-closed commissioning records. Candidates never grant motion authority |
| `modes.py` | One canonical `/robot/mode` label. Subjects do not overlap |
| `navigation_calibration.py` | Learns measurement margins, never robot dimensions, from a stationary scene |
| `round_trip.py` | LiDAR-referenced short round trip and an independent corrected repeat |
| `sensing_only.py` | Stationary diagnostic reporting. Exclusion never authorizes motion |
| `sensor_tiers.py` | The only place that decides which sensors a partial calibration may drop |
| `startup_diagnostics.py` | Sensor readiness transitions without flooding logs with samples |
| `startup_profile.py` | Pure startup selection. Process selection never grants motion readiness |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not treat a certificate, a profile, or a startup selection as permission to move.
- Rotation and translation leases stay separate. A translation lease does not start a rotation trial.
- Partial calibration may drop only the sensors `sensor_tiers.py` names.

### Testing Requirements

Matching tests live in `middleware/perception/test/test_calibration*.py`, `test_modes.py`, `test_round_trip.py`, `test_commissioning_certificate.py`, `test_sensing_only.py`, `test_sensor_tiers.py`, `test_startup_diagnostics.py`, and `test_startup_profile.py`. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`.

### Common Patterns

No ROS imports. Each module answers one calibration question and returns evidence, not a command.

## Dependencies

### Internal

- Clearance decisions come from `../safety/`.
- ROS composition and certificate storage stay in `middleware/perception/control`.

### External

- Python standard library and numpy.

## Manual Notes
