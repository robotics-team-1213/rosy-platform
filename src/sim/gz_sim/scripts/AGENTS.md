<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-24 -->

# scripts

## Purpose

Host-side swarm bench (`swarm_bench.py`, no `rclpy`) and `seed_initialpose.py` (rclpy node for D-115). `world_to_map.py` is ROS-free.

## Key Files

| File | Description |
|------|-------------|
| `swarm_bench.py` | Async bench: `follow` / `reform` / `hold` / `stuck` scenarios; CSV of slot error, stream age, relay Hz |
| `world_to_map.py` | World collision boxes → nav2 occupancy. No rclpy |
| `seed_initialpose.py` | D-115: publish `{ns}/initialpose` at spawn. rclpy. Host pytest does not import this file |
| `junction_score.py` | Junction scenarios from `lane_graph.yaml` and trajectory scoring. ROS-free |
| `junction_harness.py` | Runs the 12 junction scenarios in headless Gazebo and scores them |
| `coverage_harness.py` | Drives the all-lane coverage tour in headless Gazebo and scores it |
| `mission_harness.py` | Drives the lane-network mission (undock → tour → park) in headless Gazebo |
| `lane_live_view.py` | Live HTTP viewer (camera, perception overlay, progress) for a WSL Gazebo lane run |
| `record_debug.py` | Records `line/debug/compressed` to `overlay.mp4` plus `frames.jsonl` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- The measurement loop must not block. A blocking call stalls the relay and can cause a HOLD that the scenario did not request.
- Design: `docs/plans/2026-09-08-swarm-formation-slice-design.md` §8.2.
- `BLOCKED` is not a terminal nav state for sending the next waypoint.

### Testing Requirements

Not in host pytest. Package launch contracts are in `../test/`.

### Common Patterns

asyncio throughout. Writes CSV; does not synthesize relay frames.

## Dependencies

### Internal

- `fleet.bench` (D-148 공개면). `fleet.swarm.*` / `fleet.formation.*` 내부 직접 import는 금지 — `../test/test_bench_boundary.py` 가 고정한다.

### External

- Gazebo spawn for the `stuck` obstacle SDF; httpx/websockets via fleet transport

<!-- MANUAL: -->
