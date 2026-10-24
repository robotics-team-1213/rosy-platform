# D-856 중립 팔 사전검사와 실행 계약

**Status:** 내부 catalog·사전검사 설계 검토 승인(2026-10-24). 이 문서는 후속 상세 설계이며 현재 제공되는 API 목록이 아니다. [책임 ADR](../adr/D-856-application-action-boundary.md), [전체 계획](2026-10-24-harbor-rosy-application-action-boundary.md), [분리한 물리 계획기](2026-10-24-neutral-arm-planning-design.md)를 잇는다. 공개 path·schema·API 버전은 검토 뒤 예약하고 reference와 함께 등록한다.

## 확인한 생산자와 소비자

`omx_cell_owner.build_cell_owner`는 승인 Cell/recipe 장부, 현재 관절 상태, 계획기와 phase runner를 한 owner에 조립한다. `transfer_provider.OMXAnalyticTransferPlanner`는 `FleetCellTransferGrant`를 `pallet.transfer` 입력으로 투영하고 recipe에서 파지 기하를 읽는다. `ActionRunner`의 capability·peer·fence 검사 뒤 `PickPlaceRunner`와 `ArmCommandOwner`가 최종 상태와 출력을 검증한다.

Fleet `step_action_kinds`는 종류별 grant·승인·phase 규칙을 갖지만 `CellJobStore.start_step`에는 아직 CELL_TRANSFER digest 대조가 직접 들어 있다. `create_in_transaction`도 recipe/cell/process digest를 필수로 요구한다. 따라서 새 종류를 registry에 추가하는 것만으로 중립 실행이 완성되지 않는다. 이 필드에 물리 문서 hash를 대신 넣어 통과시키지 않는다. 기존 TRIP 전용 읽기 결과 역시 팔 공정의 실행 근거로 사용할 수 없다.

## 앱이 요청하는 것과 owner가 승인하는 것

Harbor는 불투명한 물체 참조, 설치된 팔 instance, source/target 물리 자세 참조를 선택한다. 화물 우선순위·대체 팔 정책·팔레트/층·출고·재취급·업무 관측은 전달하지 않는다. object 참조는 owner의 held-object/그리퍼 근거를 연결하며 물체 종류나 업무 상태로 분기하지 않는다.

owner에는 검토된 물리 catalog를 설치한다. catalog는 workcell/instance, profile·kinematics·calibration·transform revision, base frame, home 자세·carry 높이, 독립된 named 자세와 각각의 approach 높이, 독립된 물체 geometry 참조를 담는다. geometry는 폭·파지 깊이·높이·180도 대칭 지원을 담고 하중은 현재 backend가 검증할 수 있는 범위만 허용한다. 검증하지 않는 하중 필드를 받았다는 이유로 지지 능력을 보증하지 않는다.

catalog는 완성된 동작 목록이나 workflow가 아니다. source/target/geometry를 별도로 선택할 수 있으며 job·recipe·pallet·layer·업무 순서를 넣지 않는다. claim할 arm/workcell/zone의 설치 대응은 Fleet의 신뢰된 설치 설정이 소유한다. 앱이 자원 목록을 줄이거나 임의 zone을 만들어 기존 점유와 충돌을 피할 수 없다. catalog 변경은 새 digest이며 진행 중인 action의 기하를 덮어쓰지 않는다. 초기 구현은 시작 시 설치된 고정 catalog만 읽고 외부 등록/수정 API를 만들지 않는다.

기존 recipe의 기하를 새 catalog로 자동 승인하지 않는다. simulation fixture는 명시적으로 검토된 고정 물리 입력을 갖는다. 실물 catalog 수용은 별도 장치 검증이다.

## 읽기 전용 사전검사

첫 내부 계약은 owner의 `check_transfer` 서비스다. 입력은 catalog digest, source/target 자세 ID, geometry ID이며 새 업무 ID나 raw 관절 궤적은 없다. 실제 공개 HTTP/UDS framing은 이 서비스 검토와 fixture 뒤 확정한다.

서비스는 다음 순서로 처리한다.

1. 명시한 catalog digest와 참조를 owner 설치본에서 대조한다. 없는 참조와 구버전 digest는 계산 전에 거절한다.
2. owner가 현재 측정한 `ExecutionStateSnapshot`을 읽는다. desired home에서 합성하지 않는다. 관절 지도, 유한한 monotonic 시각, profile의 최대 상태 나이, 미래 시각, calibration/transform/scene revision을 검사한다.
3. catalog에서 `TransferMotionRequest`와 `GraspGeometry`를 구성하고 중립 계획기로 계산한다. home/open-gripper·fingertip·운반 높이·IK/workspace·연속성·속도/가속·시간 한계를 유지한다.
4. 계산 종료 시 같은 측정 snapshot이 여전히 profile의 나이 한계 안에 있는지 다시 검사한다. 긴 계산 후 오래된 결과를 현재 준비 상태로 답하지 않는다. 계획 출력 검증도 수행한다.
5. 결과에는 검사한 catalog/profile/kinematics/calibration/transform/scene revision, source state sequence와 관측/검사 시각, 요청한 물리 참조와 지원 범위를 반환한다. 관절 궤적이나 재사용 가능한 실행 permit은 반환하지 않는다. 오류는 기존 계획기 reason과 입력/상태 오류를 구별한다.

이 결과는 그 snapshot에서 지원된 물리 계획을 만들 수 있었다는 사실이다. busy·zone 점유·stop latch·실행 허가·충돌 안전·팔 전체 퇴피·화물 도착을 뜻하지 않는다. 이 backend는 collision scene을 제공하지 않는다. Harbor는 주/대체 팔 후보를 비교할 수 있지만 이를 cache해 다음 실행의 최종 검사를 생략하지 않는다. owner 호출 권한과 Fleet 조회 권한은 기존 peer/principal 경계로 확인하고 외부 앱은 owner UDS를 직접 호출하지 않는다.

内部 구현은 `omx_adapter.transfer_preflight`에 `TransferPose(pose, approach_z)`, `ArmTransferCatalog(workcell_id, instance_id, profile_revision, kinematics_revision, calibration_revision, transform_revision, planning_scene_revision, home, carry_z, poses, geometries)`와 `TransferPreflight(catalog, profile, kinematics, *, execution_state, monotonic)`를 둔다. catalog는 불변 복사본과 canonical physical-content SHA-256을 갖고 frame은 `robot_base`로 고정한다. `check_transfer(*, catalog_digest, source, target, geometry)`는 참조와 검사 revision·source sequence·관측/검사 monotonic 시각만 가진 불변 결과를 반환한다. 이 시각은 같은 owner clock domain 안에서만 비교한다. 공개 HTTP에서 다른 호스트 시계와 비교할 필드는 framing 단계에서 별도로 정한다.

상태 공급자는 owner가 admission한 측정 상태를 `ExecutionStateSnapshot`으로 투영해야 한다. runtime의 미승인 `latest_joint_state`를 그대로 읽지 않는다. 관측 timestamp와 서비스/계획기 clock은 같은 monotonic clock을 공유하며 계산 종료에 clock 역행·미래 상태·나이 초과를 다시 거절한다. 내부 서비스 생성은 실행 capability를 등록하거나 owner를 기동하지 않는다.

## 실행 접수와 기존 경로 보존

다음 단계의 중립 팔 grant는 source/target/geometry 참조, catalog digest와 불투명 object 참조를 담는다. action/attempt·request digest·principal·workcell/instance·authority epoch·dispatch generation·유효기간은 현재 grant envelope를 재사용한다. 실행 시 owner가 catalog와 현재 상태를 다시 확인해 새 계획을 만든다. 사전검사 결과를 전달해 실행 검사를 대체하지 않는다.

Fleet는 중립 step 원장에서 proposal과 다른 named operator의 승인, 명시적 시작, 신뢰된 설치 자원 claim을 같은 transaction 경계로 집행한다. 응답 유실/재시작/늦은 결과/UNKNOWN은 기존 원장 규칙과 동일하게 점유를 보존하고 GET 대조한다. 다른 팔로의 전환은 원래 팔의 불명 실행·점유를 해소한 뒤 새 proposal/승인으로 진행한다. 두 팔 동시 실행과 공중 인계는 이번 simulation 흐름에서 열지 않는다.

기존 Cell 원장을 새로 복제하지 않는다. 먼저 원장의 공통 action identity·승인·claim·복구 부분과 Cell provenance 검증을 분리하고 기존 Cell producer/consumer 시험으로 보존한다. 변경이 독립 검증되면 중립 producer를 연결한다. `CELL_TRANSFER`, 기존 UDS v1/v2, Cell compiler와 승인 recipe 검사는 호환 경로에 유지한다. 중립 경로는 palletizing import 없이 부팅·사전검사·실행해야 한다.

실제 phase 실행은 같은 `PickPlaceRunner`, 그리퍼 관측/held-object transaction, 정확한 goal 취소와 단일 `ArmCommandOwner`를 사용한다. stop/fence·상태 freshness·revision·single writer와 두 사람 승인을 우회하는 새 executor는 만들지 않는다.

## Harbor 연결과 검증 순서

Harbor의 `CargoMove`/outbound 변환은 source/target와 geometry를 설치 binding에서 선택한다. cargo ID는 앱 장부와 불투명 object 참조의 대응으로 관리한다. binding 누락·revision 변경·사전검사 불가이면 실행 요청을 만들지 않는다. 도착·배치 확인은 인증된 관측, 전체 퇴피는 측정된 팔 영역 이탈과 Fleet zone 해제 근거로 별도 판정한다. action 성공이나 home 복귀만으로 업무 완료를 기록하지 않는다.

1. catalog·사전검사 내부 API와 fixture를 독립 계약 검토한다. RED는 누락 참조/digest, 비유한·미래·오래된 상태, revision 불일치, 계산 중 freshness 만료, 도달 불가와 정상 계산을 포함한다.
2. 최소 내부 구현 후 기존 물리 계획·Cell/owner 회귀를 커밋 SHA로 원격 실행한다. service에는 submit·claim·journal·driver 의존성을 주입하지 않아 읽기가 실행을 발생시키지 않도록 한다.
3. 공개 framing·typed schema·API reference를 예약/검토하고 Fleet HTTP → 인증된 owner read 경로를 구현한다. 원격 HTTP에서 잘못된 principal/instance·timeout·구버전 응답과 caller 결속을 검증한다.
4. Cell 원장의 공통/공정 경계를 먼저 분리해 호환 회귀를 닫고 중립 grant와 simulation 실행을 연결한다. 실제 grant → phase → owner 경로와 수신 전 검증을 독립 리뷰한다.
5. Harbor 변환과 응답 유실 대조를 연결하고 공정 미설치 서버/플랫폼 Python 미설치 클라이언트/두 번째 최소 HTTP 소비자를 고정 SHA로 시험한다. 업무 관측이 없으면 성공한 action 뒤에도 업무가 진행되지 않아야 한다.

전체 D-856은 팔 HTTP·Harbor 변환·복구/독립성 증거까지 닫아야 한다. 내부 사전검사나 TRIP 통과만으로 완료 처리하지 않는다. 실물 실행·배포·push는 이 설계의 승인 범위가 아니다.
