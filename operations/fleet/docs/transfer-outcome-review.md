# 물체 이송 결과 판정과 검수용 내보내기

현재 연결은 기존 ARM transfer HTTP의 **simulation 프로필**에서 사용한다. 관측을 받은 뒤 Action 결과와 물체 목표 달성 결과를 나누어 기록한다. 실물 활성화·자동 복구·학습 데이터 수용을 추가한 기능은 아니다.

운영자 승인을 받은 한 번의 복구는 기존 HTTP·콘솔에 연결돼 있다. 공개 사용 흐름은 아래 「시뮬레이션 복구 HTTP와 콘솔」을 따른다. 내부 trusted-host 호출은 같은 원장의 호스트 조합용 인터페이스다.

## 인증된 복구 요청 원장 준비

D-899의 `RecoveryRequestService`는 HTTP와 콘솔이 사용하는 요청·근거·승인의 내부 원장이다. 원래 제안자의 요청과 독립 producer의 새 관측을 보존하고, 요청 ID·proposal/evidence digest·원래 grant/receipt/assessment/generation을 자식 생성 트랜잭션에 결속한다. 원래 제안자의 현재 권한은 해당 트랜잭션의 resolver로 확인한다. 주체와 역할을 사용자 body에서 구성하면 안 된다.

관측은 요청 생성 시점보다 새로워야 하며, 요청 대체·근거 만료·권한 취소에서는 승인을 거절한다. 승인한 뒤에는 원래 요청과 근거를 역사적으로 대조해 같은 자식을 반환하므로 owner 장애·현재 TTL 경과가 새 시도를 만들지 않는다. 부모 기록과 최대 1회 예산은 기존 D-895 경계를 따른다.

공유 API v1.327과 HTTP 인증 resolver·복구 관측 API·콘솔은 main에 반영됐다. 실제 Gazebo/실물 관측 생산자는 별도 연결과 수용이 필요하다. [내부 원장 검증 기록](../../../docs/validation/transfer-recovery-intent-2026-10-27/result.md), [공개 흐름 검증 기록](../../../docs/validation/transfer-recovery-public-2026-10-28/result.md).

## 관측 제출 뒤 남는 기록

기존 독립 observer가 POST_ACTION 관측 두 개를 제출하면 Fleet은 다음을 확인한다.

1. 같은 설치·대상·Action/attempt·owner·보정·좌표계·신선도에 속하는 자료인지 검사한다.
2. PRE_DISPATCH에 사용한 관측 ID를 다시 쓰지 않았고 sequence가 그 뒤인지 검사한다.
3. 열린 빈 집게, 관절 정지, 구역 비움과 물체 위치를 바탕으로 관측 결과를 판정한다.
4. 기존 Fleet 이벤트 원장에 `PHYSICAL_TRANSFER_ASSESSED`를 기록한다.
5. 실제 완료와 자원 해제는 기존 `confirm_physical`의 현재 권한·capability·fence·claim 검사를 그대로 거친다.

| task_outcome | 조건 | reason 예 |
|---|---|---|
| `succeeded` | 두 관측에서 대상이 목표 허용 범위에 있고 현재 프로필의 clearance 조건을 충족 | `null` |
| `failed` | 두 관측의 대상 위치가 서로 허용 범위 안에서 일치하지만 목표에는 도달하지 못함 | `TARGET_NOT_REACHED` |
| `unknown` | pose 없음·서로 상충·집게 상태 불명·정지/구역 조건 미충족 | `OBJECT_POSE_UNKNOWN`, `OBJECT_OBSERVATIONS_CONFLICT`, 원래 physical rejection reason |

실패 원인을 헛잡음·낙하·잘못 놓기로 추정하지 않는다. 그 구분에는 단계별 원본 관측이 더 필요하다. 출처·attempt·시각·원본 계보가 틀린 자료는 판정 기록을 만들지 않고 거절한다.

이 기록의 `scope`는 `observation_assessment_only`이며 `execution_authorized`는 false다. `succeeded`라는 관측 판정만으로 작업 완료·자원 해제·재시도·재무장을 허용하지 않는다. 판정 기록과 기존 완료 기록은 별개다.

기존 HTTP 응답 계약도 유지한다. 예를 들어 대상 pose가 없거나 목표가 다르면 완료 요청은 여전히 409다. 인증된 유효 관측에서 얻은 실패·미확인 판정과 원본 근거는 검수용으로 보존된다. 성공 시에도 완료 트랜잭션이 실패하면 관측 판정은 실행 완료의 증거가 아니다. 판정 기록 저장이 실패하면 새 완료 처리를 진행하지 않는다.

같은 입력 재제출은 동일 이벤트로 대조된다. 나중에 들어온 다른 관측은 이전 자료를 덮지 않는다. 기존 `fleet_physical_transfer_observations`의 단계별 성공 증거를 실패 자료로 교체하지 않는다.

## 기존 store에서 검수 자료 내보내기

Fleet을 설치한 같은 신뢰 환경에서 이미 구성한 `PhysicalTransferStore`를 사용한다. 새 HTTP endpoint나 로봇 제어 명령은 없다.

```python
from pathlib import Path
from fleet.server.physical_transfer_outcomes import export_transfer_outcomes

store = app.state.arm_transfer_job_store
export_transfer_outcomes(store, "<mission-id>", Path("<external-scratch>/outcomes.json"))
```

목적지의 부모 디렉터리는 미리 준비한다. 출력은 새 파일이어야 하며 기존 파일은 덮어쓰지 않는다. 임시 파일 쓰기·fsync 뒤 배타적 hard link로 게시한다. 내보내기는 기록된 관측 bytes의 digest와 Action/attempt 결속을 확인한다. DB 전체를 다시 작성하는 행위에 대한 인증이나 서명 증거는 아니다.

출력은 `unreviewed_metadata_only`다. `raw_camera_bytes_available=false`, `behavior_training_eligible=false`를 보존한다. 원본 RGB·상태·실제 적용 행동을 갖춘 ACT/VLA 시연이나 독립 정답으로 바로 사용하지 않는다. 첫 사용처는 사람의 결과 검수와 단계별 실패 데이터 요구사항 확인이다.

여러 export를 모을 때에는 [OMX curation의 검수 패키지](../../../learning/curation/omx/README.md)를 사용한다. 원본 bytes와 해시를 보존하고 같은 복구 root가 train/eval 양쪽에 들어가는 것을 거절한다. 분할은 검수 준비이며, export를 학습 시연이나 정답으로 승격하지 않는다.

## 실행 실패 단계와 복구 다음 행동

출력 형식 `rosy.transfer-outcome-export/2`는 기존 `outcomes`와 함께 `execution_review`를 제공한다. 종료 후 물체 관측이 없어 `outcomes`가 비어 있어도, 같은 Action/attempt의 보존된 owner receipt가 있으면 실행 실패를 내보낼 수 있다. 새로운 실행 원장이나 phase 이벤트를 중복 저장하지 않는다.

실제 실행 단계는 `approach`, `grasp`, `transfer`, `release`다. 일관된 phase prefix의 마지막 한 단계가 명시적으로 FAILED이고 Action도 FAILED일 때만 `failure_phase`를 지정한다. 취소·UNKNOWN·HOLD·controller 성공은 실패 단계로 바꾸지 않는다. 단계별 시각·event ID, 마지막 보고 단계와 owner의 원래 reason을 보존한다.

`object_hold_unconfirmed`나 `ITEM_LOST_IN_TRANSIT`는 보고된 보유 확인 문제다. 독립 물체 관측 없이 헛잡음·낙하 또는 들기/운반 중 어느 지점의 실패인지 확정하지 않는다. `physical_failure_cause`는 null, scope는 `owner_reported_execution_only`다. 현재 gripper readback의 monotonic 수신 시각을 새 source UTC capture 시각이나 action/attempt 결속으로 변환하지 않는다.

| 현재 확인된 상태 | recovery.next_step |
|---|---|
| 진행 중인 Action | `wait_for_action_result` |
| 결과 불명·취소 요청 중 | `reconcile_action` |
| 현재 작업 HOLD 또는 owner FAILED/HOLD | `operator_review` |
| Action 성공, task 실패·미확인 | `reobserve_object` |
| Action 성공, 관측상 성공이나 작업 완료 미확정 | `verify_completion` |
| 기존 완료 경로가 GOAL_CONFIRMED를 기록했고 task 성공 | `none` |

이 값은 읽기 전용 조언이다. `execution_authorized=false`, `automatic_retry_allowed=false`이며 실제 재조회·관측·동작을 자동 실행하지 않는다. 늦은 성공 receipt가 현재 HOLD를 해제하지 않는다. 현재 미션당 단일 attempt 원장과 물체·자원 조정 제약을 우회하지 않는다.

## 새 승인으로 한 번의 복구 준비

[D-895](../../../docs/adr/D-895-bounded-physical-transfer-recovery-child.md)는 기존 단일 attempt 표를 보존하고 별도 복구 미션을 연결한다. 첫 시도와 복구 자식 한 개가 같은 root를 가진다. 자식은 다시 복구할 수 없다.

원래 제안자와 그와 다른 이름 있는 운영자가 필요하다. owner FAILED(부모 job HOLD), 또는 Action 성공과 같은 grant의 최신 task failed 판정만 후보가 된다. 결과 불명·취소·owner HOLD·진행 중·성공 완료는 기존 효과를 먼저 대조한다. 정지·generation/epoch 변경을 복구 승인으로 해제하지 않는다.

기존 서버와 독립 observer 인증을 이미 구성한 신뢰 환경에서 사용한다. `proposer`와 `operator`는 인증된 기존 principal이며, 물체 시료와 producer ID는 신뢰된 host composition이 주입한다.

```python
from fleet.server.physical_transfer_recovery import recovery_context

dispatcher = app.state.arm_transfer_dispatcher
view = recovery_context(dispatcher.execution, parent_mission_id)
# 독립 producer가 view["context"] 이후의 새 source/clearance 시료 두 개를 확보한다.
bindings = {key: view[key] for key in (
    "expected_request_digest", "expected_receipt_event_id",
    "expected_assessment_digest", "expected_generation")}
result = dispatcher.recover(parent_mission_id, proposer=proposer, principal=operator,
    observations=authenticated_world_samples,
    authenticated_producer_id=installed_observer.producer_id, **bindings)
```

`expected_receipt_event_id`는 owner journal event 번호다. assessment digest는 최신 판정 전체 canonical JSON의 SHA-256이며, 그 안의 관측 evidence_digest와 다르다. 조회 문맥은 실행 허가를 만들지 않는다.

복구 시료는 원래 receipt 이후의 새로운 ID·sequence·시각이어야 한다. 같은 원래 action/attempt·설치·owner journal/session·출처를 결속하고 물체 source pose·집게 open/empty·팔 정지·구역 비점유를 확인한다. 원래 제안·현재 claims·fence·capabilities·새 자식 승인·양방향 계보를 하나의 트랜잭션으로 처리한다. 실패하면 기존 자원과 작업을 보존한다.

반환된 `job`은 자식 미션이고 `execution`은 새 PREPARED snapshot이다. 이 호출은 owner submit을 수행하지 않는다. 기존 observer가 **자식의 새 action/attempt에 결속된 새 PRE_DISPATCH 시료**를 제출해야 기존 send 경로로 이어진다. 복구에 쓴 부모 시료 ID·sequence를 자식에게 다시 사용할 수 없다. 자식의 완료는 기존 POST_ACTION·현재 claim 해제 경로를 거친다. 원래 실패 미션은 HOLD로 남아 이력을 보존한다.

정확한 요청을 재전송하면 같은 자식의 현재 상태를 대조한다. 완료·HOLD·준비됨 상태의 자식에 새 attempt를 만들지 않는다. 새 자식의 준비가 실패한 경우도 계보·자원·소비한 예산을 보존한다. 기록 조회는 owner 연결이나 현재 TTL 변경에 의존하지 않는다. 재조회한 과거 grant는 새 실행 허가가 아니며 실제 제출에는 기존 현재 상태·시간·권한 검사가 적용된다.

export v2의 추가 `recovery_lineage`에는 root/parent/child 미션과 `attempt_index`(원래 0, 복구 1)가 들어간다. 원본 receipt·참조한 task 판정·양방향 계보·관측 digest를 확인한다. 학습/평가 분할은 같은 root를 함께 둔다. 운영자 실행 승인 뒤에도 학습 라벨은 별도로 검수하고, `unreviewed_metadata_only`·`behavior_training_eligible=false`를 유지한다.

## 시뮬레이션 복구 HTTP와 콘솔

공개 형식은 API v1.327의 `ArmTransferRecovery*` 계약이다. 모든 경로는 기존 Fleet 인증·감사·동일 SQLite 원장을 사용한다. simulation 설치와 독립 observer가 없으면 사용할 수 없다.

| 경로 | 주체와 결과 |
|---|---|
| `GET /api/fleet/arm-transfers/jobs/{mission_id}/recovery` | 조회 권한으로 원래 owner의 실행 결과·단계, 요청·근거 상태와 별도 자식 ID를 읽는다. 물리 원인은 미확인으로 남는다. |
| `POST /api/fleet/arm-transfers/jobs/{mission_id}/recovery` | 원래 제안자만 `request_key`와 조회한 `expected_context_digest`로 새 관측을 요청한다. 주체를 본문에 넣지 않는다. |
| `GET /api/fleet/arm-transfers/recovery-context` | 독립 observer 자격으로 현재 수집할 요청 하나를 읽는다. 유효한 근거가 이미 있거나 원본·권한·실행 fence가 바뀐 요청은 수집 대상으로 내놓지 않는다. |
| `POST /api/fleet/arm-transfers/jobs/{mission_id}/recovery/{request_id}/observations` | observer만 `purpose=RECOVERY_RESET`, 요청 다이제스트와 새 시료 두 개를 제출한다. 콘솔은 이 자격이나 시료를 만들지 않는다. |
| `POST /api/fleet/arm-transfers/jobs/{mission_id}/recovery/{request_id}/approve` | 다른 기명 운영자가 조회한 요청·근거 다이제스트와 실행 세대를 정확히 승인한다. 현재 제안자 권한을 자식 생성 트랜잭션에서 다시 확인한다. 응답은 여과된 자식 `job`뿐이다. |

콘솔은 기존 `arm_transfer` 작업 상세에 원래 실패와 복구를 함께 표시한다. 원래 제안자의 **복구 관측 요청**은 실행 승인이 아니며, 새 사실이 없으면 관측 대기로 남는다. 다른 운영자는 표시된 근거를 확인한 뒤 별도 확인창에서 한 번 승인한다. 만료·변경·409 응답은 다시 조회해 새 근거를 검토한다. 응답이 끊겨도 자동 재전송하지 않는다.

자식을 만들면 공개 상태는 `CHILD_CREATED`다. 성공을 뜻하지 않으며 자식은 기존 새 PRE_DISPATCH·POST_ACTION 절차를 거친다. 자식 조회가 실패해도 알고 있는 ID와 소비한 복구 횟수를 보존한다. 자식에서 다시 복구를 요청할 수 없다. 정확한 과거 승인 재조회는 재시작·정지 fence·SDK 연결 실패나 제안자 권한 철회 뒤에도 같은 자식을 읽으며 새로운 실행을 승인하지 않는다.

## 다음 구현과 검증

- 파지·들기·운반 단계의 관측을 결속한 뒤 헛잡음·낙하를 구분한다.
- 현재 복구는 root당 자식 하나이며 공개 HTTP·화면도 같은 한도를 따른다. 실제 관측 생산자·장치 연결과 무인 반복 재시도는 별도 계약과 수용이 필요하다.
- 검수된 결과 판정 자료, 복구 선택 자료, 사람 교정 시연은 용도와 원본 계보를 분리한다.
- 시험은 `test_physical_transfer_outcome.py`, `test_transfer_outcome_recording.py`, `test_transfer_execution_review.py`와 기존 physical-transfer evidence/observer/closure/outcomes/stops/dispatcher suite를 공식 원격 runner에서 수행한다. 실제 장치·현장 수용은 별도다.
- 복구는 `test_physical_transfer_recovery.py`와 `test_transfer_recovery_flow.py`가 합성 World 시료·fake owner로 검증한다. 이 결과를 Gazebo 과제·실물 성공이나 모델 품질로 해석하지 않는다.
- HTTP·인증은 `test_transfer_recovery_api.py`·`test_transfer_recovery_auth.py`, 실제 HTTP/브라우저의 요청·관측·별도 승인·자식 완료·응답 유실은 `test_transfer_recovery_console_browser.py`가 검증한다. 모두 합성 관측과 owner를 사용한다.

## 2026-10-27 복구 구현 검증 기록

revision별 RED/GREEN, 독립 검토 수정, 영향 범위·착지 상태와 미수행 범위는 [검증 기록](../../../docs/validation/transfer-recovery-2026-10-27/result.md)에 보존한다. 기존 판정·실행 검토는 `2f2494cf32`에 로컬 착지했고, 후속 복구는 별도 검증한다.
