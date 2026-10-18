# 두 번째 OMX 팔은 독립 병렬부터, 양팔 협응은 마지막에

- 날짜: 2026-10-17 (Asia/Seoul)
- 기준: 로컬 main `dee4bf972`에서 읽은 ADR·소스와 2026-10-16~17 웹 조사
- 상태: 조사 보고. Accepted·Proposed ADR을 대체하지 않는다. 두 번째 팔 구매, D-281 개정, MoveIt 도입, 양팔 owner 구현을 승인하지 않는다. 아래 관문 기준은 제안이며 팀이 정한다.
- 범위: [D-281](../adr/D-281-site-host-placement-and-omx-instance-isolation.md), [D-402](../adr/D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-773](../adr/D-773-omx-ai-extension-platform-structure.md), [D-55](../adr/D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-770](../adr/D-770-fleet-omx-autonomous-imitation-pipeline.md)
- 제외: 코드 변경, 실물 측정, 장치 수용, 판매처 가격 확인
- 원본: Claude Docs 「듀얼 로봇팔 동작 조사 보고서」(같은 내용, 로드맵은 그림)

## 결론

두 번째 OMX 팔을 추가할 수는 있다. 다만 한 번에 가지 않고 단계를 밟아야 한다. 먼저 두 팔을 각자 독립적으로 돌린다. 그다음 공유 구역을 예약하는 방식으로 두 팔이 협조하게 한다. 양팔 협응은 마지막에 학습 데모로만 시도한다.

- **이미 있는 것:** D-281이 한 호스트에 OMX 두 대(`omx_01`, `omx_02`)를 독립 인스턴스로 두는 구조를 정했다. 두 인스턴스가 서로 격리되는지는 시뮬로 확인했다.
- **없는 것:**
    - 두 팔 사이의 공통 좌표계
    - 팔 간 충돌 회피
    - 동기화된 명령
    - 두 팔을 함께 다루는 owner
    - 또한 코드에는 단일 팔을 가정한 부분(루트 토픽 이름)이 남아 있다.
- **외부 동향:**
    - MoveIt 2는 두 팔을 한 URDF로 묶으면 충돌 검사와 동기 계획을 준다. 그러나 두 팔을 독립적으로 동시에 실행하는 기능은 본선에 없다.
    - 양팔 협응 작업은 ALOHA·ACT 계열의 모방학습이 주류다. 작업당 약 50회 시연으로 80~90% 성공률이 보고됐다.
- **권고:**
    1. 단일 팔의 실물 제어 승인과 캘리브레이션을 먼저 끝낸다.
    2. 루트 토픽을 namespace로 바꾼다.
    3. 아래 로드맵의 1→2→3단계 순서로 진행한다.
    - 3단계는 D-281을 개정해야 한다. 그러니 양팔이 꼭 필요한 작업이 생길 때만 연다.

## 현재 시스템

| 항목 | 현재 상태 | 근거 |
| --- | --- | --- |
| 팔 | ROBOTIS OMX-AI(OMX-F follower + leader)다. 5축 + 그리퍼이고 Dynamixel ID는 11–16이다 | `deploy/robot/omx/stack.lock.yaml`, `docs/validation/omx-follower-registers-2026-10-15/result.md` |
| 버스 | OpenRB USB 시리얼, 1 Mbps다. follower·leader 보드가 팔마다 1개씩 있다 | `docs/plans/2026-10-15-omx-hardware-control.md` |
| 호스트 | amd64 워크스테이션이다(Pinky의 Pi 5와는 별개). 현장 호스트는 Ubuntu 26.04 + ROS Lyrical이다 | `deploy/robot/omx/README.md` |
| 제어 | vendor ros2_control의 `arm_controller`(JointTrajectoryController)를 쓴다. MoveIt 없이 해석적 5축 top-down IK를 쓴다 | D-402 |
| 명령 경로 | Fleet → grant → ActionRunner → PickPlaceRunner → ArmCommandOwner → FollowJointTrajectory | D-773 |
| 학습 | LeRobot 0.4.4 + ACT(단일 팔)를 쓴다. `learned_policy`는 아직 허용 owner가 아니다 | `learning/training/omx/README.md`, `middleware/devices/omx/agent/src/rosy_agent/omx_cell_owner.py:44` |
| 카메라 | top/front V4L2 미리보기 카메라가 있다. hand-eye·TCP 캘리브레이션은 아직 승인되지 않았다 | `middleware/devices/omx/adapter/progress.md` |
| 상태 | `omx`·`omx_adapter`는 SOURCE/LOCAL GO, ROS-SIM HOLD, DEVICE/FIELD PARKED다 | `STATUS.md` |

두 팔과 관련해 이미 정한 것:

- **D-281 (Proposed):** 한 Ubuntu 호스트에 OMX를 1~2대 둔다. 팔마다 systemd 인스턴스, 시리얼, 카메라, 캘리브레이션을 따로 가진다. 두 팔을 하나의 ROS 그래프나 프로세스로 합치는 안은 기각했다. 프로세스 분리는 물리적 안전 경계가 아니라고 명시한다.
- **`omx_01` / `omx_02`:** [호스트 인벤토리 템플릿](../../deploy/robot/omx/host-inventory.yaml.example)에 둘 다 비활성으로 있다. preflight는 두 팔이 시리얼이나 카메라 장치를 공유하면 거부한다.
- **[2-인스턴스 시뮬 검증](../validation/omx-two-instance-ros-sim-2026-09-26/README.md) (2026-09-26, HOLD):** 도메인 71/72로 나눠 돌렸다. 한쪽을 멈추거나 재시작해도 다른 쪽은 영향을 받지 않았다.
- **[ER2 평가](../plans/2026-09-29-er2-isaac-sim-architecture-assessment.md):** 두 팔을 병렬로 돌리려면 Fleet Mission DAG가 필요하다. 지금의 `/api/fleet/do`는 단계를 순차로 실행한다.

단일 팔을 전제한 코드:

- `/joint_states`와 `/arm_controller/follow_joint_trajectory`가 namespace 없이 하드코딩돼 있다. 해당 파일은 `deploy/robot/omx/run_cell_owner.py`, `g2_owner.py`, `g2_common.py`, `probe_cell_transfer.py`다. `hardware_readiness.py`만 namespace를 받는다.
- `deploy/robot/omx/compose.yaml`은 장치 한 쌍(`OMX_FOLLOWER_DEVICE`/`OMX_LEADER_DEVICE`)과 도메인 하나만 받는다.
- `omx` 프로파일은 인스턴스 키가 없는 단일 블록이다.
- 시험과 픽스처는 `omx_01`을 고정해서 쓴다.

## 듀얼암 운용 방식

두 팔을 운용하는 방식은 결합이 강해지는 순서대로 세 단계다. 단계가 올라갈수록 필요한 제어 인프라가 커진다. 분류는 Smith et al.의 듀얼암 서베이(RAS 2012)를 따랐다. 우리가 지금 설계한 것은 1단계다.

| 단계 | 방식 | 예시 | 필요한 것 | 우리 상태 |
| --- | --- | --- | --- | --- |
| 1 | 비협조 (독립 병렬) | 팔 A는 픽플레이스를 하고, 팔 B는 다른 팔레트에 적재한다 | 장치·프로세스 분리, 작업공간이 겹치지 않는 배치 | D-281로 설계 완료, 시뮬 HOLD |
| 2 | 목표 협조 (goal-coordinated) | 두 팔이 한 팔레트에 번갈아 적재한다. 또는 한 팔이 건네고 다른 팔이 받는다 | 공통 좌표계, 팔 간 충돌 회피(또는 구역 예약), 작업 순서 조율 | 없음 |
| 3 | 양팔 협응 (bimanual) | 두 팔이 한 박스를 같이 든다. 뚜껑을 열거나 천을 접는다 | 닫힌 기구사슬 제어(relative Jacobian), 동기화된 궤적 또는 학습 정책, 힘 제어 | 없음 |

- **3단계의 제어 방식:**
    - 고전 방식은 master-slave다. 한 팔이 큰 동작을 맡고 다른 팔은 따라간다.
    - 대칭(symmetric) 방식은 상대 운동을 두 팔에 나눠 실어 충돌을 줄인다.
    - extended relative Jacobian을 쓰면 상대 운동을 팔마다 어떻게 나눌지 조절할 수 있다.
- **OMX의 제약:**
    - OMX-F는 5축이고 XL430급 서보를 쓴다.
    - 그래서 한 물체를 두 팔로 단단히 잡으면 자세 자유도가 모자라고, 내부 힘이 그대로 서보 부하로 간다.
    - 3단계는 가벼운 물체나 학습 기반 데모로 한정하는 편이 현실적이다.
    - 이 판단은 사양에서 추론한 것이고 실측하지 않았다.

## 하드웨어·통신

하드웨어에서 가장 큰 일은 두 가지다. 하나는 두 팔의 베이스 사이 변환을 구하는 캘리브레이션이고, 다른 하나는 공용 비상정지다. USB 포트와 전원은 현재 설계대로 팔마다 따로 두면 된다.

| 항목 | 권장 | 근거 |
| --- | --- | --- |
| 시리얼 포트 | 팔 2대 × (follower + leader) = OpenRB 4개다. 허브와 연장선 없이 호스트에 직결하고 `/dev/serial/by-id/`로 고정한다. FTDI 계열 어댑터라면 `latency_timer=1`을 설정한다 | [ALOHA README](https://github.com/tonyzhaozh/aloha), D-281 preflight |
| 카메라 | 팔마다 top·front 2대라면 총 4대다. USB 허브 하나에 최대 2대로 나눈다. 활용할 일이 있으면 양팔을 함께 보는 공용 카메라 한 대를 두는 것도 검토한다 | ALOHA README |
| 전원·E-stop | 팔마다 전원을 따로 둔다. 하드웨어 E-stop은 공유해서, 두 팔의 서보 전원을 한 번에 끊게 한다 | 엔지니어링 판단(권위 있는 출처 없음) |
| 전원 차단 시 낙하 | Dynamixel에는 브레이크가 없어서 토크를 끄면 팔이 처진다. 두 팔이 맞물린 채로 멈추면 서로 부딪힐 수 있다. 그러니 정지 자세를 정해 둔다 | ALOHA README |
| 배치 | 1단계에서는 두 팔의 도달 범위가 겹치지 않게 둔다. 2~3단계에서는 공유 구역을 일부러 만들고, 그 구역을 명시한다 | 엔지니어링 판단 |
| 베이스 간 캘리브레이션 | 팔 A 베이스와 팔 B 베이스 사이의 변환(T_AB)을 명시적으로 인수로 둔다. 베이스가 움직이면 다시 구한다. Bi-JCR은 손목 카메라 영상으로 hand-eye와 베이스 간 자세를 함께 추정한다 | [Bi-JCR](https://arxiv.org/abs/2505.24819) |
| 제어 주기 | ros2_control을 한 manager로 묶으면, manager 루프는 가장 빠른 하드웨어보다 빨라야 한다. ALOHA 계열은 50 Hz로 돈다 | [ros2_control rw_rate](https://control.ros.org/rolling/doc/ros2_control/hardware_interface/doc/different_update_rates_userdoc.html) |

지금은 hand-eye·TCP 캘리브레이션이 팔 하나에 대해서도 승인되지 않았다. 그러니 베이스 간 캘리브레이션은 단일 팔 캘리브레이션 다음에 한다.

## 제어 소프트웨어 (ROS 2 / MoveIt 2)

ROS 2에서 두 팔을 묶는 방법은 두 가지이고, 서로 맞바꾸는 것이 있다.

- 하나는 URDF 하나에 prefix를 붙여 한 그래프로 묶는 방식이다.
- 다른 하나는 namespace로 팔마다 따로 두는 방식이다.

D-281은 두 번째를 택했다. 그래서 지금 구조는 1단계에는 맞지만 2~3단계에는 모자라다.

| | A. 단일 그래프 (prefix) | B. 인스턴스 분리 (namespace / 도메인) |
| --- | --- | --- |
| 구성 | `left_`/`right_` prefix를 가진 URDF 하나, 하드웨어 인터페이스 2개를 호스팅하는 controller_manager 하나, move_group 하나 | 팔마다 controller_manager와 프로세스를 따로 둔다(현재 D-281: systemd 인스턴스와 도메인을 분리) |
| 팔 간 충돌 검사 | planning scene을 공유하므로 자동으로 된다 | 없다. 직접 만들어야 한다 |
| 동기화된 동작 | 두 팔을 담는 combined group으로 한 궤적에 계획할 수 있다 | 시간을 맞추는 상위 조율자가 따로 필요하다 |
| 독립적 동시 실행 | 한 번에 궤적 하나만 실행된다(MoveIt 2 본선의 한계) | 자연스럽게 된다 |
| 장애 격리 | 한쪽이 죽으면 둘 다 멈춘다 | 한쪽을 멈추거나 재시작해도 다른 쪽은 영향을 받지 않는다(2026-09-26 시뮬로 확인) |
| 맞는 단계 | 2단계 후반, 3단계 | 1단계, 2단계(구역 예약 방식) |

- **MoveIt 2 공식 튜토리얼:** [Dual Arms with MoveIt](https://moveit.picknik.ai/main/doc/examples/dual_arms/dual_arms_tutorial.html)은 prefix, 팔별 SRDF group, 팔별 JointTrajectoryController를 설명한다. 동시 실행은 다루지 않는다.
- **비동기 동시 실행:**
    - 관련 PR [moveit#3243](https://github.com/moveit/moveit/pull/3243)은 아직 병합되지 않았다.
    - [Stoop et al. 2023](https://ar5iv.labs.arxiv.org/html/2310.08597)은 포크에서 이를 구현했다.
    - [SMACC 사례](https://discourse.openrobotics.org/t/smacc-demonstrates-concurrent-control-of-two-arms-in-ros-2-using-moveit2-and-ros2-control/28793)도 병합되지 않은 PR에 기댄다.
- **ros2_control:** controller_manager 하나가 하드웨어 컴포넌트 여러 개를 호스팅할 수 있다. namespace로 manager를 여럿 두는 것도 된다([example 15](https://control.ros.org/jazzy/doc/ros2_control_demos/example_15/doc/userdoc.html)).
- **우리에게 맞는 방식:**
    - 지금은 MoveIt 없이 해석적 IK를 쓴다(D-402).
    - 따라서 2단계는 MoveIt을 들여오지 않고, **상위에서 공유 구역을 예약(lock)하는 방식**으로 시작한다. 이렇게 하면 D-281과 부딪히지 않는다.
    - 한 팔이 구역을 잡고 있는 동안 다른 팔은 그 구역 밖에서 기다린다.
    - 예약은 CORE나 Fleet Mission DAG가 맡는다. D-55에 따라 두 번째 팔도 CORE를 우회하지 않는다.
    - 3단계로 가려면 둘 중 하나가 필요하다. 방식 A로 바꾸거나, 학습 정책이 두 팔을 한 번에 명령하는 구조를 만들어야 한다. 어느 쪽이든 D-281을 개정해야 한다.
- **코드 정리:** 어느 방식을 고르든 이 일을 먼저 한다.
    - 하드코딩된 `/joint_states`와 `/arm_controller/follow_joint_trajectory`를 인스턴스별 namespace로 받게 바꾼다.
    - `compose.yaml`과 `omx` 프로파일에 인스턴스 키를 추가한다.

## 학습 기반 양팔 제어

양팔 협응 작업은 요즘 대부분 학습으로 푼다. 기준은 ALOHA 방식이다. leader-follower 텔레옵으로 작업당 약 50회 시연을 모으고, 그것으로 ACT를 학습한다. 우리는 이미 OMX leader-follower와 LeRobot ACT를 갖고 있어서 이 경로가 가장 가깝다.

| 시스템 | 하드웨어 | 데이터 | 카메라 / 주기 |
| --- | --- | --- | --- |
| [ALOHA + ACT](https://arxiv.org/html/2304.13705) | ViperX follower 2대 + WidowX leader 2대, $20k 미만 | 작업당 50회 시연, 성공률 80~90% | 4대(480×640, 30 fps), 50 Hz, chunk 100 |
| [Mobile ALOHA](https://arxiv.org/html/2401.02117) | AgileX Tracer 베이스 + ALOHA, 약 $32k | 작업당 20~50회, 정적 ALOHA 데이터와 co-training | 3대 |
| [ALOHA 2](https://arxiv.org/html/2405.02292) | 그리퍼·중력 보상 개선, MuJoCo 모델 공개 | — | RealSense D405 4대, 50 Hz |
| [Diffusion Policy](https://arxiv.org/html/2303.04137) | 양팔 작업 시연 | 작업당 162~284회, 성공률 55~75% | scene 2대 + wrist 2대 |
| [π0](https://arxiv.org/html/2410.24164) | UR5e·Trossen·ARX 양팔 (14차원 행동) | 약 10k시간 사전학습, 미세조정 1~100시간 | 최대 50 Hz, chunk 50 |
| [RDT-1B](https://arxiv.org/html/2410.07864) | ALOHA 양팔 | 1M+ 궤적 사전학습, 양팔 에피소드 6k로 미세조정 | 3대 |
| [GR00T N1](https://arxiv.org/html/2503.14734) | Fourier GR-1 휴머노이드 | 작업 데이터 15분~3시간 | 행동 120 Hz, VLM 10 Hz |

- **LeRobot의 양팔 지원:**
    - 현재 main에 `bi_so_follower`가 있다. `left_arm_config`/`right_arm_config`로 이루어진다([코드](https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/bi_so_follower/config_bi_so_follower.py)).
    - OMX용 양팔 클래스는 없다. 같은 패턴으로, 단일 OMX 클래스 두 개를 감싸는 `bi_omx_follower`를 만들어야 한다.
    - 이때 행동은 12차원(5축 + 그리퍼, 팔 둘)이다.
- **우리 파이프라인과의 차이:** 현재 ACT는 ResNet18, chunk 4, CPU 학습이다. ALOHA의 chunk 100, 50 Hz보다 작은 설정이다. 양팔에서는 GPU 학습과 chunk 크기를 다시 봐야 한다.
- **실행 권한:**
    - 양팔 정책은 두 팔에 명령을 한 번에 낸다. 지금 구조는 인스턴스마다 단일 owner에게 grant를 준다. 그래서 두 인스턴스의 grant를 원자적으로 함께 잡는 owner가 필요하다.
    - 그 전에 `learned_policy`를 허용 owner에 넣는 일을 단일 팔에서 먼저 끝내야 한다.
- **비용 참고:** 하드웨어를 새로 산다면 아래가 선택지다. 가격은 바뀌므로 판매처에서 확인한다.
    - [SO-101](https://github.com/TheRobotStudio/SO-ARM100): 양팔 leader-follower 부품이 약 $460이다.
    - [AgileX PiPER](https://global.agilex.ai/products/piper): 단팔 $1,999다.
    - [Trossen Stationary AI](https://www.trossenrobotics.com/post/bimanual-vs-single-arm-robot-manipulation): $23,995.95다.
    - OMX 두 번째 세트는 이미 설계가 돼 있어 가장 자연스럽다.

## 적용 로드맵

적용은 4단계로 나눈다. 단계마다 다음 단계로 넘어가기 전에 통과해야 하는 관문을 둔다. 0~2단계는 D-281 구조를 그대로 두고 할 수 있다. 구조를 바꿔야 하는 것은 3단계뿐이다. 일정은 0단계의 실물 승인 시점에 따라 정해지므로 날짜는 적지 않았다.

1. **0단계 · 선행 조건 (지금 할 일, 단일 팔)**
    - `omx_01` 실물 제어를 승인받고, hand-eye·TCP 캘리브레이션을 한다.
    - 루트 토픽을 namespace로 바꾸고, compose와 프로파일에 인스턴스 키를 추가한다.
    - 관문: `omx_01` DEVICE GO + 두 인스턴스의 토픽 격리 테스트 통과
2. **1단계 · 독립 병렬 (D-281 그대로)**
    - `omx_02`를 추가한다. 작업공간이 겹치지 않게 배치하고, 공용 하드웨어 E-stop을 단다.
    - 두 팔에 동시 궤적을 주고 부하 시험을 한다(시뮬 → 실물).
    - 관문: 두 팔이 동시에 움직이는 동안 상호 간섭 0건
3. **2단계 · 구역 예약 협조 (D-281 유지 + 상위 조율)**
    - 베이스 간 캘리브레이션(T_AB)을 하고, 공유 구역을 정의한다.
    - CORE·Fleet에 구역 lock과 Mission DAG 병렬 단계를 넣는다.
    - 관문: 공유 구역 충돌 0건 + 양팔이 필요한 실제 작업 확인
4. **3단계 · 양팔 협응 학습 데모 (선택, D-281 개정 필요)**
    - `bi_omx_follower`와, 두 팔의 grant를 함께 잡는 owner를 만든다.
    - 작업당 약 50회 시연을 모아 ACT를 학습한다(GPU, chunk 재조정).

## 리스크

| 리스크 | 영향 | 대응 |
| --- | --- | --- |
| 단일 팔이 아직 DEVICE PARKED | 두 번째 팔 작업을 먼저 하면 불확실성이 두 배로 는다 | 단일 팔의 하드웨어 제어와 캘리브레이션 승인을 먼저 끝낸다 |
| 프로세스 분리는 안전 경계가 아님(D-281 명시) | 작업공간이 겹치면 팔끼리 부딪힐 수 있다 | 1단계는 물리적으로 겹치지 않게 배치하고, 2단계는 구역 예약과 공용 E-stop을 둔다 |
| 단일 팔 가정이 코드에 남아 있음 | 두 번째 인스턴스가 첫 번째의 토픽으로 명령을 보낼 수 있다 | namespace를 파라미터로 받게 하고 토픽 격리를 시험한다 |
| MoveIt 2가 독립 동시 실행을 지원하지 않음 | 방식 A를 쓰면 두 팔이 번갈아서만 움직인다 | 2단계는 구역 예약으로 풀고, MoveIt은 3단계에서만 검토한다 |
| OMX의 페이로드와 5축 제약 | 한 물체를 두 팔로 단단히 들기 어렵다 | 3단계는 가벼운 물체와 학습 데모로 한정한다 |
| 호스트 배포판이 Jazzy가 아니라 Lyrical | 외부 패키지와 맞지 않을 수 있다 | 외부 패키지를 들이기 전에 버전을 고정한다 |

## 후속 검토: 양팔 협응을 목표로 둔다면 (2026-10-17)

검토 중에 반론이 나왔다. 양팔 협응이 관제를 하는 핵심 이유라면, 위 로드맵처럼 3단계를 "선택"으로 미뤄서는 안 된다는 것이다. 그 경우 구조적 기반은 지금 깔아야 한다. 이 반론은 타당하다. 지금의 선택 몇 가지가 나중에 양팔 협응을 막기 때문이다.

- **D-281의 단위:** D-281은 OMX 한 대를 `workcell_id` 하나로 본다. 두 팔을 한 ROS 그래프로 합치지 않는 이유로는 장치, 명령 소유권, 재시작·복구를 로봇별로 검증하기 어렵다는 점을 든다. 양팔 작업대라는 단위는 없다.
- **명령 권한:** 지금은 인스턴스마다 단일 owner에게 grant를 준다. 두 팔의 grant를 함께 잡는 길이 없다.
- **그래프 격리:** 시뮬 검증은 두 팔을 도메인 71/72로 나눴다. 이렇게 나누면 한 조율자가 두 팔에 닿을 수 없다.
- **장애 의미:** 지금 검증하는 것은 "한쪽이 재시작해도 다른 쪽은 계속 간다"이다. 양팔 협응에서는 반대로 한쪽이 멈추면 다른 쪽도 HOLD해야 한다.

양팔 협응을 목표로 둘 때 지금 정해야 할 기반은 아래와 같다. 이것은 결정이 아니라 ADR 후보다.

1. **양팔 작업대 식별:** 작업대 하나가 팔 인스턴스 둘(left/right 역할)을 가질 수 있게 한다.
2. **원자적 공동 lease:** 두 팔의 명령 권한을 둘 다 함께 잡거나, 하나도 잡지 않는다.
3. **같은 도메인, 팔별 namespace와 controller_manager:**
    - 프로세스와 장애 격리는 그대로 둔다.
    - 작업대 조율자 하나가 두 팔에 닿게 한다.
    - D-281 4항에 따라, namespace만으로 격리된다고 가정하지 않고 시뮬로 확인한다.
4. **공통 기준:**
    - 작업대 좌표계와 팔 베이스 변환 계약(`T_cell_left`, `T_cell_right`)을 둔다.
    - 같은 호스트의 시계를 쓰고, `FollowJointTrajectory` header stamp로 동기 시작한다.
5. **결합 정지:** 양팔 모드에서는 한 팔이 장애를 일으키면 두 팔이 함께 HOLD한다.
6. **역할 경계:**
    - 50 Hz 수준의 실시간 협응은 작업대 조율자가 맡는다.
    - Fleet은 작업대를 한 단위로 배정하고 순서를 정하는 데까지만 맡는다.

## 확인하지 못한 것

- 2024~2026년 사이 MoveIt 2 본선에 동시 실행이 들어갔는지
- ros2_control의 "동기화가 필요하면 manager 하나" 지침(ROSConFr 2022 발표에서 나왔다고 하나, 검색 요약으로만 봤다)
- 리셀러가 제시한 가격(Cobot Magic, Galaxea R1 Lite, PiPER $2,499 등)
- 「omx-follower-registers」 문서의 "우측 follower"가 오른쪽 팔을 뜻하는지, 오른쪽 보드를 뜻하는지

## 참고자료

외부 자료:

- [Smith et al., Dual arm manipulation — A survey (RAS 2012)](https://people.kth.se/~dimos/DualSurvey.pdf)
- [extended relative Jacobian (Almeida & Karayiannidis)](https://research.chalmers.se/en/publication/529141)
- [대칭·비대칭 협조 제어 논의](https://arxiv.org/abs/1905.01261)
- [MoveIt 2 Dual Arms tutorial](https://moveit.picknik.ai/main/doc/examples/dual_arms/dual_arms_tutorial.html)
- [moveit#3243 동시 실행 PR](https://github.com/moveit/moveit/pull/3243)
- [Stoop et al. 2023, 비동기 멀티암 스케줄러](https://ar5iv.labs.arxiv.org/html/2310.08597)
- [ros2_control example 15](https://control.ros.org/jazzy/doc/ros2_control_demos/example_15/doc/userdoc.html)
- [ALOHA / ACT](https://arxiv.org/html/2304.13705), [ALOHA 하드웨어 README](https://github.com/tonyzhaozh/aloha)
- [LeRobot bi_so_follower](https://github.com/huggingface/lerobot/blob/main/src/lerobot/robots/bi_so_follower/config_bi_so_follower.py)
- [Bi-JCR 양팔 캘리브레이션](https://arxiv.org/abs/2505.24819)
- [π0](https://arxiv.org/html/2410.24164), [RDT-1B](https://arxiv.org/html/2410.07864), [GR00T N1](https://arxiv.org/html/2503.14734)
