# D-856 중립 팔 실행: 물리 결속·권한·원장

**Status:** 실행 계약 초안. 아래 물체–기하 결속의 내부 데이터 경계는 구현·독립 검토·원격 회귀를 마쳤다. 새 공개 submit path·API 버전·dispatch kind는 아직 등록하지 않는다. [전체 계획](2026-10-24-harbor-rosy-application-action-boundary.md), [완료한 grant 검증 경계](2026-10-24-step-grant-boundary-design.md)를 잇는다.

## 현재 소스에서 이어받을 경로

`CellAcceptanceStore.capability_current`는 현재 cell hash와 recipe의 item/선택 SKU 기하를 승인 근거로 확인한다. 새로운 중립 geometry whitelist만으로 이 검증을 대체하면 물체와 기하의 대응이 사라진다. 공개 preflight는 특정 기하로 계획할 수 있는지를 조회하므로 물체 승인이나 실행 capability가 아니다.

`ActionRunner`는 grant digest·시간·UID·scope·fence·capability를 검사하고 phase factory를 선택한다. CELL_TRANSFER의 shared control admission도 별도로 요구한다. ActionStore는 workflow 완료 권한과 camera-blind observation 규칙을 갖는다. 새 kind를 추가할 때 이 두 보장도 확장해야 한다. direct driver 종류를 늘리지 않는다.

`PickPlaceRunner`는 이미 분리한 TransferMotionPlan과 같은 클래스 alias를 소비한다. 기존 gripper hold/release·phase 결과 출처·정확한 goal 취소·최종 fence를 재사용한다. `PickPlaceTransaction.for_cell_transfer`와 snapshot/recover에는 Cell grant 결속이 남아 있으므로 새 물리 결속을 넣되 기존 Cell journal 형식과 복구 결과를 보존해야 한다. `CellTransferWorkflowExecution`의 phase/그리퍼 진행은 Cell 입력을 직접 읽지 않는 물리 부분이며 중립 조립에서도 재사용할 후보이다.

## 먼저 구현할 물체–기하 결속

`omx_adapter.transfer_object_bindings.TransferObjectBindings(catalog, objects)`는 owner 설치가 제공한 고정 물리 참조를 표현한다. `catalog`는 기존 불변 ArmTransferCatalog, `objects`는 **불투명 물체 참조 → 그 catalog의 geometry 참조**인 비어 있지 않은 불변 map이다. 객체 identity는 앱 화물·SKU 정책을 해석하지 않는다. 앱은 별도 업무 장부에서 화물 ID와 물리 참조를 대응한다.

constructor는 모든 참조를 기존 public physical-ref 문자열 규칙으로 검사하고, 모든 geometry 참조가 catalog에 있는지 확인하며 map을 복사해 봉인한다. revision은 schema `rosy.omx-transfer-object-bindings.v1`, catalog digest와 objects map의 canonical JSON SHA-256이다. `ensure_ascii=False`, sorted keys, compact separators, finite JSON을 사용한다. map 순서·원본 map 변경으로 revision이나 해석이 변하지 않는다. catalog가 바뀌면 binding revision도 바뀐다.

`resolve(object_ref, *, catalog_digest, bindings_digest) -> GraspGeometry`는 설치 참조 두 개와 물체 결속을 대조한 뒤 **owner map에서 선택한 기하**만 반환한다. requester가 다른 geometry를 지정하는 인수는 없다. mismatch·미등록 물체는 부분 결과 없이 typed 거절한다. 이 데이터 클래스 생성이나 resolve 성공이 승인·실행 권한을 부여하지 않는다. owner의 명시적 설치 조립과 capability 검증에서만 사용한다. 외부 등록/갱신 API, 별도 SQLite 원장, 임의 JSON 승인 통로를 만들지 않는다.

기존 Cell acceptance/recipe와 preflight catalog hash 형식은 바꾸지 않는다. 새 결속 revision을 별도 참조로 두어 기존 preflight 소비자를 유지한다. 실제 중립 grant는 물체 참조·catalog digest·bindings digest·source/target 물리 참조를 결속하고 기하는 owner가 해석한다. grant의 정확한 필드와 wire 등록은 실행 계약 검토 단계에서 확정한다.

### 내부 결속 시험·완료 기준

- 등록한 물체가 정확한 GraspGeometry를 받고, 없는 물체·다른 catalog/bindings digest·없는 geometry·잘못된 식별자는 거절된다.
- 원본 map 변경과 map 순서가 불변 값·revision을 바꾸지 않는다. 기하 결속이나 catalog 변경은 revision을 바꾼다.
- source에는 recipe/pallet/layer·업무 상태·ROS/driver·journal 쓰기·grant 발급이 없다. 기존 Cell·preflight consumer는 변경 없이 통과한다.
- 누락 API의 커밋 RED를 공식 원격 runner로 확인한 뒤 구현하고 독립 계약 검토한다.

## 다음 실행 계약에서 닫아야 할 항목

### 내부 결속 구현 증거

commit `4ebbf08576`의 공식 원격 RED는 누락 모듈로 14 failed였다. commit `d0d7f4616d`의 결속·사전검사·기존 pose/Cell acceptance 회귀는 **112 passed, skip0, 0 NEW**다. 독립 검토에서 불변 map·canonical revision·기하 선택권·거절 경계의 material finding은 없었다. 로그는 저장소 밖 `rosy-transfer-object-bindings-red`와 `rosy-transfer-object-bindings-green`에 보존한다. 실제 소비자·물체 관측·attempt 결속과 실행 승인의 증거는 아니다.

새 ARM_TRANSFER는 같은 mission/step/action/attempt·시간·epoch/generation envelope와 canonical complete-grant digest를 사용하되 payload에는 위 물리 참조만 둔다. Cell recipe/cell/process 값을 다른 digest로 채워 이름만 바꾸지 않는다. default owner·미설치 결속·미지원 profile에서는 접수 전에 거절한다. phase runner만 허용하고 shared control admission·held-object·stop/fence를 우회하지 않는다.

기존 fleet_cell_jobs는 legacy metadata NOT NULL과 Cell 생성 검증을 갖는다. 중립 producer를 넣기 전 legacy provenance와 중립 물리 provenance를 구분하는 schema migration을 설계한다. 기존 row·step·FK·mirror trigger·grant/event·claim·UNKNOWN 상태를 보존하는 atomic migration과 회귀가 필요하다. 공통 시작 검증을 분리한 사실이 중립 DB 생성의 구현 증거는 아니다.

실행 성공과 물리 자원 해제도 구분한다. 현재 Cell 성공은 ACTION_SUCCEEDED/CLAIMED이며 별도 독립 goal evidence 뒤 최종 claim을 해제한다. 새 경로에서 success를 GOAL_CONFIRMED·화물 도착·팔 전체 퇴피로 번역하지 않는다. arm command 점유와 shared-zone 점유가 무엇으로 해제되는지 trusted producer·freshness·attempt 결속까지 정하기 전 shared-zone 자동 해제를 열지 않는다. home/TCP만으로 전체 link의 영역 이탈을 주장하지 않는다. 이 부분은 다음 계약에서 닫을 미결 사항이며 이번 결속 타입의 완료로 덮지 않는다.

Fleet의 실제 중립 producer는 기존 two-person 승인과 원장/claim/fence/불명 조회를 재사용한다. 자원 목록은 설치 설정에서 결정하고 앱은 줄이거나 바꾸지 못한다. 응답 유실 뒤 새 요청·다른 팔 재배정·claim 해제가 없다. 다른 최소 HTTP 소비자와 Harbor의 실제 CargoMove 변환을 모두 연결하고, 동작 성공만 있는 경우 업무 장부가 진행되지 않는 독립 시험을 유지한다.

공개 submit의 활성화 조건은 물리 결속·owner capability/phase runner·원장/승인/복구·자원 해제 계약과 HTTP 통합 증거가 모두 준비되는 것이다. 실물 활성화·배포·push는 별도 범위다.

## 실행·자원 종료 계약 제안 — 독립 검토 전

기존 claim 경로는 두 가지다. 단일 팔 `CellJobStore.confirm_step_goal`은 별도 goal evidence 뒤 최종 Job claim을 해제한다. 다중 팔 `cell_arm_claims.release_succeeded`는 장치 성공 뒤 자신의 arm/zone key를 해제하되 다른 미완료 Action과 공유하는 key는 유지한다. Job-level claim은 이 함수가 건드리지 않는다. 앞의 ACTION_SUCCEEDED/CLAIMED 설명은 단일 팔 Job 경로를 가리킨다. 새 kind를 다중 팔 성공 callback에 등록하는 것만으로는 아래의 물리 자원 종료 검증이 생기지 않는다.

중립 동작은 앱의 화물 도착·하역 완료를 조건으로 삼지 않는다. ROSY는 물체 참조의 목표 위치 관측과 그리퍼 해제, 설치된 자원별 안전 위치/정지 조건을 검증해 물리 실행 receipt를 만든다. Harbor는 이 receipt와 별도 업무 관측으로 자신의 장부를 진행한다. 앱의 업무 완료 요청은 ROSY claim 해제 입력이 아니다.

설치 설정은 해당 팔의 arm/zone 자원과 종료 정책을 함께 고정한다. 승인된 grant는 물체·두 catalog/binding digest·source/target뿐 아니라 그 설치 자원 정책 revision에도 결속한다. 요청자가 자원 목록·종료 허용 영역·관측 producer를 고르지 못한다. 종료 정책이 없거나 현재 revision이 다르면 pre-dispatch에서 거절한다.

물리 성공만으로 모든 zone이 비었다고 보지 않는다. 자원별 종료 증거는 동일 action/attempt·dispatch generation·authority epoch·설치 revision·owner journal에 결속하고, 완료 이후의 신선한 관측이어야 한다. arm은 실행 종료와 정지/열린 그리퍼/held-object 없음이 필요하다. zone은 추가로 승인된 전체 팔 링크 영역 이탈 증거가 필요하다. TCP 위치나 home 목표 도달만으로 대체하지 않는다. simulation에서도 전체 링크의 영역 관계를 제공하는 신뢰 producer가 없으면 zone을 유지한다. 단순 합성 joint-state 시험은 전체 링크 물리 검증의 증거로 기록하지 않는다.

receipt 저장과 해당 generation의 claim 해제는 같은 원장 transaction에 둔다. 중복 receipt는 같은 결과를 돌려주며 다른 attempt·오래된 fence·변경된 설치 revision·일부 zone 누락은 해제를 만들지 않는다. 공유 zone은 모든 점유 Action의 종료 증거가 갖춰져야 해제한다. 실패는 HELD, 접수/실행 여부 불명은 UNKNOWN으로 유지하고 기존 조회·복구 절차를 따른다. 앱 재전송·다른 팔 선택이나 TTL 만료로 이를 풀지 않는다.

위 해제 검증은 성공 callback뿐 아니라 **취소·재개·재승인·복구**에도 적용한다. 기존 단일 팔의 `resume`, `cancel`, `_set_claims`, `confirm_step_goal`, 다중 팔의 `_hold_before_send`, `record_action_result`, `confirm_step_goal`, `resume_arm`, `resume`, `cancel`을 시작 목록으로 삼아 실제 claim 삭제 소비자를 전부 추적한다. 현재 Cell의 `cancel`과 `resume_arm`에는 물리 종료 증거 없이 HELD claim을 푸는 경로가 있으므로 새 kind가 이를 그대로 호출하지 못하게 한다. 취소는 작업을 종료할 수 있지만 미검증 물리 점유는 보존한다. 접수 전 무진행 해제도 durable 미접수·이전 점유 없음이 입증된 경우만 허용한다. 기존 Cell 동작은 유지한다.

공유 점유자 계산에는 RUNNING/HOLD뿐 아니라 **동작은 성공했으나 해당 자원의 종료 증거가 없는 Action**도 포함한다. 상태명만 바꿔 공유 zone 점유자를 숨기지 않는다. 실패·부분 완료·재시작·응답 유실 뒤 cancel/resume/reapproval과 완료 미입증 sharer가 있는 경우에도 zone 유지 회귀를 둔다. 새 정책 엔진 대신 불변 설치 조건과 기존 credential/producer registry·evidence 저장·event replay·claim transaction을 사용하는 작은 검증 함수를 둔다.

구현 순서는 (1) 정확한 grant/receipt 모델과 거절 시험, (2) legacy 필수 provenance를 유지하는 원장 migration과 보존 시험, (3) 기존 owner phase runner의 중립 grant 분기 및 복구, (4) 신뢰 종료 증거와 claim transaction, (5) two-person 승인과 simulation HTTP, (6) Harbor CargoMove 변환과 업무 장부 독립 시험이다. 공개 활성화는 여섯 단계가 모두 연결된 뒤에 한다. wire 필드·API 버전은 검토된 모델을 실제 등록할 때 예약한다.

독립 초안 검토는 기존 cancel/resume의 HELD 해제 우회와 성공했지만 종료 미입증인 공유 점유자 누락을 지적했다. 위 두 조건을 활성화 게이트와 회귀 범위에 추가했다. 아직 구현을 검증한 결과는 아니다.

추가 소스 조사에서 `TaskStore._advance_dispatch_control`의 site-stop/authority 변경은 Cell/charging 보존 hook을 호출한 뒤 남은 모든 CLAIMED claim을 삭제함을 확인했다. 중립 kind의 점유도 그 hook에서 HELD/UNKNOWN 보존되는지 회귀해야 한다. `dispatch_admission.release`, `action_claims.release_keys/release_held_keys`가 실제 삭제를 수행하며, TRIP arrived와 channel task 결과의 삭제 경로도 존재한다. 후자는 해당 owner_kind/owner_id에만 한정되는지 확인해 중립 mission 점유를 지우지 못하게 한다. 함수명 검색만으로 전체 입구 검증 완료를 주장하지 않는다.

## 첫 실행 모델 등록안

`ArmTransferPayload`는 `object_ref`, `catalog_digest`, `bindings_digest`, `source`, `target`, `resource_policy_digest` 여섯 필드만 갖는다. 참조·digest는 기존 사전검사의 strict 물리 참조/SHA-256 타입을 재사용하고 source와 target은 달라야 한다. 임의 좌표·기하 override·recipe·cargo·pallet·업무 상태를 받지 않는다. resource policy digest는 설치 자원/종료 조건에 결속할 참조이며 요청자가 만든 policy의 승인을 뜻하지 않는다.

`FleetArmTransferGrant`는 기존 mission/step/action/attempt·request_digest·workcell/instance·capability/config revision·authority epoch·dispatch generation·issued/expires envelope와 `action_kind=ARM_TRANSFER`, `arm_transfer` payload를 갖는다. identity는 기존 Action identifier 규칙이며 네 실행 identity는 서로 달라야 한다. 시간은 aware timestamp이고 expiry가 issuance보다 뒤여야 한다. epoch/generation은 strict nonnegative int다. 여분 필드는 거절하고 모델은 불변이다. pair/barrier는 이번 모델에서 열지 않는다. 순차·팔 교대는 앱이 별도 Action으로 요청하며 미확정 claim을 넘겨 재배정하지 않는다.

이 등록은 wire DTO만 추가한다. 기존 `parse_action_grant`·`PHASE_RUNNER_KINDS`·registry·UDS submit은 지원하지 않는 새 kind를 계속 거절한다. 실제 소비자를 연결할 때 capability/control admission/phase workflow/recovery와 모든 해제 입구를 함께 검증한다. 새 grant의 digest는 기존의 전체 canonical grant digest 규칙으로 계산해야 하며, DTO 생성 성공 자체는 서명·승인이나 물리 검증이 아니다.

canonical export 공간은 기존 device-action/stop DTO의 정의를 별도 `device_actions.py`로 그대로 이동하고 `schemas.py`에 동일 클래스 re-export를 둬 확보한다. AST·JSON schema·기존 digest/stop/receipt 소비자 회귀로 의미 보존을 확인한다. 기존 grant와 stop 필드·validator·기본값은 바꾸지 않는다. 새 API 참조 버전은 모델 등록과 함께 예약하며 공개 submit route가 생겼다고 기록하지 않는다.

이 등록은 commit `1258314f51`, API v1.303으로 구현했다. 신규·기존 소비자 공식 원격 **1385 passed, skip0, 0 NEW**와 독립 검토를 확인했다. DTO 14개의 AST 동일성과 canonical identity/JSON schema 생성은 확인했으며 전체 JSON schema 문서 전후 비교는 별도다. [정확한 범위와 한계](../validation/harbor-neutral-arm-grant-2026-10-24/result.md)를 따른다. 실제 소비자·원장·자원 종료·Harbor 연결은 계속 진행한다.
