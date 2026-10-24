# D-856 중립 팔 실행: 물리 결속·권한·원장

**Status:** 실행 계약 초안. 먼저 아래 물체–기하 결속의 내부 데이터 경계를 검토·구현한다. 새 공개 submit path·API 버전·dispatch kind는 아직 등록하지 않는다. [전체 계획](2026-10-24-harbor-rosy-application-action-boundary.md), [완료한 grant 검증 경계](2026-10-24-step-grant-boundary-design.md)를 잇는다.

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

새 ARM_TRANSFER는 같은 mission/step/action/attempt·시간·epoch/generation envelope와 canonical complete-grant digest를 사용하되 payload에는 위 물리 참조만 둔다. Cell recipe/cell/process 값을 다른 digest로 채워 이름만 바꾸지 않는다. default owner·미설치 결속·미지원 profile에서는 접수 전에 거절한다. phase runner만 허용하고 shared control admission·held-object·stop/fence를 우회하지 않는다.

기존 fleet_cell_jobs는 legacy metadata NOT NULL과 Cell 생성 검증을 갖는다. 중립 producer를 넣기 전 legacy provenance와 중립 물리 provenance를 구분하는 schema migration을 설계한다. 기존 row·step·FK·mirror trigger·grant/event·claim·UNKNOWN 상태를 보존하는 atomic migration과 회귀가 필요하다. 공통 시작 검증을 분리한 사실이 중립 DB 생성의 구현 증거는 아니다.

실행 성공과 물리 자원 해제도 구분한다. 현재 Cell 성공은 ACTION_SUCCEEDED/CLAIMED이며 별도 독립 goal evidence 뒤 최종 claim을 해제한다. 새 경로에서 success를 GOAL_CONFIRMED·화물 도착·팔 전체 퇴피로 번역하지 않는다. arm command 점유와 shared-zone 점유가 무엇으로 해제되는지 trusted producer·freshness·attempt 결속까지 정하기 전 shared-zone 자동 해제를 열지 않는다. home/TCP만으로 전체 link의 영역 이탈을 주장하지 않는다. 이 부분은 다음 계약에서 닫을 미결 사항이며 이번 결속 타입의 완료로 덮지 않는다.

Fleet의 실제 중립 producer는 기존 two-person 승인과 원장/claim/fence/불명 조회를 재사용한다. 자원 목록은 설치 설정에서 결정하고 앱은 줄이거나 바꾸지 못한다. 응답 유실 뒤 새 요청·다른 팔 재배정·claim 해제가 없다. 다른 최소 HTTP 소비자와 Harbor의 실제 CargoMove 변환을 모두 연결하고, 동작 성공만 있는 경우 업무 장부가 진행되지 않는 독립 시험을 유지한다.

공개 submit의 활성화 조건은 물리 결속·owner capability/phase runner·원장/승인/복구·자원 해제 계약과 HTTP 통합 증거가 모두 준비되는 것이다. 실물 활성화·배포·push는 별도 범위다.
