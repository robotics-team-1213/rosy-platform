
# omx curation

**Parent context:** `../AGENTS.md`

## Purpose

Offline export of recorded OMX SIM demonstrations to a LeRobot v3 dataset (D-427 learning part, wave 1 row 1c). Never connects to a robot, never uploads. Not installed on any device and not a ROS package. Scripts and their tests are listed by `ls`; each has a docstring with its usage.

## For AI Agents

### Working In This Directory

- Production demonstration validation is `rosy.contracts.learning.omx.validate_demonstration` in `contracts/learning/src/rosy/contracts/learning/omx.py`; `lerobot_export.py` keeps a local `validate_episode` alias. `common_episode.py` validates the common Episode and OMX profile via the learning contracts.
- Both source entrypoints add the exact `contracts/learning/src` loader root themselves; `common_episode.py` adds `contracts/foundation` only for optional owner receipt validation. Adapter imports in tests supply fixtures only, not the production validator.
- Export venv and pins: `deploy/robot/omx/README.md`, `deploy/robot/omx/requirements-lerobot-export.txt`. Never install LeRobot into a ROS runtime.
- `carry_dataset.py`: recordings without the run/attempt id in `task.json` are refused, never time-matched; only placed+verified carries with a person success label become episodes; shadow predictions are never read.
- `arm_incident_labels.py`: the person's cause, the cell's measured reading and the AI PC's explanation stay apart; truth only for a repeat or a measurement.
- `data_gate.py` (D-1065 camera roles, declared legacy maps only) is the admission gate before training: `gate` writes `gate-receipt.json`; trainers call `check_receipt` (stale files, dataset rejects and open reviews refuse).
- `camera_setup_intake.py` (D-792 S3) is a shadow check and never blocks intake. `two_arm_export.py` is read only. `world_model_dataset.py` (D-782 W1): `load()` checks the receipt digest.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/omx-curation" -- learning/curation/omx/test/ -q -p no:cacheprovider
```
