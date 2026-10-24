# D-856 실제 설치 capability와 grant의 owner 결속

**Status:** 구현 전 계약 검토. [managed authority](2026-10-24-managed-transfer-authority-design.md)의 다음 단계다. 새 Fleet producer나 자원 해제는 이 변경으로 활성화하지 않는다.

## 현재 소스와 필요한 경계

`ActionApi.GetOwnerIdentity`는 생성자에 받은 정적 dict를 반환한다. 여기에 managed=True를 넣는 것만으로는 실제 ActionRunner의 등록 factory, 같은 ControlSeatAdmission/ActionStore, 최종 goal port와 영속 policy를 확인할 수 없다. `omx_managed_transfer_scope.journal_id`는 관리 scope의 내부 식별자이며, 기존 receipt/404 복구가 사용하는 `omx_journal_identity.journal_id`와 다른 값이다. 외부에는 기존 canonical journal ID를 사용하고 scope 내부 값은 새 이름으로 공개하지 않는다.

현재 ARM grant도 목표 owner의 journal/session을 포함하지 않는다. Fleet의 확인 뒤 owner가 교체돼 새 UDS 연결이 생기는 경우, 오래된 grant가 다른 실행 세션에 도달하지 않도록 목표 결속을 grant digest에 포함해야 한다. 기존 CELL_TRANSFER/TRIP 형식과 실행은 유지한다. ARM은 아직 이 브랜치의 simulation library 단계이며 실제 producer·배포·공유 소비자는 열지 않았다. 이전 ARM grant가 결속 없이 새 managed owner에 도달하면 실행하지 않는다.

## wire 계약

새 read-only local IPC v2 `GetTransferCapability`는 `{version: 2, operation: GetTransferCapability}`만 받는다. 기존 GetOwnerIdentity는 그대로 둔다. Fleet UID/principal 인증을 먼저 적용하며 coordinator/미등록 peer에게 capability를 제공하지 않는다. 미설치·unmanaged·disabled·구성/저널/owner 불일치는 `ARM_TRANSFER_CAPABILITY_UNAVAILABLE` 503, 잘못된 요청은 400, peer 거절은 403이다. 이 응답은 설치 사실이며 admission·idle·계획 가능성·충돌 검사·물리 완료·claim 해제를 뜻하지 않는다.

성공 envelope는 `{version: 2, status: 200, capability: ArmTransferCapability}`다. canonical closed/frozen DTO는 action_kind=ARM_TRANSFER, control_mode=fleet_managed, workcell_id, instance_id, journal_id, owner_session_id, catalog_digest, bindings_digest, resource_policy_digest, capability_revision, config_revision을 갖는다. 문자열/식별자/digest는 기존 ARM 타입을 재사용한다. journal ID는 같은 SQLite snapshot의 기존 canonical identity여야 하며 읽기 요청이 누락 identity를 새로 만들지 않는다.

`FleetArmTransferGrant`에는 필수 `owner_journal_id`, `owner_session_id`를 추가한다. 완전한 canonical digest가 두 값을 포함한다. ARM 접수는 실제 shared admission의 현재 owner session과 같은 DB의 canonical journal을 journal 쓰기 전에 대조한다. phase 제출 직전에도 같은 결속을 재검사하고, 현재 세션과 command.session_id가 달라지면 최종 owner가 거절한다. 기존 ARM snapshot의 결속 누락은 HOLD/거절이며 새 값을 채워 replay하지 않는다.

독립 검토에 따라 receipt/404 소비까지 결속한다. ARM receipt의 journal_id는 ActionRunner의 실제 SQLite attempt snapshot에서 읽고 정적 ActionApi identity가 덮어쓰지 않는다. Fleet의 공통 receipt 검증은 ARM의 grant.owner_journal_id를 필수 대조한다. 같은 canonical journal의 과거 Action 조회는 재시작 후에도 허용하며 과거 owner_session_id를 현재 세션으로 바꿔 새 실행하지 않는다. GetAction 404에 canonical identity가 있으면 실제 값을 보고하되, SDK는 ARM의 404를 언제나 fenced reconciliation이 필요한 UNKNOWN/unavailable로 취급한다. None을 미접수·자동 재접수·재배정·claim 해제 증거로 넘기지 않는다. Cell/TRIP의 기존 조회 계약은 유지한다.

새 공개 API minor는 구현 직전에 예약한다. canonical schemas export, API ref/changelog/live version pins를 함께 바꾼다. envelope1.0/localIPC2는 유지한다. 이전 ARM library 형식은 새 managed 실행을 승인하는 호환 경로로 사용하지 않는다. 기존 Cell/TRIP 회귀는 필수다.

## producer와 소비자 경로

설치 integration factory는 managed 구성을 선택한 경우에만 adapter의 불변 callable factory 객체를 반환한다. 이 객체는 기존 create callback과 실제 bindings·revision·admission·최종 port를 소유한다. API는 ActionRunner의 ARM registry에 그 객체가 실제 등록돼 있고 같은 store/scope/admission/final owner를 쓰는지 확인한다. 정적 dict나 임의 callable의 capability 문자열을 신뢰하지 않는다. 상태 조회는 기존 journal/scope를 같은 DB snapshot에서 읽고 현재 owner와 대조한다. 최종 command lock 안에 DB/network 조회를 추가하지 않는다.

Fleet SDK는 같은 UDS transport로 한 번 조회하고 canonical DTO·v2 envelope·요청 scope를 엄격히 검사한다. wrong instance/workcell, missing/extra fields, malformed digest/identity, unknown mode, old/unavailable owner를 거절한다. timeout은 기존 UNKNOWN/unavailable 경계로 남고 자동 retry/cache/submit을 만들지 않는다. 실제 physical producer는 후속으로 이 결과를 승인 snapshot/step/claim에 보존한다.

## 구현 범위와 검증

1. canonical capability DTO/ARM grant 필수 목표 결속, fixture와 소비자 전체를 조사해 RED를 먼저 커밋한다.
2. adapter installed-factory/capability 조회와 실제 owner/DB/session 대조, integration factory, ActionApi의 v2 read/auth를 연결한다. 기존 pure planner·stop/phase/final owner·default 거절은 유지한다.
3. SDK의 strict read와 ARM receipt journal 대조/404 HOLD를 추가한다. actual UDS와 주입 final owner의 source 경로를 검증하고 journal 교체·session 변경·미설치·다른 owner·위조 정적 identity·잘못된 peer/version·응답 유실을 거절하는 회귀를 둔다. 같은 journal에서 세션이 바뀐 과거 Action의 durable GET도 유지한다.
4. 기존 Cell/PICK/TRIP와 snapshot HOLD를 공식 고정 SHA로 원격 검증한다. foundation 변경의 FULL 선택을 축소하지 않는다. 소스 독립 검토, size/safety, 모든 run의 known_failures 분류를 기록한다.

이 단계의 통과가 Fleet 승인/dispatch·resource closure·World 관측·Harbor 업무 완료의 수용을 대신하지 않는다. 실물 활성화·배포·push는 수행하지 않는다.
