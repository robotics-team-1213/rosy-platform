## D-442 Motion Intent와 DeviceControlPort: 장치마다 제어 포트 하나, Arbiter와 Safety Guard 뒤에

**Status:** Accepted (2026-10-04, 사용자 수용; D-429 후속 1·D-399 후속 5). 이번 변경은 문서뿐이다. 코드·contracts 패키지·매니페스트·wire·실기 gate 변화는 없다. 독립 리뷰(REVISE) 뒤 사용자 결정 3건(U1 자율 출처는 활성 MANUAL을 빼앗지 못함, U2 publish를 옮기지 않는 얇은 래퍼, U3 OMX Arbiter 전용 `preempt`)과 나머지 질문의 리뷰 권고 수용을 2026-10-04 반영했다(Validation). 이행(§4)의 각 단계는 별도 변경이며, safety 태그 코드를 건드리는 단계는 D-430 §5의 독립 리뷰와 `Safety-Review:` trailer를 받는다.

> 번호 메모: 요청 번호는 D-439였다. 그러나 D-439(task-oriented web app design, `feat/hmi-task-layout`), D-440(per-device power policy), D-441(site stack automatic update)이 이미 다른 브랜치에서 쓰였다. 그래서 D-442를 쓴다.

### Context

D-429 §4는 로봇 제어 포트의 모양을 원칙으로만 정했다. Motion Intent는 스킬·MANUAL이 내는 의도이고, DeviceControlPort는 단일 writer가 장치 출력에 쓰는 포트다. 장치마다 binding은 하나이고 그 writer만 쥔다. Pinky binding은 `ros_bridge.py`의 `cmd_vel` publisher, OMX binding은 `ActionPort`다. D-430 §3 불변식 3은 모든 binding이 그 장치의 Arbiter와 Safety Guard 뒤에 있다고 정하고, wave 0 시험으로 구조와 행동을 나눠 검사한다. D-399 후속 5는 Motion Intent 공통 스키마, 장치별 Arbiter 우선순위표, MANUAL의 phase 선점을 미뤄 두었다. D-427 §5는 실물 RL의 선행 조건 3(MANUAL 선점)과 4(OMX 리더 팔을 MANUAL 입력으로)를 이 빈칸에 걸어 두었다.

지금 코드(origin/main `0b277ae38` 기준)는 같은 개념을 장치마다 다른 모양으로 갖고 있다.

- **Pinky 중재.** 명령 후보는 `CommandManager`의 세 슬롯(수동·nav·도킹)에 들어간다(`src/runtime/services/core_features/command/manager.py:91,148,163`). `select_output`은 우선순위 정렬이 아니라 **현재 모드로 슬롯 하나를 고른다**(`manager.py:290-327`). 선점은 `ModeMachine`의 전이 표 `_ALLOWED`가 맡는다(`arbitration.py:44-51`). `Priority`·`DEFAULT_SOURCES`·`SourceRegistry`(`arbitration.py:17-33,61`)는 출처 등록과 거부에만 쓰인다. `FLEET` 우선순위는 있으나 `Mode`에는 FLEET이 없다. Fleet 주행은 Nav2를 거쳐 NAVIGATION으로 실행된다.
- **Pinky nav 슬롯은 여럿이 같이 쓴다.** Nav2(`src/runtime/gateway/core/bridge/observation.py:209-213`, 라인 추종이 켜져 있으면 버림), 라인 추종(`core/bridge/traffic_gate.py:42`), 지역화 미션(`core_features/localization/mission.py:274-276`)이 모두 `set_nav_twist`를 부른다. swarm은 NAVIGATION 동급으로 등록된다(`arbitration.py:31`). 도킹은 `set_docking_twist`(`core/bridge/docking_executor.py:59`), 수동은 `teleop`(`src/runtime/api_web/core_api_web/api/v1/control.py:51`)이다.
- **Pinky 출력.** `cmd_vel_cycle`(`core/bridge/cmd_vel.py:43-70`)이 고르고, 준비 전이면 0으로 누르고, `_send_twist`(`core/bridge/ros_bridge.py:439-452`)가 `cmd_vel_pub`(`ros_bridge.py:86`)으로 50 Hz 발행하고, **발행 뒤에** D-422 `observation.wheels_sent`(`ros_bridge.py:447-452`)로 바퀴에 나간 값을 라인 추종 근접 기억에 넘긴다. 만료 규칙은 수동 500 ms watchdog(SAF-002, `manager.py:43`)과 nav·도킹 슬롯 0.5 s(`manager.py:58`)다.
- **Pinky 주행 목표는 지금 MANUAL을 빼앗는다.** `_ALLOWED[MANUAL]`에 NAVIGATION이 있다(`arbitration.py:46`). 주행 목표 처리기 `navigation_goal`(`core_api_web/api/v1/navigation.py:35-44`)은 `enter_navigation_mode`(`api/v1/common.py:107-122`)를 부르고, 이 함수는 살아 있는 teleop 세션을 보지 않고 MANUAL→NAVIGATION으로 바꾼다. 같은 함수가 return-home·swarm follow·라인 추종 진입에도 쓰이고, `correlation_id`가 붙은 Fleet 목표(D-316)도 같은 길이다.
- **OMX.** `ArmCommandOwner.submit(TrajectoryCommand)`(`src/products/omx/adapter/omx_adapter/command_owner.py:458-555`)이 owner 허용 목록, 세션, 보정 revision, 관절 상태 신선도·순번, 시작 자세 허용치, 관절·속도·가속 상한, 시간 상한을 모두 확인한 뒤 `ActionPort.send_goal`(`command_owner.py:290-291`, ROS 구현은 `ros_runtime.py:301`의 FollowJointTrajectory 클라이언트)을 부른다. 우선순위는 없다. 동작 중 새 명령은 `busy`로 거부된다(`command_owner.py:472`). 취소는 항상 HOLD 래치로 간다(`command_owner.py:602-611`). 해제는 `recover(operator_confirmed=..., observed_sequence=...)`(`command_owner.py:613`)다. 그리퍼는 별도 포트가 아니라 같은 궤적의 그리퍼 관절이다(`pilot_sim_runtime.py:255-275,321`).
- **OMX 명령 출처 이름.** `KNOWN_OWNERS = {leader_teleop, moveit, rule_based, learned_policy, pilot_sim}`(`command_owner.py:22`). 운영 셀은 `pilot_sim`·`rule_based`만 허용한다(`apps/agent/src/rosy_agent/omx_cell_owner.py:42`). `leader_teleop`는 이름만 있고 켠 프로필이 없다.
- **D-430 wave 0 시험은 main에 있다.** 구조 시험 `test_cmd_vel_publisher_is_single_and_only_send_twist_touches_it`(`test/architecture/test_safety_separation.py:361`)이 `cmd_vel` publisher가 하나이고 `send_goal` 호출자가 `ArmCommandOwner` 하나임을 본다(`:371-372`). 행동 시험 `test_estop_zeroes_every_source_and_clip_applies`(`src/runtime/services/test/test_safety_behaviour.py:73`)와 `test_every_registered_source_is_covered`(`:52`)도 있다.
- **contracts.** ROS 무의존 계약 패키지는 `contracts/skill`(`rosy.contracts.skill`: `SkillInvocation`, `AttemptIdentity`, `ReceiptBinding`)이 첫 예다. `rosy.skills.api`의 `SkillContract`(`modules/skills/api/src/rosy/skills/api/contracts.py:25`)는 스킬의 선행·완료 조건과 취소 계약을 정하지만 움직임의 모양은 정하지 않는다. Device Action 스키마(`src/contracts/foundation/core_common/protocol/schemas.py`의 `FleetActionGrant:234`, `DeviceActionReceipt:376`, `LocalStopRequest:455`)는 semantic 행동과 시도 식별(`attempt_id`)까지이고 움직임 명령은 없다.

외부 근거(설계 방향의 맥락이며 준수 주장이 아니다):

- ros2_control은 controller와 hardware interface를 나눈다. hardware component가 state·command interface를 내놓고, controller manager가 controller에 interface 접근을 허가하며 접근 충돌이면 오류를 낸다(https://control.ros.org/jazzy/doc/getting_started/getting_started.html, 2026-10-04 조회). "command interface 하나는 controller 하나만 쥔다"는 문장 자체는 그 페이지에서 찾지 못했다. *(배타 규칙의 정확한 문구는 미확인)*
- LeRobot의 `Robot` 기반 클래스는 `action_features`, `send_action(action) -> action`, `get_observation`, `connect`/`disconnect`를 계약으로 둔다. 문서는 `send_action` 안에서 clip·smoothing 같은 안전 한도를 더하고 실제로 보낸 값을 돌려주라고 적는다(https://huggingface.co/docs/lerobot/integrate_hardware, 2026-10-04 조회).
- Gemini Robotics-ER는 사용자가 정의한 로봇 함수를 부르는 오케스트레이터이고, 안전 책임은 통합자에 있다(https://ai.google.dev/gemini-api/docs/robotics-overview, D-429·D-430과 같은 출처). *(이번에 다시 대조하지 않았다)*

세 근거는 같은 방향이다. 하드웨어 쪽 쓰기 지점은 장치마다 좁은 인터페이스 하나이고, 그 위의 정책·모델은 그 인터페이스의 교체 가능한 클라이언트다. ROSY에서는 그 사이에 Arbiter와 Safety Guard가 반드시 있다(D-430 불변식 3).

### Decision

#### 1. Motion Intent — "어떤 움직임을 요청하는가"의 계약

**자리.** 새 ROS 무의존 계약 패키지 `contracts/motion`(import `rosy.contracts.motion`)에 둔다. `contracts/skill` 옆이다. part는 contracts, concern은 contracts다(`tools/harness/platform_parts.yaml`의 기존 contracts root와 같다). ROS 메시지 타입·`rclpy`·벤더 SDK를 import하지 않는다. 시도 식별은 `rosy.contracts.skill`의 `AttemptIdentity`를 그대로 쓴다.

**두 단계.** Motion Intent는 **목표형**(goal)과 **서보형**(servo)으로 나눈다. 목표형은 Motion Executor(Nav2, 라인 추종, 해석 IK, MoveIt)가 받아 서보형으로 바꾼다. DeviceControlPort(§2)는 서보형만 받는다. 이렇게 나눠야 "Nav2 목표"와 "Nav2가 낸 Twist"가 같은 출처와 같은 시도 식별을 지니면서도, Arbiter가 출력 주기 단계에서 판단할 수 있다.

| kind | 단계 | 내용 | 단위 | frame | 지금 대응 |
|---|---|---|---|---|---|
| `base.twist` | servo | 선속도 `linear_mps`, 각속도 `angular_radps` | m/s, rad/s | `base_link`(REP-103: x 전방, z 위) | `CommandManager.Twist`(`manager.py:23`) |
| `base.pose_goal` | goal | 목표 `x, y, yaw`와 허용치 | m, rad | `map` | `NavGoalSpec` → `ros_bridge.py:723` `send_goal` |
| `base.path_follow` | goal | 경로 참조(차선·경로 id, 방향) | — | `map`(경로 정의 frame) | 라인 추종·차선 주행(D-407) |
| `arm.joint_trajectory` | servo | 관절 이름과 점들(위치, 선택 속도·가속, 시간) | rad, rad/s, rad/s², s | 관절 공간 | `TrajectoryCommand`(`command_owner.py:182`) |
| `arm.tcp_pose` | goal | TCP 목표 자세(위치 + 방향), 접근 방향 | m, rad(쿼터니언 허용) | 팔 루트 링크(URDF 명목, 보정이 다듬음) | D-402 해석 IK, `pose_plan.py`의 `CellTransferRequest` |
| `arm.gripper` | servo | 그리퍼 관절 목표 위치(선택: `open`/`close` semantic) | rad | 그리퍼 관절 | 같은 궤적의 그리퍼 관절(`pilot_sim_runtime.py:255`) |

`arm.gripper`는 OMX binding에서 `arm.joint_trajectory`의 그리퍼 관절로 합쳐진다. 그리퍼만 따로 쓰는 경로를 만들지 않는다.

**모든 kind의 공통 머리.**

| 필드 | 뜻 | 규칙 |
|---|---|---|
| `intent_id` | 의도 하나의 식별 | 비어 있지 않음. 같은 id 재사용은 거부(지금 OMX `command_id_reused`, `command_owner.py:470`) |
| `device_id` | 대상 장치 instance | 장치 등록 identity와 같아야 한다(D-399 §4) |
| `source` | 등록된 출처 이름 | `SourceRegistry`(Pinky)·`KNOWN_OWNERS`(OMX)에 있어야 한다 |
| `priority_class` | 출처의 우선순위 등급 | **생산자가 정하지 않는다.** Arbiter가 `source`로 등록표에서 찾는다. 필드는 감사 기록용이며, 등록표와 다르면 거부한다 |
| `attempt` | 시도 식별 | Fleet이 하달한 일이면 `AttemptIdentity`와 `attempt_id`(D-316). 사람·지역 입력이면 없음. `correlation_id`는 D-170대로 계약 필드이며, 있으면 그대로 싣는다 |
| `envelope_ref` | 반응형 정책 엔벌로프 참조(D-399 후속 1) | `source`가 POLICY 등급이면 **필수.** 엔벌로프 계약이 착지하기 전에는 POLICY 의도를 모두 거부한다 |
| `issued_at`, `valid_for_s` | 발행 시각(장치 단조 시계)과 유효 기간 | 유효 기간이 지나면 stale. 상한은 kind·출처별 설정값(아래) |
| `state_sequence` | 의도를 만든 근거 관절 상태 순번 | arm kind 필수(지금 `source_state_sequence`, `command_owner.py:190`) |
| `calibration_revision` | 의도가 가정한 보정 revision | arm kind 필수(`command_owner.py:191`) |
| `limits` | 생산자가 원하는 상한 | **조이기만 한다.** 장치 상한보다 크면 장치 상한이 이긴다. 상한을 올리는 필드는 없다 |

**staleness와 정지 의미.** 지금 동작을 그대로 옮긴다.

| kind | 기본 `valid_for_s` | 만료 | 취소 |
|---|---|---|---|
| `base.twist` MANUAL | `safety.teleop_timeout_ms`(기본 0.5 s, SAF-002) | 0 출력, **래치 없음**. 만료 알림은 세션당 1회 | 슬롯 비움 → 0 |
| `base.twist` 그 밖 | 0.5 s(`_nav_timeout_s`) | 0 출력, 래치 없음 | 슬롯 비움 → 0 |
| `base.pose_goal`, `base.path_follow` | 목표 deadline(Executor 설정) | Executor가 실패로 끝내고 서보 출력을 멈춤 | 목표 취소(D-40 취소 수명주기, D-316 결과 상관) |
| `arm.joint_trajectory`, `arm.gripper`(SKILL·POLICY·Pilot 조그) | 지금은 의도별 값이 아니라 고정 `action_timeout_s` 2.0 s(`command_owner.py:59`)이고, 목표 길이 상한은 `max_goal_duration_s` 1.0 s(`:58`)다. 의도별 `valid_for_s`는 §4(c)에서 이 고정값을 상한으로 도입한다 | **owner HOLD 래치**(`action_timeout`) | 정확한 goal UUID로 취소 → owner HOLD 래치(D-376 §6). 결과가 불명이면 재발행하지 않음(D-369 §3) |
| `arm.joint_trajectory` MANUAL 스트림(리더 팔, 미래) | 스트림 주기 기반, §4(c)에서 정함 | **래치 없는 멈춤**(질문 5 결정). 이미 보낸 짧은 구간은 끝까지 가서 만료되게 두고, 새 구간이 없으면 그 자리에 선다. 바로 위 행의 owner HOLD 래치 규칙에 대한 예외다 | 스트림 중단 |
| `arm.tcp_pose` | Executor deadline | 계획 실패는 거부. 실행 중 만료는 서보형과 같음 | 서보형과 같음 |

정지 요청(E-stop, `StopLocal`)은 Motion Intent가 아니다. 정지는 safety의 공개 진입점으로만 간다(D-430 §3). Motion Intent에 "0 속도"는 있어도 "정지 해제"는 없다.

**HOLD라는 말의 세 뜻.** 이 ADR은 다음처럼 나눠 쓴다.

- **준비 HOLD**(readiness HOLD): Pinky 하드웨어 그래프가 준비되지 않은 동안 `cmd_vel_cycle`이 0을 내는 것(`cmd_vel.py:65-66`). 래치가 아니며 조건이 풀리면 스스로 풀린다(D-430 §4).
- **owner HOLD 래치**: `ArmCommandOwner`의 `hold` 상태(`command_owner.py:420`). 새 `submit`을 모두 거부하고, 해제는 `recover`뿐이다(§3).
- **D-419 `HOLD` 정책**: Fleet 상실 시 고르는 정책 값의 하나(`core_features/safety/fleet_loss.py:29`). 물리적으로 STOP과 같고 래치가 없다.

이와 별개로 OMX **local stop 래치**(`LocalStopController`, `StopLocal`로 걸고 `RearmLocal`로 품)는 owner HOLD 래치와 다른 저장소의 다른 래치다(§3).

**Motion Intent에 절대 들어가지 않는 것.**

1. raw 장치 값: Dynamixel 레지스터·tick, PWM, 모터 전류, 시리얼 바이트, 코일·레지스터 주소(D-429 §4 "semantic 명령만", D-430 불변식 5).
2. ROS 이름과 타입: 토픽·액션 이름, `geometry_msgs`·`control_msgs` 타입. ROS는 binding 안에만 있다.
3. 엔벌로프를 거치지 않은 모델 출력. 숙고형 모델(ER2·VLM)은 Motion Intent를 만들지 않는다(D-399 §2, D-326 §2, D-392 §4). 반응형 정책 출력은 `envelope_ref`가 있는 POLICY 의도로만 들어온다.
4. 안전 우회 필드: E-stop 무시, 상한 올리기, watchdog 끄기, HOLD 해제. 해제·rearm은 safety 공개 진입점의 일이다.
5. 생산자가 스스로 정한 우선순위.

**기존 생산자 대응.** 이 표는 §4(a)의 대응 시험 목록이기도 하다. 대응은 값과 슬롯을 바꾸지 않는다.

| 생산자 | 지금 호출 | Motion Intent | source → 등급 |
|---|---|---|---|
| Pilot·대시보드 teleop | `api/v1/control.py:51` → `CommandManager.teleop` | `base.twist` | `manual` → MANUAL |
| Nav2 | `nav_cmd_vel` → `observation.py:213` → `set_nav_twist` | 목표는 `base.pose_goal`, 출력은 `base.twist` | `navigation` → NAVIGATION |
| 라인 추종 | `traffic_gate.py:42` → `set_nav_twist` | 목표는 `base.path_follow`, 출력은 `base.twist` | 지금 `navigation` 슬롯 공유. 출처를 `line_follow`로 나눌지는 질문 3 → NAVIGATION |
| 지역화 미션 | `localization/mission.py:274-276` | `base.twist` | `navigation` → NAVIGATION |
| 도킹 | `docking_executor.py:59` | `base.twist` | `docking` → DOCKING |
| swarm | `arbitration.py:31` 등록 | `base.pose_goal`, `base.twist` | `swarm` → NAVIGATION |
| Fleet Action | Device Action(`FleetActionGrant`) → 장치 Action Gateway | **Fleet은 Motion Intent를 내지 않는다.** 장치 Action Gateway가 semantic Action을 목표형 의도로 바꾸고 `attempt`를 싣는다 | 실행 스킬의 출처(예: `navigation`, `rule_based`) |
| OMX Pilot 연습 | `pilot_sim_runtime.py:321` → `ArmCommandOwner.submit` | `arm.joint_trajectory`(그리퍼 포함) | `pilot_sim` → MANUAL |
| OMX 셀 규칙 실행 | `omx_cell_owner.py`(`rule_based`) | 목표는 `arm.tcp_pose`, 출력은 `arm.joint_trajectory` | `rule_based` → SKILL |
| OMX MoveIt(미래) | — | 같음 | `moveit` → SKILL |
| 리더 팔(미래) | — | `arm.joint_trajectory` 스트림 | `leader_teleop` → MANUAL |
| 반응형 정책(미래) | — | `base.twist` 또는 `arm.joint_trajectory` + `envelope_ref` | `learned_policy` → POLICY |

#### 2. DeviceControlPort — 파이프라인과 제어 backend 사이의 포트

**자리.** 포트 Protocol과 결과 타입은 `rosy.contracts.motion`에 둔다. binding 구현은 장치 middleware 안, writer 옆에 둔다(Pinky는 `src/runtime/gateway/core/bridge/`, OMX는 `omx_adapter`). 다른 backend 어댑터는 D-429 §4대로 `integrations/robots/<model>`의 포트 구현이다.

**연산(최소).**

```text
capabilities() -> PortCapabilities        # 받는 kind, 관절 이름, frame, 장치 상한, 스트림/목표 여부
submit(cmd: GuardedMotion) -> PortDecision   # accepted, state, reason, intent_id
cancel(intent_id) -> PortDecision
state() -> PortState                      # disabled | ready | active | hold, 활성 intent_id, 최신 readback 순번
estop_status() -> EstopStatus             # 소프트웨어 래치 상태(읽기). 물리 E-stop은 장치가 알려 줄 때만, 아니면 unknown
```

- `submit`은 Motion Intent를 직접 받지 않는다. Safety Guard가 만드는 **`GuardedMotion`**(서보형 의도 + Arbiter 판정 + Safety Guard의 clip 결과와 guard revision)을 받는다. AST 검사만으로는 생성 위치를 묶지 못한다. 별칭 import, `dataclasses.replace`, `copy`, `__new__`, `type(x)(...)`, Protocol 덕 타이핑으로 우회된다. 그래서 세 겹으로 둔다.
  1. **생성 심볼 허용 목록.** `GuardedMotion`을 만드는 곳은 `core.bridge.cmd_vel.cmd_vel_cycle`과 `omx_adapter.command_owner.ArmCommandOwner.submit` 두 심볼뿐이다. "safety 태그 파일 전체"가 아니다. 그 목록은 지금 17개이고 Fleet `console.py`까지 들어 있다(`platform_parts.yaml:542-559`).
  2. **런타임 검사.** binding은 `type(cmd) is GuardedMotion`인지, safety 모듈의 비공개 토큰을 지녔는지, 해당 binding의 Arbiter·Safety Guard가 발급하고 보관한 원본 객체와 `is`로 동일한지 확인하고 아니면 거부한다. 토큰은 위 두 심볼의 모듈만 쥔다. 타입과 토큰만으로는 `copy`·`replace` 사본을 구별하지 못하므로 원본 identity 검사도 필수다. 발급·보관·만료의 구체적 구현과 사본 거부 행동 시험을 §4(b)의 선행 조건으로 둔다. 이 보호는 현재 구현됐다는 주장이 아니다.
  3. **행동 시험.** 같은 필드의 다른 클래스, `replace`·`copy`로 만든 사본, 토큰 없는 인스턴스를 binding이 거부한다(아래 d).
- **Arbiter 판정을 싣는 비용.** 지금 `cmd_vel_cycle`은 `select_output()`이 주는 `Twist` 하나만 받는다(`cmd_vel.py:43-57`). 판정과 guard revision을 실으려면 `CommandManager.select_output`의 반환형을 바꿔야 하고, 그것은 safety 파일 변경이다(trailer, §4(c)). `GuardedMotion` 생성이 예외를 내면 지금 `select_output` 예외와 같이 **0을 보내고 경고한다**(`cmd_vel.py:56-64`의 규칙). 그러지 않으면 50 Hz 발행이 멈추고 바퀴가 마지막 값을 쥔다. 생성 실패 주입 시험을 같이 둔다(아래 d).
- 포트에는 `release`·`rearm`·상한 변경이 **없다.** 그것은 safety 공개 진입점(D-430 §3: `SafetyManager.release`, `ModeMachine.release_emergency`, `LocalStopApi`의 `RearmLocal`)의 일이다. `estop_status`는 읽기 전용이다.
- `PortDecision`의 모양은 OMX `CommandDecision`(`command_owner.py:295-300`)을 따른다. 거부 사유 문자열을 그대로 남긴다.
- Pinky binding은 스트림이다. 50 Hz 주기마다 `submit`이 직전 값을 대체한다. 0 출력도 정상 `submit`이다(지금 `cmd_vel_cycle`이 0을 보내는 것과 같다, `cmd_vel.py:61,66`).

**불변식.**

1. **장치마다 binding은 정확히 하나다.** 장치 프로필이 binding 하나를 이름으로 고른다. 둘을 고르거나 없으면 기동하지 않는다.
2. **binding은 writer만 쥔다.** Pinky: 사용자 결정 U2에 따라 binding은 `cmd_vel_cycle`이 넘겨받는 `send`(= `self._send_twist`)를 감싸는 얇은 래퍼이고, 부르는 곳은 `cmd_vel_cycle` 하나다. publish와 그 뒤의 D-422 `wheels_sent` 호출은 `_send_twist` 안에 그 순서대로 남는다. OMX: binding(`ActionPort`)은 `ArmCommandOwner`가 생성자로 받아 쥐고(`command_owner.py:306-322`), 부르는 곳은 `submit` 하나다(`command_owner.py:547`).
3. **모든 호출 경로는 Arbiter, 그다음 Safety Guard를 지난다.** Pinky: 출처 → `CommandManager`(모드 선택 = Arbiter) → `SafetyManager.clip`과 D-400 정책(`_policy_output`) → `cmd_vel_cycle`의 준비 HOLD → binding. OMX: 출처 → §3의 OMX Arbiter → `ArmCommandOwner.submit`의 HOLD 래치·상한 검사(Safety Guard) → binding. OMX는 Arbiter와 Safety Guard가 지금 한 클래스 안에 있다. 둘을 나누는 것은 §4(c) 이후의 선택이다.

**binding 이름.**

| 장치 | binding | backend | 받는 kind |
|---|---|---|---|
| Pinky | `PinkyTwistPort`(가칭). `GuardedMotion`을 확인·풀어 기존 `_send_twist`(publish + D-422 `wheels_sent`)를 부르는 얇은 래퍼. publish는 옮기지 않는다(사용자 결정 U2) | ROS 2 `/cmd_vel` `geometry_msgs/Twist` → Pinky 베이스 드라이버 | `base.twist` |
| OMX | `ActionPort`(이미 Protocol). ROS 구현은 `ros_runtime.py:301`의 FollowJointTrajectory 클라이언트 | ros2_control 궤적 controller(ROBOTIS 스택) | `arm.joint_trajectory`(그리퍼 관절 포함) |
| 미래 비-ROS | 벤더 SDK binding(예: LeRobot `Robot.send_action` 모양의 버스 쓰기), PLC 구동 축 binding(Modbus 등) | 벤더 SDK, PLC | 장치 `capabilities`가 선언한 서보 kind |

- **해석 IK(D-402)와 MoveIt은 binding이 아니다.** 둘은 `arm.tcp_pose`를 `arm.joint_trajectory`로 바꾸는 Motion Executor(플래너)이고 포트 **위**에 있다. 같은 binding 위에서 플래너를 바꿔 끼울 수 있다(D-399 후속 3 보강과 같다).
- **PLC 구동 축과 사이트 장치를 구분한다.** 연속 움직임을 Arbiter 아래에서 받는 축(예: 리니어 스테이지)은 로봇 장치이고 이 포트를 쓴다. 이산 semantic 명령(컨베이어 시작·정지·속도 등급, 문 열기)은 `rosy.site-device/1`(D-429 후속 2)이다. 어느 쪽이든 안전 영역 주소에는 쓰지 않는다(D-430 불변식 5).
- **LeRobot 네이티브 모드는 binding이 아니다.** D-299 §2의 개발·녹화 모드는 LeRobot이 버스를 단독 소유하는 별도 모드이고, 그동안 운영 owner와 binding은 정지한다(D-399 §2).

**D-430 불변식 3을 어떻게 확인하나.**

- (a) **기존 구조 시험 유지.** 사용자 결정 U2(publish를 옮기지 않음)에 따라 다음 셋이 기대값 그대로다.
  - `test_cmd_vel_publisher_is_single_and_only_send_twist_touches_it`(`test_safety_separation.py:361`). `:370`이 publisher 경로를 `ros_bridge.py`로, `cmd_vel_pub` 사용 함수를 `__init__`·`_send_twist`로 고정한다. `send_goal` 호출 클래스는 `ArmCommandOwner` 하나다.
  - `test_the_bridge_actually_calls_the_cycle`(`src/runtime/gateway/test/test_cmd_vel_cycle.py:136-155`). 브리지의 `cmd_vel_cycle` 호출 인자에 `self._send_twist`를 고정한다. 그래서 U2는 이 호출을 그대로 두고, 래퍼를 `cmd_vel.py` 안에서 `send`를 감싸는 자리에 둔다.
  - `test_the_bridge_still_owns_the_only_cmd_vel_publisher`(`test_cmd_vel_cycle.py:159-164`). `self.cmd_vel_pub.publish(` 정확히 1회와 `_send_twist` 서명을 고정한다.
  - publish를 다른 모듈로 옮기는 안(U2의 대안)을 고르면 이 셋의 기대값이 바뀐다. 그 변경은 행동 변경과 같은 무게로 trailer와 독립 리뷰를 받는다.
  - **허점.** 구조 시험은 속성 이름 `cmd_vel_pub`으로 찾는다. 포트가 `self._pub` 같은 다른 이름으로 같은 publisher를 쥐고 발행하면 시험은 공허하게 통과한다. 그래서 (c)에 이름과 무관한 시험을 더한다.
- (b) **기존 행동 시험 유지.** `test_estop_zeroes_every_source_and_clip_applies`(`test_safety_behaviour.py:73`), `test_every_registered_source_is_covered`(`:52`), `src/runtime/gateway/test/test_cmd_vel_cycle.py`의 순서·HOLD 시험, OMX `test_omx_command_owner.py`·`test_omx_stop_fence.py`.
- (c) **새 구조 시험**(§4 각 단계와 함께, 이름은 제안):
  - `test_guarded_motion_is_built_only_by_allowed_symbols`: `GuardedMotion` 생성(직접 호출, 별칭, `replace`·`copy` 포함)이 허용 심볼 두 개(`cmd_vel_cycle`, `ArmCommandOwner.submit`) 안에서만 일어남. AST 검사는 첫 그물이고, 실제 경계는 binding의 런타임 토큰과 발급 원본 identity 검사다.
  - `test_no_other_attribute_publishes_cmd_vel`: 운영 소스에서 `"cmd_vel"` 토픽(또는 기본값이 `"cmd_vel"`인 파라미터)으로 만든 publisher 객체를 **속성 이름과 무관하게** 따라가, 그 객체의 `.publish(` 호출이 `_send_twist` 한 곳뿐임을 단정한다. 다른 이름의 속성(예: `self._pub`)이 같은 publisher로 발행하면 실패한다.
  - `test_each_device_profile_selects_exactly_one_binding`: 프로필마다 binding 하나.
  - `test_port_bindings_are_constructed_only_by_their_writer`: binding 클래스 생성 위치가 writer 모듈뿐(`test/`·`src/runtime/sensing/tools/gz/`는 D-430과 같은 경로 목록으로 제외).
- (d) **새 행동 시험.** OMX가 owner HOLD 래치이면 어떤 출처의 `submit`도 binding에 닿지 않는다. 가짜 `GuardedMotion`(다른 클래스, 사본, 토큰 없음)은 binding이 거부한다. `GuardedMotion` 생성에 예외를 주입하면 그 주기에 0이 바퀴로 나가고 다음 주기도 발행이 이어진다. POLICY 의도는 `envelope_ref` 없이 거부된다(§4(c) 뒤). 만료된 의도는 binding에 0(베이스) 또는 owner HOLD 래치(팔)로만 나타난다.
- **리뷰 전용(기계 검사 아님).** launch remap·파라미터로 다른 노드 출력을 `cmd_vel`이나 궤적 controller로 돌리는 변경(D-430 불변식 3의 리뷰 규칙과 같다), binding이 벤더 SDK로 두 번째 버스 연결을 여는 것, binding 안의 숨은 재시도, 물리 E-stop 배선.

#### 3. Arbiter 우선순위표와 MANUAL 선점 (D-399 후속 5)

**공통 원칙.**

- 정지 계열(EMERGENCY, SAFETY)은 어느 장치에서든 모든 동작 출처보다 위다(D-399 §1).
- 우선순위 등급은 등록표가 정한다. 의도가 스스로 고르지 않는다(§1).
- MANUAL은 모든 자율 출처(DOCKING, NAVIGATION, SKILL, POLICY)를 선점한다. 자율 출처는 MANUAL을 선점하지 못한다. 이것은 **목표 원칙**이다.
  - **알려진 예외(지금 동작).** Pinky에서는 주행 목표가 MANUAL을 빼앗는다. `_ALLOWED[MANUAL]`에 NAVIGATION이 있고(`arbitration.py:46`), `enter_navigation_mode`(`api/v1/common.py:107-122`)는 살아 있는 teleop 세션(`CommandManager.manual_active`, `manager.py:139`)을 보지 않고 MANUAL→NAVIGATION으로 바꾼다. 운영자 API 주행 목표(`navigation.py:35-44`), return-home, swarm follow, 라인 추종 진입, `correlation_id`가 붙은 Fleet 목표가 모두 이 길이다.
  - **고침은 §4(c)의 행동 변경이다(사용자 결정 U1, 2026-10-04).** `manual_active`인 동안 주행 목표(`correlation_id`가 붙은 Fleet 목표 포함)는 `409`(예: `MANUAL_ACTIVE`)로 거부한다. sim 증거, `Safety-Review:` trailer, 독립 리뷰가 필요하다. 착지 전까지 지금의 탈취는 알려진 예외로 남는다. watchdog이 만료되어 세션이 끝난 MANUAL 모드에서는 지금처럼 NAVIGATION으로 넘어갈 수 있다.
- 선점된 자율 작업은 **자동으로 재개하지 않는다.** MANUAL이 끝나면 IDLE로 간다. 다시 하려면 새 명령(Fleet이면 새 `attempt_id`)이 필요하다(D-38 "새 요청 요구", D-419 §3과 같은 방향).
- POLICY는 Fleet이 승인해 하달한 Task 안의 스킬로만 돈다(D-399 §2). 그래서 POLICY는 같은 장치의 다른 스킬과 동시에 돌지 않는다.

**Pinky (지금 동작을 적는다. 등급 하나를 예약하고, MANUAL 보호 하나를 §4(c)에서 고친다).**

| 등급 | 출처 | 방식 |
|---|---|---|
| EMERGENCY (1) | E-stop 래치, `ModeMachine` EMERGENCY | 모든 출력 0. 해제는 `release_emergency`만 |
| SAFETY (2) | `SafetyManager`, D-400 정책, 준비 HOLD | 0 또는 clip |
| MANUAL (3) | `manual`(Pilot·대시보드) | 모드 MANUAL. `_ALLOWED`상 NAVIGATION·DOCKING에서 진입 가능. **지금은 주행 목표가 MANUAL을 NAVIGATION으로 되빼앗을 수 있다**(위 알려진 예외. 사용자 결정 U1로 §4(c)에서 고친다) |
| DOCKING (4) | `docking` | 모드 DOCKING |
| NAVIGATION (5) | `navigation`(Nav2·라인 추종·지역화), `swarm` | 모드 NAVIGATION. 그 안에서는 라인 추종이 켜져 있으면 Nav2 출력을 버린다(`observation.py:209-213`) |
| POLICY (예약) | `learned_policy` | 이 ADR은 **자리만** 예약한다. Pinky 주행 정책은 D-427 §5 순서상 마지막이다. 위치는 질문 4 |
| FLEET (6) | `fleet` | 등록만 있고 모드가 없다. Fleet 목표는 NAVIGATION으로 실행 |
| IDLE (7) | — | 0 |

Pinky Arbiter는 "우선순위 정렬"이 아니라 "모드 + 전이 표"다(`manager.py:290-327`, `arbitration.py:44-51`). 이 ADR은 그 방식을 바꾸지 않는다. 위 표는 그 동작을 등급 이름으로 적은 것이다. 예외는 MANUAL 보호(사용자 결정 U1) 하나이며, 그것은 §4(c)의 행동 변경으로만 들어온다.

**OMX (새로 정한다).**

| 등급 | 출처 | 지금 코드 | 규칙 |
|---|---|---|---|
| EMERGENCY (1) | `StopLocal`(`LocalStopApi`), 물리 E-stop 읽기 | `local_stop.py:123`, `action_api.py:206` | local stop 래치를 걸고 활성 goal 취소를 시도한다(`local_stop.py:123-165`). 해제는 `RearmLocal` → `LocalStopController.rearm`(`action_api.py:228`, `local_stop.py:177`)이며, 운영자 확인, 미해결 로컬 Action 0건, 최신 Fleet 세대가 필요하다 |
| SAFETY (2) | owner HOLD 래치: 관절 상태 stale, 시계 역행, action 시간 초과, 제출 실패, 취소 실패 | `command_owner.py:420,557-600` | owner HOLD 래치. 해제 API는 `recover(operator_confirmed=True, observed_sequence=...)`(`:613`)뿐인데 **운영 호출자가 0개다**(시험만 부른다). `RearmLocal`은 이 래치를 풀지 않는다 |
| MANUAL (3) | `leader_teleop`(리더 팔), `pilot_sim`(Pilot 조그·그리퍼) | `pilot_sim`만 동작. `leader_teleop`는 이름만 | 아래 선점 절차 |
| SKILL (4) | `rule_based`, `moveit` | `rule_based`만 동작 | Fleet이 하달한 Device Action의 phase(D-376 §4) |
| POLICY (5) | `learned_policy` | 없음 | `envelope_ref` 필수(D-399 후속 1 전에는 거부). 엔벌로프 이탈·시간 초과는 HOLD(D-399 §2), RL이면 `terminated=True`(D-427 §5) |
| IDLE (6) | — | — | 움직임 없음 |

**D-430과의 차이 정리.** D-430 §4의 "래치된 정지" 목록은 "OMX owner HOLD 래치(`RearmLocal`)"로 적었다. 코드에는 래치가 둘이다. (1) **local stop 래치**: `LocalStopController`의 SQLite 상태다. `StopLocal`로 걸고 `RearmLocal`로 푼다. (2) **owner HOLD 래치**: `ArmCommandOwner`의 `hold` 상태다. 내부 이상과 취소로 걸리고 `recover`로만 풀린다. `LocalStopController.rearm`은 owner를 받지도 만지지도 않는다(`local_stop.py:177-225`). 이 ADR은 두 래치를 나눠 부르고, owner HOLD 래치의 정본 해제를 `recover`로 본다. `recover`의 운영 호출 경로(누가, 어떤 확인으로)를 만드는 일은 §4(c) 범위다. D-430 본문 정정은 이 ADR 범위 밖이며 후속 6에 적는다.

SKILL과 POLICY는 같은 칸에서 다투지 않는다. 한 장치의 활성 Action은 하나이고(지금 `busy` 거부, `command_owner.py:472`), 그 Action이 어떤 스킬로 도는지는 Fleet 승인 때 정해진다. POLICY를 SKILL 아래에 둔 이유는, 같은 Action 안에서 규칙 감시가 정책 phase를 끊을 수 있게 하려는 것이다.

**MANUAL 선점 절차 (OMX).**

1. **요청.** 운영자가 MANUAL 진입을 요청한다(Pilot 좌석 또는 리더 팔 활성 스위치). 요청 자체가 감사 이벤트다(actor, 시각, 장치, 당시 활성 Action).
2. **새 phase 차단.** Arbiter가 SKILL·POLICY의 새 phase 제출을 먼저 닫는다.
3. **활성 phase 취소.** 활성 ROS goal을 **정확한 UUID**로 취소한다(D-376 §6). 지금 `cancel`은 항상 HOLD로 간다(`command_owner.py:602-611`). 이 ADR은 그 동작을 유지한다. 즉 MANUAL 선점은 HOLD를 거쳐 일어난다. 부모 Device Action은 `UNKNOWN/HOLD`로 남고 Fleet이 그것을 본다. 재제출하지 않는다(D-376 §4, D-369 §3).
4. **HOLD 해제.** 운영자 확인과 새 관절 상태로 `recover`한다. 확인 없이 MANUAL로 넘어가지 않는다.
5. **정렬.** 리더 팔 입력은 팔로워 현재 자세와 허용치 안에서만 스트림을 시작한다. 지금의 `expected_start_state_positions`·`start_state_tolerances`와 `max_start_state_tolerances`(`command_owner.py:200-201,503-515`)를 쓴다. 정렬이 안 되면 거부하고 운영자에게 리더 팔을 맞추라고 알린다. 점프를 만들지 않는다.
6. **MANUAL 중.** 리더 팔 스트림이 `valid_for_s`를 넘겨 끊기면 팔은 그 자리에서 멈춘다(래치 없음, 질문 5 결정). Safety Guard 상한(관절·속도·가속)은 MANUAL에도 그대로다.
7. **종료.** MANUAL 종료는 IDLE이다. 선점된 Action을 이어 하지 않는다. 다시 하려면 Fleet의 새 시도다.
8. **학습 중.** RL과 모방학습 녹화 중의 사람 개입도 같은 MANUAL 경로이고 Episode events에 기록한다(D-427 §5).

**지금 코드로는 이 절차가 돌지 않는다.** 다음은 모두 §4(c) 범위다.

- **선점 진입점이 없다.** `cancel`은 활성 명령과 같은 owner만 부를 수 있다(`command_owner.py:607-608`). 그래서 `pilot_sim`이 `rule_based` phase를 취소하지 못한다. 사용자 결정 U3: owner와 무관한 Arbiter 전용 진입점 `preempt(reason)` 하나를 둔다. 결과는 항상 owner HOLD 래치이고, 정본 해제는 `recover`다. local stop 래치가 함께 걸렸다면 그것은 `RearmLocal`로 따로 푼다(§3 D-430 차이 정리).
- **`recover` 운영 호출자가 0개다.** 4단계를 하려면 운영자 확인과 새 관절 상태 순번을 받는 호출 경로(UDS 연산 또는 Pilot 좌석 API)가 필요하다.
- **리더 팔 스트림이 지금 owner 규칙과 맞지 않는다.** 활성 중 새 명령은 `busy`(`:472`)이고, 관절 상태 순번은 직전 명령보다 엄격히 커야 하며(`:498`), 목표 길이 상한은 `max_goal_duration_s` 1.0 s(`:58`)다. 30 Hz 안팎의 스트림은 셋에 모두 걸린다. 스트림용 수락 규칙(대체 허용, 순번 규칙, 짧은 점 상한)을 owner에 더해야 하며, 그것은 safety 파일 변경이다.

이 절차와 표는 D-427 §5 선행 조건 3(MANUAL 선점)의 **결정**을 채운다. 구현과 시험은 §4(c) 뒤에 온다. 선행 조건 4(리더 팔을 MANUAL로 여는 ADR)에 대해서는 이 ADR이 **중재 쪽**(등급, 선점, 정렬, 끊김)만 정한다. 리더 팔 하드웨어 읽기·보정·포트 식별(D-299 §4와 Validation)은 남는다(질문 6).

#### 4. 이행 — 행동을 바꾸지 않는 것부터

각 단계는 별도 브랜치·별도 커밋이다. safety 태그 경로(D-430 §1: `command/manager.py`, `command/arbitration.py`, `bridge/cmd_vel.py`, `command_owner.py`, `local_stop.py`, `action_api.py` 등)를 건드리는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5). 호스트 pytest 통과는 장치 수용이 아니다.

- **(a) 계약 타입과 대응 시험.** `contracts/motion`에 Motion Intent kind, 공통 머리, `GuardedMotion`, `PortDecision`·`PortState`·`EstopStatus`·`PortCapabilities`, `DeviceControlPort` Protocol을 둔다. §1 생산자 표의 각 행마다 "지금 값 → Motion Intent → 지금 값"이 같은지 보는 대응 시험을 둔다(`Twist` 두 값, `TrajectoryCommand` 전 필드). 운영 코드는 이 패키지를 아직 import하지 않는다. 매니페스트에 root를 더한다(part contracts, concern contracts). safety 태그 코드를 건드리지 않으므로 trailer는 필요 없다. 다만 정지 의미를 정하는 타입이므로 독립 리뷰는 받는다. 같은 단계에서 `test_no_production_config_allows_learned_policy`를 넣는다. `learned_policy`는 이미 `KNOWN_OWNERS`에 있어(`command_owner.py:22`) 설정 한 줄로 엔벌로프 없이 허용될 수 있다. POLICY 거부가 코드에 들어오는 것은 (c) 뒤이므로, 그 전까지 운영 설정의 `allowed_owners`(예: `omx_cell_owner.py:42`, `pose_plan.py:305`, `pilot_sim_server.py:63`)에 `learned_policy`가 없음을 시험으로 지킨다.
- **(b) 기존 writer를 binding으로 감싼다(행동 변화 없음).**
  - Pinky(사용자 결정 U2): **publish를 옮기지 않는다.** `_send_twist`(publish 뒤 D-422 `wheels_sent` 순서 포함)는 `ros_bridge.py`에 그대로 둔다. `PinkyTwistPort`는 `cmd_vel.py` 안에서 `cmd_vel_cycle`이 받은 `send`(= `self._send_twist`)를 감싸는 얇은 래퍼이고, `GuardedMotion`을 확인·풀어 `send(Twist)`를 부른다. 브리지의 `cmd_vel_cycle(self._svc.command, self._svc.power, self._send_twist, self._readiness)` 호출도 그대로다. safety 모듈(`cmd_vel.py`)은 브리지를 import하지 않는다. D-430 불변식 1의 로봇 쪽 edge 0건이 유지된다.
  - (b)를 "행동 변화 없음"으로 두려고, (b)의 `GuardedMotion`은 `Twist`와 guard revision만 싣는다. Arbiter 판정 필드는 (c)에서 `select_output` 반환형을 바꿀 때 채운다. `GuardedMotion` 생성 실패 시 0 출력 규칙(§2)은 (b)부터 적용한다.
  - OMX: `ActionPort`는 이미 포트 모양이다. `state`·`estop_status`·`capabilities`를 더하는 얇은 어댑터를 `ArmCommandOwner` 옆에 둔다. `send_goal` 호출자는 그대로 하나다.
  - 증명: §2 (a)의 세 구조 시험과 (b)의 행동 시험이 기대값 변경 없이 통과한다(`test_cmd_vel_cycle.py`, `test_safety_behaviour.py`, `test_safety_separation.py`, `test_omx_command_owner.py`, `test_omx_stop_fence.py`, `test_omx_ros_runtime.py`). §2 (c)의 binding 시험 셋을 같이 넣는다. 둘 다 safety 경로이므로 trailer가 필요하다.
- **(c) 생산자를 하나씩 Motion Intent로 옮긴다.** 한 커밋에 한 생산자. 순서 제안: teleop → 도킹 → Nav2 → 지역화 → 라인 추종 → swarm, 그다음 OMX `pilot_sim` → `rule_based`. 각 커밋은 그 생산자의 기존 시험과 §1 대응 시험이 그대로 통과해야 한다. `CommandManager`를 건드리면 trailer가 필요하다. 이 단계 뒤에 OMX Arbiter 표와 MANUAL 선점(§3)을 구현한다. 이것은 동작 추가이므로 sim 증거(D-390 Pilot 연습, Gazebo OMX)와 trailer가 필요하다. (c)에 드는 행동 변경은 다음과 같다.
  - **Pinky MANUAL 보호:** §3 알려진 예외를 고친다(사용자 결정 U1: `manual_active` 동안 Fleet 목표 포함 409. sim 증거·trailer·독립 리뷰). `api/v1/common.py`와 `ModeMachine` 쪽 시험, trailer 필요.
  - **`select_output` 반환형 변경:** Arbiter 판정을 `GuardedMotion`에 싣는다(`CommandManager`, trailer).
  - **OMX 선점 범위:** `preempt` 진입점(사용자 결정 U3), `recover` 운영 호출 경로, 리더 팔 스트림 수락 규칙(§3 끝 목록), 의도별 `valid_for_s` 도입(상한은 지금 `action_timeout_s`).
- **(d) 그다음에만 두 번째 backend.** 같은 장치 종류에 두 번째 binding을 붙이는 일(예: 벤더 SDK, PLC 축)은 (c)가 끝나고 §2 (c)·(d) 시험이 녹색일 때만 한다. 두 번째 backend마다 자기 ADR을 가진다(D-429 후속 4의 PLC 경계, D-430 불변식 5 시험 포함).

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-429 (Accepted) | §4의 Motion Intent·DeviceControlPort 원칙과 후속 1을 이 ADR이 구체화한다. binding 하나, writer만 쥠, Pinky Twist, OMX `ActionPort`를 그대로 따른다. `skills/manipulation`·`omx_adapter` 포트의 `api` 추출은 §4(b) 뒤의 별도 변경이다(질문 7) |
| D-430 (Accepted) | 불변식 3을 바꾸지 않는다. 기존 구조·행동 시험을 증명 수단으로 쓰고, `GuardedMotion` 생성 위치·프로필 binding 수·binding 생성 위치 시험을 더한다. 층 5(Arbiter + MANUAL 선점)의 OMX 빈칸을 §3이 채운다(결정만, 구현 전). 변경 통제는 §5 그대로다. D-430 §4의 "OMX owner HOLD 래치(`RearmLocal`)" 표기는 코드와 다르다. local stop 래치와 owner HOLD 래치를 나눈 §3 정리를 따르며, D-430 본문 정정은 후속 6이다 |
| D-429 §1 표(반응형 행) | 라인 추종을 반응형, 즉 "엔벌로프 안 Motion Intent"로 분류했다. 이 ADR은 라인 추종을 지금 동작대로 NAVIGATION 등급의 출처로 둔다. 지금 라인 추종은 규칙 기반이고 학습 출력이 없어 엔벌로프를 걸 대상이 없다는 판단이다. D-356 학습 인식이 라인 추종 입력에 붙으면 그때 엔벌로프 대상(D-399 후속 1)이 된다. 이 차이를 숨기지 않고 질문 3에 함께 둔다 |
| D-399 (Proposed) | §1 파이프라인(Action Gateway → Arbiter → Safety Guard → Motion Executor → 단일 writer)을 그대로 쓴다. 구조도의 Controller Adapter가 DeviceControlPort binding이다. 후속 5를 닫는다. 후속 1(엔벌로프)은 열린 채이며, 그 전까지 POLICY 의도는 거부된다 |
| D-2, D-38 (Accepted) | 유지한다. Pinky의 단일 `cmd_vel` writer와 CORE 최종 중재. binding으로 감싸도 publisher와 그 사용 함수는 하나다 |
| D-40 (Accepted), D-44 (Proposed) | 유지한다. 두 ADR의 ControlBackend는 Nav2와 비교하는 **주행 실행기 후보**이고, 이 ADR에서는 Motion Executor 자리다. DeviceControlPort는 그 아래의 출력 포트다. 이름 충돌을 피하려고 ControlBackend라는 이름을 쓰지 않는다(D-429 §4와 같다). 이 ADR의 "control backend"는 binding 너머 하드웨어 쪽(드라이버, controller, SDK)만 뜻한다 |
| D-208 (Accepted) | 유지한다. 감지 프로파일은 binding을 갖지 않는다. 레거시 `safety_node`는 binding이 아니며 D-149 단독 모드 예외로 남는다 |
| D-299 (Proposed) | 유지한다. 운영 경로의 팔로워 최종 명령 owner는 OMX 로컬 제어기 하나이고, 그 binding이 `ActionPort`다. LeRobot 네이티브 모드는 binding이 아닌 별도 모드다. 리더 팔은 owner가 아니라 MANUAL 입력이다(§3) |
| D-326, D-392 (Accepted) | 유지한다. 모델은 Motion Intent를 내지 않고 이동 도구도 없다. 모델 도구 금지 목록은 그대로다 |
| D-357 (Accepted) | 유지한다. ER2 피드백 루프와 장치 제어는 독립이다. Motion Intent는 ER2 도구 결과로 노출되지 않는다 |
| D-316, D-170 (Accepted) | Motion Intent의 `attempt`는 D-316의 `attempt_id`를 싣는다. `correlation_id`는 D-170대로 계약 필드이며, 이 ADR이 런타임 사용을 열지 않는다 |
| D-376, D-369 (Accepted) | OMX phase 취소의 정확한 UUID, 불명 결과 재발행 금지, `UNKNOWN/HOLD` 복구를 MANUAL 선점에 그대로 쓴다 |
| D-402 (Accepted) | 해석 IK는 binding이 아니라 포트 위의 Motion Executor(플래너)다 |
| D-427 (Accepted) | 새 계약은 `contracts/motion`(part contracts)에 둔다. binding은 middleware, 다른 backend 어댑터는 `integrations/robots/<model>`이다. §5 선행 조건 3의 결정과 4의 중재 쪽을 채운다 |

### Alternatives

- **Motion Intent 없이 장치마다 지금 모양 유지(Twist와 `TrajectoryCommand`).** 코드 변경이 없다. 하지만 새 장치·새 생산자마다 출처·시도 식별·정지 의미를 다시 정하게 되고, 반응형 정책이 어떤 모양으로 나와야 하는지 정할 수 없다. D-399 후속 1·5가 계속 막힌다. 기각.
- **포트가 Motion Intent를 직접 받음(`submit(intent)`).** 단순하다. 하지만 타입만으로는 Arbiter·Safety Guard를 거쳤는지 드러나지 않아, 포트를 얻은 코드가 바로 쓸 수 있다. `GuardedMotion`을 받게 하고 생성 위치를 시험으로 묶는다.
- **ros2_control을 모든 장치의 공통 포트로.** 업계 표준이고 Pinky·OMX 모두 ROS다. 하지만 Pinky CORE의 단일 writer·E-stop·D-400 정책은 ROS 밖 순수 로직이고(D-38), 미래 비-ROS 장치(벤더 SDK, PLC 축)를 덮지 못한다. ros2_control은 OMX binding의 backend로 남는다.
- **LeRobot `Robot.send_action`을 공통 포트로.** 정책 학습과 바로 맞는다. 하지만 관절 공간 사전 하나뿐이라 베이스 목표·취소·HOLD 래치·시도 식별이 없고, 네이티브 모드는 버스를 단독 소유한다(D-299). 벤더 SDK binding의 모양 참고로만 쓴다.
- **Pinky를 우선순위 정렬 Arbiter로 다시 씀.** 장치 간 모양이 같아진다. 하지만 지금의 모드·전이 표 방식이 동작 중이고 E-stop·watchdog 시험이 그 위에 있다. 행동을 바꾸는 재작성은 §4 이행 원칙과 어긋난다. 기각.
- **MANUAL이 HOLD를 거치지 않고 바로 선점.** 운영자가 더 빨리 잡는다. 하지만 OMX 취소 결과는 불명일 수 있고(D-369 §3), 활성 궤적과 리더 팔 스트림이 겹치면 점프가 난다. HOLD → 확인 → 정렬을 거친다.

### Consequences

- 로봇 움직임 요청에 하나의 이름과 모양이 생긴다. 새 장치는 "받는 kind를 선언한 binding 하나"로 붙는다.
- Fleet·모델·정책이 어디까지 오고 어디서 멈추는지가 타입으로 보인다. Fleet은 semantic Action까지, 모델은 아무것도 못 내고, 정책은 `envelope_ref`가 있는 의도까지다.
- OMX에 우선순위표와 MANUAL 선점이 생긴다. 선점은 HOLD를 거치므로 운영자 손이 한 번 더 간다.
- 사용자 결정 U2에 따라 Pinky binding은 이미 safety 모듈인 `cmd_vel.py` 안에 있어 변경 통제 범위가 늘지 않는다. publish를 옮기는 대안을 고르면 새 모듈을 `safety_modules:`에 넣어야 한다.
- Pinky MANUAL 보호(사용자 결정 U1)는 지금 동작을 바꾼다. 운영자 teleop 중에는 주행 목표가 409로 거부된다.
- 계약 패키지 하나와 시험 셋이 늘어난다. 두 번째 backend는 (c)가 끝날 때까지 미뤄진다.
- 실물 RL은 여전히 막혀 있다. 이 ADR은 D-427 §5 선행 조건 3의 결정만 채우고, 1·2·5·6과 4의 하드웨어 쪽은 남는다.

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, 번호 충돌 부재(adr_gaps 갱신 포함), harness lint 0 error, `test/architecture` 통과다. 코드·매니페스트·wire 변경은 없다.

**사용자 결정(2026-10-04):**

- **U1 — 자율 출처는 활성 MANUAL 세션을 빼앗지 못한다.** Pinky에서 주행 목표는 `correlation_id`가 붙은 Fleet 목표까지 포함해 `manual_active`인 동안 409로 거부한다. §4(c)의 행동 변경이며 sim 증거, `Safety-Review:` trailer, 독립 리뷰가 필요하다. 착지 전까지 지금의 탈취는 알려진 예외로 문서화한다(§3).
- **U2 — (b)에서 `PinkyTwistPort`는 얇은 래퍼다.** `GuardedMotion`을 풀어 기존 `_send_twist`를 부른다. publish는 옮기지 않고 기존 시험은 그대로 두며, 다른 속성이 cmd_vel에 발행하면 실패하는 시험을 더한다(§2 (a)·(c)).
- **U3 — OMX 선점은 owner와 무관한 Arbiter 전용 `preempt(reason)` 하나로만 한다.** 결과는 항상 owner HOLD 래치다. 정본 해제는 `recover`이고, `RearmLocal`은 local stop 래치만 푼다(§3).

**그 밖의 질문 — 리뷰 권고를 사용자가 수용했다(2026-10-04):**

1. **번호.** D-439가 이미 쓰였다. D-442로 가도 되는가? — 결정(권고 수용): D-442 유지. 병렬로 D-440을 쓰는 세션과는 병합 때 adr_gaps 항목을 맞춘다.
2. **계약 자리.** 새 패키지 `contracts/motion` 대 `contracts/skill` 안의 모듈. — 결정(권고 수용): 새 패키지. 스킬 계약과 수명이 다르고, 장치 binding이 스킬 계약을 끌어오지 않게 한다.
3. **라인 추종 출처 분리.** 지금 Nav2와 nav 슬롯·`navigation` 출처를 공유한다. `line_follow` 출처로 나눌 것인가? — 결정(권고 수용): §4(c)에서 이름만 나누고 등급은 NAVIGATION으로 둔다. 슬롯 공유와 "라인 추종이 켜져 있으면 Nav2 버림" 규칙은 유지한다. 감사 기록에서 누가 바퀴를 쥐었는지 보이게 하려는 것이다. D-429 §1이 라인 추종을 반응형으로 분류한 것과의 차이는 관계 표에 적었다. 엔벌로프는 D-356 학습 인식이 붙을 때 건다.
4. **Pinky POLICY 등급 위치.** NAVIGATION과 같은 칸(모드로 상호 배제) 대 그 아래. — 결정(권고 수용): 같은 칸. 새 모드 없이 NAVIGATION 모드 안의 스킬로 둔다. Pinky 주행 정책은 D-427 §5 순서상 마지막이므로 지금은 예약만 한다.
5. **리더 팔 스트림 끊김의 래치 여부.** 래치 없는 멈춤(스트림 재개로 계속) 대 HOLD 래치. — 결정(권고 수용): 래치 없는 멈춤. 사람이 곁에 있고, Pinky SAF-002 teleop watchdog과 같은 규칙이다. 이미 보낸 짧은 구간은 만료되게 둔다. 단, 끊김이 장치 쪽 관절 상태 stale(`max_joint_state_age_s`)과 겹치면 기존 owner HOLD 래치가 이긴다.
6. **D-427 §5 선행 조건 4를 닫는가.** — 결정(권고 수용): 닫지 않는다. 이 ADR은 중재 쪽만 정한다. 리더 팔 포트 식별·보정·하드웨어 읽기는 D-299 Validation 순서의 별도 ADR로 남긴다.
7. **`api` 추출(D-429 후속 1 범위).** `omx_adapter`·`skills/manipulation`의 포트를 `api`로 꺼내는 일을 이 이행에 넣는가. — 결정(권고 수용): 넣지 않는다. §4(b) 뒤에 D-427 wave 계획의 별도 carve로 한다. 그래야 (b)가 "행동 변화 없음"으로 남는다.
8. **OMX 취소가 늘 HOLD인 것.** MANUAL 선점을 위해 "취소가 확인된 정상 정지"를 HOLD 없이 IDLE로 둘 것인가. — 결정(권고 수용): 지금은 HOLD 유지. 물리 정지 증거(D-298, D-369 §5)가 생긴 뒤 다시 본다.

**후속:**

1. §4(a) 계약 패키지와 대응 시험.
2. §4(b) Pinky·OMX binding 감싸기와 §2 (c) 시험, `Safety-Review:` trailer.
3. §4(c) 생산자 이전, OMX Arbiter·MANUAL 선점 구현(sim 증거).
4. D-399 후속 1(엔벌로프 스킬 계약). POLICY 의도를 여는 조건이다.
5. 리더 팔 하드웨어 ADR(D-427 §5 선행 조건 4의 나머지).
6. D-430 §4의 OMX 래치 표기 정정(local stop 래치와 owner HOLD 래치를 나눔).
7. **이전 직후 첫 안전 작업으로 예약한다.** D-427 소스 이전이 끝나면 가장 먼저 다음을 한다: U1 Pinky MANUAL 보호(`manual_active` 동안 409), U3 OMX `preempt(reason)`와 `recover` 운영 호출 경로, U2 binding 래퍼와 `test_no_other_attribute_publishes_cmd_vel`. 각각 sim 증거(해당하면), `Safety-Review:` trailer, 독립 리뷰를 받는다.

**References:** [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-430](D-430-safety-as-a-separate-concern.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-2](D-2-cmd-vel.md), [D-38](D-38-core.md), [D-40](D-40-nav2-backend.md), [D-44](D-44-controlbackend-omx.md), [D-208](D-208-sensing-profile-publishes-no-velocity.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-326](D-326-agent-loop-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-357](D-357-er2-mission-feedback-loop.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [D-170](D-170-prt-004-deferred-until-central-fleet.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-419](D-419-saf003-fleet-link-loss-policy.md), [소유 매니페스트](../../tools/harness/platform_parts.yaml), [ros2_control getting started](https://control.ros.org/jazzy/doc/getting_started/getting_started.html), [LeRobot integrate hardware](https://huggingface.co/docs/lerobot/integrate_hardware), [Gemini Robotics-ER](https://ai.google.dev/gemini-api/docs/robotics-overview)
