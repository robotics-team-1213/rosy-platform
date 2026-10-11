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

- Production demonstration validation is `rosy.contracts.learning.omx.validate_demonstration` in `contracts/learning/src/rosy/contracts/learning/omx.py`; `lerobot_export.py` retains its local `validate_episode` alias. `common_episode.py` also validates the common Episode and OMX profile through the learning contracts. The old learning-to-adapter validation violation has been removed.
- Both source entrypoints add the exact `contracts/learning/src` loader root themselves. `common_episode.py` adds `contracts/foundation` only for optional owner receipt wire validation. Adapter imports in tests supply existing recorded-demonstration fixtures; they are not the production validator. For export dependencies, the export venv and its pins are in `deploy/robot/omx/README.md` and `deploy/robot/omx/requirements-lerobot-export.txt`. Never install LeRobot into a ROS runtime.

### Testing Requirements

```bash
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/omx-curation -- learning/curation/omx/test/ -q -p no:cacheprovider
python test/known_failures.py X:/DevTemp/omx-curation/run-1.txt
```

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/omx.py` (`validate_demonstration`, `validate_profile`, owner correlations).
- `contracts/learning/src/rosy/contracts/learning/__init__.py` (common Episode sealing and validation).
- `contracts/foundation/core_common/protocol/schemas.py` for optional owner receipt validation.
- `middleware/devices/omx/adapter/test/test_demonstration.py` and the adapter package are retained fixture sources only.

### External

- `lerobot==0.4.4`, `numpy`, `Pillow`

<!-- MANUAL: -->
