
# decision

**Parent context:** `../../../AGENTS.md`

## Purpose

Proposal implementation at `operations/decision/src/rosy/decision`, import `rosy.decision` (D-429 section 5, D-637). The Fleet distribution installs this namespace; no separate wheel/server or `fleet.ai` shim. Proposal-only embodied-model adapters: a model may propose pick/place candidates and request allowlisted, non-executable feedback tools; nothing here moves a robot or calls CORE. Pixel-level identity evidence only: no 3D pose, grasp or physical completion is inferred.

## For AI Agents

### Working In This Directory

- Fleet keeps its proposal store, stop/fence generations, watermarks and shared SQLite transaction; the D-657 adapter `fleet.server.model_feedback_dispatch` consumes these contracts. Moving the namespace grants no execution authority.
- Keep the tool catalog (`model_tool_catalog.py`) closed: a new tool needs a catalog entry, an effect class and a dispatch allowlist decision together.
- Model output is untrusted. `selector_bridge.py` resolves selectors only against candidates of the same camera frame; reject mismatches, never guess.
- No robot command path here. Execution belongs to Fleet missions and CORE. `vision_observation_source.py` reads only the source-scoped Vision preview API, bounded.
- `decision_pipeline.py` parses two AI PC replies and stops (D-523): an identity fact (`wall`/`object`/`robot`/`person`/`unknown`) or one Fleet allowlist choice or abstention. It never chooses `WAIT`, `YIELD`, `RESUME`, `ABORT` or `MANUAL` and never calls the network.
- `structured_output.py` (D-878) owns the per-provider wire and one reply-envelope check; callers keep schema, error code and semantic validation. `deliberation/` (D-640) is an advisory supervisor; Fleet owns durable records and activation.
- Import wire schemas from `core_common.protocol.schemas`; no `rclpy` or `core`. Inject `httpx` calls so tests use fakes; no network in tests.

### Testing Requirements

D-584: committed HEAD on a remote test PC.

```bash
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/decision" -- operations/fleet/test/test_er2_standard.py operations/fleet/test/test_er2_candidate_fence.py operations/fleet/test/test_er2_tool_dispatch.py operations/fleet/test/test_model_tool_catalog.py operations/fleet/test/test_model_tool_contract.py operations/fleet/test/test_model_tool_adapter_conformance.py operations/fleet/test/test_selector_bridge.py operations/fleet/test/test_vision_observation_source.py operations/fleet/test/test_decision_pipeline.py -q
```

Related: `test_model_tool_call_journal.py`, `test_mission_ai_proposal.py`, `test_mission_model_turn_store.py`, `test/test_remaining_platform_installed.py` (installed namespaces, sdist). Move records: [progress.md](../../../progress.md) · [logs.md](../../../logs.md) · [index.md](../../../index.md).
