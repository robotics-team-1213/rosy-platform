
# fixtures

**Parent context:** `../AGENTS.md`

## Purpose

Recorded lidar scans, maps, and localization snapshots used by the ROS-free Control pytest suite. Do not regenerate as a side effect of running tests.

## Subdirectories

| Directory | Purpose |
|-----------|---------|

## For AI Agents

### Working In This Directory

- These are inputs, not outputs. Changing a fixture requires a matching test-expectation change and a reason in the test.
- Prefer gzip JSON / npz as already used; do not check in huge uncompressed dumps.

### Testing Requirements

Loaded by `../` pytest. No tests live in this folder.

### Common Patterns

Dated filenames (`YYYYMMDD`). Binary-ish JSON.gz and npz.

## Dependencies

### Internal

- Consumers: `../test_*.py`

### External

- numpy (npz)
