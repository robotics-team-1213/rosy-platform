## D-927 Harbor 첫 흐름 시연 경계와 자동 시뮬 회귀

**Status:** Accepted (2026-10-30, 사용자의 11/21 시연 목표·최대 자동화·시뮬 사용 지시). 경계와 자동화 방식의 결정이다. 구현·원격 회귀·배포·장치·현장 수용은 각각 증거로 판단한다.

### Context

PRODUCT.md 완료 조건 1(Harbor 첫 흐름 ①반출 전 변경 지시 → ②재취급 화물 처리 → ③이송 → ④S 내려놓기 → ⑤재취급 화물 정리·팔 퇴피를 공개 계약만으로 시뮬에서 끝까지)을 11/21까지 증명한다. 개발자는 2명이고 구현은 병렬 에이전트 흐름이 맡는다. 흐름이 서로 기다리지 않으려면 경계를 먼저 고정해야 한다.

2026-10-30 확인한 현재:

- 조각은 따로 통과한다. Harbor `tools/integration/real_fleet_http.py`는 TRIP(`fleet_harness.RealFleet`)과 ARM(`arm_fleet_harness.ArmFleet`)을 서로 다른 Fleet으로 띄우고 ①~⑤를 잇는 실행이 없다.
- Fleet ↔ OMX owner는 `work/physical_transfer_dispatcher.py`의 owner SDK 5연산과 `local_action_transport.py`의 UDS, 종류별 wire v2로 이미 정해져 있고 simulation profile에서만 열린다.
- 정상 단계 관측은 Harbor 하네스 스레드가 고정 scene 값으로 만들고 같은 스레드가 승인한다. 플랫폼의 비시험 관측 도구는 복구 전용 `tools/sim/recovery_observer.py`뿐이다.
- D-866 §2 공유 backend 계약에서 Gazebo·MuJoCo·Isaac 5.1이 같은 적합성을 통과했다(D-877). MuJoCo·Isaac은 `/sim/object_tf`로 물체 위치를 낸다(흔들림 0.0mm).
- 재사용할 시뮬 자산이 있다: Gazebo `worlds/omx_cell_workcell.sdf`와 `deploy/robot/omx/run_cell_sim.sh`(명령 owner 없는 follower, owner는 별도 실행, D-403 §8), 구독만 하는 독립 측정 프로세스 `deploy/robot/omx/g2_observer.py`, 플랫폼 시뮬 owner 구성 `profiles/installations/omx_cell_sim.yaml`. D-866(Proposed)은 Gazebo를 실행 계약 회귀용으로 둔다.

### Decision

**1. 시연 계약을 동결한다.** Harbor ↔ Fleet은 TRIP 조회 v1.298, ARM v1.312, 물리 근거 조회 v1.330을 시연 기준으로 쓴다. 시연까지 이 경로의 변경은 additive만 허용한다.

**2. Fleet 하나가 TRIP과 ARM을 함께 서빙한다.** simulation profile의 Fleet 한 프로세스·한 원장에서 ①~⑤가 돈다. 두 Fleet으로 나눈 실행은 완료 조건 1의 증거가 아니다.

**3. 시연 owner는 플랫폼 시뮬 구성이고 OMX 시뮬 backend는 MuJoCo가 기본이다.** ARM은 `omx-cell-sim` 구성(`hardware_dispatch_enabled: false`)의 owner가 D-866 §2 공유 층(`tools/sim/omx_topic_backend.py`) 위의 `tools/sim/omx_mujoco_backend.py`를 구동한다. MuJoCo는 같은 셀 장면(`omx_cell_world.py`)에서 적합성을 통과했고 AI PC 실시간 배율 0.999다(D-877, `validation/omx-sim-object-facts-2026-10-27`). Gazebo는 같은 계약의 CI 기준선으로 남고, owner는 backend를 구분하지 않는다. Fleet의 owner UDS는 같은 호스트(`UnixLocalActionTransport`)라 시뮬 Fleet과 OMX owner·MuJoCo는 한 PC에 둔다. Harbor 하네스의 가짜 owner는 Harbor 단위 시험에만 쓴다. TRIP은 기존 Pinky Gazebo 차로 시뮬과 CORE 경로를 쓴다. 최종 명령은 주행 CORE, 팔 owner만 낸다.

**4. 정상 단계 관측은 독립 시뮬 관측 프로세스가 만든다.** 새 `tools/sim/transfer_observer.py`는 `g2_observer.py`처럼 시뮬 topic을 구독만 하고 goal을 보내지 않는다. D-866 공유 계약의 `/joint_states`와 backend가 내는 `/sim/object_tf`(정책 입력과 분리된 평가용 사실)로 관절·링크 상태와 물체 자세를 측정해 `GET /api/fleet/arm-transfers/observation-context` → `POST …/jobs/{mission_id}/observations`로 제출한다. 별도 프로세스·만료되는 관측자 자격을 쓰며 앱·승인자·owner 자격과 합치지 않는다. 시뮬 backend(Gazebo, D-866의 다른 backend)가 같은 topic 층을 내면 바꿀 수 있다. 결과는 시뮬 관측이며 물리·보정·현장 근거가 아니다.

   표본은 진행 중인 D-917(원본 source stamp·수신 monotonic·안정 observation_id/digest, 시각 역행 시 거절 latch)과 D-918(Fleet context 요청 뒤 물리 step을 증명하는 요청 결속 capture)의 규칙을 따른다. Gazebo backend는 D-918 capture를 그대로 입력으로 쓰고, MuJoCo backend는 같은 표본 필드와 요청 결속을 `/sim/object_tf`·`/joint_states` 위에 제공한다. D-917·D-918은 Fleet 관측 제출기를 두지 않았다. 이 결정은 그 제출기를 **simulation profile에서만** 연다. 실물 관측 admission은 계속 닫혀 있다.

**5. 승인은 자동화하되 단계를 나눈다.**
- 5a. 매일 밤 회귀는 시험 전용 named operator 자격의 승인 스크립트가 같은 admit 경로로 승인한다. 이 자격은 시험 PC 시뮬 Fleet에만 발급한다.
- 5b. D-865 정책 승인을 simulation profile에서 먼저 시험 활성화하는 것은 D-865 갱신으로 따로 결정한다. 이 ADR은 그것을 열지 않는다.
- 시연 당일은 사람이 Fleet 화면에서 승인한다. 실물 profile의 승인 방식은 바꾸지 않는다.

**6. 물리 기하의 정본은 플랫폼이다.** 셀 기하·팔·zone·장치 칸의 물리 참조는 플랫폼 installation profile 하나가 소유한다. Harbor binding은 그 ID와 digest만 참조하고 기하를 복제하지 않는다(Harbor ADR 0005 결정 4).

**7. 전체 흐름 회귀를 자동으로 매일 돌린다.** 한 명령이 시뮬 world, 시뮬 Fleet, 시뮬 owner, `transfer_observer.py`, 승인 스크립트, Harbor를 양 끝 SHA 고정으로 띄우고 ①~⑤를 실행한다. 단계별 결과와 처음 실패한 단계를 남긴다. 시험 PC는 `tools/remote/remote_pytest.py --pick sim`이 고른다. 이 결과는 ROS-SIM 증거이며 DEVICE·FIELD가 아니다.

**8. 변경 규칙.** 시연까지 결정 1·2·4·6의 경계를 바꾸는 변경은 양쪽 코드와 계약 시험을 한 변경 묶음에서 고치고, 전체 흐름 회귀(결정 7)를 통과해야 착지한다.

### Alternatives

- Harbor 하네스 가짜 owner·고정 scene 관측으로 시연: 플랫폼 owner와 독립 관측 경로를 증명하지 못해 채택하지 않는다.
- 운동학 계산만으로 관측 생성: owner 자신의 계획 값으로 자기 결과를 판정하게 되어 독립 관측이 아니므로 채택하지 않는다.
- Gazebo를 OMX 시연 backend로: 같은 계약을 통과하지만 MuJoCo가 headless(EGL)·실시간 배율이 좋아 매일 밤 회귀에 맞다. 공유 층이라 언제든 바꿀 수 있어 기준선으로만 둔다.
- Isaac Sim을 시연 backend로: 적합성은 통과했으나 D-866 전환 조건(640×480 두 대 10Hz, 실시간 배율 1)이 미충족(6~7Hz, 0.91~0.94)이다. 충족하면 결정 4에 따라 교체한다.
- D-865 정책 승인을 이 ADR에서 개방: 승인 정책은 D-865 소유라 채택하지 않는다(결정 5b).

### Consequences and verification

- 흐름 분담: A Harbor 업무 실행기, B Fleet 한 프로세스 TRIP+ARM, C 시뮬 owner 연결, D `transfer_observer.py`, E 전체 흐름 회귀. 각 흐름은 이 결정의 경계를 상대로 개발한다.
- 완료 판정: 결정 7의 회귀가 ①~⑤를 통과하고, Harbor 정책 하나를 바꾼 회귀에서 rosy-platform diff가 0이다.
- 실물 owner·실물 관측·현장 수용은 D-858 S4·S5와 DEVICE·FIELD 관문이 따로 판정한다.

### Related decisions

D-917·D-918(진행 중, 시뮬 관측 표본·capture 규칙), D-403, D-836, D-856, D-858, D-865, D-866, D-877. Harbor ADR 0005·0013·0015(참조 ADR 0016 예정).
