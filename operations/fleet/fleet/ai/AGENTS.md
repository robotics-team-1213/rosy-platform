<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# ai

## Purpose

Proposal-only embodied-model adapters used by Fleet services. A model may propose pick/place candidates and request allowlisted, non-executable feedback tools; nothing here moves a robot or calls CORE. Pixel-level identity evidence only: no 3D pose, grasp or physical completion is inferred.

## Key Files

| File | Description |
|------|-------------|
| `candidate.py` | Typed, provenance-carrying proposals (`PickPlaceProposalCandidate`, `ImageObservation`, `ER2ProposalError`) |
| `er2_standard.py` | Gemini Robotics ER 2 standard-endpoint adapter (httpx); proposal-only |
| `model_tool_catalog.py` | Closed Fleet tool catalog and provider-schema projection |
| `model_tool_contract.py` | Provider-neutral `ModelToolCall` / `ModelToolResult` (pydantic) |
| `tool_dispatch.py` | Fleet-owned allowlist dispatch for non-executable feedback tools |
| `selector_bridge.py` | Resolves ER 2 image selectors against candidates from the same camera frame |
| `vision_observation_source.py` | Trusted, bounded reads of the source-scoped Vision preview API |

## For AI Agents

### Working In This Directory

- Keep the catalog closed: a new tool needs a catalog entry, an effect class and a dispatch allowlist decision together.
- Model output is untrusted. Selectors must resolve against the candidates of the same frame; reject mismatches rather than guessing.
- Do not add a robot command path here. Execution belongs to Fleet missions and CORE, the robot's only external API.
- Import wire schemas from `core_common.protocol.schemas`; do not import `rclpy` or `core`.

### Testing Requirements

```bash
python -m pytest operations/fleet/test/test_er2_standard.py operations/fleet/test/test_er2_candidate_fence.py operations/fleet/test/test_er2_tool_dispatch.py operations/fleet/test/test_model_tool_catalog.py operations/fleet/test/test_model_tool_contract.py operations/fleet/test/test_model_tool_adapter_conformance.py operations/fleet/test/test_selector_bridge.py operations/fleet/test/test_vision_observation_source.py -q
```

Related: `test_model_tool_call_journal.py`, `test_mission_ai_proposal.py`, `test_mission_model_turn_store.py`.

### Common Patterns

Frozen/validated data types at the boundary, `httpx` calls injected so tests use fakes, no network in tests.

## Dependencies

### Internal

- `core_common.protocol.schemas`; consumed by `fleet.server` mission code

### External

- httpx, pydantic
