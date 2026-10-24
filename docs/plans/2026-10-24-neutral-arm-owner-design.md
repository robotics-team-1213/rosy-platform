# D-856 중립 팔 grant의 owner 실행

**Status:** 구현 전 검토안. [전체 실행 계약](2026-10-24-neutral-arm-execution-design.md)을 실제 OMX owner에 연결한다. schema version5와 비활성 grant DTO만으로 실행을 열지 않는다.

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
