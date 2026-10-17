# Fleet native outcome consumer implementation plan

> **For Claude:** Execute these tasks in order, with a committed remote RED result before product changes. This worktree is `feat/channel-native-outcomes`.

**Goal:** Close D-732 Fleet SAFE_RELEASE and D-728 same-conversation native/Task outcomes without turning an RPC acknowledgement, an uncertain callback, or a quiescence proof into a motion grant.

**Architecture:** The existing Fleet Task SQLite database remains the only Fleet claim, step, and reply-intent writer. A small outcome responsibility under `fleet.server.channel.execution` binds one CORE-generated boot/run UUID to one persisted dispatch, reads the existing owner GET with `run_id`, and conditionally records a local claim release. The current CORE owner, mode, safety, and final writer remain authoritative; the event audit is an idempotent hint and durable terminal history, not a command source.

**Tech stack:** ROS-free Python, Pydantic `NativeOperation`, SQLite `BEGIN IMMEDIATE`, existing `HttpRobotClient`, `CoreEventStore`, Task owner, and channel reply outbox. All pytest runs use `tools/remote/remote_pytest.py` from a committed HEAD, followed by `test/known_failures.py`; never run pytest on this laptop.

---

### 1. Freeze the merged contract and prove RED

- Source: D-732, D-728, API Reference v1.220, the original positive grammar, and current `feat/ai-discord-link` execution journal/worker. Preserve the other main-branch API/status-input contract, D-731 submission package, historic structure baselines, and additive native child units.
- Add direct tests in `operations/fleet/test/test_channel_native_outcomes.py`: exact typed ACK identity retained without completion; a live/unknown run retains the claim; wrong run/boot and stale proof never settle; exact retained terminal plus bounded fresh quiescence releases only its own claim; multi-step continuation needs both successful terminal and safe release; closure after grant expiry/revocation does not dispatch; restart/two-worker conflict never resends.
- Add Task tests in `operations/fleet/test/test_task_native_outcomes.py`: bind the first CORE navigation receipt to the current Task attempt, ignore a same-CID different-run event, and backfill an exact event which arrived before receipt binding. Legacy non-native Task correlation remains explicit and tested.
- Commit these tests and the plan. Run a focused remote suite against that exact commit and compare `known_failures`; require failures at the missing contracts, not collection/import/fixture failures. Do not implement before this terminal RED proof.

### 2. Bind the exact operation at each first receipt boundary

- Direct action: `operations/fleet/fleet/server/channel/execution/receipts.py` validates the existing CORE `operation` by verb/kind/caller CID; `journal.py` persists it with robot, step owner, original ACK, and claim generation in the existing step table. `accepted:true` remains ACCEPTED. A missing or ambiguous receipt stays UNKNOWN and holds its claim; CID alone never discovers a UUID and never triggers a resend.
- Task navigation: `operations/fleet/fleet/server/ledger/goal_lease.py` (canonical `fleet.server.goal_lease`) calls a synchronous attempt-CAS binder immediately after `client.navigation_goal` returns, before Console traffic checks/cancel/other awaits. `task_service.py`, `task_store.py`, and `task_results.py` preserve the native operation with the exact `attempt_id`, robot, boot, and run. Native-bound Task events need that identity; keep the established CID projection only for explicitly non-native legacy attempts. Read the existing CoreEventStore by exact identity after binding because its callback cursor may have passed an event that arrived first.
- Carry a newly generated, persisted caller CID into home, dock, undock, follow and one teleop pulse before dispatch. Stop/cancel commands report the exact run they close; formation and site E-stop retain their separate existing owner semantics. No new endpoint, writer, or command path.

### 3. Reconcile without replay

- Use the existing background execution lifecycle in `execution/runtime.py`; scan bound ACCEPTED/RUNNING/UNKNOWN and terminal-but-unreleased rows, with bounded per-row work and exception isolation so one offline robot cannot stop other jobs. Existing CORE `GET /api/v1/{navigation/state,docking/status,swarm/state,teleop/state}?run_id=<UUID>` supplies exact typed state and proof. Never substitute a newer operation when `lookup:UNKNOWN`, prune, reboot, or timeout occurs. The existing durable CORE event audit may preserve an exact terminal when the 32-run buffer prunes, but an event alone cannot prove quiescence.
- Persist first exact terminal `result/reason` independently of `safe_released`. Only `SUCCEEDED` can make a finite native verb COMPLETED. Active follow and its HOLD keep the resource; PREEMPTED/CANCELED/EXPIRED/FAILED do not become goal success. A teleop watchdog EXPIRED is one pulse end, not distance or task success. Never call `ExecutionJournal.guard` for read-only closure after the grant expires or the role/message is withdrawn.
- The existing conversation result view and reply-intent outbox link progress and actual result to the immutable original request. A revoked actor may lose Discord delivery and direct access; the stored outcome remains visible to currently authorized Console readers. The outbox sender's current-route/role check remains in force. No later step is sent merely because a result was stored.

### 4. SAFE_RELEASE and later admission

- Capture Fleet `time.monotonic()` immediately before the readback RPC. Under `BEGIN IMMEDIATE`, require RPC-start-to-local-CAS at most two seconds, exact robot/boot/run/step/request, a retained terminal and `quiescent:true`, all pending/admitting/callback/lease booleans false, no current owner, and internally consistent current `owner_generation`/`transport_generation`. Generations legitimately advance after the original ACK; compare values within the fresh readback, not with the initial ACK.
- Conditional update/delete touches only `fleet_action_claims` for the exact `resource_key`, `owner_kind`, `owner_id`, and local dispatch generation, with a matching step row. Persist the proof and `safe_released` in that same local transaction. Claim reassignment, extra claim, changed step/run, stale proof, missing identity, or SQLite conflict leaves the claim unresolved. SAFE_RELEASED is a classification, neither COMPLETED nor a remote atomic claim or next motion grant.
- A later step requires both exact `SUCCEEDED` and SAFE_RELEASED, then a *new* original-grant/role/expiry, dispatch generation, resource, fresh observation, capability/localization, safety, mode and transport guard. For a new native command, read that command owner's current boot/generation and send the paired `expected_boot_id` and `expected_owner_generation`; CORE rechecks them before mode or backend side effects. Preserve bodyless legacy endpoints and unrelated callers.

### 5. Structural and remote gates

- Current inherited verdict for `fleet/fleet/server/channel/execution` is 487+150; merged source is near the cap. If implementation needs an outcome child unit, first measure the simultaneous `execution` residual, proposed real outcome unit, `channel`, Fleet package, and affected files using the existing scanner. Record dated physical counts, installed wheel/sdist/source-image closure, and independent precheck before changing `SIZE_UNITS`/`SIZE_VERDICTS`. Do not rebaseline or add an exclusion to make an overage green.
- After each behavior tranche, commit and run the focused remote suite with `known_failures`. At final source: run related Fleet Task/channel/event/replies/transport and architecture/installed tests, then the broader Fleet and gateway suites as selected by `affected`; require terminal 0 NEW on the exact committed HEAD. Parent integration runs its own combined gate. Host pass is not deployment, device, Discord delivery, or physical acceptance.

### 2026-10-12 physical outcome owner precheck

At implementation candidate `ca2748f050`, the existing `_over_budget` scanner was
run as a source measurement with only the proposed innermost outcome unit added
in memory; the checked-in SIZE_UNITS/SIZE_VERDICTS remain unchanged pending the
independent precheck. Simultaneous physical counts: execution residual 563,
outcomes 315, channel residual 1453, conversation 300, health 248, Fleet residual
55237, app.py 933 and task_store.py 1041. Execution's 487+150 and Fleet's 55120+150
remain unchanged; task_store.py stays below its existing hard-tier 1060 ceiling.
The outcome child owns the actual ACK validator, first-response Task attempt CAS,
exact native evidence decoding, readback and local claim closure. The old receipts
import remains a two-line compatibility facade. It introduces no database, process,
command writer, dependency or scan exclusion. Task and channel callers share the
same existing SQLite claim owner. Wheel/sdist/source-image closure is checked by
extending the existing installed-package test, not inferred from source imports.

Remote candidate ca2748f050: 123 focused tests passed; known_failures reported
0 NEW / 0 known. The initial ed7440855 RED was 5 meaningful failing assertions.
The focused gate includes two SQLite workers, stale/delayed readback, reassigned
claims, exact boot/run, lost ACK without legacy inference, first-ACK/event races,
read-only closure after role/message/expiry changes, fresh next-command epoch,
follow RUNNING/HOLD and teleop EXPIRED. This is source evidence only.

Follow-up candidate measurement before independent registry precheck: outcome child
332, execution residual 563, Fleet residual 55249, task_store.py 1043; channel,
conversation, health and app.py remain as measured above. The first Task terminal
native event is now stored before readback; a contradictory readback cannot replace
it. Pending native closure no longer depends on a still-ANSWERED model grant, and
a process restart between Task safe release and channel projection cannot replay
the original Task. Exact installed closure passed 4 cases at db0037481e. Full Fleet
regression is running against 0a4f7d41ce; this paragraph records no terminal verdict
for that still-running job. Registry values remain unchanged pending precheck.

Independent structural precheck: ralph_native_verify approved committed 041d567e60
on 2026-10-12: register only `fleet/fleet/server/channel/execution/outcomes` at332.
The reviewer independently measured exact 0a4 archived source at outcomes327,
execution563/channel1453/conversation300/health248/Fleet55249/task_store1043,
and confirmed the subsequent reconcile-only +5 yields332. The checked-in registry
now adds this one real child; all historical parent/file/hard-tier baselines,
allowances, exclusions and previous split obligations remain unchanged.
