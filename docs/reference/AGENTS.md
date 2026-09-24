<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# reference

## Purpose

Shared contracts: REST/WS/protocol, architecture decisions, and the Host Agent unix-socket API. Changing these without code (or vice versa) is a defect.

## Key Files

| File | Description |
|------|-------------|
| `ROSY API & Protocol Reference.md` | ROSY-API-REF-001 — only shared robot/fleet/SDK interface; `/api/v1`, envelope, events |
| `ROSY ADR Log.md` | ROSY-ADR-001 — append-only decisions through D-209 (D-19 superseded by D-26, D-6 by D-33; D-29 unused gap; D-35 reserved; D-180 reserved by the unmerged perf/sd-single-verify branch; D-196 reserved by PR #36; D-204 reserved by the role-surfaces plan) |
| `rosy-host-agent-contract.md` | ROSY-HOSTAGENT-001 — `/run/rosy/host-agent.sock`, no arbitrary shell |
| `ROSY Module Operational Acceptance Criteria.md` | ROSY-MODULE-ACCEPTANCE-001 — per-package operational GO criteria, evidence gates, and M01–M14 traceability |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Schema source of truth for Python is still `core_common.protocol.schemas` (D-18); this API ref is the human contract.
- Host Agent: CORE client is `core_api_web.api.host_agent_client`; server is `deploy/release/host_agent.py`.
- Important ADRs: D-1 single process, D-2 cmd_vel mux, D-3 FastAPI replaces Flask, D-8 in-process event bus, D-22 Core/IO split + deadman, D-23 embedded dashboard, D-24/D-25 power (STANDBY not hibernate), D-27 deep-battery halt exception, D-33 robot identity from one robot number (supersedes D-6), D-34 publish rates matched to the consumer, D-38 CORE owns final cmd_vel, D-59 site fabric is a per-role contract bus, D-60 swarm follow is not owned by navigation, D-65 concept objects on CORE+D-62, D-67–D-71 concept folder freeze, D-73 per-module functional test surface, D-74 TaskKind sinks to internal ROS.

### Testing Requirements

Protocol tests: `src/core/core/test/test_protocol_schemas.py`. Host Agent: `test/test_host_agent.py`.

### Common Patterns

API versioning is path-based (`/api/v1`). Additive schema changes bump protocol MINOR (PRT-006).

## Dependencies

### Internal

- `src/core/core_common/core_common/protocol/schemas.py`
- `src/core/core_api_web/core_api_web/api/`
- `deploy/release/host_agent.py`

### External

None.

<!-- MANUAL: -->
