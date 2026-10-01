# Provider-Neutral Model Tool Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize Gemini ER 2 and future reasoning-model tool calls into one Fleet-owned, fail-closed message/effect/result contract without giving models device Action or ROS authority.

**Architecture:** Provider adapters translate native tool-call and tool-result envelopes to internal typed `ModelToolCall` / `ModelToolResult` values. A Fleet allowlist dispatcher derives identity and authority from a durable trusted turn scope, executes only bounded read/proposal effects, and records durable writes idempotently. Fleet Mission admission and the device-local Action/ROS/stop owners remain separate.

**Tech Stack:** Python 3.12, Pydantic, FastAPI/Fleet services, SQLite WAL with `synchronous=FULL`, Gemini Interactions API adapter, pytest, Rosy harness.

---

## Decision and scope

This plan implements [D-392](../adr/D-392-provider-neutral-model-tool-contract.md), informed by the pinned [official sample audit](2026-10-01-gemini-robotics-samples-research.md). The notebook's pick-and-place functions are mocks, while the Live API Spot embodiment demonstrates an actual model-to-robot application path using allowlisted OpenAPI operations, a FastAPI/Boston Dynamics backend, and correlated tool results. Reuse its catalog/adapter/feedback structure, not its authority topology: a sample-generated tool list cannot grant Rosy capability, and its model-routed `stop` is not an independent local stop or physical E-stop. Model-visible functions remain Fleet-approved read/proposal effects in this plan. Do not implement a direct `move`, joint, trajectory, gripper, Action submit, cancel, stop/E-stop, or rearm tool.

Existing behavior to preserve:

- D-331: standard Gemini proposal tool remains candidate-only, stateless (`store=false`), with no automatic physical dispatch.
- D-334 and D-357: model-visible functions are bounded and Fleet-executed; progress facts come from the Fleet journal, and tool completion is distinct from Mission/Action/goal/stop completion.
- D-358: trusted turn scope, stop/generation fences, durable provider outbox, no automatic replay after ambiguous provider transport.
- D-369 and D-376: local Action owner remains the only ROS command writer; local stop and physical E-stop remain independent.

No public REST path, shared robot wire envelope, ROS interface, capability activation, provider SDK dependency, or physical acceptance is part of this plan. If implementation changes a public response or shared schema, stop and update the API Reference/schema/consumer tests together under D-18 before continuing.

## Priority

| Priority | Phase | Completion evidence | Gate |
|---|---|---|---|
| P0 | Contract inventory | Existing provider, dispatcher, result, outbox and API scopes documented | SOURCE |
| P1 | Canonical call/result types | Strict types and boundary tests | SOURCE |
| P2 | Gemini adapter mapping | Current ER 2 path passes canonical calls/results without behavior drift | SOURCE/LOCAL |
| P3 | Fleet effect/idempotency enforcement | Allowlist, trusted scope, durable dedupe and unknown semantics | SOURCE |
| P4 | Adapter conformance and docs | Provider-neutral fixtures; generated index and clean harness lint | SOURCE |
| P5 | ROS-SIM / ARTIFACT / DEVICE / FIELD | Separate system, hardware and operator evidence | ROS-SIM control-path slice observed; full model-to-admitted-Action/fault matrix and later gates remain HOLD/PARKED |

## Task 1: Capture current boundaries and freeze compatibility behavior

**Files:**

- Read: `docs/adr/D-331-gemini-er2-proposal-adapter.md`
- Read: `docs/adr/D-334-er2-tool-and-progress-read-boundary.md`
- Read: `docs/adr/D-357-er2-mission-feedback-loop.md`
- Read: `docs/adr/D-358-er2-feedback-outbox-and-replan-fencing.md`
- Read: `docs/adr/D-369-control-authority-and-stop-evidence.md`
- Read: `docs/adr/D-376-omx-pick-place-planning-and-execution-boundary.md`
- Inspect: `src/site/fleet/fleet/ai/er2_standard.py`, `src/site/fleet/fleet/ai/tool_dispatch.py`, `src/site/fleet/fleet/server/mission_model_turn_store.py`, `src/contracts/foundation/core_common/protocol/schemas.py`
- Test: `src/site/fleet/test/test_er2_standard.py`, `src/site/fleet/test/test_er2_tool_dispatch.py`, `src/site/fleet/test/test_mission_model_turn_store.py`, `src/site/fleet/test/test_mission_feedback_loop.py`

**Steps:**

1. Record the provider-native call fields, current function schemas, trusted turn scope, durable write points, current result meanings, and current response replay behavior in the implementation change description.
2. Identify all existing compatibility invariants from D-331/334/357/358; do not rename tools or change success/failure semantics in this task.
3. Run the four focused Fleet suites before editing and save their baseline counts in the work log.

**Exit:** Existing call parsing and effect behavior are understood, and baseline tests pass. A pre-existing failure is reported before implementation proceeds.

## Task 2: Add canonical model-tool call and result types

**Files:**

- Create: `src/site/fleet/fleet/ai/model_tool_contract.py`
- Test: `src/site/fleet/test/test_model_tool_contract.py`

**Steps:**

1. Add failing tests for a `ModelToolCall` with opaque `provider_call_id`, bounded `tool_name`, JSON-object `arguments`, trusted `turn_id`, and stable call ordinal. Reject missing IDs, malformed names, non-object/non-finite JSON, unknown envelope fields, and arguments above the existing byte limit.
2. Add failing tests for `ModelToolResult` correlation and bounded outcomes `accepted`, `rejected`, `unavailable`, and `unknown`, plus uppercase bounded `reason_code` and JSON payload. Document in the type that `accepted` describes only the Fleet tool effect.
3. Implement strict immutable types in the Fleet AI boundary; do not place these internal provider messages in public robot `Envelope`, REST, or ROS schemas.
4. Run `python -m pytest src/site/fleet/test/test_model_tool_contract.py -q` and confirm all tests pass.

**Exit:** Provider call ID is explicitly distinct from Mission, Action, attempt, and ROS goal identity; trusted turn identity cannot be supplied or overridden by model arguments.

## Task 3: Normalize Gemini Interactions calls at the provider edge

**Files:**

- Modify: `src/site/fleet/fleet/ai/er2_standard.py`
- Test: `src/site/fleet/test/test_er2_standard.py`
- Use: `src/site/fleet/fleet/ai/model_tool_contract.py`

**Steps:**

1. Add failing adapter tests for feedback calls (`get_mission_status`, `propose_replan`) normalized into `ModelToolCall`, preserving opaque provider call ID and turn-local ordinal. Preserve D-331's one-shot `propose_pick_place` candidate parser; it is not dispatched as a callback and gets no function-result round-trip.
2. Add failing tests proving current Interactions declarations and arguments remain unchanged. Task 4 moves those declarations into the server-owned catalog.
3. Normalize only after provider response validation and before dispatcher invocation. Keep provider native objects, signatures and required replay material in bounded turn memory only as D-357 requires.
4. Map canonical results for dispatched feedback calls back to Gemini `function_result` with exact provider call correlation. The one-shot candidate flow has no provider result round-trip. Neither path may claim Action success, placement, or stop based on model output.
5. Run `python -m pytest src/site/fleet/test/test_er2_standard.py -q`.

**Exit:** Existing Gemini request shape, `store=false`, model ID, tool names, provider budgets, and candidate semantics are unchanged; calls are normalized before any Fleet effect.

## Task 4: Enforce a closed catalog and trusted-scope dispatcher

**Files:**

- Create or modify: `src/site/fleet/fleet/ai/model_tool_catalog.py`
- Modify: `src/site/fleet/fleet/ai/tool_dispatch.py`
- Test: `src/site/fleet/test/test_er2_tool_dispatch.py`

**Steps:**

1. Add failing tests for unknown tools, low-level motion/gripper/Action/cancel/stop/E-stop/rearm names, extra arguments, oversized arguments, cross-principal Mission IDs, stale event watermarks, and changed dispatch generation.
2. Add failing tests proving principal/workcell/Mission/Action/attempt/generation are derived from the persisted turn scope even if similarly named arguments are supplied.
3. Implement a closed catalog that marks each existing tool as read-only or candidate-writing and supplies only the provider schema projection needed for the selected model turn.
4. Keep `get_mission_status` bound to the trusted scoped Mission. Keep `propose_replan` and `propose_pick_place` as typed candidate effects that cannot admit a Mission or call the device Action API.
5. Run `python -m pytest src/site/fleet/test/test_er2_tool_dispatch.py -q`.

**Exit:** Only catalogued effects run, and every request is authorized against trusted server context before any read or durable write.

## Task 5: Make durable effects idempotent and ambiguity explicit

**Files:**

- Modify: `src/site/fleet/fleet/server/proposal_store.py` (call-result journal shares the Fleet SQLite database; accepted candidate and result commit in one transaction)
- Modify: `src/site/fleet/fleet/ai/tool_dispatch.py`
- Modify: `src/site/fleet/fleet/ai/er2_standard.py`
- Modify: `src/site/fleet/test/test_model_tool_call_journal.py`
- Test: `src/site/fleet/test/test_mission_model_turn_store.py`
- Test: `src/site/fleet/test/test_er2_tool_dispatch.py`
- Test: `src/site/fleet/test/test_mission_feedback_loop.py`

**Steps:**

1. Add failing tests that replay an identical `(turn_id, provider_call_id, content_digest)` and receive the stored result without repeating the durable effect.
2. Add failing tests that reuse the same provider call ID with changed name/arguments and receive a conflict without changing the first result.
3. Add failing tests for stop/generation changes before effect commit, result persistence failure, provider timeout after transport invocation, late result after stop, and restart with an ambiguous provider attempt. Assert `UNKNOWN`/HOLD and no automatic provider or physical Action replay.
4. Implement a per-turn/provider-call journal. Store the accepted candidate and its correlated result atomically using the existing shared SQLite database and transaction boundaries. On restart, interrupted calls become UNKNOWN; retain WAL and `synchronous=FULL` configuration.
5. Run the three focused suites above.

**Exit:** A repeated call cannot duplicate a candidate write; changed-content identity reuse is rejected; uncertain provider/effect outcomes remain `UNKNOWN` without reopening or dispatching physical work.

## Task 6: Add adapter conformance and official-sample alignment fixtures

**Files:**

- Create: `src/site/fleet/test/test_model_tool_adapter_conformance.py`
- Modify: `docs/plans/2026-10-01-gemini-robotics-samples-research.md` if implementation findings change the source audit

**Steps:**

1. Add an in-memory fake provider adapter that emits a canonical call for one allowed read and one allowed candidate effect.
2. Add a second fake provider format to prove native field names/response envelope can differ while Fleet effect/result semantics, trusted scope, idempotency, limits, and stop fencing stay identical.
3. Include the notebook's mock `move` / gripper calls and hard-coded success response as negative fixtures. Also include sample-shaped OpenAPI operations and the Spot model-routed `stop`: neither dynamic backend discovery nor stop tools may enter Rosy's model catalog, and no result text may become physical completion evidence.
4. Add endpoint capability-profile tests so Interactions-only structured output/code-execution assumptions cannot leak into the Live API adapter; both profiles must preserve the same Fleet tool semantics where supported.
5. Run `python -m pytest src/site/fleet/test/test_model_tool_adapter_conformance.py -q`.

**Exit:** At least two provider-shaped fixtures converge on the same internal contract without adding a second live provider dependency or enabling actuation.

## Task 7: Update contracts, regenerate indexes, and run gates

**Files:**

- Modify: `docs/reference/ROSY API & Protocol Reference.md` only if a public route or response actually changes
- Modify: `src/contracts/foundation/core_common/protocol/schemas.py` only if a shared/public wire schema actually changes
- Modify: relevant Fleet AI module `progress.md` and append to `logs.md`
- Generate: `docs/index.md`, `STATUS.md`, and module indexes through the harness

**Steps:**

1. Add API Reference/schema changes only when public consumers change; internal `ModelToolCall` must not be documented as a robot-facing API.
2. Document the provider-neutral message IDs, accepted-result meaning, idempotency rule, unknown outcome, tool classes, and forbidden low-level tools in the Fleet AI module docs.
3. Run `python -m pytest src/site/fleet/test/test_model_tool_contract.py src/site/fleet/test/test_model_tool_adapter_conformance.py src/site/fleet/test/test_er2_standard.py src/site/fleet/test/test_er2_tool_dispatch.py src/site/fleet/test/test_mission_model_turn_store.py src/site/fleet/test/test_mission_feedback_loop.py -q`.
4. If shared or public schemas changed, run their contract/API conformance suites. Run `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`, and `git diff --check` from the repo root.
5. Record SOURCE/LOCAL evidence separately from ROS-SIM, ARTIFACT, DEVICE, FIELD. Keep provider, policy, and OMX activation disabled unless their separate gates pass.

**Exit:** Tests and harness pass; all models use the same bounded internal semantics; no provider or tool result can issue, confirm, cancel, or stop a device Action.

## Task 8: Later runtime and robot acceptance gates

**Files:**

- Use separate pinned Linux/ROS 2 Jazzy, simulator, artifact, and device evidence directories only when those gates are authorized and provisioned.

**Steps:**

1. ROS-SIM: use pinned vendor simulation and the real ROS action callback path to exercise acceptance, timeout, late result, stop-generation races, restart UNKNOWN, and four-phase pick/place. Use no live hardware.
2. ARTIFACT: pin model/provider configuration, adapter version, tool catalog revision, dependencies, secrets injection, approved data classes, and image-retention policy in the immutable artifact manifest.
3. DEVICE: verify the selected robot model/revision, calibration, gripper readback, single ROS command owner, cancel semantics, local stop, and independent E-stop/standstill evidence.
4. FIELD: require a supervised fixed workcell, one semantic `PICK_PLACE`, operator-admission record, independent goal evidence, stop/recovery drills, and rollback acceptance.

**Exit:** Each gate is recorded only from its own evidence. No source/test/simulation result is promoted to device or field acceptance.

## Execution record

- Completed through Task 6 (P0-P4): current-boundary inventory, canonical messages, Gemini boundary mapping, closed Fleet catalog, durable result journal, and provider-shaped conformance fixtures.
- P3 tests reject unknown and low-level actuation names, preserve closed schemas, and verify read-only versus candidate-writing classifications. The `propose_pick_place` one-shot candidate path remains separate from feedback function-result calls.
- Verification on 2026-10-01: 108 focused tests passed; changed Python files pass flake8; harness lint reports 0 errors and 24 repository `last_verified` drift warnings. No ROS-SIM, ARTIFACT, DEVICE, or FIELD gate was run.
- Task 5 implementation: canonical feedback calls are journaled by `(turn_id, provider_call_id, tool_name, ordinal, content_digest)`. Exact replays return their saved result, changed-content ID reuse conflicts, interrupted calls recover as UNKNOWN, and a candidate plus accepted result share one SQLite transaction. UNKNOWN/IN_PROGRESS aborts the outer provider turn without sending a function result.
- A final review found early `dispatch_replan` returns that bypassed the call journal. They now claim a validated and authorized canonical call once, persist deterministic policy/fence/egress/unavailable results, and return stored results on replay; invalid scope and unauthorized requests do not create claims.
- Task 5 verification before main integration: 77 focused tests and Fleet (1,036 passed, 6 skipped). After integrating latest main, Fleet passed 1,101 tests with 6 skipped; harness lint reports 0 errors and 24 existing freshness warnings.
- Operational constraint: ProposalStore startup converts prior IN_PROGRESS rows to UNKNOWN. Until recovery is owner/lease-aware, run one active Fleet writer per shared database; a second live process could mark the first process's call UNKNOWN.
- Task 6: test-only Interactions and Live API shaped adapters map differing native call/result fields into the same canonical contracts and actual Fleet dispatcher. Fixtures cover a read and candidate request, durable replay and ID collision, canonical argument size limits, stop-invalidated turn scope, and rejection of sample mock motion/gripper functions, sample-shaped OpenAPI operations, and Spot stop. Endpoint capability fixtures keep structured output and code execution out of Live API assumptions. No second live provider dependency or hardware effect was introduced.
- Task 6 verification: 25 conformance tests pass; these fakes prove contract compatibility only, not a production Live API adapter or ROS/device acceptance.
- Task 7 documentation: D-392 and this implementation plan are indexed from the Fleet progress record; canonical IDs, accepted-result meaning, idempotency, UNKNOWN handling, tool classes, forbidden actuation names, and safety ownership remain documented in the ADR. No public REST/robot schema changed, so API Reference and wire-contract schemas are intentionally unchanged.
- Task 7 final gates: 25 conformance tests and Fleet (1,128 passed, 6 skipped); changed Python files pass flake8 at the Fleet 120-character setting; harness lint reports 0 errors and 24 existing freshness warnings; `git diff --check` passes. ROS-SIM, ARTIFACT, DEVICE, and FIELD remain HOLD/PARKED under the plan.
- Task 8 ROS-SIM partial, 2026-10-01: re-ran the isolated OMX Pilot Gazebo path using `rosy-omx-pilot:local` (`sha256:e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`, Linux/amd64), loopback-only HTTP, and a read-only checkout. `probe_pilot_sim_http.py` observed joint1 and gripper ROS goals `SUCCEEDED`, increasing joint readbacks, and explicit cancel through terminal `CANCELED`. This proves the Pilot/local-owner/ROS-action callback/readback slice only; the Gemini model tool was not connected to the device Action path. Fleet model-tool suites passed 116 tests and OMX Action/store/PICK_PLACE suites passed 48 tests. Evidence and boundaries: [model-tool ROS-SIM partial report](../validation/model-tool-ros-sim-2026-10-01/README.md).
- The direct `test_omx_ros_runtime_vendor_sim.py` was run in the Pilot image with ROS Jazzy loaded and passed (1 passed): the test's own `RosArmCommandRuntime` submitted a no-op goal, observed state readback, rejected a competing owner, and received a terminal cancel result. An earlier base-image attempt lacked Pydantic and was not counted. Existing four-phase PICK_PLACE and generation/restart cases remain SOURCE tests, not vendor ROS-SIM evidence.
- Task 8 follow-up, 2026-10-01: latest `main` was fast-forwarded into the isolated feature worktree. Added a Jazzy ROS ActionServer fault test that holds an accepted goal past the configured owner deadline, accepts the local owner's cancel request, returns terminal CANCELED, and verifies HOLD stays latched with no command replay. The pinned Pilot image ran the vendor callback test (1 passed) and ROS callback tests (2 passed); ROS-free OMX Action/store/PICK_PLACE suites passed 37 with 1 ROS-only skip. See the expanded [ROS-SIM report](../validation/model-tool-ros-sim-2026-10-01/README.md).
- Task 8 integration follow-up, 2026-10-01: added a real Fleet Mission → version-2 Unix Action API (`SO_PEERCRED`) → local Action journal → Fleet receipt/reconciliation contract test. It found and fixed a PICK_PLACE receipt bug where the local `created` field carried the journal result object instead of a boolean; listener shutdown now treats a close-triggered `accept()` error as normal shutdown. The test ran in the pinned Jazzy Pilot image: **1 passed**. It uses an approach-only accepted-phase fixture and does not submit a ROS goal or claim grasp/place; the actual vendor ROS goal remains separately covered by the preceding simulation probe. See the updated [ROS-SIM report](../validation/model-tool-ros-sim-2026-10-01/README.md).
- Task 8 artifact record: added [a simulation-only immutable manifest](../validation/model-tool-artifact-2026-10-01/manifest.json) plus detached checksum. It pins local image IDs, source/tool-catalog hashes, vendor lock hash, direct Pilot package versions, provider/secret/egress state, and retention controls. The images are local and unsigned, no registry digest or complete OS/transitive SBOM is available, and the Gemini provider was not invoked; therefore this record does not pass ARTIFACT.
- Remaining gate closure: ROS-SIM remains HOLD until the grant-to-local-owner path is joined to an actual vendor ROS goal in one harness, pending-goal generation fencing and restart UNKNOWN/no-replay are exercised there, and four-phase execution has independent simulated object/gripper evidence. ARTIFACT requires a signed/published candidate and complete dependency provenance. DEVICE/FIELD require the identified robot, calibration and gripper readback, independent stop/E-stop/standstill evidence, a supervised fixed workcell, operator admission, goal evidence, recovery drills, and rollback acceptance. Keep provider and motion capability disabled until those separate gates pass.

- Task 8 Fleet-to-ROS integration, 2026-10-01: Added `test_omx_fleet_ros_actionserver.py` and ran it in the pinned `rosy-omx-pilot:local` Jazzy image (SHA-256 `e94662607c72a7cea83c9449178099c4c9476afab0519275ce0da82a88f3da9a`): **1 passed**. It joins Mission admission, SO_PEERCRED-authenticated v2 UDS grant/receipt, the durable OMX Action journal, `PickPlaceRunner`, and one actual ROS client goal against an in-process ActionServer. It verifies callback-bound UUID/result, Fleet accepted-only/nonterminal mission semantics, and restart `UNKNOWN` with no second goal on grant replay. The goal is a bounded no-op approach fixture with no camera/contact/gripper evidence and is not a vendor Gazebo run. A separate vendor Gazebo combined attempt was blocked by slow/unready controller startup and an out-of-limit joint3 report; no goal from that attempt is counted. Full ROS-SIM remains HOLD; evidence and exact boundaries are in the [ROS-SIM report](../validation/model-tool-ros-sim-2026-10-01/README.md).
- Task 8 continuation, 2026-10-01: Extended the Fleet-to-ROS test with a pending-goal generation change. The path trips Fleet's stop latch, sends the new fence through the authenticated LocalStop UDS API, observes exact ROS goal terminal `CANCELED`, rejects stale-grant replay, and reconciles the durable device receipt to Mission `HOLD`. This exposed that the canceled phase row was terminal while its parent Action remained `ACCEPTED`; `ActionStore.record_phase_terminal` now atomically records parent `HOLD` with `ROS_PHASE_CANCELED_ACTION_INCOMPLETE` in the same journal transaction. The Windows Action API test was observed failing before the fix and passing after it; the pinned Pilot image ran Fleet-to-ROS plus Action API tests: **18 passed**. This uses an in-process ROS 2 ActionServer, not vendor Gazebo, and proves no physical standstill/E-stop. Full ROS-SIM remains HOLD.
