## D-1081 미교시 지점 자유 위치 집기를 사람 승인 없이 Fleet 셀 작업 motion으로 투입한다 (D-911 2항 개정)

**Status:** Accepted (2026-11-27, 소유자 결정 "free-position picks run without per-task human approval, wide scope; guards stay"). 구현은 이 ADR과 같은 PR이다. 실물 수용은 없다.

### Context

- D-911 2항은 자동 허용을 "정확히 일치하는 작업 경로"로 묶고 "성공한 점 사이의 공간이나 다른 Z로 허용을 확대하지 않는다"고 한다. 사람이 가르친 적 없는 지점(자유 위치)을 집는 작업은 이 문장 밖이어서, 지금은 작업마다 기명 운영자의 `admit`이 필요하다.
- D-1078은 고정 사이트·프리셋만 무승인으로 열었고 자유 좌표(`AreaXYZ`)와 밀기는 2단계로 남겼다. Fleet 작업에는 이 두 동작을 실을 칸이 없어서, 셀 작업 API(:8781)가 이미 받는 `auto_pick --from free:<anchor> --at-px --map-only`와 `push`를 Fleet이 보낼 수 없었다.
- 사용자 결정(2026-11-27): 자유 위치 집기는 작업마다 사람 승인 없이 돌 수 있다. 명령 경로는 하나다(LLM → `rosy` CLI/스킬 → Fleet 셀 작업 → 셀 작업 워커 → 셀 작업 API 가드). 가드(Gate, 접촉·토크, 손가락 간격, 복도, 깊이 fail-closed 범위, 사고 보류, 정지 증명)는 모두 남는다. 모델은 미터·operator·proposer·reviewed_auto·person_at_switch를 주지 않는다. 밀기가 매번 사람 승인을 요구하는지는 사용자가 아직 정하지 않았으므로 지금은 제안만(사람 승인) 한다.

### Decision

1. **D-911 2항 개정(미교시 자유 위치 집기 한정). 사용자(소유자) 결정 2026-11-27: "자유 위치 집기는 작업마다 사람 승인 없이 돌고, 범위는 넓게, 가드는 그대로".** 아래 조건을 모두 만족하는 자유 위치 집기는 "정확히 일치하는 검토된 경로"가 아니어도, 작업마다 사람 승인 없이 `QUEUED`(`approval_mode: autonomous_policy`)가 된다. 그 밖의 자동 `run`/`transfer`와 D-911 3~8항은 그대로다.
   - 사이트 전체 자율 스위치(`ROSY_FLEET_AUTONOMOUS_CELL_DISPATCH`, D-1078)가 켜져 있고, `service` 주체가 `propose: true` 없이 만들었다. 스위치가 꺼져 있거나 `propose: true`이거나 `operator` 주체가 만들면 `PROPOSED`이고, 만든 사람은 자기 motion을 승인하지 못한다(`/admit`은 다른 기명 운영자만).
   - 출발 기준(anchor)과 목적지가 알려진 사이트이고, A/B 셀이다.
   - **dry-run 해시 묶음은 만들지 않았다.** 패널이 권고한 "요청 그대로의 서버측 dry-run 통과 + 1회용·만료 해시에 승인 묶기"는 이 결정에서 채택하지 않았다. 대신 셀이 실행 시점에 다시 측정한다: 픽셀 `at_px`의 깊이 블롭(없으면 거절), 앵커 깊이 확인, 이웃 간격, 정지 증명(D-1077), `map_only`, 측정된 완료 검증(D-1057). 요청 시점의 프레임과 실행 시점의 장면이 달라졌는지를 승인이 보증하지는 않는다.
   - 실패한 자유 위치 집기는 같은 픽셀로 자동 재시도하지 않는다: `retry`, repark 재투입, ACT 폴백 도구는 motion이면 거절한다(`CORRELATED_PLACEMENT_REQUIRES_NEW_PLAN`, `MOTION_NOT_REPARKED`). 새 motion은 새 요청이다.
2. **typed motion.** Fleet 셀 작업에 `motion`을 더한다: `free_pick`(anchor 사이트, 픽셀, 고른 프레임의 seq와 sha256, 목적지 사이트, 물체 필터)과 `push`(사이트, 픽셀, 방향, 5..20 mm). 픽셀만 받고 미터는 받지 않으며 모르는 키는 거절한다. `frame_seq`·`frame_sha256`은 **감사 기록일 뿐 묶음이 아니다**: 셀 작업 API는 프레임 신원을 받지 않으며(`auto_pick`에 해당 인자 없음), 셀이 실행 시점에 다시 측정하고 `at_px`에 측정된 블롭이 없으면 거절한다. 자유 위치 집기는 A/B 셀에 한정한다(arm_s는 고정 사이트).
3. **밀기는 제안만, 아직 실행 불가.** 밀기는 어떤 스위치에서도 자동 투입하지 않는다(소유자 결정은 자유 위치 집기만 다룬다). 실행·완료 경로가 없어서 `QUEUED`가 될 수 없다: 만들 때 `PROPOSED`(`PUSH_NOT_EXECUTABLE`)로 두고 `/admit`도 거절한다. 사용자가 밀기를 정하면 이 항을 바꾼다.
4. **실행 경로.** 셀 작업 워커는 셀 작업 API를 **전용 기계 주체 `cell-task-worker`**(자기 토큰 파일 `ROSY_CELL_JOB_WORKER_TOKEN_FILE`)로 부른다. 공용 `cell-job-machine` 토큰(AI 다리·Fleet 프록시)은 새 권한을 얻지 않는다. `auto_pick`의 `machine_ids`에 이 주체를 두어(D-1079 `recover_hold` 선례) 정지 증명이 그대로 측정되고 `--commissioning --person-at-switch`가 증명 뒤에만 붙는다. 이 주체에는 좁은 규칙이 더해진다: `source`가 `free:`로 시작, `map_only` true, `at_px` 있음, 그리고 허용 키 목록(arm, config, catalog, roi, source, dest, at_px, map_only, object, colour, verify_zones=true)만 통과한다(`reviewed_auto`·`operator`·`proposer` 등은 키가 있는 것만으로 거절). 그 밖은 403(`WORKER_SCOPE_FORBIDDEN`). 토큰 파일이 없으면 기능이 꺼진다(fail closed). 워커는 자기 토큰과 워커 전용 변수 `ROSY_CELL_JOB_WORKER_URL`(없으면 루프백)의 주소를 클라이언트에 직접 넘겨, 공용 `ROSY_CELL_JOB_URL`·`ROSY_CELL_JOB_TOKEN`이 덮어쓰지 못한다. 멱등 키는 작업 id + claim 임대인데 임대 id가 작업마다 결정적이라 재 claim은 같은 키로 이전 셀 작업을 되받고 두 번 움직이지 않는다. 시간 초과·유실(`CELL_JOB_LOST`)은 최선의 취소 요청(협조적 중지, 위험 항목 참고) 뒤에 중단으로 보고한다.
5. **구현 상태.** motion 검증·typed handoff·워커의 셀 API 호출·CLI(`rosy pick --free-anchor`, `rosy push`)·무승인 투입(결정 1)·셀 API 워커 주체. 아직 없음: 밀기 실행과 완료 검증, 프레임 신원 묶음, 스위치 만료·횟수 한도. 코드는 시험을 통과했으나 실물 수용은 없다.

### D-427 · D-429 · D-430 및 D-911 · D-1057 · D-1077 · D-1078 · D-1079 관계표

| 기준 ADR | 유지되는 계약 | 이번 결정의 변경 |
|---|---|---|
| D-427 | 정본·소유 경계(값마다 주인 하나) | 변경 없음. motion은 Fleet 원장의 작업 필드이고 셀의 측정·가드는 셀이 소유한다. |
| D-429 | 원시 장치 직접 구동 금지, Fleet 원장 경유 단일 경로 | 변경 없음. motion은 같은 셀 작업 원장·claim·완료 경로를 쓴다. 모델이 셀 API로 직접 보내는 "motion tools"는 쓰지 않는다. |
| D-430 | 정지 증명, 사고 보류, 접촉·토크·복도·깊이 한계, 안전 경로 변경 통제 | 어떤 가드도 완화하지 않는다. 새 `cell_task_motion.py`·`cell_job_worker.py`·`cell_motion.py`와 `cell_job_client.py`를 `safety_review_paths`에 올렸다. |
| D-911 | 2항 정확 경로 묶음, 3~8항 검토·감독 시험·ledger | **2항을 미교시 자유 위치 집기에 한해 개정**(결정 1). 자동 `run`은 그대로 검토 필요. |
| D-1024 | 학습 정책의 감독 실물 시험, 입회 승인 | 변경 없음. 학습 정책 실행은 이 결정의 범위가 아니다. |
| D-1057 | 완료는 측정된 구역·깊이·접힘 증거로만 | 변경 없음. 자유 위치 집기의 완료도 같은 증거로 검증한다. 밀기는 완료 증거가 정의되지 않아 실행하지 않는다. |
| D-1072 | 실패 맥락 CAS, 폴백은 기명 승인, 에이전트 도구 경로 | 변경 없음. 실패한 motion을 고정 사이트 집기로 폴백하는 제안은 기명 승인 그대로다(재시도 `retry`는 motion이면 거절). |
| D-1077 | 입회 대신 실행 직전 정지 증명, 밀기·한계 최초 탐색은 사람 | 정지 증명은 셀 API가 측정한다. 밀기는 사람 승인으로 유지. |
| D-1078 | 사이트 단위 무승인 자율 투입(고정 사이트·프리셋), 2단계에 자유 좌표·밀기 | **2단계의 일부를 연다**: 자유 위치 집기만, 스위치 켜짐 + `service` 주체 + `propose` 없음. 밀기는 열지 않는다. 스위치의 만료·횟수 한도는 이 결정이 정하지 않는다. |
| D-1079 | 사람 없이 복구를 되풀이하는 기계 주체 선례 | 변경 없음. `cell-task-worker`가 같은 `machine_ids` 경로를 쓴다(결정 4). |

### Consequences

- 스위치가 켜진 사이트에서 AI가 미교시 지점 집기를 사람 승인 없이 할 수 있다. 셀이 실행 시점에 다시 측정하는 가드(깊이 블롭, 앵커 깊이, 이웃 간격, 정지 증명, `map_only`, 측정된 완료)가 유일한 방어선이다. 패널이 권고한 dry-run 해시 승인은 없다.
- 알려진 빈틈: arm_s는 깊이가 없어 자유 위치 집기를 받지 않는다(고정 사이트만). D-1078 스위치에 만료·횟수 한도가 없다. dry-run은 프레임마다 틈 값이 뒤집힐 수 있어(14↔8 mm) 3프레임 통과를 요구하는 설계(lens-c)를 따라야 한다.
- 셀 작업 API는 `reviewed_auto` 없는 기계 주체의 움직이는 작업을 `MACHINE_COMMISSIONING_FORBIDDEN`으로 거절하고, `reviewed_auto`는 정지 증명을 건너뛴다. 그래서 워커는 `reviewed_auto`를 쓰지 않고 전용 주체 `cell-task-worker`로 `machine_ids` 경로를 탄다(결정 4). 이는 `cell_job_spec.py`·`cell_job_guards.py`·`cell_job_api.py`·`cell_job_worker.py` 변경이므로 별도 안전 검토가 필요하다. 배포는 셀 호스트에서 토큰 파일을 만들고 두 서비스를 재시작해야 켜진다.
- 셀 작업 API에 `POST /jobs/<id>/cancel`이 생겼다(협조적 중지). 실행 중인 `auto_pick`에 중지 표식 파일(`ROSY_CELL_JOB_STOP_FILE`)을 쓰고, `Guarded.act`가 다음 보호 단계에서 표식을 보면 기존 정지 경로(park, `Aborted`, 토크 ON 유지)를 탄다. 신호·kill은 없다. 비상 정지가 아니다: 진행 중인 청크는 끝난 뒤에 멈춘다. 사람 주체 또는 그 작업을 시작한 주체만 부를 수 있다(다른 기계 주체는 403). 워커는 330초 대기가 끝나거나 연결이 끊긴 뒤 job id를 알면 한 번(최선, 오류 무시) 취소를 요청하고 그래도 `CELL_JOB_LOST`로 보고한다. 취소 요청이 도달하지 못하거나 청크가 멈추지 않으면 작업은 그대로 계속될 수 있다.
- 배포 순서(롤아웃): 스위치를 켜기 전에 셀 호스트에 셀 작업 API와 워커를 먼저 배포한다. 토큰 파일(`ROSY_CELL_JOB_WORKER_TOKEN_FILE`)을 만들고, 워커에 `ROSY_CELL_JOB_WORKER_URL`(셀 API는 루프백이 아니라 호스트의 tailnet 주소에서만 듣는다)을 준 뒤 두 서비스를 재시작한다. 토큰 파일이 비었거나 짧거나 다른 토큰과 같으면 그 주체만 꺼지고 셀 API는 그대로 뜬다. 옛 워커가 움직임 작업을 고정 지점 집기로 오해하지 않도록 워커는 claim 요청에 `capabilities: ["motion"]`를 싣고, Fleet은 그 표지가 없는 claim에 움직임 작업을 주지 않는다(`WORKER_LACKS_MOTION_CAPABILITY`, 작업은 QUEUED로 남고 아무것도 소비되지 않는다). 워커의 셀 요청은 허용 키 목록(arm, config, catalog, roi, source, dest, at_px, map_only, object, colour, verify_zones=true)만 통과한다.
- 남는 위험: 스위치가 켜져 있는 동안에는 서비스 자격 증명 어느 것이든 QUEUED 자유 위치 집기를 받을 수 있다. 이 자격 증명을 가진 주체가 곧 실행을 부르는 권한이다.

### 남은 확인

1. arm_s를 넣을지(깊이 없음, 지금은 거절).
2. D-1078 스위치를 만료·횟수 없는 플래그로 둘지, 한정 승인으로 바꿀지.
3. 밀기가 매번 사람 승인인지, 그리고 실행·완료 증거 정의(D-1077 7항).
4. 셀 쪽 `cell-task-worker` 주체의 안전 검토, 셀 호스트 배포 시점, 협조적 취소(`cell_job_cancel.py`, `cell_auto_safety.py`)의 안전 검토.

### 다른 세션이 해야 하는 Safety-Review

D-430 5항에 따라 이 변경을 쓰지 않은 세션이 다음을 검토한다.

- `deploy/robot/omx/cell_task_motion.py`(새 파일, `safety_review_paths`에 추가) · `cell_task_exec.py`의 motion 분기: 워커가 사람 토큰·reviewed_auto·operator를 보내지 않는지, 셀 거절이 `stop_event.ok=false`로 중단되는지, push가 셀 호출 전에 거절되는지.
- `operations/fleet/fleet/pipeline/cell_motion.py`와 라우트 연결: `service` 주체 + 스위치 + `propose` 없음일 때만 free_pick이 `QUEUED`가 되는지, 만든 사람이 자기 motion을 승인하지 못하는지, push가 `QUEUED`가 되지 않고 `/admit`도 거절되는지, repark·ACT 폴백이 motion을 버리지 않고 거절하는지, 모르는 키와 미터 값이 거절되는지, `retry`가 motion을 고정 사이트 집기로 바꾸지 않는지, `cell_site_targets.py`의 push 예외가 다른 같은 사이트 쌍을 열지 않는지.
- `deploy/robot/omx/cell_job_worker.py`·`cell_job_guards.py`·`cell_job_spec.py`(`auto_pick.machine_ids`)·`cell_job_api.py`: 워커 토큰 상수 시간 비교, 좁은 규칙(`free:`, `map_only`, `at_px`, `reviewed_auto` 거절), 정지 증명 측정 뒤에만 `--commissioning --person-at-switch`, 공용 기계 토큰이 새 권한을 얻지 않는지.
