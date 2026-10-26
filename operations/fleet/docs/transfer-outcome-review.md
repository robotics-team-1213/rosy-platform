# 물체 이송 결과 판정과 검수용 내보내기

현재 연결은 기존 ARM transfer HTTP의 **simulation 프로필**에서 사용한다. 관측을 받은 뒤 Action 결과와 물체 목표 달성 결과를 나누어 기록한다. 실물 활성화·자동 복구·학습 데이터 수용을 추가한 기능은 아니다.

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

## 다음 구현과 검증

- 파지·들기·운반 단계의 관측을 결속한 뒤 헛잡음·낙하를 구분한다.
- 현 원장은 미션당 단일 attempt다. 반복 attempt의 이관·원본 보존·권한 재검증 없이 자동 재파지를 추가하지 않는다.
- 검수된 결과 판정 자료, 복구 선택 자료, 사람 교정 시연은 용도와 원본 계보를 분리한다.
- 시험은 `test_physical_transfer_outcome.py`, `test_transfer_outcome_recording.py`, `test_transfer_execution_review.py`와 기존 physical-transfer evidence/observer/closure/outcomes/stops/dispatcher suite를 공식 원격 runner에서 수행한다. 실제 장치·현장 수용은 별도다.
