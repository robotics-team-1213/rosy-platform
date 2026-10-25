<!-- Parent: ../../../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# decision

**Parent context:** `../../../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

Actual proposal implementation under `operations/decision/src/rosy/decision`, canonical import `rosy.decision` (D-429 section 5, D-637). The existing Fleet distribution installs this namespace; source composition uses static holder mapping. There is no separate wheel/server or `fleet.ai` shim. Proposal-only embodied-model adapters used by Fleet services. A model may propose pick/place candidates and request allowlisted, non-executable feedback tools; nothing here moves a robot or calls CORE. Pixel-level identity evidence only: no 3D pose, grasp or physical completion is inferred.

## Key Files

| File | Description |
|------|-------------|
| `candidate.py` | Typed, provenance-carrying proposals (`PickPlaceProposalCandidate`, `ImageObservation`, `ER2ProposalError`) |
| `er2_standard.py` | Gemini Robotics ER 2 standard-endpoint adapter (httpx); proposal-only |
| `model_tool_catalog.py` | Closed Fleet tool catalog and provider-schema projection |
| `model_tool_contract.py` | Provider-neutral `ModelToolCall` / `ModelToolResult` (pydantic) |
| `fleet.server.model_feedback_dispatch` (Fleet holder) | D-657 store/journal/fence adapter consumes these contracts; no Decision implementation or old module shim |
| `selector_bridge.py` | Resolves ER 2 image selectors against candidates from the same camera frame |
| `vision_observation_source.py` | Trusted, bounded reads of the source-scoped Vision preview API |
| `structured_output.py` | D-878 wire per provider family (Ollama `format`, OpenAI-compatible `response_format`) and one reply-envelope check; callers keep schema, error code and semantic validation |
| `decision_pipeline.py` | D-523 parsers: identity fact or allowlisted choice. No stuck answer and no network |
| `deliberation/` | D-640 bounded advisory supervisor and fixed CLI translator; Fleet owns durable records and activation |

## For AI Agents

### Working In This Directory

- Fleet retains its proposal store, stop/fence generations, watermarks and shared SQLite transaction. Moving the namespace does not redesign the store port/cycle or grant execution authority.
- Keep the catalog closed: a new tool needs a catalog entry, an effect class and a dispatch allowlist decision together.
- Model output is untrusted. Selectors must resolve against the candidates of the same frame; reject mismatches rather than guessing.
- Do not add a robot command path here. Execution belongs to Fleet missions and CORE, the robot's only external API.
- `decision_pipeline.py` parses two AI PC replies and stops there (D-523). An identity fact is `wall`/`object`/`robot`/`person`/`unknown`. A choice is one Fleet allowlist entry or abstention. This module does not choose `WAIT`, `YIELD`, `RESUME`, `ABORT`, or `MANUAL`, and it does not call the network.
- Import wire schemas from `core_common.protocol.schemas`; do not import `rclpy` or `core`.

### Testing Requirements

D-584: send committed HEAD to a remote test PC and keep logs in the X session. Preserve the existing proposal/catalog/transaction regression suites.

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/decision" -- operations/fleet/test/test_er2_standard.py operations/fleet/test/test_er2_candidate_fence.py operations/fleet/test/test_er2_tool_dispatch.py operations/fleet/test/test_model_tool_catalog.py operations/fleet/test/test_model_tool_contract.py operations/fleet/test/test_model_tool_adapter_conformance.py operations/fleet/test/test_selector_bridge.py operations/fleet/test/test_vision_observation_source.py operations/fleet/test/test_decision_pipeline.py -q
```

Related: `test_model_tool_call_journal.py`, `test_mission_ai_proposal.py`, `test_mission_model_turn_store.py`. `test/test_remaining_platform_installed.py` checks installed namespaces and self-contained sdist delivery in both import orders alongside World/execution/skills. Source-move records: [progress.md](../../../progress.md), [logs.md](../../../logs.md), [index.md](../../../index.md).

### Common Patterns

Frozen/validated data types at the boundary, `httpx` calls injected so tests use fakes, no network in tests.

## Dependencies

### Internal

- `core_common.protocol.schemas`; consumed by `fleet.server` mission code

### External

- httpx, pydantic
