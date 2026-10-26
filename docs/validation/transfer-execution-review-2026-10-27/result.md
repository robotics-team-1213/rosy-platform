# 물체 이송의 보고된 실패 단계와 복구 다음 행동

## 검증 범위

기존 Fleet에 저장된 owner receipt와 task 판정을 읽어 접근·파지·이송·놓기 단계 요약, 명시적인 실패 단계, 원래 reason과 복구 다음 확인을 export v2에 연결한다. 종료 후 물체 관측이 없는 FAILED Action도 검수 자료로 내보낸다.

기준 revision: `7e61b45fc8d56b721b6415ad7bf990fd69243fdf`. 구현·독립 검토 revision: `c86b3e51d5`. 앞선 첫 구현의 시험 결과를 새 revision의 증거로 재사용하지 않았다.

## 원격 실행 증거

모든 pytest는 공식 원격 runner에서 실행했다. 아래 로그 디렉터리는 개발 PC 시스템 임시 폴더 아래에 있으며 실제 호스트 주소·계정·token은 기록하지 않는다.

| revision | 목적 | 결과 | 로그 디렉터리 |
|---|---|---|---|
| `26344ecf9b` | 단계·불확실성·복구 제안·실행 실패 export RED | 16 failed, 1 passed | `rosy-transfer-review-red` |
| `812b3b224c` | 첫 구현·기존 결과/observer/closure/dispatcher 통합 | 156 passed, 0 skipped | `rosy-transfer-review-green` |
| `e231ff081a` | 기본값 외 허가 유효시간과 긴 관측 창 반례 RED | 2 failed | `rosy-transfer-review-ttl-red` |
| `c86b3e51d5` | 보존된 유효시간 복원 뒤 관련 통합 | 172 passed, 0 skipped | `rosy-transfer-review-final` |

최종 관련 통합은 새 execution-review suite, 기존 task outcome·recording·owner outcome·observer API·closure·evidence·stops·dispatcher·preparation suite다. official runner exit 0, known NEW 0·known 0·flaky 0을 확인했다.

동일 `c86b3e51d5`의 affected 선택은 Fleet 전체와 역의존·guard 묶음을 실행했다. `rosy-transfer-review-affected/run-1.txt`는 4,604 passed, 190 skipped, 5 subtests passed와 문서 비밀값 검사 1 failed로 끝났다. 실패 위치는 이전 검증 기록의 `head:` 뒤 40자리 Git SHA였다. 실제 Git commit 객체임을 확인했고, 기존 scanner가 허용하는 `revision` 표기로 문맥을 명시했다. 값·검사기·허용 목록은 바꾸지 않았다. 수정 후 해당 guard를 별도 원격 재검사한다. Fleet 전체 `run-2.txt`는 진행 중이다.

## 독립 검토와 수정

읽기 전용 계약 검토자가 새 exporter가 기본 15초 executor를 재구성해, 다른 유효시간으로 준비한 정상 작업을 거절하는 P2를 찾았다. 1.5초 허가와 30초 허가/20초 관측 창으로 원격 RED를 확인했다. 보존된 typed grant의 실제 유효시간을 사용하고 기존 `_state`의 ID·profile 재구성 검사를 유지했다. 최종 source `c86b3e51d5` 재검토에서 남은 중요 발견은 없었다.

## 의미와 한계

- `failure_phase`는 같은 owner Action/attempt의 명시적 FAILED 단계만 뜻한다. 취소·HOLD·보유 미확인은 물리 파지 실패나 낙하의 정답이 아니다.
- 실제 runtime은 네 단계다. 현재 원장에 없는 lift/carry phase를 새로 만들어 기록하지 않았다. 원래 gripper 수신 시각을 source UTC capture나 action/attempt 결속으로 추정하지 않는다.
- `physical_failure_cause=null`, scope는 `owner_reported_execution_only`다. 단계별 원본 시각·event ID와 reason은 검수 근거로 유지한다.
- 복구 다음 행동은 대기·실행 대조·재관측·사람 검토·완료 재검사다. `execution_authorized=false`, `automatic_retry_allowed=false`이며 실제 재조회·이동·재파지·재무장을 실행하지 않는다.
- exporter는 같은 DB snapshot에서 현재 작업과 보존된 receipt를 읽는다. source DB·claim·attempt를 변경하지 않고, 기존 파일을 덮어쓰지 않는다.
- export v2는 `unreviewed_metadata_only`이며 원본 RGB·적용 행동이 없는 자료를 행동 시연으로 승인하지 않는다. DB 전체 재작성에 대한 인증도 아니다.
- 실제 재시도에는 append-only attempt 원장 이관, 원래 물리 효과 대조, 새 승인·claim·정지 조건 검증이 남아 있다. 실물·Gazebo 과제 성공·모델 품질·현장 수용과 main 착지·push는 수행하지 않았다.

CE: 해당 없음 — 새 구현 결함과 해결은 회귀 시험·기존 유효시간 계약·이 검증 기록으로 확인할 수 있어 별도 교훈으로 늘리지 않았다.
