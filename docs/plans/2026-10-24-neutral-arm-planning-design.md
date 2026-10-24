# D-856 공정 검증과 팔 동작 계산의 분리

**Status:** 상세 설계 검토 승인·내부 분리 구현 (2026-10-24). 독립 설계 검토를 받았고 코드 commit 613c6b1b20의 관련 원격 회귀 135개가 통과했다. [D-856](../adr/D-856-application-action-boundary.md)의 팔 경계를 구현하는 다음 단계다. 기존 TRIP 흐름의 통과를 팔 분리 완료로 대신하지 않는다. 이번 단계는 장치 내부 순수 계획기 분리이며 새 wire·dispatch kind·실물 허가가 아니다.

## 현재 결합과 보존할 보장

현재 `pose_plan.AnalyticCellTransferPlanner.plan_transfer`는 승인 recipe/cell hash와 물체 기하를 확인한 뒤 같은 함수에서 IK·접근·파지·이송·놓기/복귀 궤적을 계산한다. 요청의 job/recipe/cell/item은 앞부분의 공정 provenance 검증에 쓰이고 실제 궤적 계산에는 쓰이지 않는다. 그 뒤는 home/pick/place·접근 높이·carry 높이와 물체 폭/파지 깊이/높이, 설치된 로봇 한계·관절 상태를 소비한다.

다음 보장을 보존한다: 승인 cell hash의 계획 직전 재확인, 승인 recipe의 폭/깊이 대응, fingertip overhang과 물체 높이, 검토된 kinematics/profile revision, 정확한 관절 지도, planning scene, home 시작 자세, 열린 그리퍼, 운반 높이, IK·workspace·연속성, 속도·가속·phase 시간, 부분 놓기와 복귀. 결과를 실제 실행하기 전의 기존 owner state freshness·fence·그리퍼 관측·single writer 검증도 바꾸지 않는다.

기존 backend는 충돌 장면이 없고 180도 대칭 물체만 다루는 simulation 전용이다. 이를 중립 타입으로 바꾸는 것이 임의 물체·실물·충돌 회피 기능을 만든다는 뜻은 아니다.

## 모듈과 정확한 인터페이스

`omx_adapter.transfer_motion`은 `ArmPlanningProfile`, `TransferMotionRequest`, `GraspGeometry`, `TransferMotionPlan`, `TransferPlanRejected`와 공통 물리 검증을 소유한다. `ArmPlanningProfile`의 내용·파일 schema·revision 해시는 현재 `CellPlanningProfile`과 같으며 이름 때문에 승인된 파일 형식을 바꾸지 않는다.

`TransferMotionRequest(home, pick, place, pick_approach_z, place_approach_z, carry_z)`는 base frame의 `TopDownPose` 세 개와 유한한 물리 높이 세 개만 가진 불변 값이다. cargo·job·recipe·pallet·layer·업무 상태가 없다.

`GraspGeometry(grasp_width_m, grasp_depth_m, height_m, yaw_symmetric_pi)`는 불변 물리 기하다. 폭·높이는 유한 양수, 깊이는 유한 비음수이며 `yaw_symmetric_pi is True`만 이 backend에서 지원한다. 기하를 선택·승인하는 것은 호출자의 등록/설치 검증 경계이며 이 데이터 타입의 생성이 실행 권한을 부여하지 않는다.

`omx_adapter.transfer_planner.AnalyticTransferPlanner(kinematics, *, monotonic=time.monotonic)`의 `plan_transfer(request: TransferMotionRequest, profile: ArmPlanningProfile, state: ExecutionStateSnapshot, *, geometry: GraspGeometry) -> TransferMotionPlan`은 물리 계산만 한다. 계획 함수·helper 본문은 기존 식·단위·시도 중재를 바꾸지 않고 옮긴다. 수신자에게 장치 SDK·ROS 경로·추가 writer를 요구하지 않는다.

`pose_plan`은 기존 public 이름을 재수출하는 호환 면과 `CellTransferRequest`, `AnalyticCellTransferPlanner` 공정 adapter를 유지한다. adapter는 기존 hash/item callback을 정확히 같은 시점에 검사한 뒤 승인 기하와 물리 요청을 공통 계획기에 넘긴다. `CellPlanningProfile`·`CellTransferPlan`·`CellTransferPlanRejected`·`validate_cell_transfer_plan`의 기존 import와 `isinstance`·동작을 alias로 보존한다. 기존 서명과 반환 필드는 유지하며 dispatcher·grant·실행 스키마는 변경하지 않는다.

## 구현 순서와 시험

1. 기존 `pose_plan`의 모든 생산자·소비자 import를 검색한다. 현행 profile/plan·geometry guard·owner 수용 시험을 먼저 대조한다.
2. 중립 요청만으로 계획, 승인 기하의 높이·대칭성·유한값 거절, 기존 궤적/오류/owner 검증 보존 시험을 추가하고 커밋된 RED를 공식 원격 runner에서 확인한다.
3. 물리 타입·profile/plan 검증과 계산을 각각 500줄 이하의 두 모듈로 옮긴다. `pose_plan` 호환 adapter는 공정 provenance 검증을 남긴다. 크기 ratchet은 실제 줄어든 파일만 낮추며 기준을 올려 통과시키지 않는다.
4. 원격으로 `test_omx_pose_plan.py`, 새 중립 계획 시험, `test_omx_cell_transfer_runner.py` 및 해당 owner/물리 검증 회귀를 실행한다. 전체 기존 suite/FULL 선택 결과는 별도 근거로 확인한다.
5. 공정 adapter 검증을 생략하거나 앱이 임의 기하를 승인된 것으로 제공하는 통로가 생기지 않았는지 독립 계약/안전 검토한다.

## 다음 공개 계약의 선행 조건

중립 계획기를 만든 뒤에만 owner 측의 등록된 물체 기하·profile/state revision을 선택하는 읽기 전용 preflight 경계를 설계한다. 앱은 계획과 등록 물리 참조를 요청하고, owner는 현재 보정·freshness·도달/한계를 검사한다. preflight는 예약·실행 허가·화물 완료 증거가 아니다. 새로운 공개 요청에서 recipe/cell을 이름만 바꿔 숨겨 보내지 않는다.

Harbor의 주 팔/대체 팔 선택은 이 사전 검증 결과와 설치 revision을 소비한다. 공정 변환·결과 해석은 Harbor 소유로 연결한다. 중립 실행 요청은 현재 안전 검증과 원장/승인에 대응하는 별도 계약·양 끝 시험을 갖춘 뒤 simulation에서만 연다. 이 설계 단계가 그 후속 구현 완료를 주장하지 않는다.
