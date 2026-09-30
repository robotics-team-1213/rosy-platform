# Fleet action admission baseline — 2026-09-29

## Baseline

- Worktree branch: `feat/fleet-mission-control`
- Starting revision: `951b6a02979d70227391e0ad81479eb0fbdbf101`
- Working tree was clean before this report.
- Command: `python -m pytest src/site/fleet/test/test_task_store.py src/site/fleet/test/test_task_scheduler.py src/site/fleet/test/test_task_api.py -q`
- Result: **43 passed**.

## Current action paths

| Entry | Principal and gate | Durable state / queue | Dispatch or stop writer | Current gap |
|---|---|---|---|---|
| `POST /api/fleet/robots/{robot_id}/goal` (`app.py:470`) | `operator_guard`, `require_operator` | With `task_service`, creates a `fleet_tasks` row and queues through `FleetTaskScheduler`; without it, no Fleet task admission | Background worker calls `FleetConsole.goal()` to CORE | The non-task-service fallback bypasses durable claim; CORE remains the final base command owner |
| `POST /api/fleet/do` (`app.py:609`) | `operator_guard`, `require_operator` | Each interpreted step runs sequentially; navigation enters task service only when enabled | Other robot verbs call `_robot_call()` directly; site verbs call `_site_call()` | Not an atomic Mission; nested goal/stop operations can bypass common admission; `stop`/`cancel` are not proof of physical stop |
| `POST /api/fleet/robots/{robot_id}/cancel` (`app.py:539`) | `operator_guard`, `require_operator` | Cancels queued Fleet work through `cancel_pending_task_queue()` | Calls `FleetConsole.cancel()` / robot navigation-cancel endpoint | Queue cancellation and device cancellation are separate outcomes |
| `POST /api/fleet/estop` (`app.py:663`) | `operator_guard`, `require_operator`; mutation audit middleware runs before route | Cancels queued Fleet work | `FleetConsole.estop_all()` scatters stop requests to registered CORE endpoints | Audit write failure currently prevents route; returned HTTP replies are not physical stop evidence |
| Background `_task_dispatch_loop()` (`app.py:723`) | Internal worker; available set comes from live Fleet snapshot and safety state | `FleetTaskScheduler.claim_next()` and `fleet_robot_reservations` in SQLite | `FleetTaskService.dispatch_next()` persists attempt, then calls `FleetConsole.goal()` | `FleetTaskService.__init__()` calls recovery; current recovery returns unsent READY/WAITING work to dispatchable state after restart |
| Direct CORE command | External API client/operator; separate CORE authentication | CORE-owned task/attempt state | CORE Command Manager is the only final base `cmd_vel` publisher | Fleet admission cannot fence callers that bypass Fleet; CORE authorization/fencing contract is required before Mission activation |
| OMX local command owner (`command_owner.py`, `ros_runtime.py`) | Local adapter profile and command-owner checks | Device-local action/owner state | OMX local adapter owns final arm trajectory submission | Fleet robot reservation does not fence workcell/object or prove goal receipt after process crash |

## Implementation constraints confirmed

- `fleet_robot_reservations.task_id` is a foreign key to `fleet_tasks(task_id)`. A Mission owner cannot be placed in that column without changing the schema; preserve old task/history identities during any migration.
- `FleetTaskStore.claim_next()` uses `BEGIN IMMEDIATE`, but there is no durable stop generation or persisted dispatch permit yet.
- A claimed navigation task is marked `DISPATCHING` before CORE is called. A process restart during that phase becomes `UNKNOWN`; however, work proven not sent is currently made READY and may dispatch after restart.
- Fleet `/estop` is a remote stop request. Device-local stop/readback, physical E-stop, CORE final command ownership, and Fleet HTTP responses remain distinct evidence.
- No policy, Mission, or OMX physical dispatch capability is enabled by this baseline.
