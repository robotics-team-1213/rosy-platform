# D-856 중립 물리 작업의 원장과 두 사람 승인

최신 소스 commit `76a173b5fd33b1907bfedba8b5a1bf5f78506ac3`(원장 기능 source `3c95937a56`). [실행 계획](../../plans/2026-10-24-neutral-transfer-closure-and-producer-design.md) 단계2의 내부 원장·승인 부분이다. 공개 HTTP/DTO, live capability 수집, 준비된 action/attempt context, 관측 credential ingress, dispatcher와 물리 receipt/claim 종료는 아직 연결하지 않았다. 새 API 버전·지원 action kind·장치 writer를 열지 않았다.

## 소유권과 데이터

`PhysicalTransferStore`는 실제 Fleet DB의 tasks/missions/control/claim 구조·PK·control 행을 read-only 연결로 확인한 뒤 공통 `CellJobStore` initializer를 사용한다. 별도 DB를 만들거나 무관한 SQLite 파일에 스키마를 추가하지 않는다. 동작 profile은 simulation만 허용한다.

공통 parent journal의 physical provenance와 기존 events/claims를 재사용한다. job_id·recipe/cell/process-artifact digest는 NULL이며, 앱 업무 metadata를 저장하지 않는다. legacy Cell read/admit/resume/완료 함수로 physical row를 통과시키지 않는다. 별도 physical projection은 고정 request/installation 두 키와 typed 내용·원장 binding을 확인하고 권한·status·approval 필드를 원장/승인 행에서만 읽는다.

schema version6은 `fleet_physical_transfer_approvals`와 physical principal/request-key의 unique index를 기존 migration transaction 안에 추가한다. parent·step/mirror·checkpoint·새 승인 테이블·FK 검사를 함께 commit/rollback한다. version5 이하 host는 새 원장을 거절한다. 기존 v4 자료의 행·claim·view/trigger와 FK를 보존하며, 구형 parent에 provenance 필드가 없는 부팅 순서에서도 먼저 수행되는 task startup hook이 physical 자료를 조회하지 않는다.

기존 Cell 완료 메서드는 같은 Cell 소유의 `cell_job_completion.py`로 옮겼다. 이동 전후 AST가 동일하며 기존 evidence·replay·fence·claim 해제 의미를 유지한다. `CellJobStore.confirm_step_goal` 호출자는 그대로다. 파일을790줄로 줄이고 ratchet도790으로 낮췄다. physical store는 이 legacy 완료/해제 메서드를 호출하지 않는다.

## 생성과 승인

- 설치 snapshot은 물리 정책, source/target 참조, 모든 참가자의 managed capability를 고정한다. primary의 catalog/bindings와 전체 capability의 resource-policy digest가 정책과 같아야 한다. 설치·capability는 host composition의 입력이며 앱 body로 받지 않는다.
- 정책 digest에 참가자별 arm 자원 ID, 구역별 zone ID와 object 자원 ID를 포함했다. 모든 participant의 owner workcell도 함께 claim한다. 이 workcell 키가 기존 Cell의 single/multi-arm 점유와 충돌하므로 서로 다른 arm alias로 같은 owner를 동시 접수하지 못한다. 앱은 자원 목록을 고르지 않는다.
- 인증 경계에서 공급할 service/operator SitePrincipal의 역할·사이트 권한을 검사한다. 실제 credential 인증은 후속 HTTP composition의 책임이다. principal/request-key가 같고 요청이 같으면 기존 proposal을 그대로 읽으며 다른 요청이면 충돌한다. 설치가 바뀌어도 기존 요청의 snapshot을 조용히 갱신하지 않는다. creator와 기명 operator만 해당 제안을 읽을 수 있고 다른 service/viewer에는 넘기지 않는다.
- 승인자는 proposer와 다른 기명 operator여야 한다. service·익명 site-console·비밀번호 변경이 필요한 principal은 승인하지 못한다. 정확한 proposal digest, 현재 설치 snapshot, 현재 dispatch generation/enabled와 모든 capability/owner identity의 일치·freshness를 확인한다.
- 하나의 SQLite write transaction에서 전체 자원 reserve, 예약 이후의 경계 시각, 승인 행, READY와 event를 기록한다. 중간 SQL 실패나 자원 경합은 전부 rollback한다. capability snapshot은 transaction 안의 현재 시각으로 다시 확인하며, 예약 전후 server 시각이 역행하면 rollback한다.
- READY 재시도도 현재 capability를 확인한다. 기존 operator·digest·fence·전체 CLAIMED 점유가 일치할 때만 기존 승인 결과를 반환하고 승인/경계/claim을 새로 만들지 않는다.

READY는 자원과 승인 기록만 뜻한다. action/attempt/grant는 아직 준비되지 않았고 전송되지 않는다. 후속 coordinator는 READY 이후의 독립 관측, 현재 participant identity와 claim/fence를 확인해야 한다. 이 store의 capability 인자는 아직 실제 SDK 조회와 연결되지 않았다.

전체 정지·startup latch는 physical READY/RUNNING/ACTION_SUCCEEDED를 HOLD로 바꾸고 점유를 보존한다. CLAIMED는 HELD, DISPATCHING은 UNKNOWN으로 남기며 UNKNOWN은 rearm을 막는다. restart 시험의 in-flight 상태는 주입한 원장 상태이고 실제 장치 stop/복구 관측이 아니다. physical resume/cancel/재전송은 제공하지 않는다.

## 원격 검증과 독립 검토

- 자원 정책 RED commit `13584e1fb3`: 1 failed/skip0, 누락 arm-resource 필드를 확인했다. source `f11a7577e6`의 정책·공통 점유·기존 provenance 검사는48 passed/skip0/known0 NEW였다. `rosy-physical-policy-claims-red`, `rosy-physical-policy-claims-green`의 run-1.txt에 보존한다.
- store RED commit `bc70be1ff6`: 누락 store module로21 errors/skip0/known21 NEW였다. `rosy-physical-store-red/run-1.txt`다.
- 첫 source8f 검사는135 passed/1 failed였다. 실패는 실제 startup latch를 호출하지 않은 새 시험의 가정이었다. 호출을 정정하고 Cell 완료 함수를 이동한 source6c의 검사는136 passed/skip0/2 warnings/known0 NEW였다. 원본 `rosy-physical-store-green`, `rosy-physical-store-size-green`의 run-1.txt를 구별한다. D-766 실패를 숨기지 않고 같은 소유 commit의 이동·ratchet 하향으로 정정한 현재 계보의 source는 `3760312082`다.
- 독립 검토는 READY retry의 capability 생략, 무관한 DB 초기화, JSON의 권위 필드 덮어쓰기와 예약 중 시계 역행의 P2 네 건을 확인했다. RED commit `fccdf34204`의 원격5 failed/24 passed/skip0/known5 NEW가 네 조건을 재현했다. `rosy-physical-store-review-red/run-1.txt`다.
- source3c는 네 건을 보완했다. fixed SHA 독립 재검토는 모두 해소·추가 material finding 없음이다. store/정책/Cell·원장 migration·복구/공통 점유·holder import 집중 검사는 **142 passed/skip0/2 warnings**, exit0/known0 NEW였다. `rosy-physical-store-review-green/run-1.txt`다.
- source3c의 공식 affected 전체2 invocations는 실패로 종료했다. run1은2 failed/4589 passed/187 skipped/39 warnings/5 subtests, run2는1 failed/6341 passed/336 skipped/2 warnings다. 각 known2 NEW·1 NEW이며 원본 `rosy-physical-store-3c-affected/run-1.txt`, `run-2.txt`에 보존한다. 신규 writer 목록 누락, safety 내부 normalize_resources import2개와 기존 version5 기대값 누락이 원인이다.
- source `9d3db3beecf60215eb4a93d598a36ba316254008`는 순수 자원 정규화만 별도 모듈로 옮겨 safety 내부 import를 없애고 기존 re-export를 보존했다. normalize_resources/reserve/release AST는 그대로다. 실제 physical 점유 상태 writer 하나를 정확한 KNOWN_WRITERS 항목에 등록하고 version6 시험 기대값을 보완했다. [별도 독립 안전 검토](source-review.md)의6개 source hash와 commit Safety-Review trailer로 이 수정의 범위를 결속했다. assertion·frozen safety 예외 목록을 약하게 만들지 않았다.
- source9d focused는149 passed/1 failed/skip0/known1 NEW였다. 새 helper가 여전히 Fleet/Decision concern에 있어 safety→decision import 방향이 남았다는 구조 검사 실패다. 원본 `rosy-physical-store-9d-focus/run-1.txt`를 보존한다.
- source76은 helper를 stdlib-only `core_common.resource_keys`로 옮겨 safety/decision 양쪽이 contracts leaf를 소비하도록 했다. 원래 Fleet normalize_resources 재수출은 유지하고 임시 Fleet helper는 삭제했다. 공유 leaf 누락 RED commit `e717f5aec5`의7 failed/skip0/known7 NEW를 확인한 뒤 옮겼다. 독립 후속 안전 검토는 이5개 경로의 변경을 승인 가능·finding 없음으로 판정했고 정규화 hash와 별도 commit trailer로 결속했다. source76의 Foundation 전체·중립/Cell 원장·공통 점유·writer/safety 구조 집중 검사는 **1292 passed/skip0**, exit0/known0 NEW다. 원본 `rosy-resource-leaf-red`, `rosy-resource-leaf-green`의 run-1.txt를 구별한다.
- writer guard 소유권 목록과 공용 foundation 변경이 FULL 사유다. source9d와 최신source76에서 각각 공식23개 full_invocations 전체를 실행했다. 원본 selection은 `rosy-physical-store-9d-selection.json`, `rosy-physical-store-76-selection.json`이고 각 full-execution.json은 runner가 읽는 local_invocations만 원본 full_invocations23개와 정확히 같게 확장했다. mode FULL·원본 targets·모든 metadata를 유지했으며 원본 명령 이외의 skip/ignore 필터는 추가하지 않았다.
- 원본 source9d FULL은 exit1,23개 원본 log를 모두 분류했다. run21만2 NEW: safety→Decision helper 의존과 G1 접촉 간격 시험이다. root는9708 passed/1132 skipped/2 failed/56 warnings였다. 나머지22개는0 NEW다. 이 실패를 최신 소스의 통과로 덮지 않는다.
- 최신 source76 FULL은 **23개 모두 exit0/known0 NEW**, runner exit0로 종료했다. 대표 run9는7378 passed/91 skipped/12 warnings/5 subtests, run12 Fleet는6343 passed/336 skipped/2 warnings, run21 root는9707 passed/1135 skipped/56 warnings다. 각 원본과 target·count·NEW ID는 [전체 실행 분류](full-run-summary.json)에 보존한다. 두 소스와 겹치는 집중 검사는 합산하지 않고 skips는 수용 증거로 세지 않는다.
- 원본 G1 실패는 contact gap p99 **0.525457s > 0.5s**였다. 최신76의 root FULL과 별도 동일 source의 G1 timing 파일 전체 재확인 **4 passed/skip0/known0 NEW**가 기존 strict bounds를 통과했다. 원본 `rosy-physical-store-76-g1-recheck/run-1.txt`다. 원본 실패의 원인을 해결했다고 주장하지 않는다. 원격99615/22670/29827/33063은 모두 종료했다.
- source 구간679608→76의 size/safety는 각각9 commits, exit0다. 집중/과거 결과의 중복은 합산하지 않는다.
- 최종 독립 evidence 검토는 원본/최신46개 log의 target·count·duration과 manifest를 대조하고 공식 known_failures로 재분류했다. focused1292·G1 재확인4와 FULL 확장 JSON까지 일치했으며 문서 과장/불일치 finding은 없었다.

실물·현장·기존 장치의 업무 완료를 수용한 증거가 아니다. 배포·push·병합·실물 실행 없음.

CE: 미해결 — 원본 G1 접촉 간격 실패의 원인은 미확정이다. 증상은 위 p99 초과이며, 부하·스케줄링 또는 표본 구간 혼입은 아직 검증한 원인이 아니다. 다음 재현에서는 contact별 action/attempt와 활성 구간·host scheduling 시각을 함께 수집해야 한다. 현재 source76의 strict 통과와 원인 해결을 구별한다. 검토 finding·시험 가정·파일 크기 정정은 source·회귀·이 기록에서 확인되므로 새 해결 교훈을 쓰지 않았다. 과거 e26 G1 timing 기록도 그대로 유지한다.
