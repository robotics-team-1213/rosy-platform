## D-1078 AI 자율 판단·폴백·학습 정책 무승인 즉시 실행 및 `rosy` 직접 Pick-and-Place 파이프라인 (1단계)

**Status:** Accepted (2026-11-27, 사용자 지시: "무승인정책도 바로 되어야해. 우리가 말을 하면 바로 동작하게끔 까지 가야해" — 1단계: AI 자율 판단·폴백·정책까지 전면 무승인 자동 실행, 고정 사이트/프리셋 기반 `cell_s` + `cell_ab`, 물리 안전가드 유지).

관련 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md) · [D-429](D-429-five-concerns-control-port-and-site-devices.md) · [D-430](D-430-safety-as-a-separate-concern.md) · [D-911](D-911-omx-native-reviewed-operating-envelope.md) · [D-1024](D-1024-omx-learned-policy-supervised-real-trial-fast-track.md) · [D-1057](D-1057-cell-task-admission-evidence.md) · [D-1072](D-1072-omx-ai-failure-fallback-context-and-agent-tool-pipeline.md) · [D-1077](D-1077-stop-capability-proof-replaces-presence.md).

### D-427 · D-429 · D-430 관계표

| 기준 ADR | 유지되는 계약 | 이번 ADR에서의 변경 |
|---|---|---|
| D-427 (파트 소유) | `middleware/`·`operations/`·`learning/`·`contracts/`·`tools/` 파트 경계 및 import 방향을 유지한다. 새 최상위 폴더를 두지 않는다. | Fleet 무승인 정책 헬퍼(`operations/fleet/fleet/server/pipeline/pipeline_autonomous_policy.py`)는 `operations/fleet`에, OMX 실행·정지증명 연동은 `deploy/robot/omx`에, LLM/CLI 브리지 도구는 `tools/remote/`에 둔다. |
| D-429 (다섯 관심사·포트) | 원시 장치 직접 구동(raw joint/PWM/FIFO/`cmd_vel`) 금지와 Fleet 원장 경유 단일 경로(`DeviceControlPort`/OMX owner)를 유지한다. | **D-429 §3·D-1072 개정(자율 운용 옵션):** `ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1`이 켜진 현장에서는 `service`/`ai_observer` 주체와 AI 폴백(`act_policy -> guarded_pick` 포함)이 별도 `admit` 없이 즉시 `QUEUED`로 투입된다(`propose: true` 명시 시 `PROPOSED` 유지). 기본값(`0`/미설정)은 기존 fail-closed(`PROPOSED` + 기명 승인)를 유지한다. |
| D-430 (safety 관심사·불변식) | 물리 E-stop, `HUMAN_HOLD`, `omx_incident` hold, A/B 피어 팔 접힘 확인, 관절/속도/하중 한계, D-1077 실행 직전 측정 정지 능력 증명(`cell_stop_proof`), 1 s 실행 lease(`cell_task_act_run`), 완료 시 `folded: true` 및 구역·깊이 검증을 유지한다. | `pipeline_autonomous_policy.py`를 `tools/harness/platform_parts.yaml`의 `safety_review_paths`에 등록해 §5 변경 통제를 적용한다. 어떤 설정에서도 안전 가드·래치·정지 증명을 우회하거나 완화하지 않는다. |

### Context

- D-1072 구현으로 에이전트 HTTP 브리지(`rosy_agent_bridge.py` / `rosy_cli.py`)가 구축되었으나, 모든 AI/에이전트 제안은 `propose: true`로 `PROPOSED` 상태에 머물고 기명 운영자의 콘솔 `admit`과 `presence-confirm`(120 s)을 매번 거쳐야 실행되었다.
- D-1077이 `--person-at-switch` 선언을 실행 직전 측정하는 `cell_stop_proof`로 대체했으나, Fleet `claim_cell_task`, `cell_task_act`, `cell_auto_setup` 및 `rosy` CLI가 여전히 `PROPOSED`·`presence`·개별 JSON 인자에 묶여 있어 "사용자가 말하면 LLM이 바로 Pick-and-Place를 실행"하는 1단계 파이프라인이 막혀 있었다.

### Decision

1. **사이트 단위 opt-in 무승인 자율 투입 (fail-closed 기본값 유지)**
   - **Fleet-R (`ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1`):**
     - `POST /api/fleet/pipeline/cell-tasks`에서 `propose: true`가 명시되지 않으면 `service`/`ai_observer` 주체도 즉시 `QUEUED`로 생성되며 `approval_mode: "autonomous_policy"`, `approved_by: "autonomous_policy"`가 원장에 기록된다.
     - AI 폴백(`act_policy -> guarded_pick`, `auto_admit: true`)도 선행 작업이 종결 상태(`COMPLETED`/`CANCELLED`/`ABORTED`)이고 체인 깊이 `<= 2`·단일 재시도·CAS 펜스를 만족하면 즉시 `QUEUED` 투입을 허용한다.
     - `POST /api/fleet/pipeline/cell-tasks/claim`에서 `ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1`이고 작업이 `requires_presence_confirm`을 명시하지 않았으면 `PRESENCE_CONFIRMATION_REQUIRED`를 생략한다. 단, `ROSY_FLEET_CELL_AB_RELEASE_ENABLED`, E-stop, `HUMAN_HOLD`, 인시던트 홀드, AMR 정지·적재함(`amr_bed`) 또는 `cell_internal` 게이트는 그대로 집행한다.
   - **OMX 셀 워커 (`ROSY_OMX_AUTONOMOUS_POLICY=1` 또는 handoff `approval_mode == "autonomous_policy"`):**
     - `cell_task_act.py`·`cell_task_act_run.py`는 `presence_ok(handoff)` 없이도 `effective_operator(handoff)`(`approved_by` 또는 `"autonomous_policy"`)와 1 s 실행 lease(`--policy-lease`)로 실행을 계획·수행한다(`--person-at-switch`는 `presence_ok`일 때만 전달하며 `cell_policy_drive.py`가 D-1077 `cell_stop_proof`를 직접 측정한다).
     - `cell_task_exec.py`는 `presence_ok`가 아니고 자율 정책이 활성화된 `guarded_pick` 작업에 `--stop-proof`를 전달하며, `cell_auto_setup.py`의 `open_cell`은 `--dry-run`이 아닐 때 `cell_stop_proof.session_proof()`를 실행 직전 측정해 통과 시에만 `config["_commissioning"] = {"stop_proof": proof}`를 설정하고 실패 시 즉시 중단한다.

2. **`rosy` CLI / MCP 브리지 직접 실행 도구 추가 (`tools/remote/`)**
   - `rosy_agent_tools.py`로 도구 명세를 분리하고 `fleet_cell_sites` (`GET /api/fleet/pipeline/cell-sites`)와 `fleet_dispatch_cell_task` (`POST /api/fleet/pipeline/cell-tasks`, `propose: true` 미강제, `tiers`/`auto_admit` 지원)를 추가한다. 기존 `fleet_propose_cell_task`는 하위 호환을 위해 유지한다.
   - `rosy_agent_bridge.py` 및 `rosy_cli.py`의 `call`에 `--args-file`을 추가해 Windows 셸 JSON 따옴표 손실 문제를 해소한다.
   - `rosy_cli.py`에 `rosy sites`와 `rosy pick` (`--cell`, `--arm`, `--src`, `--dst`, `--tier`, `--tiers`, `--preset`, `--mode`, `--max-chunks`, `--propose`, `--auto-admit`, `--dry-run`, `--wait`) 복합 명령을 추가한다.

3. **범위 제한 (1단계)**
   - 본 ADR 1단계는 고정 사이트·프리셋(`cell_s`, `cell_ab`) 대상이며, `AreaXYZ` 임의 좌표(`directive`) 워커 연동과 `pinky-tasks` 통합 도구는 2단계로 남긴다.
   - `cell_ab` 실물 실행을 위해서는 현장 Fleet-R에 `ROSY_FLEET_CELL_AB_RELEASE_ENABLED=1` 및 `ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH=1`, 셀 워커에 `ROSY_OMX_AUTONOMOUS_POLICY=1`을 설정하고 열린 `arm_a` 토크오프 홀드 등을 먼저 해제해야 한다.

### Consequences

- 미설정 환경(기본값)과 기존 엄격 거버넌스 시험은 변경 없이 그대로 유지된다.
- 자율 투입이 켜진 현장에서는 사용자가 자연어로 지시하면 LLM이 `rosy sites`/`rosy pick`을 통해 즉시 `QUEUED` 투입부터 실행·완료 확인까지 한 번에 수행할 수 있다.
- 모든 실행은 여전히 D-430 물리 안전 가드, D-1077 실행 직전 정지 증명, 1 s 실행 lease, 완료 후 `folded: true` 및 구역·깊이 검증을 통과해야 한다.

### Validation

- `python tools/harness/rosy_harness.py lint` 0 error(s), `size_range.py` 및 `safety_review.py` 통과.
- 원격 pytest (`test_autonomous_cell_dispatch.py`, `test_omx_autonomous_policy.py`, `test_rosy_agent_bridge.py`, 기존 거버넌스/안전/아키텍처 회귀 시험) 통과 및 독립 D-430 안전 리뷰 완료.
