# 독립 승인된 단일 이송 복구 후손

## 범위와 구현

기준 revision `2f2494cf32`는 앞선 결과 판정·실행 검토를 공식 도구로 로컬 main에 착지한 버전이다. 후속 `feat/transfer-recovery`는 D-895의 내부 simulation 복구를 구현한다. 원래 미션의 attempt·grant·관측·receipt를 보존하고, 별도 운영자와 새 물리 전제 관측을 검증한 자식 미션을 root당 하나만 승인한다.

현재 epoch/generation·모든 claims·capabilities·source/clearance를 한 트랜잭션에서 검증하고, 새 제안·부모 HOLD·정확한 claim 이전·새 승인·양방향 계보를 함께 기록한다. 자식 prepare를 명시 호출하며 새 자식 관측이 기존 send와 완료 경로를 거친다. 같은 요청의 재전송·재시작·준비 실패는 예산을 초기화하지 않는다.

## 원격 시험 증거

모든 pytest는 공식 원격 runner에서 커밋된 revision으로 실행했다. 아래 로그 디렉터리는 개발 PC 시스템 임시 폴더 아래에 있다. 주소·계정·token은 기록하지 않는다. 이전 A/B1의 시험을 후속 구현의 시험으로 재사용하지 않는다.

| revision | 목적 | 결과 | 로그 디렉터리 |
|---|---|---|---|
| `c2311e16e3` | 원자적 복구·예산·불확실성·자원·rollback RED | 모듈 부재로 21 failed | `rosy-transfer-recovery-red` |
| `a50df7e16e` | 복구 승인과 기존 store/prepare/submit/outcome/stop 회귀 | 128 passed | `rosy-transfer-recovery-green` |
| `fef2b760d0` | dispatcher→자식 관측→완료·계보 RED | 미연결 method로 3 failed | `rosy-transfer-recovery-flow-red` |
| `90a776e67c` | 기존 제출·완료·observer·export 통합 | 201 passed | `rosy-transfer-recovery-flow-green` |
| `2cefcba4c5` | 최신 판정·기본값 외 TTL·승인 중 시계 역행 등 | 복구 두 suite 33 passed | `rosy-transfer-recovery-edge` |
| `4d3d074cef` | 독립 검토의 SDK 장애·child TTL drift·원래 assessment delete/tamper RED | 4 failed | `rosy-transfer-recovery-review-red` |
| `db6f4f8c02` | 검토 수정 뒤 관련 통합 | 212 passed, 첫 호출/재조회 snapshot 필드 차이 2 failed | `rosy-transfer-recovery-review-green` |
| `7f0a8a152a` | 첫 호출과 재조회 모두 보존된 snapshot으로 통일 | 관련 12 suite 214 passed | `rosy-transfer-recovery-final` |
| `73f2fe5a03` | epoch·현재 owner session drift 거절 포함 최종 관련 회귀 | 관련 12 suite 216 passed, 0 skipped | `rosy-transfer-recovery-acceptance` |

최종 관련 회귀의 runner exit 0, known NEW 0·known 0·flaky 0을 확인했다. tests revision `73f2fe5a03`의 코드 내용은 `7f0a8a152a`와 같다. 위 RED·수정 중 2 failures는 해당 당시 실제 결과이며 baseline에 추가하지 않았다. 전체 영향 범위·착지 gate는 아직 완료로 보고하지 않는다.

최초 문서 lint는 다른 세션이 선점한 D-893/D-894 미착지 공백과 로그 제목 형식으로 3 errors였다. refs/adr의 실제 예약을 확인해 기존 `adr_gaps.txt`에 pending을 명시하고 제목을 정본 형식으로 고쳤다. 검사기·허용 목록을 약화하거나 다른 예약을 해제하지 않았다. `f71f090ad9`에서 lint 0 errors/37 warnings, 기준 이후 11 commits size-range 통과를 확인했다. 정본 selector의 mode는 affected이며 선택된 시험 범위를 유지한다.

## 독립 검토와 수정

읽기 전용 계약 검토에서 정확한 재조회가 owner SDK 조회와 현재 executor TTL에 의존하는 P2 두 건을 찾았다. 원래 task failed 판정의 full digest를 실제 보존된 이벤트와 대조하지 않는 원본 보존 검증 공백도 확인했다. 네 반례를 원격 RED로 재현했다.

공통 인증·설치·전체 요청 digest 대조를 owner 접근 전에 수행하고, 부모와 자식의 과거 grant를 각각 보존된 유효시간으로 읽는다. 새로운 자식의 승인·준비·실제 제출에는 현재 검사와 설정을 유지한다. 원래 참조 assessment는 현재의 최신 판정이 아닌, 승인 당시 정확한 historical full digest로 대조한다. 원래 receipt와 FAILED/SUCCEEDED 의미도 함께 확인한다.

첫 호출의 prepare view와 재조회 state view 사이 필드 차이를 기존 동등성 시험이 찾아, 첫 준비 뒤에도 보존된 state를 다시 읽도록 했다. 시험을 약화하지 않았다. `7f0a8a152a`의 두 줄 수정까지 독립 재검토했고 추가 중요 발견은 없었다. 검토자는 시험·장치 수용을 독립 실행하지 않았다.

## 확인한 동작과 한계

- UNKNOWN·HOLD·취소·진행 중 owner, 성공 완료, 최신 task unknown/succeeded는 과거 실패를 사용해 재시도하지 않는다.
- wrong source·보유 불명·움직임·구역 점유·stale·다른 attempt·재사용 ID/sequence·권한·fence/claim 변경을 거절한다. 중간 원장 실패와 시계 역행은 부모·자식·claims 전체를 rollback한다.
- 원래 제안자와 별도 운영자만 복구를 요청한다. observer는 그 역할을 맡지 않는다. exact replay는 같은 자식·과거 grant를 반환하며 새 SDK submit이나 새 attempt를 만들지 않는다.
- 자식에 새로운 source 시료를 제출하고 기존 owner receipt·새 POST_ACTION 시료·완료·claim 해제까지 합성 World/fake owner로 통합 검증한다. 자식 완료 후 과거 부모를 observer 문맥으로 재선택하지 않는다.
- 계보 export는 부모·자식의 같은 root와 attempt_index를 보존한다. 원본 receipt·참조 판정·관측 digest·양방향 연결의 소실/변조는 거절한다. DB 전체 재작성의 인증이나 서명 증거는 아니다.
- 운영자 실행 승인 뒤에도 `unreviewed_metadata_only`, 원본 RGB 없음, `behavior_training_eligible=false`를 유지한다. 학습 라벨 검수는 별도다.
- 새 공개 API·복구 화면·무인 반복 재시도·실제 Gazebo 과제·실물 동작·모델 학습/독립 평가·현장 수용·push는 수행하지 않았다. 호스트 통합 시험은 해당 수용을 대신하지 않는다.

CE: 해당 없음 — 재조회와 새 실행 설정의 구분, 원본 보존 판단은 D-895·보존 읽기 함수·반례 시험·이 기록에 남겨 별도 교훈으로 중복하지 않았다.
