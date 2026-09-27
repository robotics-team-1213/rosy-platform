# ROSY Platform P0 — navigation task and result trace

**Date:** 2026-09-27

**Scope:** current Site Fleet → Pinky CORE navigation path in source and host tests.

**Evidence level:** SOURCE/LOCAL only. No robot, Nav2, physical stop, or FIELD observation.

## One requested move, traced by owner

| Boundary | Current evidence and owner | What it proves | What it cannot prove |
|---|---|---|---|
| Operator → Fleet | `app.py` requires an operator bearer and `Idempotency-Key`; `task_service.py` creates a durable `task_id`, validates the goal and queues it; `task_store.py` records status history. | Fleet accepted one site intent and can return the same task for the same key. | CORE received or executed the move. |
| Fleet → CORE | `task_service.dispatch_next` records a dispatch attempt; `console.goal` calls `HttpRobotClient.navigation_goal`, which POSTs `{x,y,yaw}` to `/api/v1/navigation/goal`. | A CORE request was attempted; an explicit positive response can move Fleet to `ACCEPTED`. | The request carries no `task_id`/`correlation_id`; a timeout cannot be interpreted as rejection or safely replayed. |
| CORE → Nav2 | `navigation_goal` resolves the goal, checks capability/readiness and calls `svc.nav.goal`; `NavigationManager.goal` sends it to its executor and emits `nav.started` with goal/by. The REST result is `{accepted,mode,goal}`. | CORE accepted the goal into its local navigation path. | Nav2 arrival, physical travel, or a specific Fleet task result. |
| CORE final event → Fleet | `NavigationManager.on_result` emits `nav.completed` with no data or `nav.failed` with `error_code`; Site Fleet `CoreEventStore` can retain an event by `(robot_id,event_id)`. | An event from a robot can be audited when the Agent path delivers it. | Event identity and order do not correlate that event to `task_id` or a particular command attempt. |
| Fleet task readback | `task_store.transition` rejects `RUNNING` and `COMPLETED` on the generic path; `/api/fleet/tasks/{task_id}` returns receipt and history. | A receipt stays distinct from execution. | Completion is unavailable until a separately verified result transition exists. |
| Cancel and stop | Queued task cancellation stops before dispatch. CORE navigation cancel issues an executor cancel and emits `nav.canceled`; site robot stop calls the CORE safety path. | A software cancel/stop request and its current software response. | Physical standstill, driver output, independent E-stop response, or safe recovery (D-298). |

`AckStatus` is a robot command ACK contract; `FleetTaskStatus` is the site task
projection. Their same-named values do not make them one state machine. D-297
is the proposed activation design; D-177 is superseded. No command
`correlation_id` is emitted or consumed on this current navigation REST path.

## Minimum comparison before a common device contract

| Meaning | Pinky evidence | OMX evidence | Decision |
|---|---|---|---|
| Site task identity and idempotency | Fleet `task_id` and operator request key are durable. | No operating site Device Action consumer. | `proven(Pinky)` for Fleet intent; `candidate(OMX)` for a future request. No new shared schema. |
| Device acceptance | CORE positive REST receipt; Fleet stores only accepted/queued booleans. | Current adapter is inactive for site operation. | `proven(Pinky)` receipt semantics; OMX result shape open. |
| Device final result | CORE local `nav.completed`/`nav.failed` exists, without task or command ID. | No DEVICE result/readback trace. | `open` for cross-device correlation and Fleet completion. |
| Stop evidence | Software cancel/event path exists. | Hardware stop/readback unverified. | `open` for physical standstill in both cases. |

## First heterogeneous mission candidate and physical result

The existing mobile manipulation research stages **Pinky transport plus a fixed
OMX workcell** after a fixed OMX pick/place baseline. A bounded first mission
candidate is: Pinky carries one registered test object in a defined transfer
fixture to the workcell, stops at a validated handoff pose, then the fixed OMX
transfers that object from the fixture to a designated output location. The
mission result is **the identified object physically at that output location**,
with a separately evidenced Pinky stop and OMX arm/gripper state. Fleet owns the
order and handoff record; Pinky CORE and OMX local control retain their final
motion commands and stop decisions.

This is a **candidate acceptance case**, not an enabled Mission/Step contract.
Object mass and dimensions, fixture geometry, pose tolerance, work envelope,
stop/readback method, object-presence sensor, fault recovery and who confirms
the final placement require the selected hardware and FIELD procedure. A CORE
arrival event, OMX action success, camera detection or Fleet receipt alone
cannot declare the physical mission result. If the fixture or stationary
handoff cannot be validated, the first mission must be reselected before a
shared schema is approved. Pinky-mounted OMX is a separate local-interlock case.

## Required counterexamples for the next contract change

1. Two consecutive goals with identical coordinates: a `nav.completed` event
   cannot be assigned by coordinates or arrival order alone.
2. CORE accepts a goal while the Fleet HTTP response is lost: Fleet must keep
   `UNKNOWN`, preserve the attempt and reconcile without automatic replay.
3. A cancel returns while a late success arrives: verify command ID, robot ID,
   attempt and event sequence before any task transition. A cancel response is
   not stop readback.
4. Duplicate, delayed, out-of-order or post-restart events: persist and audit
   them without manufacturing a new physical result or overwriting prior
   uncertainty.
5. A wrong robot or never-issued command ID: reject as task result even if the
   event type is `nav.completed`.

## Gate and next unit

The existing guard is verified by `test_task_store.py` (unverified execution
transitions rejected) and `test_task_api.py` (positive receipt leaves task at
`ACCEPTED`). The focused host suite also covers CORE navigation API response.
P0 records the missing join; it does not activate D-297. Before implementing a
result transition, decide and test the command ID lifecycle across Fleet's
durable attempt, CORE's acceptance and final event, restart/reconnect and
negative cases above. Change API Reference and `core_common` schemas together
if the public envelope changes. Keep Fleet `COMPLETED` unavailable until that
implementation and its source tests pass; DEVICE/FIELD must still establish
actual motion and stop behavior independently.

**Source pointers:** `src/site/fleet/fleet/server/{app,task_service,task_store,core_event_store}.py`,
`src/site/fleet/fleet/{server/console,swarm/transport}.py`,
`src/runtime/api_web/core_api_web/api/v1/navigation.py`,
`src/runtime/services/core_features/navigation/manager.py`,
`src/contracts/foundation/core_common/protocol/schemas.py`,
`docs/plans/2026-09-12-rosy-os-module-evaluation-maintenance-design.md`,
`docs/plans/2026-09-12-mobile-manipulation-research.md`, D-297, D-298.
