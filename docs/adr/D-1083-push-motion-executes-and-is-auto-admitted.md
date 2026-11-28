## D-1083 밀기(push)를 Fleet 셀 작업 motion으로 실행하고 자유 위치 집기와 같은 조건으로 무승인 투입한다 (D-1077 7항·D-1081 3항 개정)

**Status:** Accepted (2026-11-28, 소유자 결정). 구현은 이 ADR과 같은 PR이다. 실물 수용은 없다.

### Context

- D-1077 7항은 밀기·한계 최초 탐색에 사람을 두었고, D-1081 3항은 밀기를 제안만(`PUSH_NOT_EXECUTABLE`)으로 두었다. 실행 경로(워커 → 셀 작업 API)와 완료 증거가 없었기 때문이다. 워커는 셀 호출 전에 `CELL_MOTION_NOT_EXECUTABLE`로 거절했고, 셀 작업 API의 `push`는 기계 주체를 거절했으며, Fleet에는 밀기 완료 검사가 없었다.
- 소유자 결정(2026-11-28, 원문): "바로 처리해 실행까지 해야지 당연히 자동승인까지". 밀기가 실행되고, 자유 위치 집기와 같은 조건(D-1078 스위치 켜짐 + `service` 주체 + `propose` 없음)으로 작업마다 사람 승인 없이 `QUEUED`가 된다. 모든 셀 가드는 그대로다: 가드·한계·시험을 약하게 만들지 않았다.

### Decision

1. **D-1077 7항·D-1081 3항 개정(밀기 한정).** `restrict_motion_admission`은 밀기와 자유 위치 집기를 같은 조건으로 다룬다(`cell_motion.py:115`). 조건을 못 채우면 `PROPOSED`(`motion_admission: HUMAN_APPROVAL_REQUIRED`)이고 `/admit`은 다른 기명 운영자가 받는다(`PUSH_NOT_EXECUTABLE` 제거: `pipeline_governance_store.py`). 만든 사람은 자기 motion을 승인하지 못한다. `retry`·repark 재투입·ACT 폴백은 motion을 그대로 거절한다(실패한 밀기를 같은 픽셀로 자동 재시도하지 않는다). 밀기 작업에는 화물 신원(`object_ref`·`identity`·`identity_observation_ref`·`emit_release_permit`)을 실을 수 없다(`MOTION_CONFLICTS_WITH_TASK_FIELDS`): 옮기기만 한 용기가 "보관됨" 이벤트를 내면 안 된다.
2. **claim 표지.** 밀기는 `capabilities`에 `"push"`가 있는 워커만 받는다(`WORKER_LACKS_PUSH_CAPABILITY`, 작업은 `QUEUED`로 남고 아무것도 소비되지 않는다). 워커는 `["motion","push"]`를 싣는다. `"motion"`만 있는 워커는 자유 위치 집기만 받는다(`cell_motion.claim_refusal`).
3. **셀 작업 API.** `push`의 `machine_ids`에 `cell-task-worker`를 둔다(`cell_area_job_spec.py:51`). 정지 증명은 `cell_job_proof.needs_proof`가 그대로 측정한다(움직임, `reviewed_only`·`reviewed_auto`·`attach_live_hold`·`recovery_home` 아님): 증명 통과 뒤에만 `--commissioning --person-at-switch`가 붙는다. 워커 범위(`cell_job_worker.py:53`)는 push에 두 번째 엄격 허용 목록을 둔다: 키는 정확히 `arm, config, site, roi, catalog, px_x, px_y, dir_x, dir_y, mm`(모두 필수, 다른 키는 있는 것만으로 거절: operator·proposer·reviewed_auto·half_mm·dry_run·person_at_switch 등), `mm`는 5..20(스펙의 `_num(5, 20)`에 더해 범위 검사에도 둔다; bool·문자열·NaN 거절).
4. **워커 실행.** `cell_task_exec`가 밀기를 `cell_task_motion.run_push`로 보낸다: 셀 작업 API에 `cell-task-worker` 토큰·멱등 키(작업 id + claim 임대)·워커 URL로 부른다(`run_job` 재사용). `CELL_MOTION_NOT_EXECUTABLE`은 알 수 없는 motion 종류와 A/B 밖 셀에만 남는다.
5. **측정된 완료.** 종료 코드만으로 성공을 보고하지 않는다. `cell_push.py`는 밀기 뒤(팔이 접힌 뒤) 계획에 쓴 같은 블롭 검출을 다시 돌려, 밀기 전 프레임에서 픽셀 아래에 있던 카탈로그 일치 물체와 밀기 뒤 계획 끝점에 가장 가까운 물체로 `displacement = {measured, commanded_mm, moved_mm, along_dir_mm, lateral_mm}`를 낸다(`cell_push_measure.py`). 어느 쪽 물체도 못 찾으면 `measured: false`이고 실패다. 마지막 `park` 단계는 `STEP_KEYS`(state·settled·fault)를 담아 접힘 판독에 쓴다. 워커는 그 증거를 `stage_result.push`에 싣고, pick과 같은 `fold_readback`(park 판독) + `measured_fold`(실시간 텔레메트리)가 둘 다 접힘이어야 `stop_event.ok`다. Fleet `/complete`는 밀기 작업에서 `cell_motion.push_completion_verified`로 증거를 직접 검사한다(`release_verified`가 구역 검증 대신 쓴다): 정확한 키 집합, `result == "pushed"`, `measured is True`, `commanded_mm`가 작업의 `mm`와 같음, `along_dir_mm`가 `0.5×mm` 이상 `1.5×mm+3` 이하, `lateral_mm` 0 이상 6 이하, `moved_mm`가 `hypot(along, lateral)`과 0.5 안, 모두 유한 숫자(bool 아님), `site`가 작업의 motion/src 사이트. 불리언은 믿지 않는다. 임계값은 실물에서 검증한 값이 아니다: 워커(`cell_task_motion.py`)와 Fleet이 같은 숫자를 쓰고 시험이 둘을 묶는다. 변위가 없거나 옆 오차가 크면 `FAILED`(작업 `ABORTED`)이고 같은 픽셀로 자동 재시도하지 않는다.
6. **CLI.** `rosy push`는 `rosy pick`과 같은 도구를 쓴다: 기본 `fleet_dispatch_cell_task`, `--propose`는 `fleet_propose_cell_task`, `--auto-admit`는 같은 플래그. 응답이 `PROPOSED`일 때만 `needs_approval`을 붙인다. `--dry-run`은 그대로다.

### 남는 셀 가드(코드에서 확인한 것)

| 가드 | 위치 |
|---|---|
| 정지 증명(측정 뒤에만 commissioning 꼬리) | `cell_job_proof.py:30`(`needs_proof`), `cell_job_spec.py` `build_argv` 꼬리 |
| 사이트 거절: 모르는 사이트, AMR 침대·`on_vehicle`·`moves`·`moving_px` | `cell_push.py:44-51` |
| 층 불일치(`layers_below`가 스택 윗면을 가리키는 기본 사이트) 거절 | `cell_push.py:52`(`cell_place_fit.tier_mismatch`) |
| 어두운 프레임 거절 | `cell_push.py:261`(`cell_preflight.ready`) |
| 경로 비어 있음: 뒤(턱 내림 자리)·앞(쓸림 구간)·옆(손가락 면 폭+지도 오차) 표본, 지도 밖·표면 밖·화면 밖은 거절 | `cell_push.py:286`(`path_clear`), `cell_push.py:306` |
| 거리 5..20 mm, 방향 0 아님 | `cell_area_job_spec.py:38`, `cell_push.py:239`, 워커 범위 `cell_job_worker.py:53` |
| 높이: 사이트 `surface_z` + `push.height_m`, 손목이 닿는 요각만, 실행 전 look 보정(`push.look_tol_mm`) | `cell_push.py:255`, `cell_push.py:212`, `cell_push.py:323` |
| 접촉·변형 시 후퇴 후 park | `cell_push.py:175-179` |
| `--commissioning --person-at-switch` 없이는 계획만 | `cell_push.py:243` |
| 사고 보류·Fleet 안전 온라인 | 셀 작업 API `check_arm_incident_hold`·`check_fleet_safety_online`(변경 없음) |

### D-427 · D-429 · D-430 및 D-911 · D-1077 · D-1078 · D-1079 · D-1081 관계표

| 기준 ADR | 유지되는 계약 | 이번 결정의 변경 |
|---|---|---|
| D-427 | 정본·소유 경계(값마다 주인 하나) | 변경 없음. 밀기 변위의 측정·가드는 셀이 소유하고 Fleet은 증거를 검사만 한다. |
| D-429 | 원시 장치 직접 구동 금지, Fleet 원장 경유 단일 경로 | 변경 없음. 밀기도 같은 셀 작업 원장·claim·완료 경로다. |
| D-430 | 정지 증명, 사고 보류, 접촉·토크·복도·깊이 한계, 안전 경로 변경 통제 | 어떤 가드도 약화하지 않았다. 새 `cell_push_measure.py`를 `safety_review_paths`에 올렸다. |
| D-911 | 2항 정확 경로 묶음, 3~8항 | D-1081이 연 자유 위치 집기 예외에 **밀기를 더한다**(1항). 자동 `run`/`transfer`는 그대로 검토 필요. |
| D-1057 | 완료는 측정된 증거로만 | 밀기의 측정된 증거를 정의한다(5항). pick의 구역 검증은 그대로다. |
| D-1077 | 입회 대신 실행 직전 정지 증명 | 정지 증명은 그대로 측정된다. **7항의 "밀기는 사람"을 개정**한다. |
| D-1078 | 사이트 무승인 자율 투입 스위치 | 같은 스위치 조건이 밀기에도 적용된다. 스위치의 만료·횟수 한도는 여전히 없다. |
| D-1079 | 기계 주체 선례(`machine_ids`) | `cell-task-worker`가 `push`에서도 같은 경로를 쓴다. |
| D-1081 | free_pick motion, 워커 주체, 협조적 취소 | **3항(밀기는 제안만)을 개정**한다. 나머지는 그대로다. |

### Consequences

- 스위치가 켜진 사이트에서 AI가 밀기를 사람 승인 없이 할 수 있다. 셀이 실행 시점에 다시 측정하는 가드(경로 비어 있음, 정지 증명, 어두운 프레임, 사이트 거절, 측정된 완료)가 유일한 방어선이다. dry-run 해시 승인은 없다(D-1081과 같다).
- 알려진 빈틈:
  - **완료 증거는 워커가 보고한 숫자다.** Fleet은 모양과 임계값만 확인하고 카메라를 직접 보지 않는다. 워커 자격을 가진 쪽이 숫자를 꾸밀 수 있다(집기 완료와 같은 한계).
  - **픽셀 아래 물체 확인과 프레임 묶음이 없다.** 지정 픽셀에 물체가 없어도(빈 바닥) 밀기는 실행되고, 제안자가 본 물체와 다른 물체일 수 있다. `frame_seq`·`frame_sha256`은 기록일 뿐이다. 이 경우 변위 증거가 없어 작업은 실패로 끝난다.
  - **5 mm 밀기는 판정이 가장 약하다.** 통과 하한(0.5×mm = 2.5 mm)이 측정 잡음과 비슷한 크기다.
  - **협조적 취소 없음.** `cell_push`는 `Guarded.act`가 아니라 맨 `FifoCell`을 쓰므로 중지 표식을 읽지 않는다. 그래서 `push`는 `cancellable`이 아니고 취소 요청은 409(`JOB_NOT_CANCELLABLE`)이며 워커는 오류를 무시한다. 새 중지 경로를 만들지 않았다. 시간 초과·유실 뒤 밀기는 끝까지 갈 수 있다(밀기는 몇 초이고 러너 자체 가드와 접촉 후퇴가 있다).
  - 스위치가 켜져 있는 동안 서비스 자격 증명 어느 것이든 `QUEUED` 밀기를 받을 수 있다.
  - 실물 셀 수용이 없다. 변위 임계값(0.5×mm, 1.5×mm+3, 옆 6 mm)은 측정 잡음(블롭 중심 2~3 mm 추정)에서 고른 추정치이고, 이 PR은 이를 실물로 검증하지 않았다.
  - 스택 옆 밀기: `cell_push`는 기본 사이트의 `layers_below` 불일치(`tier_mismatch`)와 경로·옆 띠에 물체가 있는 경우만 거절한다. 같은 층의 이웃이 띠 밖에 있거나 윗 단의 상자를 아래에서 미는 경우를 따로 거절하는 규칙은 없다. 밀기는 층 사이트(`-l1` 등)의 `surface_z`를 쓰고 그 위의 단은 보지 않는다.
  - 재측정: 증거가 65초 넘게 묵어 워커의 `remeasure`가 불리면 밀기에는 재측정 맥락(`write_context`)이 없어 실패하고 작업은 사람이 치울 때까지 `RUNNING`으로 남는다(실패 닫힘).
  - 같은 물체를 다른 후보와 구별하는 것은 카탈로그 일치와 "픽셀 아래·계획 끝점 근처" 규칙뿐이다.

### 남은 확인

1. 변위 임계값을 실물 밀기 몇 번으로 검증(또는 사이트별 값으로 분리).
2. `cell_push`를 `Guarded.act`로 옮겨 협조적 취소를 달지(별도 안전 검토).
3. 스택 옆 밀기 거절 규칙.
4. 셀 쪽 `cell-task-worker` push 범위의 안전 검토, 셀 호스트 배포(워커를 먼저 `push` 표지로 배포해야 Fleet이 밀기를 내줄 수 있다).

### 다른 세션이 해야 하는 Safety-Review

D-430 5항에 따라 이 변경을 쓰지 않은 세션이 다음을 검토한다.

- `cell_job_worker.py`(push 허용 목록이 정확히 10개 키인지, mm 범위, operator·proposer·reviewed_auto 거절)·`cell_area_job_spec.py`(`machine_ids`, `cancellable` 아님)·`cell_job_proof.needs_proof`가 push에 정지 증명을 요구하는지.
- `cell_push.py`·`cell_push_measure.py`: 변위 측정이 계획 검출과 같은 함수인지, 측정 못 하면 `measured: false`인지, park 판독이 `STEP_KEYS`를 담는지, 어떤 가드도 줄지 않았는지.
- `cell_task_motion.py`(`run_push`, `push_evidence_ok`)·`cell_task_exec.py`·`cell_task_worker.py`: 종료 코드만으로 `task_verified`가 되지 않는지, 접힘 판독 둘이 모두 필요한지, push가 `place`·구역 검증 경로를 건너뛰어도 Fleet 검사를 대신하지 않는지.
- `operations/fleet/fleet/pipeline/cell_motion.py`와 `pipeline_camera_routes.py`(`/complete`의 `release_verified`)·`pipeline_governance_store.py`(`/admit`): 밀기가 자유 위치 집기와 같은 조건으로만 `QUEUED`가 되는지, 증거 검사가 불리언을 믿지 않는지, `push` 표지 없는 워커에 밀기가 안 나가는지, 일반 작업이 밀기 증거로 완료되지 않는지.
