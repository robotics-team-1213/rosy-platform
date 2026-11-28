
# reference

**Parent context:** `../AGENTS.md`

## Purpose

Shared contracts: REST/WS/protocol, architecture decisions, and the Host Agent unix-socket API. Changing these without code (or vice versa) is a defect. `ls` lists the files; the rules below are the ones a file name does not show.

## For AI Agents

### Working In This Directory

- `ROSY API & Protocol Reference.md` (ROSY-API-REF-001) is the only shared robot/fleet/SDK interface (`/api/v1`). Python schema source stays `core_common.protocol.schemas` (D-18). Additive schema changes bump protocol MINOR (PRT-006).
- `ROSY ADR Log.md` is an append-only index: never rewrite an old row.
- `rosy-host-agent-contract.md` (`/run/rosy/host-agent.sock`): no arbitrary shell. Client `core_api_web.api.host_agent_client`; server `deploy/robot/pinky_pro/release/host_agent.py`.
- `sim2real-gaps.md` and `perception-gaps.md` are GENERATED from `tools/harness/*.yaml` by `rosy_harness.py generate`: edit the YAML. OMX gap rows start at G-17 in `sim2real_gaps.yaml`.
- `platform-folder-responsibilities.md` (D-625 to D-630, D-637) is the current tree; ownership stays in `tools/harness/platform_parts.yaml`. `fleet-rulebook.md` (D-674, D-678): `FL-*`/`FR-*` are search ids, not API fields. `common-services.md` (D-987) is pinned by `test_common_services.py`.
- `shared-checkout.md` holds the full shared-git procedure (pinned by `test/test_readme_agent_start.py`); root `AGENTS.md` keeps the safety summary. `git-workflow.md` sources: D-372, D-427, D-510, D-584, D-761, D-762. `pr-pipeline.md` is the gate for publishing.
- `held-branches.md`: archive tags and wip snapshots exist only in the lab clone; wip is never pushed to the public remote (D-172, D-762).
- `atlassian-integration.md` and `team-discord-incidents.md`: no site addresses, tokens, webhook URL, channel id or receipts in the public repo (D-437 secret ban).
- Files that accepted ADRs name by path must not move: `ROSY_Platform_Architecture_Design_v0.2.md` (D-413), `OMX_AI_ROS2_Camera_Report_2026-09-26.md` (D-273, D-299), `isaac-sim-integration-research.md` (D-322), `jev-local-decision-alternatives-2026-10-08.md` (D-516),
- `site-lan-discovery-profile.md` (D-341, D-361, D-370, D-382).
- `legacy-tools/wsl` is frozen (D-637; pinned by `test_colcon_roots.py`).
- Key ADRs: D-1 single process, D-2 cmd_vel mux, D-3 FastAPI replaces Flask, D-8 event bus, D-22 Core/IO split + deadman, D-23 dashboard, D-24/D-25 power (STANDBY not hibernate), D-27 deep-battery halt exception, D-33 robot identity (supersedes D-6), D-34 publish rates, D-38 CORE owns final cmd_vel,
- D-59 site fabric, D-60 swarm follow, D-65 concept objects, D-67-D-71 concept folder freeze, D-73, D-74, D-161 native runtime, D-197 Docker exits the product chain, D-246 native default; container sidecar is profile-declared and non-safety.

### Testing Requirements

Protocol: `middleware/core/gateway/test/test_protocol_schemas.py`; Host Agent: `test/test_host_agent.py` (D-584 remote).
