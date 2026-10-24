# D-856 중립 팔 grant의 owner 실행

**Status:** 내부 transaction·명시적 설치 factory·phase-only IPC v2 구현과 집중 원격 검증 완료. actual owner-state 조립·독립 HTTP·Fleet producer와 물리 자원 종료는 미완료다. [전체 실행 계약](2026-10-24-neutral-arm-execution-design.md)을 따른다. 기본 owner에 factory를 설치하거나 배포한 것은 아니다.

## 소비 경로

Fleet의 인증된 UID → ActionApi v2 → typed ARM_TRANSFER grant → ActionRunner의 digest/시간/scope/fence/capability → 같은 owner의 shared control admission → ActionStore/phase recorder → 설치 결속을 검증하는 phase factory → 기존 PickPlaceRunner/goal port → 기존 물리 workflow/gripper 검증 순서다. direct driver와 새 ROS owner는 추가하지 않는다. Fleet registry·승인·자원 종료는 별도 소비 경로이며 owner의 Action 성공이 그것을 대신하지 않는다.

## transaction과 복구

`PickPlaceTransaction.for_arm_transfer`는 검증된 전체 grant를 복제하고 물체 identity를 `object_ref`에 결속한다. source/destination TargetEvidence를 만들거나 Cell item/pallet을 채우지 않는다. 새 snapshot은 `action_kind=ARM_TRANSFER`, 전체 `arm_grant`, 공통 identity/generation·sensor revision·상태·held-object 정보를 저장한다. camera observation이나 가짜 destination object ID를 만들지 않는다. 기존 Cell/PICK snapshot은 내용·복구 결과를 유지한다.

recover는 새 tag와 grant를 함께 요구하고 Cell grant와의 혼합을 거절한다. identity/generation은 변환 전 strict type/value로 grant와 대조한다. 별도 중복 물체 참조도 grant와 달라지면 거절한다. 단계 도중 재시작은 기존처럼 HOLD와 object-may-be-held를 유지하며 자동 phase 재실행이 없다. 완료 상태의 복구는 owner journal/parent Action에 결속한 기존 복구 경로를 거쳐야 하며 snapshot 하나가 외부 완료 증거가 되지 않는다.

첫 내부 transaction 구현은 runtime kind를 열지 않는다. 태그 누락/혼합·다른 attempt/scope/generation/object·bool generation·가짜 완료·GRASP/TRANSFER 중 재시작과 기존 Cell snapshot 회귀를 확인한다.

## 설치 결속과 phase factory

owner 설치 객체는 immutable `TransferObjectBindings`, 허용 capability/config revision, 설치 자원 정책 digest를 갖는다. grant의 scope·두 catalog/bindings digest·resource policy digest·물체/source/target을 대조한다. 객체 생성이나 requester가 보낸 digest는 승인 자료가 아니다. 외부 설치/승인 API는 추가하지 않는다.

factory는 이 설치 객체, 승인된 profile/kinematics, owner-admitted measured state와 같은 monotonic clock, 기존 command/goal/stop/fence ports, 필수 gripper sensor revision/readback을 받는다. catalog/profile/kin/calibration/transform/scene의 일치와 freshness를 계획 전후에 확인하고 owner-resolved geometry로 순수 planner를 호출한다. requester가 좌표·geometry를 덮어쓰지 못한다.

PickPlaceRunner와 현재 CellTransferWorkflowExecution의 물리 부분을 재사용한다. TransferSkill/Cell recipe invocation을 만들어 우회하지 않는다. phase gate와 최종 완료는 같은 owner stop/fence에 직렬화하고 gripper observation은 scope·sensor revision·generation·object·freshness를 검증한다. callback/계획/그리퍼 오류에서 명령을 만들지 않거나 기존 HOLD/UNKNOWN으로 귀결한다. factory는 ROS node·poll loop·자동 retry를 만들지 않는다.

## runtime 활성화 게이트

transaction·설치 factory가 검증된 뒤 parse/grant union·phase-only kind·shared control admission 요구·ActionStore camera-blind/완료 event·UDS 최소 v2를 같은 변경으로 연결한다. capability callback은 기존 필수 인수를 유지하고 설치 검증을 수행해야 한다. default owner는 설치 factory가 없어 새 kind를 journal 전 거절한다. direct-driver 종류는 늘리지 않는다. 새 kind를 지원하게 되는 시점에 API 버전을 예약·기록한다.

기존 비활성 DTO의 parser 거절 시험은 설치 없는 실제 runner/API 거절 시험으로 바꾸되 동일한 journal/actuator 무변경 보장을 유지한다. 승인 factory의 simulation 성공·gripper 누락/물체 변경·stale calibration/fence·응답 유실 뒤 중복·재시작 HOLD를 통합 검증한다. 팔/zone claim 해제와 Harbor 도착·하역·퇴피 업무 판단은 이 owner 코드의 권한이 아니다.

## 내부 transaction 확인

commit `11486ce7cd`에서 raw identity/generation·물체 결속과 새 snapshot의 HOLD 복구를 구현했다. 독립 검토가 발견한 태그 두 개 삭제 우회는 RED 뒤 legacy 필수 형식 검증으로 차단했다. 신규·기존 Cell/PICK 소비자 원격 74 passed/skip0/0 NEW와 재검토를 확인했다. [정확한 소스와 한계](../validation/harbor-neutral-arm-owner-2026-10-24/result.md)를 따른다. parent Action kind·grant·durable journal과의 대조는 실제 recovery 소비자를 연결할 때 수행하며 factory/runtime 활성화 조건은 그대로다.

설치 factory/phase-only 연결은 commit `45173e6f92`, API v1.305로 구현하고 test-only `337e42e314`의 원격 153 passed/skip0/0 NEW와 최종 SHA 독립 검토를 확인했다. Fleet client의 ARM→v2 누락도 RED 뒤 `fc5d75eecd`에서 연결해 원격 15 passed/skip0/0 NEW를 확인했다. Fleet registry·physical creator는 계속 닫혀 있고 actual owner-state/HTTP·모든 자원 종료 입구·Harbor 연결은 남는다.

Pilot/raw 명령이 Fleet epoch/generation을 새로 만들지 않는 source 경로를 확인해 [managed authority](2026-10-24-managed-transfer-authority-design.md)를 추가했다. `69607b2b0d`의 영속 profile/최종 owner 권한 보강은 원격 119 passed/skip0/0 NEW와 고정 SHA 독립 검토를 확인했다. [결과와 남은 affected/ROS/claim 게이트](../validation/harbor-managed-arm-2026-10-24/result.md)를 따른다. 이 단계로 resource closure나 Fleet producer를 활성화하지 않는다.

`46f56d6b48`, API v1.306에서 실제 등록 factory·canonical journal/session의 capability 조회와 grant/receipt/404 결속을 추가했다. 집중 원격 790 passed/7 skipped/0 NEW와 fixed SHA 독립 검토를 확인했다. FULL23은 변경 이력 표 행 누락1 NEW로 종료했고 문서 수정 후 실패 entry9를 재검증한다. [결과](../validation/harbor-managed-capability-2026-10-24/result.md)를 따른다. capability는 설치 사실이며 admission·World 물리 관측·claim 해제를 대신하지 않는다.
