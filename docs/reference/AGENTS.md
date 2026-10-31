<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-29 -->

# reference

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-29

## Purpose

Shared contracts: REST/WS/protocol, architecture decisions, and the Host Agent unix-socket API. Changing these without code (or vice versa) is a defect.

## Key Files

| File | Description |
|------|-------------|
| `ROSY API & Protocol Reference.md` | ROSY-API-REF-001 — only shared robot/fleet/SDK interface; `/api/v1`, envelope, events |
| `ROSY ADR Log.md` | ROSY-ADR-001 — append-only index of every ADR. Do not rewrite an old row. The file is the list |
| `rosy-host-agent-contract.md` | ROSY-HOSTAGENT-001 — `/run/rosy/host-agent.sock`, no arbitrary shell |
| `team-guide.md` | 개인 클론 설정·훅 예외·공유 범위·작업 분담·인수인계. 게시 조건은 `pr-pipeline.md`로 연결 |
| `pr-pipeline.md` | 작성·독립 검토·게시·CI·병합의 기준과 확인일을 붙인 GitHub 설정 |
| `atlassian-integration.md` | Jira·Confluence 연결 안내: 이슈 키를 적는 자리(브랜치·커밋·PR), GitHub for Jira 앱, 스프린트 리뷰 표(`tools/jira_refs.py`), 문서 기록을 이슈의 기록용 코멘트 하나에 링크로 이어 붙이는 규칙(§4), 공개 저장소에 두지 않는 것(사이트 주소·토큰, D-437 secret 금지). 팀 관례이며 저장소 규칙이 아니다 |
| `shared-checkout.md` | 「같이 하는 깃」: 실험실 PC 공유 체크아웃의 착수 순서(README에서 옮김, `test/test_readme_agent_start.py`가 고정). 명령 전문도 이 문서다(2026-10-30). 루트 `AGENTS.md`는 안전 요약 |
| `git-workflow.md` | 사람용 git 규칙 한 장: 팀원 PR 길과 실험실 착지 길의 비교, `--no-verify` 기준, push 순서, D-762 단계 현황, 사용자가 정할 것. 규칙 원본은 D-372·D-427·D-510·D-584·D-761·D-762와 루트 `AGENTS.md` |
| `handoff.md` | 인수인계: 목표, 증거 기준의 현재 상태, 흐름별 2026-10-15 인계 문서, 다음 할 일, 담당, 새 컴퓨터 체크리스트. 날짜가 있는 사실이다 |
| `held-branches.md` | 2026-10-13/14 정리의 결과: 보류한 브랜치 5개와 풀리는 조건, 보관 태그(`archive/<날짜>/<브랜치>`) 목록·되살리기 명령. 태그와 wip 스냅샷은 실험실 clone에만 있고 wip은 공개 원격에 push하지 않는다 (D-172, D-762) |
| `developer-guide.md` | 구조, 빌드·시뮬, 테스트 단계(affected/quick/full), 관제 배치, Pi 5 런타임, 로드맵 — README에서 옮김 |
| `sim2real-gaps.md` | GENERATED from `tools/harness/sim2real_gaps.yaml` by `rosy_harness.py generate`; edit the YAML, not this table |
| `perception-gaps.md` | GENERATED from `tools/harness/perception_gaps.yaml`. Do not hand-edit |
| `ROSY Module Operational Acceptance Criteria.md` | ROSY-MODULE-ACCEPTANCE-001 — per-package operational GO criteria, evidence gates, and M01–M14 traceability |
| `platform-folder-responsibilities.md` | Current semantic tree (D-625, D-626, D-627, D-628, D-630, D-637). Ownership stays in `tools/harness/platform_parts.yaml` |
| `core-drive-responsibilities.md` | CORE, Drive, and Arm responsibility map (D-625 through D-630) |
| `fleet-rulebook.md` | Fleet rule pipeline index (D-674, D-678). `FL-*` and `FR-*` are search ids, not API fields |
| `application-contract-support.md` | 외부 업무 앱이 소비하는 Fleet HTTP 경로·권한·상태 의미와 정본·복구 책임 (D-836 W0) |
| `site-lan-discovery-profile.md` | mDNS/DNS-SD discovery contract. Tests and `deploy/site` read this path (D-341, D-361, D-370, D-382) |
| `team-discord-incidents.md` | Operator procedure for the team Discord incident channel. Webhook URL, channel id, and receipts stay out of the public repo |
| `ROSY_Platform_Architecture_Design_v0.2.md` | Architecture design v0.2. Accepted ADRs, including D-413, name this path |
| `OMX_AI_ROS2_Camera_Report_2026-09-26.md` | Camera report dated 2026-09-26. D-273 and D-299 name this path |
| `isaac-sim-integration-research.md` | Isaac Sim integration notes. D-322 names this path |
| `jev-local-decision-alternatives-2026-10-08.md` | Local decision-model notes dated 2026-10-08. D-516 names this path |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `legacy-tools/` | Frozen WSL scripts named by D-637 (`legacy-tools/wsl`). Not an operational path. `test/architecture/test_colcon_roots.py` pins that directory |

## For AI Agents

### Working In This Directory

- Schema source of truth for Python is still `core_common.protocol.schemas` (D-18); this API ref is the human contract.
- Host Agent: CORE client is `core_api_web.api.host_agent_client`; server is `deploy/robot/pinky_pro/release/host_agent.py`.
- Important ADRs: D-1 single process, D-2 cmd_vel mux, D-3 FastAPI replaces Flask, D-8 in-process event bus, D-22 Core/IO split + deadman, D-23 embedded dashboard, D-24/D-25 power (STANDBY not hibernate), D-27 deep-battery halt exception, D-33 robot identity from one robot number (supersedes D-6), D-34 publish rates matched to the consumer, D-38 CORE owns final cmd_vel, D-59 site fabric is a per-role contract bus, D-60 swarm follow is not owned by navigation, D-65 concept objects on CORE+D-62, D-67–D-71 concept folder freeze, D-73 per-module functional test surface, D-74 TaskKind sinks to internal ROS, D-161 native product runtime, D-197 Docker exits the product chain, D-246 native is the default and the container sidecar lane is profile-declared and non-safety.

### Testing Requirements

Protocol tests: `middleware/core/gateway/test/test_protocol_schemas.py`. Host Agent: `test/test_host_agent.py`.

### Common Patterns

API versioning is path-based (`/api/v1`). Additive schema changes bump protocol MINOR (PRT-006).

## Dependencies

### Internal

- `contracts/foundation/core_common/protocol/schemas.py`
- `middleware/core/api/core_api_web/api/`
- `deploy/robot/pinky_pro/release/host_agent.py`

### External

None.

<!-- MANUAL: -->
