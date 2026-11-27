<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# localization

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-14

## Purpose

D-395 Fleet localization arbiter. Scores each robot's pose candidates with bounded cues and decides only when one leads the next by a margin held for 2 s. Pure: no transport, no asyncio, no robot calls. The service loop that feeds it and sends decisions belongs to `server/` (Phase 2).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `cues.py` | Bounded cues per hypothesis: peers, slot (10 cm / 20 deg, either way along the axis), last good pose (never after a pickup), overhead sighting (≤ 300 ms), reference square |
| `auto_locate.py` | D-989: LED-confirmed camera track + robot map pose -> SLAM-to-site transform (rigid fit, or heading from lidar objects toward peers). Disagreement latches DEGRADED. Observation only |
| `track_heading.py` | Pure `TrackHeading`: the motion heading of a blob track that has none (moving odometry + track moved past a deadband). Shared by lane compliance and the track anchor |
| `arbiter.py` | `Weights`, `Context`, `score()`, `Arbiter.observe()` → `LocalizationDecision` |
| (not in this folder) | MapPose lives in `rosy.world.state.projections.map_pose`. Import it directly (D-752). This folder does not re-export it. Fleet service, transaction, and admission stay in `server/` |
| `lane_compliance.py` | D-511 2: signed lateral offset (left +), body margin `width_m/2 − (|d| + half width)` from `core_common.robot_body`, `LaneComplianceTracker` (OK/WARN/ACT/UNKNOWN, `persist_n`), `LaneComplianceConfig` (`fleet.lane_compliance`, provisional defaults). Observe only |
| `topview_pose.py` | 2026-11-27: Pinky offset from the model S training spot read from the arm cell's top camera (SIFT registration to a stored reference frame, orange tray, px-to-site map in `deploy/site/cell-topview/*.json`); `solve_px_to_site` self-calibration. Lazy cv2, no network. Used by `server/trips/named_stop_topview.py` |
| `wall_grid.py` | SLAM fallback: active site map walls -> Nav2 trinary map in the site frame (0.025 m, walls >= 1 cell, pure stdlib, deterministic sha256), served by `GET /api/fleet/site-map/wall-grid` |
| `wall_tiebreak.py` | D-1046 bounded exception to "overhead never decides alone": two ~180-degree twin loc_assist candidates, both scan fit >= 0.85, picked by ceiling camera position (>= 1 m apart, 2 s hold); allowed only while CORE reports `slam_fallback.phase` WAITING_LOCALIZATION, never ACTIVE |

## For AI Agents

### Working In This Directory

- Keep it pure: `test_boundaries.py` forbids httpx, websockets, rclpy, asyncio, fastapi, `fleet.swarm` and `fleet.server` here.
- A missing input is a 0 cue, never a guess; the arbiter must work with no camera and no peers.
- `last_good` and `overhead` weigh less than the margin on purpose: neither may decide alone (D-395 §7).
- Exception `wall_tiebreak.py` (D-1046, owner: SLAM fallback): only in `slam_fallback.phase` WAITING_LOCALIZATION (first pose after the wall-map switch, never ACTIVE), only between scan-fit >= 0.85 mirror twins, fresh camera sighting held 2 s; decision carries `source: overhead` and `evidence.tiebreak`.

### Testing Requirements

`python -m pytest operations/fleet/test/test_localization_cues.py operations/fleet/test/test_localization_arbiter.py operations/fleet/test/test_boundaries.py -q`

## Dependencies

### Internal

- `core_common.protocol.localization` (`CandidateReport`, `LocalizationDecision`)

### External

None.

<!-- MANUAL: -->
