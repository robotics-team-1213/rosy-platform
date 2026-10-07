# pinky

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Turns a closed `rosy.recording.session/1` folder, plus `bag_to_video.py` metadata, into a common Episode. `environment` and `clock` are provenance declarations, not a certificate that a physical robot was authenticated.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Inputs, output layout, and the stamp rules |
| `pinky_episode.py` | Build a new Episode directory from a raw session and a video json |
| `prepare_behavior.py` | Behavior-prep helper for the same recordings |
| `raw_messages.py` | Raw message reads used by the verifier |
| `verify_raw.py` | Compare ROS 2 CDR/MCAP camera, cmd_vel, odom, JSON, and scan against sidecars |
| `requirements-raw.txt` | Separate environment pins for the raw verifier |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Host checks for the Pinky episode builder |

## For AI Agents

### Working In This Directory

- cmd_vel linear/angular in the episode is the recorded CORE final output (m/s, rad/s), not a new command.
- Do not invent task outcomes. `task_id` stays only where the source had it. policy and calibration stay null unless the source said otherwise.
- `verify_raw.py` must see the same hashes in the DatasetManifest before and after verification.

### Testing Requirements

Run `pinky/test` with the raw requirements environment when the test needs MCAP. Do not add those pins to the robot image.

### Common Patterns

Output layout is `source/raw/`, `source/video/`, `source/binding.json`, `episode.json`, `dataset-manifest.json`.

## Dependencies

### Internal

- `contracts/learning/` for the manifest shape.
- `learning/registry/policy/dataset_store.py` registers the output.

### External

- ROS 2 CDR/MCAP libraries only in the verifier environment named by `requirements-raw.txt`.

## Manual Notes
