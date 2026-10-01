## D-376 OMX PICK_PLACE 계획은 장치 로컬에 두고 trajectory 실행은 Action owner가 맡는다

**Status:** Accepted (2026-09-30, 소프트웨어 경계와 fail-closed gate만). typed planning 계약과 ROS trajectory 단일 writer를 결정한다. production planner 설정, OMX profile 활성화, public API, 장치/현장 동작 또는 안전 성능은 승인하지 않는다.

**부분 개정 (D-402, 2026-10-01, 시뮬레이션 한정):** [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md)(Proposed, 사용자 승인)가 §2 마지막 문장의 "별도 결정"으로 해석 5축 수직하향 IK backend를 고른다. 적용 범위는 `CELL_TRANSFER` Action과 `simulation` 프로필뿐이다. 이 범위에서는 §3의 SRDF·planning group·충돌 scene 조건을 URDF 기구학, 시뮬 프로필 한계, 작업 영역, 운반 높이 경유로 대신한다. RGB-D `PICK_PLACE`와 실물 프로필에서는 §3 HOLD가 그대로다. §1의 단일 제출자와 §4–§8은 바꾸지 않는다. 이 개정은 D-402가 Accepted가 되면 효력이 생긴다. 그 전에는 원문이 그대로 적용된다.

**관련 결정:** [D-327](D-327-semantic-manipulation-actions-and-device-adapters.md) (의미 조작 경계; 고정 작업대 구현 외 항목은 Proposed), [D-336](D-336-fleet-omx-local-ipc-boundary.md) (같은 호스트 UDS), [D-348](D-348-goal-evidence-producer-and-verifier-wiring.md) (Fleet 독립 목표 검증), [D-369](D-369-control-authority-and-stop-evidence.md) (권한과 정지 증거).

### Context

Fleet의 `PICK_PLACE` grant는 동기화된 이미지 관측에서 출발 물체와 목적지를 식별한다. `ResolvedTargetEvidence`에는 픽셀 상자, 프레임 digest, 카메라/좌표계 identity, calibration/transform revision과 capture time이 있지만 depth, workcell pose, grasp, 충돌 검사 경로, 관절 trajectory는 없다. OMX target resolver는 의도적으로 픽셀 identity까지만 처리한다. ROS owner는 현재 최종 joint-position map 하나를 받아 한 점짜리 `FollowJointTrajectory` goal을 보낸다. phase journal은 있지만 계획을 여러 ROS goal로 연결하는 runner는 없다.

잠금된 `rosy-omx-workstation:native-action-only-local` 이미지(`sha256:b47034e436119cea97c2922a1b4af9bd6596975ac8acbb4cece3a19d2fe1e9f0`)에는 ROS 2 Jazzy, 고정된 ROBOTIS OMX-F description, `ros2_control`이 있다. MoveIt/MTC 패키지는 없고, OMX-F description에는 URDF/Xacro 및 controller 파일만 있으며 SRDF 또는 MoveIt kinematics/planning 설정은 없다. 분리된 임시 컨테이너에서 ROS apt index를 갱신해 공식 Jazzy 후보 `moveit_task_constructor_core 0.1.8-1noble.20260904.024044`, `moveit_core 2.12.4-1noble.20260903.075716`를 확인했다. 이는 패키지 후보의 존재만 증명한다. 패키지를 설치하지 않았고, OMX MoveIt 설정·planning scene·IK·trajectory export·실행 호환성을 빌드하거나 시험하지 않았다.

### Decision

1. **모델과 Fleet은 관절 명령을 만들거나 제출하지 않는다.** ER 2는 후보를 만드는 주체로 남고 `get_mission_status` 읽기 및 후보형 replan 도구만 쓴다. Fleet은 Action을 승인하고 Mission 순서, grant, attempt, Mission feedback을 소유한다. 장치 로컬 OMX Action owner만 팔 `FollowJointTrajectory` goal을 제출한다.
2. **계획 경계는 plan-only다.** 로컬 `PickPlacePlanProvider`는 신선한 RGB-D 근거를 해석해 typed object pose와 네 순서의 motion phase(`approach`, `grasp`, `transfer`, `release`)를 반환할 수 있다. MoveIt Task Constructor는 평가 후보이지 승인된 production backend가 아니다. 후보를 채택해도 계획만 반환해야 하며 controller 실행에 직접 연결하지 않는다. 다른 결정론적 backend는 근거 검토와 별도 결정 전에는 선택하지 않는다.
3. **planner 호환성은 HOLD다.** Jazzy 패키지 후보가 있다는 사실은 잠금된 OMX-F 모델과의 호환성을 증명하지 않는다. production provider 전에는 검토된 workcell SRDF, planning group/end-effector, IK solver, 충돌 geometry/scene, 제한값, frame/calibration identity와 기존 owner 계약으로 완전한 timed trajectory를 내보내는 재현 가능한 빌드가 필요하다. 이 조건 전에는 근거가 없거나 지원되지 않는 계획을 `HOLD`로 거절하고 production 계획을 합성하지 않는다.
4. **각 ROS goal은 내구성 있는 phase 하나다.** dispatch 전에 phase intent를 저장한다. 첫 phase 응답에서는 부모 Action의 결과와 phase 접수/goal UUID를 SQLite 단일 트랜잭션으로 갱신한다. 이 commit 전에 응답 유실이나 재시작이 나면 부모와 phase를 `UNKNOWN/HOLD`로 복구하고 재제출하지 않는다. 이후 phase는 바로 앞 ROS UUID의 terminal 성공 뒤에만 시작한다. 물체 보유·배치 검증 workflow는 ROS goal phase로 위장하지 않는다.
5. **trajectory 실행자는 local owner 하나다.** 계획의 모든 timed waypoint는 명시적으로 승인된 joint map/limits, state sequence, calibration, planner/scene revision 및 제출 직전 stop generation으로 검증한다. MTC execution manager, trajectory topic, leader teleoperation 또는 별도 프로세스가 owner를 우회할 수 없다.
6. **피드백 종류를 합치지 않는다.** goal 접수, running feedback, cancel ACK, controller terminal 결과, gripper readback, local software latch, 물리 E-stop/standstill, Fleet goal confirmation은 별개의 사실이다. 활성 phase의 정확한 ROS UUID를 지정해 취소한다. UUID 기반 취소를 지원하지 않으면 Action을 미해결/HOLD로 둔다. Fleet `GOAL_CONFIRMED`는 기존 독립 goal evidence service만 판정한다.
7. **Fleet/model 경계에 phase 상태를 읽기 전용으로 전달한다.** Fleet phase projection을 구현할 때 기존 UDS operation 6개를 유지한다. 제한된 phase summary는 버전이 있는 UDS v2 receipt로 전달하고 비-phase 호출의 v1 동작을 보존한다. phase dispatch는 v2를 요구하며 무음 fallback을 하지 않는다. ROS UUID, trajectory, 원본 이미지, planner scene, cancel/stop/E-stop/rearm은 ER 2 도구로 노출하지 않는다. 새 public REST 경로를 만들지 않는다.
8. **배포는 비활성으로 유지한다.** 이 결정은 `omx.disabled.yaml` 활성화, 물리 capability 광고, artifact 게시, 장치/현장 시험을 허용하지 않는다. 물리 E-stop과 독립 standstill은 별도 device acceptance gate다.

### Consequences and validation

typed interface, fail-closed 검사, phase journal, receipt schema 및 Fleet 읽기 전용 projection은 injected fake를 사용해 SOURCE/LOCAL에서 구현할 수 있다. ROS-SIM은 선택 모델/config와 ROS Action callback 연결을 잠금된 Linux 환경에서 재현한 뒤 진행한다. 현재 패키지 후보 확인은 build 또는 ROS-SIM 통과가 아니다. 실물 workcell profile, 독립 정지, gripper 동작, calibration, 서명 artifact, 운영자 수용을 증명할 때까지 DEVICE/FIELD는 PARKED다.

**References:** [ROS 2 Actions design](https://design.ros2.org/articles/actions.html), [Jazzy MoveIt Task Constructor package](https://index.ros.org/p/moveit_task_constructor_core/), [MTC ROS 2 source branches](https://github.com/moveit/moveit_task_constructor), [Jazzy Joint Trajectory Controller](https://control.ros.org/jazzy/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html).
