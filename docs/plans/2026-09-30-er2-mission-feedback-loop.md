# ER 2 Mission Feedback Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver bounded, durable Mission progress back to ER 2 so it can return better typed candidates while Fleet retains admission authority and ROS/OMX retain action and safety control.

**Architecture:** Keep the Fleet Mission journal as the durable source of truth. Add an allowlisted standard Interactions tool loop for scoped status reads and candidate-only replans, then enqueue fresh stateless ER 2 turns from eligible durable Mission events. Keep per-turn provider replay ephemeral, all Mission changes and proposals correlated to event/attempt/generation IDs, and every controller action asynchronous and independent from provider availability.

**Tech Stack:** Python 3.12, Pydantic contracts, FastAPI/Fleet services, SQLite WAL/outbox, `httpx` standard Interactions adapter, pytest with fake transport/clock/controller. No Live API, streaming, ROS device calls, or hardware enablement in this plan.

---

## Scope and preconditions

- Governing decision: [D-357](../adr/D-357-er2-mission-feedback-loop.md); related boundaries: D-326, D-330 through D-334, D-18.
- Existing code includes `MissionProgressService.snapshot()` and owner/workcell-scoped `model_context()`, a Mission event journal/cursor, an ER 2 one-shot candidate adapter, and an opt-in Mission dispatcher. The provider tool runner, durable model-turn outbox, and asynchronous progress-to-model trigger are new work; verify exact current composition before editing.
- `POLICY_DISPATCH_ENABLED` remains `False`; do not activate Mission dispatch as part of this plan. Any sample Mission used by tests is fake and has explicitly controlled admission.
- Keep `/api/fleet/missions` operator read routes and provider-internal tools as separate surfaces. Add no public REST path unless implementation proves one is required; if a wire contract changes, update API Reference, shared Pydantic schema, producer, consumer, and both sides' contract tests together per D-18.
- Standard Interactions only. `store=false` remains mandatory. No provider key, raw image, opaque provider step/signature, or full provider transcript may enter SQLite, logs, fixtures, or user-facing error text.
- Every asynchronous model turn must be recoverable from Fleet state and event watermark. A stale/unknown Action never auto-replays. Stop generation invalidates pending turns and proposals; no automatic rearm.
- Evidence tiers remain separate: SOURCE/LOCAL tests do not establish ROS-SIM, ARTIFACT, DEVICE, or FIELD acceptance.

## Task 1: Freeze the model feedback and tool-result contract

**Files:**
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py`
- Test: `src/contracts/foundation/test/test_mission_progress_contracts.py`
- Review: `src/site/fleet/fleet/server/mission_progress.py`, `src/site/fleet/fleet/server/mission_service.py`

1. Add/extend typed models for a bounded ER 2 feedback context and tool result. Include Mission ID, active action/attempt, dispatch generation, latest event watermark, axis states, source, observation time/freshness, and bounded reason. Exclude arbitrary event detail, credentials, raw observations, and evidence payloads.
2. Add candidate-only replan request/result fields bound to Mission, observation ID, current generation and `based_on_event_id`. Reject missing/mismatched attempt or stale generation. Keep request IDs distinct from provider call IDs and Mission/Action IDs.
3. Test valid snapshots and rejection of extra/oversized fields, wrong owner/workcell, stale event/generation, unknown action/attempt, and model-provided terminal/completion claims.
4. Run `python -m pytest src/contracts/foundation/test/test_mission_progress_contracts.py -q` and record the baseline result before proceeding.

**Exit:** provider-facing types are typed, bounded, and cannot represent device authority or physical completion claims.

## Task 2: Build the middleware-owned allowlisted tool dispatcher

**Files:**
- Create: `src/site/fleet/fleet/ai/tool_dispatch.py`
- Test: `src/site/fleet/test/test_er2_tool_dispatch.py`
- Modify only if needed: `src/site/fleet/fleet/server/mission_progress.py`, `mission_service.py`

1. Write failing tests for `get_mission_status` owner/workcell isolation and `propose_replan` candidate-only behavior, including wrong IDs, wrong generation, stale event watermark, duplicate call ID, unknown tool, malformed arguments, and over-budget calls.
2. Implement an explicit allowlist and typed argument validators. Resolve every tool through Fleet services, not arbitrary import paths, URLs, ROS topics, or driver methods. Execute serially under per-turn call, payload, timeout, and cost budgets.
3. Return bounded structured results: `accepted`, `rejected`, or `unavailable`, a stable reason code, and relevant event/proposal IDs. Never encode an Action submit, cancel, stop, E-stop, rearm, motor, joint, or gripper function.
4. Verify rejected tool calls do not mutate Mission state, admitted proposals remain subject to existing operator/policy gates, and duplicate call IDs do not create duplicate candidate records.

**Exit:** only status reads and typed, non-executable replan proposals can pass the dispatcher; unsupported or unsafe calls fail closed.

## Task 3: Implement bounded stateless Interactions function-result turns

**Files:**
- Modify: `src/site/fleet/fleet/ai/er2_standard.py`
- Test: `src/site/fleet/test/test_er2_standard.py`
- Modify: `src/site/fleet/fleet/ai/candidate.py` only for typed candidate correlation fields

1. Add fake-transport tests for a function call followed by a function result and a final model response using the provider's documented stateless replay format. Assert `store=false` on every request and required prior call/result steps appear in the correct order.
2. Add tests for multiple or reordered calls, unknown tool, invalid provider step/signature, oversized replay, total turn/time/tool budget exhaustion, HTTP timeout, malformed result, and error response. No automatic retry after an ambiguous POST.
3. Keep provider step/signature bytes only in bounded per-turn memory; inspect logs, exceptions, and persisted records to prove they are redacted/not written. Discard the transcript at turn completion or failure.
4. Keep the existing single proposal path backward compatible and ensure no adapter method invokes a tool itself without the Fleet dispatcher or calls a public operator endpoint.

**Exit:** standard ER 2 can consume Fleet tool results within one bounded `store=false` turn; it cannot retain server-side interaction state or directly execute controller work.

## Task 4: Persist idempotent follow-up turns from eligible Mission events

**Files:**
- Create: `src/site/fleet/fleet/server/mission_model_turn_store.py`
- Create: `src/site/fleet/test/test_mission_model_turn_store.py`
- Modify: `src/site/fleet/fleet/server/mission_store.py`, `mission_dispatcher.py`, `app.py` as required by current composition
- Test: `src/site/fleet/test/test_mission_dispatcher.py`, new `src/site/fleet/test/test_mission_feedback_loop.py`

1. Define eligible triggers narrowly: a reconciled terminal Action result and an independent goal evidence transition. HOLD or stale/unknown state records a blocked/suppressed follow-up; an active stop latch suppresses model re-entry. Ordinary status reads and model-generated events never trigger another model turn.
2. Create an SQLite outbox unique on Mission ID, triggering event ID, dispatch generation, and model-policy revision. Persist only sanitized context references/watermarks and queue state; never provider replay material, image bytes, API key, or full transcripts. A terminal Action event with unresolved object/physical effects or pending/unknown goal evidence may prompt status reasoning but cannot authorize `propose_replan`.
3. Test duplicate event delivery, event-before-provider-completion ordering, restart/replay of queued work, provider timeout after acceptance, outbox write failure, stale generation, and same trigger arriving twice. Ambiguous provider requests become `UNKNOWN` and require state reconciliation; do not blindly retry the request.
4. Add a bounded worker/dispatcher that loads a fresh scoped snapshot when consuming an outbox row, rechecks stop/generation/admission before provider call, and attaches any returned candidate to the trigger watermark. A candidate must use the existing Proposal/Mission approval path.

**Exit:** each eligible durable event produces at most one logical feedback turn; provider or process failure leaves the physical Mission recoverable and cannot resubmit its Action.

## Task 5: Fence stop, cancel, late results, and Mission completion

**Files:**
- Modify: `src/site/fleet/fleet/server/mission_model_turn_store.py`, `mission_progress.py`, `mission_service.py`
- Test: `src/site/fleet/test/test_mission_feedback_loop.py`, `test_mission_progress.py`, `test_mission_service.py`

1. Test stop arriving before tool dispatch, during provider turn, after proposal creation, and before outbox consumption. Ensure stop/generation changes invalidate pending turns and proposed candidates from older generations.
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

1. Document provider-internal tool declarations/results separately from authenticated Fleet REST routes. State role/workcell scope, response limits, event cursor, freshness semantics, tool budgets, and `UNKNOWN`/`HOLD` behavior. Do not promise WebSocket, streaming, direct ROS access, or physical progress percentages.
2. Document what counts as accepted proposal, terminal Action result, verified goal completion, and physical stop readback. Explicitly identify user-visible Mission status as Fleet/controller evidence, not provider `Interaction.status`.
3. Test the producer and consumer contracts together. Verify public errors reveal no API key, provider transcript, signed step, image, or cross-principal data.

**Exit:** API Reference, shared schema, Fleet readers/writers and tests describe the same contract; no undocumented route or tool is exposed.

## Task 7: Verify and hand off to ROS-SIM/device gates

**Files:**
- Run only the focused suites below; no ROS/device configuration changes are authorized by this plan.
- Update implementation evidence only after the corresponding gate is actually run.

1. Run `python -m pytest src/contracts/foundation/test/test_mission_progress_contracts.py -q`.
2. Run `python -m pytest src/site/fleet/test/test_mission_progress.py src/site/fleet/test/test_mission_service.py src/site/fleet/test/test_mission_dispatcher.py src/site/fleet/test/test_er2_standard.py src/site/fleet/test/test_er2_tool_dispatch.py src/site/fleet/test/test_mission_model_turn_store.py src/site/fleet/test/test_mission_feedback_loop.py -q`.
3. Run the repository quick documentation gate: `python -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q`; then `python tools/harness/rosy_harness.py lint`.
4. Run `python -m pytest src/site/fleet/test/ src/contracts/foundation/test/ -q` only if focused tests expose a shared-contract risk or the change touches shared consumer imports.
5. Record test counts and failures precisely. Host tests establish SOURCE/LOCAL only. Plan later ROS-SIM with a fake/event-driven controller; require independent device stop, Action, goal, operator-admission, artifact, and field evidence before any live enablement.

**Exit:** focused tests and harness pass; Mission dispatch remains disabled by default; no provider call, ROS execution, device install, or physical acceptance is claimed.
