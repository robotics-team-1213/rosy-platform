# ER 2 Mission Feedback Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver bounded, durable Mission progress back to ER 2 so it can return better typed candidates while Fleet retains admission authority and ROS/OMX retain action and safety control.

**Architecture:** Keep the Fleet Mission journal as the durable source of truth. Add an allowlisted standard Interactions tool loop for scoped status reads and candidate-only replans, then enqueue fresh stateless ER 2 turns from eligible durable Mission events. Keep per-turn provider replay ephemeral, all Mission changes and proposals correlated to event/attempt/generation IDs, and every controller action asynchronous and independent from provider availability.

**Tech Stack:** Python 3.12, Pydantic contracts, FastAPI/Fleet services, SQLite WAL/outbox, `httpx` standard Interactions adapter, pytest with fake transport/clock/controller. No Live API, streaming, ROS device calls, or hardware enablement in this plan.

---

## Scope and preconditions

- Governing decisions: [D-357](../adr/D-357-er2-mission-feedback-loop.md), [D-358](../adr/D-358-er2-feedback-outbox-and-replan-fencing.md); related boundaries: D-326, D-330 through D-334, D-18.
- Existing code includes `MissionProgressService.snapshot()` and owner/workcell-scoped `model_context()`, a Mission event journal/cursor, an ER 2 one-shot candidate adapter, and an opt-in Mission dispatcher. The app always composes the durable outbox scanner and accepts a model-turn worker only by explicit injection; its CLI/default composition supplies no worker, provider adapter, credential, or egress approval, so it queues eligible feedback without making a model request.
- `POLICY_DISPATCH_ENABLED` remains `False`; do not activate Mission dispatch as part of this plan. Any sample Mission used by tests is fake and has explicitly controlled admission.
- Keep `/api/fleet/missions` operator read routes and provider-internal tools as separate surfaces. Add no public REST path unless implementation proves one is required; if a wire contract changes, update API Reference, shared Pydantic schema, producer, consumer, and both sides' contract tests together per D-18.
- Standard Interactions only. `store=false` remains mandatory. No provider key, raw image, opaque provider step/signature, or full provider transcript may enter SQLite, logs, fixtures, or user-facing error text.
- Provider egress is denied before transport invocation unless the configured provider project/service tier and the specific camera/workcell/task data class are explicitly approved for the image and feedback fields being sent. `store=false` is a request option, not proof of provider-side non-retention or restricted human review. Runtime credentials must come from the approved secret injection path, separated by environment and restricted/rotatable; no API key is accepted from a Mission, tool argument, or operator payload.
- Every durable model-turn row carries its trusted principal, workcell, Mission, action/attempt, dispatch generation, event watermark, and policy revision. Provider-supplied tool arguments cannot select or widen this scope; the middleware intersects requested identifiers with the durable turn scope and rechecks current authorization and freshness on every tool call.
- Every asynchronous model turn must be recoverable from Fleet state and event watermark. A stale/unknown Action never auto-replays. Stop generation invalidates pending turns and proposals; no automatic rearm.
- **Ownership is split by effect:** ER 2 emits bounded tool requests and typed candidates only; the Fleet tool dispatcher validates and executes the allowlist; the Fleet Mission journal owns mission/step state and evidence references; the model-turn outbox/worker owns provider-attempt scheduling only; the Fleet admission path owns whether a candidate becomes an admitted Mission; the device-local Action owner is the only ROS/driver command writer; the independent goal verifier owns `GOAL_CONFIRMED`; the device stop owner and independent physical safety chain own stop action/readback. A provider tool result or `Interaction.status` never transfers any of these authorities.
- **Observation-source constraint:** the provider tool request carries only its trusted trigger watermark and rationale; the model cannot name an observation it has not seen. Fleet acquires a fresh post-action image through the optional trusted Vision reader, then runs the existing selector proposal adapter on that image. `VisionPostActionObservationSource` uses an immutable workcell-to-source/camera/frame/calibration mapping, a short-lived source-scoped lease, and bounded no-store JPEG reads with trusted freshness metadata. It is wired only when explicitly injected alongside a worker; runtime source configuration and camera/Mission-data egress approval remain separate deployment gates. Until those gates are satisfied, `propose_replan` returns `unavailable`; status feedback can proceed. Never treat rejected goal evidence as an unsatisfied goal or reuse selectors from an old image.
- **Provider delivery is not exactly-once:** the unique outbox key guarantees one logical row, not one provider-side execution. Record an attempt durably before invoking the provider transport. Known success becomes `RESPONDED`; local validation/preflight failure before transport invocation may return to `PENDING`; any exception after invocation begins, including timeout or disconnect, becomes `UNKNOWN` and is never automatically resubmitted. With `store=false`, do not assume an API exists to retrieve a lost response. A fresh attempt requires a new eligible event/generation after rechecking current model policy, while the old attempt remains `UNKNOWN`. Candidate persistence is idempotent by turn/attempt and event watermark. No provider-attempt status changes Mission or Action state.
- Evidence tiers remain separate: SOURCE/LOCAL tests do not establish ROS-SIM, ARTIFACT, DEVICE, or FIELD acceptance.

## Task 1: Freeze the model feedback and tool-result contract

**Files:**
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py`
- Test: `src/contracts/foundation/test/test_mission_progress_contracts.py`
- Review: `src/site/fleet/fleet/server/mission_progress.py`, `src/site/fleet/fleet/server/mission_service.py`

1. Add/extend typed models for a bounded ER 2 feedback context and tool result. Include Mission ID, active action/attempt, dispatch generation, latest event watermark, axis states, source, observation time/freshness, and bounded reason. Exclude arbitrary event detail, credentials, raw observations, and evidence payloads.
2. Add candidate-only replan request/result fields bound to source Mission, observation ID, action/attempt, current generation and `based_on_event_id`. Reject missing/mismatched attempt or stale generation. A replan is a separate linked successor-Mission proposal (`supersedes_mission_id`); never mutate or reopen the source Mission/Action in place. Operator resolution creates a distinct Mission draft through the existing approval path, and the existing admission gate still decides whether that successor can run. Keep request IDs distinct from provider call IDs and Mission/Action IDs.
3. Test valid snapshots and rejection of extra/oversized fields, wrong owner/workcell, stale event/generation, unknown action/attempt, and model-provided terminal/completion claims. Freeze named limits for context/result bytes, function calls per turn, provider deadline, replay step count/bytes, response bytes, image bytes, post-action observation age (30 seconds), and cost; tests exercise each exact boundary and fail closed when a limit or egress policy is absent.
4. Run `python -m pytest src/contracts/foundation/test/test_mission_progress_contracts.py -q` and record the baseline result before proceeding.

**Exit:** provider-facing types are typed, bounded, and cannot represent device authority or physical completion claims.

## Task 2: Build the middleware-owned allowlisted tool dispatcher

**Files:**
- Create: `src/site/fleet/fleet/ai/tool_dispatch.py`
- Test: `src/site/fleet/test/test_er2_tool_dispatch.py`
- Modify only if needed: `src/site/fleet/fleet/server/mission_progress.py`, `mission_service.py`

1. Write failing tests for `get_mission_status` owner/workcell isolation and `propose_replan` candidate-only behavior, including wrong IDs, wrong generation, stale event watermark, duplicate call ID, unknown tool, malformed arguments, and over-budget calls.
2. Implement an explicit allowlist and typed argument validators. Resolve every tool through Fleet services, not arbitrary import paths, URLs, ROS topics, or driver methods. Derive principal/workcell/Mission/action/attempt/generation/event scope from the durable turn row, never from model arguments, and recheck authorization, freshness, stop generation, and row policy before each call. Execute serially under the frozen per-turn call, payload, timeout, and cost budgets.
3. Return bounded structured results: `accepted`, `rejected`, or `unavailable`, a stable reason code, and relevant event/proposal IDs. Never encode an Action submit, cancel, stop, E-stop, rearm, motor, joint, or gripper function.
4. Verify rejected tool calls do not mutate Mission state, cross-principal/cross-workcell IDs supplied by prompt-injected arguments are denied, admitted proposals remain subject to existing operator/policy gates, and duplicate call IDs do not create duplicate candidate records. A replan proposal stores immutable source-Mission/action/attempt/generation/event/observation correlation and resolves only to a separately identified successor Mission draft; it cannot alter the source Action or skip operator admission.

**Exit:** only status reads and typed, non-executable replan proposals can pass the dispatcher; unsupported or unsafe calls fail closed.

## Task 3: Implement bounded stateless Interactions function-result turns

**Files:**
- Modify: `src/site/fleet/fleet/ai/er2_standard.py`
- Test: `src/site/fleet/test/test_er2_standard.py`
- Modify: `src/site/fleet/fleet/ai/candidate.py` only for typed candidate correlation fields

1. Add fake-transport tests for a function call followed by a function result and a final model response using the provider's documented stateless replay format. Assert `store=false` on every request and required prior call/result steps appear in the correct order.
2. Add tests for multiple or reordered calls, unknown tool, invalid provider step/signature, oversized replay, total turn/time/tool budget exhaustion, HTTP timeout, malformed result, and error response. Assert missing/denied provider-egress policy prevents any transport call; provider secret injection is environment-scoped and API key material is absent from logs/errors/traces. No automatic retry after an ambiguous POST.
   - **Deadline enforcement:** `ER2_PROVIDER_DEADLINE_SECONDS` bounds provider requests and Fleet tool dispatch as one turn. Async replan dispatch is cancellable at the remaining budget; synchronous read tools run off the event loop and the adapter stops awaiting them at the turn deadline. A turn that expires after provider invocation remains an ambiguous outbox attempt and is never resubmitted.
3. Keep provider step/signature bytes only in bounded per-turn memory; inspect logs, exceptions, and persisted records to prove they are redacted/not written. Discard the transcript at turn completion or failure.
4. Keep the existing single proposal path backward compatible and ensure no adapter method invokes a tool itself without the Fleet dispatcher or calls a public operator endpoint.

**Exit:** standard ER 2 can consume Fleet tool results within one bounded `store=false` turn; it cannot retain server-side interaction state or directly execute controller work.

## Task 4: Persist idempotent follow-up turns from eligible Mission events

**Files:**
- Create: `src/site/fleet/fleet/server/mission_model_turn_store.py`
- Create: `src/site/fleet/test/test_mission_model_turn_store.py`
- Modify: `src/site/fleet/fleet/server/mission_store.py`, `mission_dispatcher.py`, `mission_model_turn_store.py`, `mission_model_turn_worker.py`, `app.py` as required by current composition
- Test: `src/site/fleet/test/test_mission_dispatcher.py`, new `src/site/fleet/test/test_mission_feedback_loop.py`

1. Define eligible triggers narrowly: a reconciled terminal Action result and an independent goal evidence transition. Use this outcome policy: active stop or generation mismatch => `SUPPRESSED` with no provider turn; Action `UNKNOWN`/`HOLD` or stale Action readback => `SUPPRESSED` with no tools; reconciled terminal Action plus pending/unknown/rejected/stale goal evidence or unresolved object effects => status-only turn (`get_mission_status`), never `propose_replan`; only a fresh, independently verified unsatisfied goal with reconciled Action/object effects and no stop latch may enable candidate-only `propose_replan`; confirmed goal => status-only summary, no replan. Ordinary status reads and model-generated events never trigger another model turn.
2. Create an SQLite outbox unique on Mission ID, triggering event ID, dispatch generation, and model-policy revision. Persist only sanitized context references/watermarks and queue state; never provider replay material, image bytes, API key, or full transcripts. A terminal Action event with unresolved object/physical effects or pending/unknown goal evidence may prompt status reasoning but cannot authorize `propose_replan`.
3. Give each row an explicit transition (`PENDING -> CLAIMED -> SUBMITTING -> RESPONDED | REJECTED | UNKNOWN`, with `SUPPRESSED` for stop/stale-generation policy). Commit `SUBMITTING` before invoking the provider transport. Only local validation/preflight failure before transport invocation may return to `PENDING`; expired `CLAIMED` work is reclaimable, but expired `SUBMITTING` work is `UNKNOWN` and not reclaimable for another provider POST. This is at-most-one client submission attempt, not exactly-once provider execution.
4. Test duplicate event delivery, event-before-provider-completion ordering, restart before/after `SUBMITTING`, provider timeout after acceptance, local preflight rejection before transport invocation, outbox write failure, stale generation, duplicate candidate persistence, and same trigger arriving twice. Assert the provider-call count stays at one after an ambiguous attempt and no path resubmits a physical Action.
5. Add a bounded worker/dispatcher that loads a fresh scoped snapshot when consuming an outbox row, rechecks stop/generation/admission before provider call, and attaches any returned candidate to the trigger watermark. **Implemented:** `ProposalStore.create_feedback_candidate_fenced()` uses one `BEGIN IMMEDIATE` transaction over the shared SQLite database to compare the current dispatch latch/generation, source Mission/action/attempt, latest event watermark, unsatisfied goal event, and an authorized post-action observation no older than 30 seconds before inserting a linked proposal. Operator resolution rechecks the fence and creates a separate successor Mission with `supersedes_mission_id`; stop/source-event drift marks the candidate rejected. The dispatcher has an injectable async post-action observation source and returns `REPLAN_OBSERVATION_UNAVAILABLE` when none is configured. The worker atomically claims the next pending row and the app runs its consumer loop only when a worker using the same SQLite database is explicitly injected. The app can inject and close the optional `VisionPostActionObservationSource`: it uses immutable workcell/source/camera/frame/calibration mapping, a short-lived source-scoped lease, bounded no-store JPEG reads, trusted frame metadata, and a capture timestamp later than the terminal Action; it never takes a URL or source ID from model arguments. After frame acquisition, the dispatcher rechecks trusted Mission/stop/event scope and full workcell/task/data-class approval immediately before sending image bytes to the selector adapter. Configuring the reader does not authorize provider egress. The default app and CLI still have no provider worker. The worker owns only provider-attempt lifecycle; it cannot admit a Mission, call ROS, or claim action/goal/stop completion.

**Exit:** each eligible durable event produces at most one logical outbox row and at most one client provider submission attempt. Stop/generation fencing is atomic with candidate visibility. A provider outcome that cannot be known stays `UNKNOWN`; provider or process failure leaves the physical Mission recoverable and cannot resubmit its Action.

## Task 5: Fence stop, cancel, late results, and Mission completion

**Files:**
- Modify: `src/site/fleet/fleet/server/mission_model_turn_store.py`, `mission_progress.py`, `mission_service.py`
- Test: `src/site/fleet/test/test_mission_feedback_loop.py`, `test_mission_progress.py`, `test_mission_service.py`

1. Test stop arriving before tool dispatch, during provider turn, after provider response but exactly before candidate commit, and before outbox consumption. Ensure atomic stop/generation fencing rejects or invalidates all older-generation candidates before they become visible/resolvable.
2. Test late model response, late Action readback, duplicate terminal event, Action `SUCCEEDED` without goal evidence, rejected/stale goal evidence, and physical stop `UNKNOWN`. Keep Action, goal, and stop axes distinct in every context sent to the model.
3. Ensure cancel/stop goes only through the existing authorized Fleet/device owner path. Provider cancellation may discard model computation but cannot stand in for Action cancellation or physical stop. Restart/rearm requires current human/operational gates and never replays queued physical work automatically.
4. Keep `POLICY_DISPATCH_ENABLED` false in config and add a regression assertion in the relevant Fleet test that candidate creation/follow-up cannot admit or dispatch a Mission by itself.

**Exit:** no stale model/provider response or unsupported completion claim can reopen, finish, or physically stop a Mission.

## Task 6: Close API/schema/docs and operational diagnostics

**Files:**
- Modify: `docs/reference/ROSY API & Protocol Reference.md`
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py` if the final wire model differs from Task 1
- Modify: `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/ai/` only for the consumed contracts
- Test: `src/contracts/foundation/test/test_mission_progress_contracts.py`, `src/site/fleet/test/test_mission_api.py`, `test_er2_tool_dispatch.py`, `test_er2_standard.py`

1. Document provider-internal tool declarations/results separately from authenticated Fleet REST routes. State trusted turn scope, role/workcell scope, response limits, event cursor, freshness semantics, tool budgets, provider-egress policy, and `UNKNOWN`/`HOLD` behavior. Do not promise WebSocket, streaming, direct ROS access, or physical progress percentages.
2. Document what counts as accepted proposal, a linked successor-Mission replan, terminal Action result, verified goal completion, and physical stop readback. Explicitly identify user-visible Mission status as Fleet/controller evidence, not provider `Interaction.status`.
3. Test the producer and consumer contracts together. Verify public errors reveal no API key, provider transcript, signed step, image, or cross-principal data, and verify replan resolution cannot mutate/reopen the source Mission or Action.

**Exit:** API Reference, shared schema, Fleet readers/writers and tests describe the same contract; no undocumented route or tool is exposed.

## Task 7: Verify and hand off to ROS-SIM/device gates

**Files:**
- Run only the focused suites below; no ROS/device configuration changes are authorized by this plan.
- Update implementation evidence only after the corresponding gate is actually run.

1. Run `python -m pytest src/contracts/foundation/test/test_mission_progress_contracts.py -q`.
2. Run `python -m pytest src/site/fleet/test/test_mission_progress.py src/site/fleet/test/test_mission_service.py src/site/fleet/test/test_mission_dispatcher.py src/site/fleet/test/test_er2_standard.py src/site/fleet/test/test_er2_tool_dispatch.py src/site/fleet/test/test_mission_model_turn_store.py src/site/fleet/test/test_mission_feedback_loop.py -q`.
3. Run the repository quick documentation gate: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`; then `python tools/harness/rosy_harness.py lint`.
4. Run `python -m pytest src/site/fleet/test/ src/contracts/foundation/test/ -q` only if focused tests expose a shared-contract risk or the change touches shared consumer imports.
5. Record test counts and failures precisely. The three D-357 suites (`test_er2_tool_dispatch.py`, `test_mission_model_turn_store.py`, `test_mission_feedback_loop.py`), the atomic candidate-fence suite, the trusted Vision reader suite, and an integrated event→outbox→atomic provider-submission-fence test are mandatory exit gates; pre-existing progress/one-shot adapter tests do not count as D-357 coverage. The fenced candidate writer, stop-before-commit/resolution tests, optional app worker lifecycle, and bounded Vision reader are implemented. Numeric boundary tests cover context/result/replay/response/image/freshness/cost limits, and adapter tests cover the exact function-call cap, malformed steps, stateless tool-result ordering, and a deadline expiring inside async tool dispatch. A stop/event/eligibility change during frame acquisition is rechecked before image egress, and denied camera/data-class approval prevents that egress. Final 2026-09-30 SOURCE/LOCAL gates: the D-357/D-358 contract, feedback, outbox, candidate-fence, Vision, API, and overhead invocation passed 137 tests; documentation gate passed 80 tests; changed-file flake8 passed; harness lint reported 0 errors and 12 existing freshness warnings. Runtime activation remains gated on trusted workcell/source configuration, camera-observation and Mission-data egress approval, provider project/service tier and data policy, secret injection/rotation/permissions, and a production worker configuration. Include evidence for the mission-progress and mission-instruction data classes and the frozen numeric limits from Task 1. Host tests establish SOURCE/LOCAL only. Plan later ROS-SIM with a fake/event-driven controller; require independent device stop, Action, goal, operator-admission, artifact, and field evidence before any live enablement.

**Exit:** focused tests and harness pass; Mission dispatch remains disabled by default; no provider call, ROS execution, device install, or physical acceptance is claimed.
