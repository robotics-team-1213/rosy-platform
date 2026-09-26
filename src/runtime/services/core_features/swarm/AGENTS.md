<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-15 | Updated: 2026-09-15 -->

# swarm

## Purpose

SWM-001~007 robot-side follow. ROS-free. Aims via NavigationManager moving-goal
sessions. Does not own Nav2, sockets, or formation geometry.

## Key Files

| File | Description |
|------|-------------|
| `poses.py` | `ReferencePose`, `follow_goal` |
| `manager.py` | `SwarmManager` session, 2 Hz, HOLD |

## Testing Requirements

`test_swarm.py`, `test_swarm_api.py`, `test_swarm_stream.py`, `test_swarm_integration.py`, `test_navigation_swarm_boundary.py`

<!-- MANUAL: -->
