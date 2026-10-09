<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-03 | Updated: 2026-10-03 -->

# omx curation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Offline export of recorded OMX SIM demonstrations to a LeRobot v3 dataset (D-427 learning part, wave 1 row 1c). Never connects to a robot, never uploads. Not installed on any device and not a ROS package.

## Key Files

| File | Description |
|------|-------------|
| `lerobot_export.py` | `python learning/curation/omx/lerobot_export.py <episode> <output> [--repo-id ...]`: validates the episode, writes the dataset, reads every frame back, copies the source into `rosy_provenance/` |
| `test/test_lerobot_export.py` | Schema, frame and refusal checks; the full LeRobot round trip skips without `lerobot` |

## For AI Agents

### Working In This Directory

- Episode validation comes from `omx_adapter.demonstration` (`middleware/apps/device/omx/adapter`). That learning -> middleware import is a frozen `KNOWN_VIOLATIONS` entry (D-427 Q6) until 2b moves the check to the Episode profile.
- Put `middleware/apps/device/omx/adapter` and `contracts/foundation` on `PYTHONPATH` to run it; the export venv and its pins are in `deploy/robot/omx/README.md` and `deploy/robot/omx/requirements-lerobot-export.txt`. Never install LeRobot into a ROS runtime.

### Testing Requirements

```bash
python -m pytest learning/curation/omx -q -p no:cacheprovider
```

## Dependencies

### Internal

- `middleware/apps/device/omx/adapter` (`omx_adapter.demonstration`, test fixtures in its `test/test_demonstration.py`)

### External

- `lerobot==0.4.4`, `numpy`, `Pillow`

<!-- MANUAL: -->
