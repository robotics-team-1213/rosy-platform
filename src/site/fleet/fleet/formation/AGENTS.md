<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# formation

## Purpose

Pure FOR-001/002 functions: named formations → slot offsets, and a swappable slot assigner. No transport, no asyncio, no ROS. Output is numbers a follower can pass to `follow_goal`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `geometry.py` | `Formation`, `SlotOffset`, `slots()`, `MIN_SPACING` (0.4 m, derived from Nav2 inflation + footprints), `DEFAULT_SPACING` (0.6 m) |
| `assignment.py` | `SlotAssigner` protocol and `GreedyDistanceAssigner` (FOR-002) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Keep this tree import-pure. `test/test_boundaries.py` fails on httpx/websockets/asyncio/rclpy.
- If Nav2 inflation/footprint changes, recompute `MIN_SPACING` from the formula in `geometry.py` — do not pick a nicer round number.
- `SlotAssigner` is a Protocol so a Hungarian assigner can replace greedy without touching callers.

### Testing Requirements

```bash
python -m pytest src/site/fleet/test/test_geometry.py src/site/fleet/test/test_assignment.py src/site/fleet/test/test_boundaries.py -v
```

### Common Patterns

Dataclasses + enums. Input numbers, output numbers. Follower pose is leader heading + `(distance, lateral)`.

## Dependencies

### Internal

- Spacing rationale cites `src/runtime/navigation/params/nav2_params.yaml`
- Slot offsets feed `core.navigation.swarm.follow_goal` (contract, not an import)

### External

None.

<!-- MANUAL: -->
