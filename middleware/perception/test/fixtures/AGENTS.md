<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# fixtures

## Purpose

Recorded lidar scans, maps, and localization snapshots used by the ROS-free Control pytest suite. Do not regenerate as a side effect of running tests.

## Key Files

| File | Description |
|------|-------------|
| `execution_escape_dropout_20260910.json` | Escape-path dropout trace |
| `gazebo_localization_corner.npz` | Corner localization snapshot |
| `mapping_corner_scan.json` | Mapping corner scan |
| `map_offcenter_start_20260910.json.gz` | Off-center map start |
| `registration_endpoint_v14_20260909.json.gz` | Registration endpoint v14 |
| `registration_stationary_endpoints_20260909.json.gz` | Stationary registration endpoints |
| `rotation_scan_missing_returns_20260909.json.gz` | Rotation scan with missing returns |
| `wall_tracker_after_9mm_20260909.json.gz` | Wall tracker after 9 mm motion |
| `wall_tracker_stationary_20260909.json.gz` | Stationary wall-tracker scan |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `mapping-finish-2026-09-08/` | Saved track maps and identity/corner scans that `test_straight_escape.py` reads (moved from `docs/validation` by D-226: data a test reads lives beside the test) |

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

<!-- MANUAL: -->
