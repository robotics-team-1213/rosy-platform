<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# test

## Purpose

Launch-file contracts for `gz_multi.launch.py` when `core:=true`: per-robot identity, API port, and bind address. Skips when `launch` is missing (Windows host).

## Key Files

| File | Description |
|------|-------------|
| `test_gz_multi_core.py` | Imports launch by path; asserts `rosy_02` / port / `api_host == 127.0.0.1`; robots manifest lists every core with the dev operator token |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Sim cores must bind `127.0.0.1`. `0.0.0.0` would expose the dev token on the LAN.
- Do not convert this into a live Gazebo run in CI. It is a launch-graph unit test.

### Testing Requirements

```bash
python3 -m pytest integrations/simulation/gazebo/test/test_gz_multi_core.py -v
```

Requires `launch` / `launch_ros` (skipped otherwise).

### Common Patterns

`importlib` load of `../launch/gz_multi.launch.py` — the launch file is not a package module.

## Dependencies

### Internal

- `../launch/gz_multi.launch.py`

### External

- pytest, ROS 2 `launch` / `launch_ros` (optional on Windows)

<!-- MANUAL: -->
