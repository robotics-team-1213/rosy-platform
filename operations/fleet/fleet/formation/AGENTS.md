
# formation

**Parent context:** `../AGENTS.md`

## Purpose

Pure FOR-001/002 functions: named formations → slot offsets, and a swappable slot assigner. No transport, no asyncio, no ROS. Output is numbers a follower can pass to `follow_goal`.

## For AI Agents

### Working In This Directory

- Keep this tree import-pure. `test/test_boundaries.py` fails on httpx/websockets/asyncio/rclpy.
- If Nav2 inflation/footprint changes, recompute `MIN_SPACING` from the formula in `geometry.py` — do not pick a nicer round number.
- `SlotAssigner` is a Protocol so a Hungarian assigner can replace greedy without touching callers.

### Testing Requirements

```bash
python -m pytest operations/fleet/test/test_geometry.py operations/fleet/test/test_assignment.py operations/fleet/test/test_boundaries.py -v
```

### Common Patterns

Dataclasses + enums. Input numbers, output numbers. Follower pose is leader heading + `(distance, lateral)`.

## Dependencies

### Internal

- Spacing rationale cites `middleware/drive/planning/nav2/params/nav2_params.yaml`
- Slot offsets feed `core.navigation.swarm.follow_goal` (contract, not an import)
