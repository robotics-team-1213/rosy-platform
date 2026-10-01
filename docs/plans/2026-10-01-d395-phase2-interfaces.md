# D-395 Phase 2 — interface contract between the three lanes

Status: fixed for Phase 2 lanes A (robot node), B (CORE) and C (Fleet). The user approved Phase 2 on 2026-10-01 (robot launch/params, new CORE API paths, capability/role change, Fleet behaviour, check/homing motion). Real-robot runs (P2-10, S3) still need an announcement to the sessions sharing the robots and must wait for any session that is driving them.

Wire models are the Phase 1 ones in `core_common.protocol.localization` (`LocalizationStatus`, `CandidateReport`, `LocalizationDecision`, D-395 rev. 3: `cues`, `ttl_s` from receipt). Nothing below adds fields to them except where marked **new**.

## 1. Robot (sensing) ↔ CORE: ROS topics, robot namespace, JSON in `std_msgs/String`

Repo convention: like `line/observation` and `dock/observation`, payloads are one JSON object per message.

| Topic | Publisher → subscriber | Payload | Rate / QoS |
|---|---|---|---|
| `localization/state` | sensing `loc_assist_node` → CORE bridge | `{"status": LocalizationStatus, "pose": {x, y, yaw} \| null, "stamp": float}`; `pose` is the AMCL map pose when `status.pose_frame == "map"` | 2 Hz and on every change; reliable, depth 1, transient-local |
| `localization/candidates` | sensing → CORE | `CandidateReport` without `robot_id` (CORE fills it from its identity) | on every new request id and every 2 s while CANDIDATES (re-report with a new `stamp`, so a lost decision is retried, rev. 3) ; reliable, depth 1, transient-local |
| `localization/decision` | CORE → sensing | `{"decision": LocalizationDecision, "received_s": float}`; `received_s` is CORE's monotonic-free ROS clock at receipt | reliable, depth 5 |
| `localization/suspect` | CORE → sensing | `{"reason": str}` (Fleet monitor, §9) | reliable, depth 5 |
| `localization/result` | sensing → CORE | `{"request_id": str, "accepted": bool, "reason": str \| null, "state": LocState}` for every decision | reliable, depth 10 |
| `localization/mission` | CORE mission executor → sensing `loc_assist_node` (P2-7) | `{"kind": str, "state": "running" \| "done" \| "aborted", "reason": str \| null}` on start and end; the node searches no more while running and searches at once after every end | reliable, depth 5 |

`/initialpose` is published only by the sensing node's `inject_pose` action (through the existing CORE bridge path is **not** used any more for Fleet decisions). The legacy human `POST /api/v1/localization/initialpose` becomes a `LocalizationDecision(source=human, pose=...)` published on `localization/decision` (lane B), so every injection passes the same 3 s check (lane A).

## 2. CORE ↔ Fleet: HTTP, `/api/v1`, bearer token as today

| Method + path | Body / response | Auth |
|---|---|---|
| `GET /api/v1/robot/state` (existing) | `StateSnapshot.localization` now filled; `pose` frame per `pose_frame` | Viewer (unchanged) |
| `GET /api/v1/localization/candidates` **new** | latest `CandidateReport` (with `robot_id`) or `404 {"code":"NO_CANDIDATES"}` when the robot is not in CANDIDATES | `LOCALIZE_ASSIST` |
| `POST /api/v1/localization/decision` **new** | body `LocalizationDecision`; `202 {"request_id"}` when published to the robot, `409 STALE_REQUEST` when CORE already knows the id is not the open one, `423` during a D-321 calibration lease | `LOCALIZE_ASSIST`; `source: human` additionally needs `NAVIGATE` (Operator) |
| `POST /api/v1/localization/suspect` **new** | `{"reason": str}` (≤ 64 chars) | `LOCALIZE_ASSIST` |
| `POST /api/v1/localization/initialpose` (existing) | unchanged body `{x, y, yaw}`; now routed as `source: human` | `NAVIGATE` (unchanged) |
| `POST /api/v1/localization/mission` **new, lane B P2-7** | `{"kind": "rotate_in_place" \| "nudge_forward" \| "to_square" \| "lane_to_stopline", "max_distance_m": float, "max_time_s": float, "target": {...} \| null}` → `202` / `409 {"code": "path_not_clear" \| "busy" \| "estop" \| "calibration_lease" \| "localized"}` | `LOCALIZE_ASSIST` |
| `GET /api/v1/localization/mission` **new** | `{"kind", "state": "idle" \| "running" \| "done" \| "aborted", "reason"}` (P2-7 adds `idle` before the first mission; API Ref v1.72) | Viewer |

Events (catalogue rows added by lane B with emitters): `localization.state` (state changes), `localization.candidates` (new request id), `localization.result` (decision accepted/rejected, with `source` and `cues`), `localization.initialpose` (existing; now carries `source`).

Capability: `LOCALIZE_ASSIST` (**new**), granted to the Fleet operator token, separate from human `NAVIGATE`. API Ref moves to v1.70 with all version pins (header, `app.py` ×2, `test_line_follow_contract_docs.py`, `src/site/fleet/test/test_task_contract_docs.py` ×2, `src/site/fleet/test/test_mission_progress.py`).

## 3. Fleet behaviour (lane C)

- `server/localization_service.py`: every 0.5 s per robot, read `/robot/state`; when `localization.state == CANDIDATES` read `/localization/candidates`, build `Context` (LOCALIZED peers at their reported map poses, slots and squares from `lane_rules.yaml` `reference_squares`, overhead sightings ≤ 300 ms), run `Arbiter.observe`, `POST` the decision. Monitor (§9): a LOCALIZED robot whose overhead sighting or a peer's observation disagrees by > 25 cm or > 60° for 1.5 s → `POST /localization/suspect {"reason":"fleet_monitor"}`. Ladder timer: CANDIDATES for > 10 s without a decision → request `rotate_in_place`; > 25 s → `to_square` / `lane_to_stopline`; > 60 s → `needs_human` badge "위치 확인 필요" on the console.
- Traffic and bays (P2-2): skip a robot's pose when `localization` is present and (`pose_frame == "odom"` or `state != "LOCALIZED"`); such a robot is a wide obstacle (0.45 m keep-out) at its last trusted pose, or blocks the whole track when it has none. **Legacy policy (open question 2, decided):** `localization: null` (a robot without D-395) keeps today's behaviour, with a console warning "위치 상태 미보고".
- `RobotClient` gains `localization_candidates()`, `localization_decision(decision)`, `localization_suspect(reason)`, `localization_mission(...)`; `HttpRobotClient` and the test fakes implement them.

## 4. Lanes, branches, ownership

| Lane | Branch / worktree | Owns |
|---|---|---|
| A robot | `feat/d395-p2-robot-node` / `.worktrees/d395-p2-robot` | `src/runtime/sensing/control/loc_assist_node.py` (new), `localization_node.py` (remove its `/initialpose` on unique match), sensing launch + `setup.py`, sensing tests |
| B CORE | `feat/d395-p2-core-api` / `.worktrees/d395-p2-core` | gateway bridge, `core_api_web` routes, `capability.py`, auth/roles, events catalogue, `initial_pose.py`, API Ref v1.70 + pins, mission executor (P2-7) |
| C Fleet | `feat/d395-p2-fleet-service` / `.worktrees/d395-p2-fleet` | `swarm/transport.py` client, fakes, `server/localization_service.py`, traffic/bays/console, Fleet web badge |

Each lane works test-first against this document; integration and the Gazebo S1 bench (P2-8) follow after the three lanes land.
