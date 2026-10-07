<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# localization

## Purpose

D-395 Fleet localization arbiter. Scores each robot's pose candidates with bounded cues and decides only when one leads the next by a margin held for 2 s. Pure: no transport, no asyncio, no robot calls. The service loop that feeds it and sends decisions belongs to `server/` (Phase 2).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `cues.py` | Bounded cues per hypothesis: peers, slot (10 cm / 20 deg, either way along the axis), last good pose (never after a pickup), overhead sighting (≤ 300 ms), reference square |
| `arbiter.py` | `Weights`, `Context`, `score()`, `Arbiter.observe()` → `LocalizationDecision` |
| `map_pose.py` | D-494 3 trip-only map pose: sighting anchor + odom bridge, `MapPoseTracker`, `MapPoseConfig` (`fleet.map_pose`), stdlib only. Not read by `/route`, D-395 or traffic |

## For AI Agents

### Working In This Directory

- Keep it pure: `test_boundaries.py` forbids httpx, websockets, rclpy, asyncio, fastapi, `fleet.swarm` and `fleet.server` here.
- A missing input is a 0 cue, never a guess; the arbiter must work with no camera and no peers.
- `last_good` and `overhead` weigh less than the margin on purpose: neither may decide alone (D-395 §7).

### Testing Requirements

`python -m pytest operations/fleet/test/test_localization_cues.py operations/fleet/test/test_localization_arbiter.py operations/fleet/test/test_boundaries.py -q`

## Dependencies

### Internal

- `core_common.protocol.localization` (`CandidateReport`, `LocalizationDecision`)

### External

None.

<!-- MANUAL: -->
