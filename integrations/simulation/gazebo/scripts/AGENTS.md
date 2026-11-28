
# scripts

**Parent context:** `../AGENTS.md`

## Purpose

Host-side swarm bench (`swarm_bench.py`, no `rclpy`) and `seed_initialpose.py` (rclpy node for D-115). `world_to_map.py` is ROS-free.

## Key Files

| File | Description |
|------|-------------|
| `world_to_map.py` | World collision boxes → nav2 occupancy. No rclpy |
| `seed_initialpose.py` | D-115: publish `{ns}/initialpose` at spawn. rclpy. Host pytest does not import this file |

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
