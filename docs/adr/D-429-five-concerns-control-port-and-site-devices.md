## D-429 D-427 세 파트 위에 다섯 관심사를 드러내고, 장치 제어 포트와 사이트 장치 경계를 정한다

**Status:** Accepted (2026-10-03, 사용자 방향 결정 4건 + 리뷰 뒤 사용자 답변 3건, 독립 리뷰 2회 뒤 사용자 승인; 안전 체인은 별도 D-430). D-427 §1·§2를 보강하고 §3을 확장한다. 독립 리뷰와 사용자 승인 뒤 Accepted로 올린다. 이번 변경은 문서뿐이다. 코드·폴더 이전·매니페스트 수정·wire 변경·실기 gate 변화는 없다.

### Context

사용자는 2026-10-03 플랫폼을 다섯 관심사로 설명했다. **학습, 판단, 로봇 제어, 통신 규약, 기타**다. 로봇이 아닌 사이트 하드웨어도 함께 다뤄야 한다고 했다. 지금은 정거장 신호등과 도크이고, 나중에는 컨베이어·문·PLC다. ROSY는 이 모두를 다루는 중간층이며, 목표는 확장성이다.

D-427은 최상위를 middleware·operations·learning 세 파트와 공용 contracts·integrations·shared/web으로 나눴다. 그런데 다섯 관심사 중 "판단"과 "로봇 제어"는 그 구조에서 보이지 않는다. architect·critic·외부 조사 세 갈래 검토를 따로 돌렸고, 다음에 의견이 모였다.

**최상위 `decision/`은 기각한다.**

- ER2 제안 저장과 stop 세대 확인은 한 SQLite 트랜잭션을 공유한다(D-358 §4). 실제로 `src/site/fleet/fleet/ai/tool_dispatch.py:19`가 `fleet.server.proposal_store`를 import한다. ER2를 Fleet 밖 최상위로 빼면 이 원자성이 프로세스 경계를 넘는다.
- "decision" 폴더는 이동 도구를 부르는 이름이다. 반응형 정책(ACT·RL)까지 끌어당겨 엔벌로프 밖으로 빼낼 위험이 있다(D-399 §2).
- 업계 관행도 같다. 추론 모델은 skill/action API의 교체 가능한 클라이언트로 두고, 제어는 하드웨어 추상 뒤에 두며, 안전은 모델 밖에 둔다. 근거는 Gemini Robotics-ER 문서(모델이 사용자 정의 함수를 호출하는 오케스트레이터), SayCan(언어 모델이 사전 학습된 skill만 고름), Open-RMF(Fleet adapter·door/lift adapter가 중앙 조정자의 클라이언트), ros2_control(controller와 hardware interface 분리), LeRobot(정책이 `select_action`으로 행동만 냄)이다.

**실제 빈틈은 있다.**

1. "판단"이 층마다 흩어져 있다. 층으로 묶으면 7개, 그 안의 판단 종류(아래 §1 표의 "예" 열)는 십여 개다. 서로 다른 권한과 시간 척도를 가진 것들이 같은 단어로 불린다.
2. Motion Intent는 D-399 문서에만 있고 코드에는 없다(`.py` 파일에서 `motion.intent` 대소문자 무시 검색 0건). 공통 제어 백엔드 포트도 없다. Pinky는 `src/runtime/gateway/core/bridge/ros_bridge.py`가 Twist를 낸다. OMX는 `src/products/omx/adapter/omx_adapter/command_owner.py:290`의 `ActionPort.send_goal(TrajectoryCommand)`를 쓴다. 두 장치가 같은 개념을 다른 모양으로 갖고 있다.
3. D-427 §1과 §2가 서로 어긋난다. §1은 `integrations/robots/<model>`을 둔다. §2는 integrations가 contracts만 import하게 한다. 그런데 provider·로봇 어댑터는 소유 모듈이 정의한 포트를 구현해야 하므로 그 API를 import할 수밖에 없다. 그래서 `integrations/robots/omx/src/rosy/integrations/robots/omx/transfer_provider.py:10-11`은 §2 아래 영구 위반이다.
4. 매니페스트가 `firmware/signal`·`firmware/dock`을 middleware로 대응시킨다(`tools/harness/platform_parts.yaml:155-160`). 둘 다 로봇 위가 아니라 사이트에 놓이는 장치다. 신호 순서는 Fleet이 소유하고(D-337 §2), 신호등 heartbeat 폴링·`/command` POST·failsafe 재단언도 Fleet 프로세스 안에서 돈다(`src/site/fleet/fleet/server/signals.py:197-420`). 관측기는 제어와 분리된 읽기 전용 평면이다(D-163; 실행 호스트는 D-163이 정하지 않았다). 도크는 로봇이 `/status`를 직접 읽는다(`core_features/docking/agent.py:74-107`).
5. D-392 §4의 모델 도구 금지 목록에 사이트 장치 구동이 없다. 녹색 신호는 사실상 로봇에게 주는 진입 허가다. 문 열기·컨베이어 기동도 같은 무게다.

외부 근거(2026-10-03 조회):

- https://ai.google.dev/gemini-api/docs/robotics-overview
- https://arxiv.org/abs/2204.01691
- https://osrf.github.io/ros2multirobotbook/integration.html
- https://control.ros.org/jazzy/doc/getting_started/getting_started.html

### Decision

#### 1. 판단은 층마다 이름을 따로 붙인다 (사용자 결정 1)

최상위 `decision/`은 만들지 않는다. 대신 층마다 판단의 이름과 권한을 명시한다. 아래 표가 판단 종류의 정본이다. 새 판단 코드는 이 표의 한 줄에 들어가야 하며, 들어갈 줄이 없으면 ADR로 줄을 추가한다.

| 층 | 이름 | 예 (현재 코드) | 자리 | 출력 | 실행 권한 |
|---|---|---|---|---|---|
| 숙고형 | deliberative | ER2·VLM 제안(`fleet/ai`) | `operations/decision`, provider는 `integrations/models/<provider>` | Mission·Task·replan 후보 | 없음(D-326, D-392) |
| 조정 | coordination | Fleet admission(`dispatch_admission.py`), dispatch(`mission_dispatcher.py`, `step_dispatcher.py`), 교통(`traffic.py`), 양보 bay(`bays.py`), 신호 순서(`signals.py`) | `operations/fleet` | 승인된 Mission·Step, 점유·진입 grant, 신호 순서 | Fleet 원장 쓰기, 장치에는 semantic Device Action만 |
| 장치 지역 규칙 | device local rules | `core_features/decision`(lane·router·contract), DOCKING 진입 판단 | `middleware/core` | 장치 모드·주행 결정 | 장치 안 Arbiter 입력까지 |
| 중재·안전 | arbitration and safety | Command Arbiter, Safety Guard, CORE cmd_vel mux | `middleware/core` | 최종 명령 하나, HOLD·정지 | 단일 writer(D-2, D-38) (안전 체인: D-430) |
| 반응형 | reactive | line follow, 엔벌로프 스킬(ACT·Diffusion·RL) | `middleware/skills`, `middleware/perception` | 엔벌로프 안 Motion Intent | Arbiter 뒤에서만 |
| 판정기 | verifiers | 성공 분류기, VLM 심판, GOAL_CONFIRMED | 산출은 learning, 온라인 판정은 operations(D-328 §4) | 성공·실패 증거 | 없음 |
| 사람 | MANUAL | 운영자 원격 조작, Pilot, 리더 팔 | 입력은 middleware Arbiter의 MANUAL 우선순위 | Motion Intent(MANUAL) | Arbiter 우선순위 안에서(D-399 후속 5) |

안전 체인은 [D-430](D-430-safety-as-a-separate-concern.md)이다(중재·안전 층의 안전 부분).

이 표는 D-427 §3 표(숙고형·반응형·판정기·인식)를 대체하지 않고 확장한다. 인식은 판단이 아니라 관측 evidence이므로 이 표에 넣지 않는다.

이름 규칙은 다음과 같다.

- `core_features/decision`은 문서에서 **"device local rules(장치 지역 규칙)"**로 부른다. 코드 이름은 D-231대로 그대로 둔다. 숙고형 decision과 혼동하지 않게 하는 문서 이름이다.
- `operations/decision`은 숙고형만 담는다. 조정 로직(admission·traffic·bays·signal)은 `operations/fleet`에 남는다. 두 판단은 같은 Fleet 원장과 트랜잭션을 쓰므로 같은 파트 안 import로 묶인다.
- provider 자리는 D-427 §1대로 `integrations/models/<provider>`를 유지한다. `integrations/decision/<provider>`로 바꾸는 안은 **선택지로만** 남긴다. 판단 축으로 찾기는 쉬워지지만, 같은 모델을 learning이 오프라인 평가에도 쓰므로 "models"가 더 정확하다. 이 ADR은 바꾸지 않는다.

**다섯 관심사 view.** 매니페스트 각 root에 `concern:` 태그를 추가한다(값 `learning | decision | control | contracts | other`). 파트는 폴더와 의존 방향을 정하고, concern은 사용자가 보는 다섯 갈래를 보여주는 읽기 전용 view다. concern이 import 규칙을 바꾸지는 않는다. 현재 root의 기본 대응은 다음과 같다.

| concern | 주요 root (현재 경로 → D-427 목적지) |
|---|---|
| learning | `tools/perception`, `src/sim/isaac_sim`, `data` → `learning/*` |
| decision | `src/site/fleet/fleet/ai` → `operations/decision`; Fleet 조정 로직(admission·dispatch·traffic·bays·signals)은 `src/site/fleet` 안이므로 root 단위 태그는 `operations/fleet`의 주 concern으로 본다(아래 해석 참고) |
| control | `src/runtime/{gateway,services,events,api_web,navigation}`, `src/runtime/sensing`, `src/products/*`, `src/drivers/*`, `modules/skills/*`, `modules/execution/.../local`, `apps/agent`, `integrations/robots/*`, `src/sim/gz_sim/launch`, 그리고 사이트 장치 owner(`operations/site_devices/*`) |
| contracts | `src/contracts/*`, `modules/execution/.../api` |
| other | `src/site/{vision,cam,games,cell}`, `modules/world`, `modules/processes/*`, `apps/gateway`, `src/hmi/*`, `shared/web`, `profiles`, `deploy`, `tools/*`, `test`, `docs` |

`src/site/fleet` 한 root가 조정 판단과 원장·API를 함께 가지므로 root 하나에 concern 하나가 깔끔히 붙지 않는다. wave 0에서는 `src/site/fleet`을 `decision`(조정)으로 태그하고, `fleet/ai`는 별도 하위 root로 `decision`(숙고형)을 단다. 원장·웹은 그 안에 남는다. 태그 값의 최종 확정은 wave 0 매니페스트 리뷰에서 한다.

#### 2. 사이트 장치는 operations에 두고, 소비자는 제자리에 둔다 (사용자 결정 2)

- **소유:** 사이트 장치 owner는 `operations/site_devices/<kind>`에 둔다. kind는 지금 `signal`·`dock`, 나중에 `conveyor`·`door`다. 소유 범위는 펌웨어와 장치 계약이다. 런타임이 있는 kind는 그 런타임 라이브러리도 소유한다.
- **신호 런타임:** 지금 heartbeat 폴링, `/command` POST, failsafe 재단언은 Fleet 프로세스 안에서 돈다(`src/site/fleet/fleet/server/signals.py:197-420`). `operations/site_devices/signal`은 펌웨어, 장치 계약, 그리고 Fleet이 import하는 driver 라이브러리를 소유한다. 별도 프로세스는 만들지 않는다. 두 번째 명령 진입점도 만들지 않는다. 신호등에 명령을 내리는 길은 Fleet 하나다.
- **도크:** 도크에는 operations 런타임이 없다. 로봇이 도크 `/status`를 직접 폴링하고(`src/runtime/services/core_features/docking/agent.py:74-107`), 펌웨어에는 `/status`만 있다(`firmware/dock/firmware/rosy_dock/rosy_dock.ino:195`). `operations/site_devices/dock`은 펌웨어와 장치 계약만 소유한다. 로봇의 직접 읽기는 그대로 둔다. 도크 heartbeat·semantic 명령·감독 failsafe는 지금 없으며, 필요해지면 별도 ADR로 정한다.
- **관측:** 신호등 관측기(`firmware/signal/observer`, D-163의 읽기 전용 평면)는 operations 관측 평면으로 옮긴다. 목적지 경로는 wave 3 계획에서 정한다(예: `operations/vision/signal_observer`). 실행 호스트는 D-163이 정하지 않았고 이 ADR도 정하지 않는다. 제어와 관측의 분리(D-163)는 그대로다.
- **로봇 쪽 도킹:** DOCKING 모드(D-200)와 도크 상태 읽기(`core_features/docking/agent.py`, `charging.py`)는 middleware에 남는다. 도크 펌웨어는 사이트에 있고, 도크에 들어가는 로봇의 판단은 로봇에 있다. D-349·D-350·D-351의 단계·재시도 규칙은 그대로다.
- **신호 순서:** 신호 순서의 유일한 소유자는 Fleet이다(D-337 §2). `site_devices/signal`의 driver는 Fleet이 정한 순서를 장치에 전달할 뿐 순서를 정하지 않는다.
- **로봇의 소비:** 로봇은 사이트 장치를 fail-closed evidence로만 소비한다. 신호는 관측 서비스의 실측만 쓰고 접점 주장은 쓰지 않는다(D-337 §1·§3). 사이트 장치 상태만으로 로봇 안전 동작을 억제하거나 진입을 단독 허가하지 않는다. (안전 체인: D-430)

#### 3. ER2는 사이트 장치 변경을 후보로만 제안할 수 있다 (사용자 결정 3)

- ER2는 사이트 장치 변경(예: "정거장 2 신호를 녹색으로")을 **후보 제안**으로만 낼 수 있다. 자동 실행은 없다.
- **승인자:** 승인자는 인증된 사람 Fleet 운영자뿐이다. 어떤 모델·자동화도 승인할 수 없다. 승인은 후보 기록과 별개 행위다. 근거: D-357 §4는 replan 후보가 기존 admission·사람 확인 규칙을 받는다고 정하고, D-332 §4는 확인을 actor·시각·대상·근거가 남는 감사 이벤트로, 운영 조정 권한을 `operator` 역할로 정하며 뷰어는 확인할 수 없게 한다. "모델·자동화 승인 불가"는 그 위에 이 ADR이 사이트 장치 후보에 대해 명시하는 규칙이다. D-332 §4는 재발의 승인(`policy-admin`)과 운영 조정(`operator`)을 나눌 뿐이며, 사이트 장치 후보 승인을 운영 조정(`operator`)으로 분류하는 것은 이 ADR의 결정이다.
- **승인의 효과:** 승인된 후보는 Fleet 신호 순서·교통 로직(`signals.py`, `traffic.py`)의 **입력**일 뿐이다. 장치에 직접 내려가는 명령이 아니다. 실행 시점에 Fleet이 현재 점유와 세대를 다시 확인한다. 재확인에 실패하면 후보를 stale로 표시하고 재시도하지 않는다(사용자 결정, 2026-10-03). 운영자는 실패 사유를 본다. ER2는 새 턴에서 다시 제안할 수 있고, 그 제안은 새 승인이 필요하다. 승인은 나중에 발동하려고 대기하지 않는다. 조건이 풀리면 실행되는 "예약 승인"은 없다.
- **인터록 우선:** 운영자 승인은 Fleet 인터록(교차로 점유, 진입 grant, all_red·e-stop scatter, stop latch)을 결코 넘어서지 않는다. (안전 체인: D-430)
- **fence 범위:** 이 후보는 다른 제안과 같은 turn·stop 무효화를 받는다(D-357 §6, D-358 §4). 다만 사이트 장치 후보는 Mission에 묶이지 않을 수 있으므로, fence 범위는 site/signal-group 세대 또는 장치 `last_seq`(`signals.py:46`)다. D-358 §4의 공유 트랜잭션 확인을 이 범위로 넓힌다.
- **밸브 유지:** `POLICY_DISPATCH_ENABLED=False`를 유지한다(D-392 §7, D-357 §7). 이 결정은 밸브를 열지 않는다.
- **D-392 §4 확장:** 사이트 장치 직접 구동 도구는 금지 목록에 명시적으로 넣는다. 신호 점등·순서 변경, 문 열기·닫기, 컨베이어 기동·정지·속도, PLC 출력 쓰기다. 이 이름들은 **wave 0에서 지금** 도구 거부 시험에 넣는다(사용자 결정, 2026-10-03). 후보 제안을 여는 후속 ADR 3과는 별개 작업이다. 대상은 `src/site/fleet/test/test_model_tool_adapter_conformance.py:157`의 `test_sample_actuation_and_openapi_operations_stay_outside_catalog`이다. 이 시험은 `@pytest.mark.parametrize("name", [...])`의 문자열 목록(현재 `move`, `set_gripper_state`, `execute_action`, `cancel_action`, `stop`, `emergency_stop`, `rearm`, `post_actions_execute`)으로 이름을 열거하고, 각 이름이 `TOOL_NOT_ALLOWED`로 거부되며 `MODEL_TOOL_CATALOG`에 없음을 확인한다. 패턴 매칭은 없으므로 구체 이름을 더한다:
  - 신호: `set_signal`, `set_signal_mode`, `set_signal_phase`, `signal_command`, `signal_all_red`, `post_signal_command`(Fleet 신호 HTTP 명령 경로와 같은 모양)
  - 문: `open_door`, `close_door`, `set_door_state`
  - 컨베이어: `start_conveyor`, `stop_conveyor`, `set_conveyor_speed`
  - PLC: `write_plc_output`, `write_coil`, `write_register`
  - 일반: `set_site_device_state`, `site_device_command`

  이름 목록은 막는 예시이지 허용 목록의 반대가 아니다. catalog는 닫혀 있으므로(D-392 §3) 목록에 없는 이름도 거부된다. 시험이 지키는 것은 "이런 이름이 catalog에 들어오는 순간 실패한다"는 회귀 경계다. 같은 변경에서 catalog 쪽에 사이트 장치 effect class가 없음을 확인하는 단정을 하나 더한다.
- 후보 스키마, 감사 기록, 승인 UI는 별도 후속 ADR(후속 3)이 정한다. 그 ADR이 착지하기 전에는 이런 도구가 catalog에 없다. 지금 ER2가 사이트 장치에 대해 할 수 있는 일은 없다.

#### 4. 제어 포트: 공통 바탕 위에 로봇과 사이트 장치를 나눈다 (사용자 결정 4)

**공통 바탕(contracts).** 로봇과 사이트 장치가 같이 지는 의무다.

- 식별·등록(identity/registration)
- 상태: 측정값과 주장값을 구분한다(D-337의 measured vs claimed)
- heartbeat
- semantic 명령만 받는다. raw I/O(핀·레지스터·코일)는 contracts에 나오지 않는다
- failsafe 의무: 감독이 끊기면 장치가 스스로 안전 상태로 간다 (제안: D-430 §4)

heartbeat·semantic 명령·감독 failsafe는 명령을 받는 장치의 의무다. 지금 도크처럼 상태만 내놓는 읽기 전용 장치는 식별과 상태만 진다. (제안: D-430 §4)

**로봇.** Motion Intent와 DeviceControlPort를 둔다.

- Motion Intent는 스킬·MANUAL이 내는 의도다. per-device Arbiter → Safety Guard → 단일 writer(D-2, D-38)를 지난다.
- **DeviceControlPort**는 단일 writer가 장치 출력에 쓰는 포트다. 장치마다 binding은 정확히 하나이고, 그 binding은 단일 writer만 쥔다. 다른 구성 요소는 이 포트를 얻을 수 없으므로 두 번째 writer가 될 수 없다. 지금 Pinky의 binding은 `ros_bridge.py`의 `cmd_vel` publisher다. 이 파일 자체가 유일한 cmd_vel writer다(`ros_bridge.py:3,84`, D-2). OMX의 binding은 `command_owner.py:290`의 `ActionPort`다.
- 이름을 `ControlBackend`로 하지 않는 이유: D-40·D-44의 ControlBackend는 Nav2와 비교하는 주행 실행기 후보(Control 패키지의 자율 로직)를 뜻한다. 출력 포트와 다른 개념이므로 이름을 나눈다.
- 이 작업은 D-399 후속 5(Motion Intent 공통 스키마·Arbiter 우선순위표)와 하나로 합친다(후속 1).

**사이트 장치.** `rosy.site-device/1`을 둔다.

- 공통 바탕에 kind별 semantic 명령(signal: mode·phase, conveyor: start/stop/speed class, door: open/close; dock은 지금 읽기 전용 `/status`뿐이며 명령은 별도 ADR 뒤의 미래 항목)을 더한다.
- 장치 로컬 failsafe가 필수다. 예: 신호는 감독 상실 시 `mode=failsafe`, 전 기능 적색 점멸이다(펌웨어 계약 `firmware/signal/README.md` "하트비트와 페일세이프"; 명령된 `all_red` 점등과 구별된다. D-337 §3상 진입 불허), 문은 마지막 안전 상태 유지, 컨베이어는 정지. (안전 체인: D-430)
- 물리 E-stop과 safety PLC 회로는 ROSY와 독립이다. ROSY는 그 상태를 읽을 수 있으나 그 회로를 쓰거나 우회하지 않는다. (제안: D-430 §3 불변식 5)

**integrations의 재정의.**

- `integrations/robots/<model>`은 **포트 구현**이다. writer가 아니다. 명령은 여전히 장치의 단일 writer를 지난다. 사이트 장치 어댑터(예: 미래 `integrations/site_devices/modbus`)도 같다.
- **import 규칙(D-427 §2 보강):** `integrations/*`는 contracts와 **소유 모듈의 `api`만** import할 수 있다. 구현 모듈은 import하지 못한다. 이것은 D-413 §3의 의존 역전이다. 소유 모듈이 `api`에 포트를 정의하고, 통합이 구현한다. 세부 규칙:
  1. **api root 판정:** 매니페스트 root의 `import_prefix`가 `.api`로 끝나고, **그리고** 그 root에 `api: true`가 명시된 경우에만 api root다. 경로나 접두어 하나만으로는 api가 아니다.
  2. **api root의 의존:** api root는 contracts와 다른 api root만 import할 수 있다. api가 구현을 끌어오면 통합이 api를 통해 구현에 닿기 때문이다.
  3. **종류별 범위:** integration은 자기 종류(kind)를 import하도록 D-427 §2 표가 허용한 파트의 api만 import할 수 있다. `robots`·`policies/lerobot_inference`는 middleware, `policies/lerobot_training`은 learning, `simulation`은 middleware·learning, `models`·`storage`는 operations·learning이다. 그래서 `integrations/robots/*`가 `rosy.execution.api`(operations)를 통해 middleware→operations로 우회하는 경로는 닫힌다.
  4. **시험:** 1–3은 모두 wave 0에서 `test/architecture/test_platform_parts.py`로 강제한다. 시험 없이는 이 규칙이 발효되지 않는다.
- 이 규칙으로 OMX 어댑터의 고정 위반 3건(KNOWN_VIOLATIONS 9건 중)을 다시 판정한다. **대상이 `api` 모듈인 edge만 허용 edge가 된다.** 2026-10-03 main `ab239c4eb` 기준:

| edge | import | 판정 |
|---|---|---|
| `integrations/robots/omx` → `modules/skills/api` | `transfer_provider.py:10` `from rosy.skills.api import SkillInvocation` | **허용으로 전환된다.** 대상이 api다 |
| `integrations/robots/omx` → `modules/skills/manipulation` | `transfer_provider.py:11` `rosy.skills.manipulation.transfer`의 `TransferPlanner`·`TransferSkill` | **위반으로 남는다.** 구현 모듈이다. manipulation이 포트를 `api`로 내놓아야 풀린다 |
| `integrations/robots/omx` → `src/products/omx/adapter` | `cell_workflow.py:6`, `transfer_provider.py:15-21·244·274`의 `omx_adapter.{pick_place_transaction, command_owner, manipulation_plan, …}` | **위반으로 남는다.** omx_adapter에는 `api` 모듈이 없다. 15-21행은 `TYPE_CHECKING` 블록이지만 시험은 정적 import를 모두 센다 |

따라서 이 규칙만으로 줄어드는 위반은 1건이다(`modules/skills/api`에 `api: true`를 달고, 그 root가 contracts·api만 import함을 확인한 뒤). 나머지 2건은 포트를 `api`로 추출하는 작업(후속 1과 함께)이 필요하다. 같은 edge는 이전 계획 2a로도 따로 없앨 수 있다. 2a가 `SkillInvocation`을 `rosy.contracts.skill`로 옮기므로 `transfer_provider.py:10`을 새 이름으로 바꾸면 이 edge는 api 규칙과 무관하게 사라진다. 다만 2a 본문은 현재 이 import를 고칠 대상으로 적지 않았다.

**첫 비-ROS 대상.** 확장성의 예로 PLC/Modbus 컨베이어를 첫 비-ROS `rosy.site-device/1` 구현 대상으로 둔다. 지금 만들지 않는다. 이 예는 포트가 ROS를 전제하지 않는지 확인하는 기준이다.

#### 5. ER2 숙고형 코드는 `rosy.decision`으로 개명한다 — D-231의 유일한 예외 (사용자 결정, 2026-10-03)

- **대상과 이름:** `src/site/fleet/fleet/ai`(ER2·VLM 숙고형 코드)를 `operations/decision`으로 옮기며 import 이름을 `fleet.ai`에서 **`rosy.decision`**으로 바꾼다. 기존 wheel namespace가 `rosy.<모듈>`(`rosy.execution`, `rosy.world`, `rosy.skills`, `rosy.processes.palletizing`)이고 파트 이름을 넣지 않으므로 `rosy.operations.decision`이 아니라 `rosy.decision`을 쓴다.
- **예외 범위:** D-231의 "패키지 이름은 그대로 둔다"에 대한 예외는 이 패키지 하나뿐이다. ROS 패키지·노드·토픽 이름, HTTP API 경로, 공개 wire, 저장 스키마, 모델 도구 이름은 하나도 바꾸지 않는다. 다른 패키지의 개명 근거로 이 절을 쓰지 않는다.
- **같은 커밋:** 호출자, 시험, 그리고 `fleet.server.proposal_store` ↔ `fleet.ai`의 양방향 import(`fleet/ai/tool_dispatch.py:19` → `fleet.server.proposal_store`, `fleet/server/proposal_store.py:16` → `fleet.ai.model_tool_contract`)를 이동 커밋 하나에서 함께 처리한다. 옛 이름 re-export shim은 두지 않는다(두 이름이 공존하면 같은 계약이 둘로 보인다).
- **순환 끊기(권고):** 의존 방향은 proposal store → `rosy.decision.api`의 타입 하나로 둔다. 역방향은 두지 않는다. 즉 `ModelToolCall`·`ModelToolResult` 같은 타입과 proposal store가 내는 예외(`ProposalConflict`·`ProposalRejected`, 지금 `tool_dispatch.py:19`가 import)를 `rosy.decision.api`(`api: true` root, §4 api 규칙)에 두고 proposal store가 그것을 import한다. `rosy.decision`의 dispatch 구현은 Fleet이 주입하는 저장 포트를 통해 proposal store를 쓴다. 정확한 포트 모양은 carve 커밋에서 정한다.
- **트랜잭션:** D-358 §4의 공유 SQLite 트랜잭션(후보 삽입과 stop·세대·watermark 확인)은 Fleet 안에 그대로 둔다. `rosy.decision`은 트랜잭션을 열지 않고 Fleet의 저장 포트를 호출한다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-427 (Accepted) | §1·§2를 보강한다. integrations import 규칙에 "소유 모듈의 `api`" 허용을 더한다. middleware의 정의는 로봇에 대해 유지하고, 사이트 장치 펌웨어·owner는 operations로 옮긴다. §3 표를 판단 층 표(§1)로 확장한다. D-427 본문에 조건부 "부분 보강 제안" 표기를 추가했다(Accepted 전 미발효) |
| D-392 §4 (Accepted) | 금지 목록에 사이트 장치 구동(신호·문·컨베이어·PLC 출력)을 명시적으로 더한다. §3의 후보 제안 경로는 후속 ADR이 정하기 전까지 열리지 않는다. §7 밸브(`POLICY_DISPATCH_ENABLED=False`)는 그대로다. D-392 본문에 조건부 표기를 추가했다 |
| D-399 (Proposed) | 후속 1(엔벌로프 스킬)과 후속 5(Motion Intent·Arbiter)를 이 ADR의 후속 1과 연결한다. §2의 AI 두 부류를 §1 표가 계승한다 |
| D-163, D-337 | 유지한다. 관측은 읽기 전용, 로봇의 제2 신호 소스는 실측뿐, 신호 순서는 Fleet |
| D-200, D-349, D-350, D-351 | 유지한다. 로봇 쪽 도킹 판단은 middleware에 남는다 |
| D-12 | 유지한다. Mission은 Fleet 전용. 신호 순서의 Fleet 소유 근거는 D-337 §2다 |
| D-2, D-38 | 유지한다. 단일 최종 writer. DeviceControlPort는 장치당 binding 하나이며 그 writer만 쥔다 |
| D-40 (Accepted), D-44 (Proposed) | 유지한다. 두 ADR의 ControlBackend는 Nav2와 비교하는 주행 실행기 후보이고, 이 ADR의 DeviceControlPort(단일 writer의 출력 포트)와 다르다. 이름 충돌을 피하려고 이 ADR은 ControlBackend라는 이름을 쓰지 않는다 |
| D-330 (Accepted) | 유지한다. Fleet의 단일 발행 권한과 정지·재시작 차단은 승인된 사이트 장치 후보에도 적용된다. 승인은 Fleet 인터록을 넘지 않는다 |
| D-336 (Accepted) | 유지한다. Fleet–OMX 제어 owner 연결 경계는 바뀌지 않는다. OMX의 DeviceControlPort binding(`ActionPort`)은 그 owner 안에 있다 |
| D-332 (Accepted) | 사람 확인은 감사 이벤트이며 운영 조정 권한은 `operator`라는 규칙을 사이트 장치 후보 승인에 쓴다 |
| D-357, D-358 | 유지한다. 사이트 장치 후보도 같은 turn·fence·stop 무효화를 받는다 |
| D-413 §3 | 소유 모듈 API 원칙을 integrations import 규칙의 근거로 쓴다 |
| D-231 (Accepted) | 패키지·코드 이름 유지 원칙을 지킨다. `core_features/decision`은 이름을 바꾸지 않고 문서 이름만 붙인다. **유일한 예외:** §5의 `fleet.ai` → `rosy.decision` 한 패키지. ROS·토픽·API·wire 이름은 그대로다 |
| D-326 | 유지한다. ER2는 Fleet 옆 소비자다 |

### Alternatives

- **최상위 `decision/` 파트:** 다섯 관심사가 폴더에 바로 보인다. 하지만 ER2와 Fleet의 공유 트랜잭션(D-358 §4)을 갈라 놓고, 반응형 정책과 이동 도구를 끌어들이는 이름이다. D-427 §3·D-399 §1이 이미 기각한 "AI 상자"를 되살린다. 기각.
- **사이트 장치를 middleware에 그대로 둠:** 매니페스트 수정이 없다. 하지만 middleware의 정의("어떤 로봇이든 같은 계약으로 안전하게 움직인다")와 맞지 않고, 신호 순서 소유자(Fleet)와 장치 owner가 다른 파트에 갈라진다. 기각.
- **사이트 장치를 integrations 아래에 둠:** 펌웨어·failsafe·heartbeat의 소유가 "외부 기술 연결"로 흐려진다. 어댑터(Modbus 등)만 integrations에 두고 owner는 operations에 둔다.
- **ER2의 사이트 장치 직접 도구 허용(운영자 확인 대화상자 뒤):** 녹색 신호는 진입 허가다. 확인 UI 하나에 안전을 맡기면 D-392 §4의 취지를 우회한다. 후보 기록 → 별도 운영자 승인으로만 연다. 기각.
- **로봇·사이트 장치를 하나의 제어 포트로 통일:** 공통 바탕은 같다. 하지만 로봇은 Arbiter·Safety Guard·연속 Motion Intent가 필요하고, 사이트 장치는 이산 semantic 명령과 로컬 failsafe가 핵심이다. 한 포트로 묶으면 어느 쪽에도 맞지 않는다. 공통 바탕 + 둘로 나눈다.
- **integrations가 contracts만 import(D-427 §2 원문 유지):** 규칙은 단순하다. 하지만 포트를 구현하는 어댑터가 존재 자체로 위반이 된다. 포트를 모두 contracts로 올리면 contracts가 모듈 내부 API로 부풀어 D-413 §3과 어긋난다. 기각.

### Consequences

- 다섯 관심사가 매니페스트 view와 이 ADR의 표로 보인다. 폴더는 D-427 세 파트를 유지한다.
- "판단"이라는 말이 층 이름과 함께 쓰인다. 새 판단 코드의 자리를 표로 정한다.
- 사이트 장치를 늘리는 경로가 생긴다. 새 장치 종류는 `operations/site_devices/<kind>` owner와 필요 시 `integrations/site_devices/<protocol>` 어댑터로 늘어난다.
- 모델 도구 금지 목록이 사이트 장치까지 넓어진다. 거부 시험 매개변수는 wave 0에서 늘린다(§3).
- integrations의 의존 역전이 규칙이 된다. OMX 어댑터 위반 중 1건만 바로 허용 edge가 되고, 2건은 api 추출 작업이 남는다.
- D-427 이전 계획의 wave 구성이 바뀐다(아래).

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, D-427 부분 보강 표기, 번호 충돌 부재, harness lint 0 error, `test/architecture` 통과다. 코드·폴더·매니페스트·wire 변경은 없다.

**D-427 이전 계획(`docs/plans/2026-10-03-d427-source-migration.md`) 영향.** 계획 문서는 이 ADR이 Accepted된 뒤 갱신한다.

- **Wave 0:**
  - 매니페스트 `concern:` 태그를 넣는다.
  - 사이트 장치 목적지를 바꾼다. `firmware/signal`·`firmware/dock` → `operations/site_devices/{signal,dock}`(part: operations). 신호 driver 라이브러리를 Fleet에서 떼어 낼지는 이 매니페스트 변경과 별개이며, 떼어 내도 Fleet이 import하는 라이브러리다. `firmware/signal/observer`는 별도 root로 떼어 operations 관측 평면으로 둔다.
  - import 규칙 시험에 §4의 api 규칙 1–4를 넣는다. api root는 `import_prefix`가 `.api`로 끝나고 `api: true`가 있는 root이며, api root는 contracts·api만 import하고, integration은 자기 kind가 허용된 파트의 api만 import한다.
  - KNOWN_VIOLATIONS를 다시 판정한다. `integrations/robots/omx → modules/skills/api` 1건이 빠진다(set equality이므로 같은 변경에서 지운다).
  - `test_model_tool_adapter_conformance.py:157`의 거부 목록에 §3의 사이트 장치 구동 이름을 넣는다. 후속 ADR 3과 별개로 지금 한다. Fleet 시험이므로 wave 0 게이트에 `python -m pytest src/site/fleet/test/test_model_tool_adapter_conformance.py -q`를 더한다.
- **Wave 3c:** 이름 붙은 carve 커밋 `refactor(d427): carve fleet.ai to rosy.decision`으로 `fleet/ai`를 `operations/decision`(import `rosy.decision`)으로 옮긴다(§5). 같은 커밋에서 호출자(main `ab239c4eb` 기준 비시험 1개 `fleet/server/proposal_store.py`, 시험 10개)와 양방향 import를 함께 고친다. 같은 커밋에서 `rosy.decision`의 설치 단위(새 `pyproject.toml`, Fleet `setup.py`·`package.xml` 의존 추가)를 만든다. `docs/validation/model-tool-artifact-2026-10-01/manifest.json`의 옛 경로는 증거 기록이므로 고치지 않는다(D-226). shim을 두지 않으므로 carve 직전에 `fleet/ai`·`proposal_store.py`를 건드리는 미병합 브랜치를 다시 확인한다. 신호 관측기도 wave 3에서 옮긴다.
- **Wave 4a:** `firmware/{dock,signal}`(23파일)이 빠진다. 4a는 `modules/skills/*`·`apps/agent`만 남는다.
- **위반 잔량:** 계획 문서의 "모든 wave 뒤에도 위반 5건"은 4건이 된다(OMX 어댑터 3건 중 skills/api 1건 해소).

**후속 ADR:**

1. **Motion Intent + DeviceControlPort.** D-399 후속 5와 합친다. Motion Intent 공통 스키마, 장치별 Arbiter 우선순위표, MANUAL 선점, Pinky·OMX 구현 대응, `skills/manipulation`·`omx_adapter`의 포트를 `api`로 추출하는 범위.
2. **`rosy.site-device/1`.** 공통 바탕(식별·상태·heartbeat·semantic 명령·failsafe), kind별 명령, 감독 상실 timeout, 측정/주장 구분, 물리 E-stop·safety PLC 독립. (제안: D-430 §3 불변식 5)
3. **ER2 사이트 장치 후보 제안.** 후보 스키마, 감사 기록, 운영자 승인 UI, 무효화 규칙. 착지 전에는 catalog에 도구가 없다. 직접 구동 이름의 거부 시험은 이 ADR보다 먼저 wave 0에서 들어간다. 후보 도구 이름은 그 거부 목록과 겹치지 않게 정한다.
4. **PLC 인터록.** PLC/Modbus 컨베이어를 첫 비-ROS 대상으로, ROSY 감독 신호와 safety PLC 회로의 경계. 안전 영역 쓰기 금지 시험은 D-430이 소유하며 이 후속은 참조만 한다(제안: D-430 §3 불변식 5).
5. **로컬 VLA 배치(D-399 §2).** VLA를 반응형 정책으로 옮길 때의 호스트·엔벌로프·D-231 §4 개정 여부.

**References:** [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-326](D-326-agent-loop-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-357](D-357-er2-mission-feedback-loop.md), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md), [D-163](D-163-signal-observation-readonly-plane.md), [D-337](D-337-robot-signal-source-measured-light.md), [D-200](D-200-docking-owns-the-docking-mode.md), [D-349](D-349-dock-auto-charge-code-readiness.md), [D-350](D-350-dock-hardware-phase-tiers.md), [D-351](D-351-docking-retry-by-failure-kind.md), [D-12](D-12-mission-fleet.md), [D-2](D-2-cmd-vel.md), [D-38](D-38-core.md), [D-413](D-413-platform-modules-integrations-apps-profiles.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-427 이전 계획](../plans/2026-10-03-d427-source-migration.md), [소유 매니페스트](../../tools/harness/platform_parts.yaml)
