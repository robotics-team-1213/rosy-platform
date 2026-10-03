## D-429 D-427 세 파트 위에 다섯 관심사를 드러내고, 장치 제어 포트와 사이트 장치 경계를 정한다

**Status:** Proposed (2026-10-03, 사용자 방향 결정 4건). D-427 §1·§2를 보강하고 §3을 확장한다. 독립 리뷰와 사용자 승인 뒤 Accepted로 올린다. 이번 변경은 문서뿐이다. 코드·폴더 이전·매니페스트 수정·wire 변경·실기 gate 변화는 없다.

### Context

사용자는 2026-10-03 플랫폼을 다섯 관심사로 설명했다. **학습, 판단, 로봇 제어, 통신 규약, 기타**다. 로봇이 아닌 사이트 하드웨어도 함께 다뤄야 한다고 했다. 지금은 정거장 신호등과 도크이고, 나중에는 컨베이어·문·PLC다. ROSY는 이 모두를 다루는 중간층이며, 목표는 확장성이다.

D-427은 최상위를 middleware·operations·learning 세 파트와 공용 contracts·integrations·shared/web으로 나눴다. 그런데 다섯 관심사 중 "판단"과 "로봇 제어"는 그 구조에서 보이지 않는다. architect·critic·외부 조사 세 갈래 검토를 따로 돌렸고, 다음에 의견이 모였다.

**최상위 `decision/`은 기각한다.**

- ER2 제안 저장과 stop 세대 확인은 한 SQLite 트랜잭션을 공유한다(D-358 §4). 실제로 `src/site/fleet/fleet/ai/tool_dispatch.py:19`가 `fleet.server.proposal_store`를 import한다. ER2를 Fleet 밖 최상위로 빼면 이 원자성이 프로세스 경계를 넘는다.
- "decision" 폴더는 이동 도구를 부르는 이름이다. 반응형 정책(ACT·RL)까지 끌어당겨 엔벌로프 밖으로 빼낼 위험이 있다(D-399 §2).
- 업계 관행도 같다. 추론 모델은 skill/action API의 교체 가능한 클라이언트로 두고, 제어는 하드웨어 추상 뒤에 두며, 안전은 모델 밖에 둔다. 근거는 Gemini Robotics-ER 문서(모델이 사용자 정의 함수를 호출하는 오케스트레이터), SayCan(언어 모델이 사전 학습된 skill만 고름), Open-RMF(Fleet adapter·door/lift adapter가 중앙 조정자의 클라이언트), ros2_control(controller와 hardware interface 분리), LeRobot(정책이 `select_action`으로 행동만 냄)이다.

**실제 빈틈은 있다.**

1. "판단"이 층마다 흩어져 있다. 이름을 붙이면 약 12종이다(아래 §1 표). 서로 다른 권한과 시간 척도를 가진 것들이 같은 단어로 불린다.
2. Motion Intent는 D-399 문서에만 있고 코드에는 없다(`grep -ri "motion.intent"` 코드 0건). 공통 제어 백엔드 포트도 없다. Pinky는 `src/runtime/gateway/core/bridge/ros_bridge.py`가 Twist를 낸다. OMX는 `src/products/omx/adapter/omx_adapter/command_owner.py:290`의 `ActionPort.send_goal(TrajectoryCommand)`를 쓴다. 두 장치가 같은 개념을 다른 모양으로 갖고 있다.
3. D-427 §1과 §2가 서로 어긋난다. §1은 `integrations/robots/<model>`을 둔다. §2는 integrations가 contracts만 import하게 한다. 그런데 provider·로봇 어댑터는 소유 모듈이 정의한 포트를 구현해야 하므로 그 API를 import할 수밖에 없다. 그래서 `integrations/robots/omx/src/rosy/integrations/robots/omx/transfer_provider.py:10-11`은 §2 아래 영구 위반이다.
4. 매니페스트가 `firmware/signal`·`firmware/dock`을 middleware로 대응시킨다(`tools/harness/platform_parts.yaml:155-160`). 둘 다 로봇 위가 아니라 사이트에 놓이는 장치다. 신호등의 접점 제어는 Fleet이 하고(D-12, D-337 §2), 관측 서버는 사이트 PC에서 돈다(D-163).
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
| 중재·안전 | arbitration and safety | Command Arbiter, Safety Guard, CORE cmd_vel mux | `middleware/core` | 최종 명령 하나, HOLD·정지 | 단일 writer(D-2, D-38) |
| 반응형 | reactive | line follow, 엔벌로프 스킬(ACT·Diffusion·RL) | `middleware/skills`, `middleware/perception` | 엔벌로프 안 Motion Intent | Arbiter 뒤에서만 |
| 판정기 | verifiers | 성공 분류기, VLM 심판, GOAL_CONFIRMED | 산출은 learning, 온라인 판정은 operations(D-328 §4) | 성공·실패 증거 | 없음 |
| 사람 | MANUAL | 운영자 원격 조작, Pilot, 리더 팔 | 입력은 middleware Arbiter의 MANUAL 우선순위 | Motion Intent(MANUAL) | Arbiter 우선순위 안에서(D-399 후속 5) |

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

- **소유:** 사이트 장치 owner는 `operations/site_devices/<kind>`에 둔다. kind는 지금 `signal`·`dock`, 나중에 `conveyor`·`door`다. owner는 펌웨어, heartbeat, semantic 명령, 감독이 끊겼을 때의 failsafe를 함께 소유한다.
- **관측:** 신호등 관측기(`firmware/signal/observer`, D-163의 읽기 전용 평면)는 operations 관측 평면으로 옮긴다. 목적지 경로는 wave 3 계획에서 정한다(예: `operations/vision/signal_observer`). 제어와 관측의 분리(D-163 §2)는 그대로다.
- **로봇 쪽 도킹:** DOCKING 모드(D-200)와 도크 상태 읽기(`core_features/docking/charging.py`)는 middleware에 남는다. 도크 펌웨어는 사이트에 있고, 도크에 들어가는 로봇의 판단은 로봇에 있다. D-349·D-350·D-351의 단계·재시도 규칙은 그대로다.
- **신호 순서:** 신호 순서의 유일한 소유자는 Fleet이다(D-12, D-337 §2). `site_devices/signal`은 Fleet이 정한 순서를 실행하는 장치 owner이고 순서를 정하지 않는다.
- **로봇의 소비:** 로봇은 사이트 장치를 fail-closed evidence로만 소비한다. 신호는 관측 서비스의 실측만 쓰고 접점 주장은 쓰지 않는다(D-337 §1·§3). 사이트 장치 상태만으로 로봇 안전 동작을 억제하거나 진입을 단독 허가하지 않는다.

#### 3. ER2는 사이트 장치 변경을 후보로만 제안할 수 있다 (사용자 결정 3)

- ER2는 사이트 장치 변경(예: "정거장 2 신호를 녹색으로")을 **후보 제안**으로만 낼 수 있다. Fleet 운영자가 승인해야 하며 자동 실행은 없다.
- 이 후보는 다른 제안과 같은 turn·fence·stop 무효화를 받는다(D-357 §6, D-358 §4). 제안한 모델은 승인자가 될 수 없다(D-427 §3 조건 5).
- **D-392 §4 확장:** 사이트 장치 직접 구동 도구는 금지 목록에 명시적으로 넣는다. 신호 점등·순서 변경, 문 열기·닫기, 컨베이어 기동·정지·속도, PLC 출력 쓰기다. 후속 작업에서 `src/site/fleet/test/test_model_tool_adapter_conformance.py:~154`의 도구 거부 시험(`test_sample_actuation_and_openapi_operations_stay_outside_catalog`) 매개변수에 이 이름들을 추가한다.
- 후보 스키마, 감사 기록, 승인 UI는 별도 후속 ADR(후속 3)이 정한다. 그 ADR이 착지하기 전에는 이런 도구가 catalog에 없다. 지금 ER2가 사이트 장치에 대해 할 수 있는 일은 없다.

#### 4. 제어 포트: 공통 바탕 위에 로봇과 사이트 장치를 나눈다 (사용자 결정 4)

**공통 바탕(contracts).** 로봇과 사이트 장치가 같이 지는 의무다.

- 식별·등록(identity/registration)
- 상태: 측정값과 주장값을 구분한다(D-337의 measured vs claimed)
- heartbeat
- semantic 명령만 받는다. raw I/O(핀·레지스터·코일)는 contracts에 나오지 않는다
- failsafe 의무: 감독이 끊기면 장치가 스스로 안전 상태로 간다

**로봇.** Motion Intent와 ControlBackend 포트를 둔다.

- Motion Intent는 스킬·MANUAL이 내는 의도다. per-device Arbiter → Safety Guard → 단일 writer(D-2, D-38)를 지난다.
- ControlBackend는 단일 writer 뒤의 포트다. Pinky의 Twist 발행(`ros_bridge.py`)과 OMX의 `ActionPort`가 이 포트의 두 구현이 된다.
- 이 작업은 D-399 후속 5(Motion Intent 공통 스키마·Arbiter 우선순위표)와 하나로 합친다(후속 1).

**사이트 장치.** `rosy.site-device/1`을 둔다.

- 공통 바탕에 kind별 semantic 명령(signal: phase, dock: enable/disable, conveyor: start/stop/speed class, door: open/close)을 더한다.
- 장치 로컬 failsafe가 필수다. 예: 신호는 감독 상실 시 전부 적색 또는 소등(D-337 §3상 진입 불허), 문은 마지막 안전 상태 유지, 컨베이어는 정지.
- 물리 E-stop과 safety PLC 회로는 ROSY와 독립이다. ROSY는 그 상태를 읽을 수 있으나 그 회로를 쓰거나 우회하지 않는다.

**integrations의 재정의.**

- `integrations/robots/<model>`은 **포트 구현**이다. writer가 아니다. 명령은 여전히 장치의 단일 writer를 지난다. 사이트 장치 어댑터(예: 미래 `integrations/site_devices/modbus`)도 같다.
- **import 규칙(D-427 §2 보강):** `integrations/*`는 contracts와 **소유 모듈의 `api`만** import할 수 있다. 구현 모듈은 import하지 못한다. 이것은 D-413 §3의 의존 역전이다. 소유 모듈이 `api`에 포트를 정의하고, 통합이 구현한다.
- 이 규칙으로 OMX 어댑터의 고정 위반 3건(KNOWN_VIOLATIONS 9건 중)을 다시 판정한다. **대상이 `api` 모듈인 edge만 허용 edge가 된다.** 2026-10-03 main `ab239c4eb` 기준:

| edge | import | 판정 |
|---|---|---|
| `integrations/robots/omx` → `modules/skills/api` | `transfer_provider.py:10` `from rosy.skills.api import SkillInvocation` | **허용으로 전환된다.** 대상이 api다 |
| `integrations/robots/omx` → `modules/skills/manipulation` | `transfer_provider.py:11` `rosy.skills.manipulation.transfer`의 `TransferPlanner`·`TransferSkill` | **위반으로 남는다.** 구현 모듈이다. manipulation이 포트를 `api`로 내놓아야 풀린다 |
| `integrations/robots/omx` → `src/products/omx/adapter` | `cell_workflow.py:6`, `transfer_provider.py:15-21·244·274`의 `omx_adapter.{pick_place_transaction, command_owner, manipulation_plan, …}` | **위반으로 남는다.** omx_adapter에는 `api` 모듈이 없다. 15-21행은 `TYPE_CHECKING` 블록이지만 시험은 정적 import를 모두 센다 |

따라서 이 규칙만으로 줄어드는 위반은 1건이다. 나머지 2건은 포트를 `api`로 추출하는 작업(후속 1과 함께)이 필요하다.

**첫 비-ROS 대상.** 확장성의 예로 PLC/Modbus 컨베이어를 첫 비-ROS `rosy.site-device/1` 구현 대상으로 둔다. 지금 만들지 않는다. 이 예는 포트가 ROS를 전제하지 않는지 확인하는 기준이다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-427 (Accepted) | §1·§2를 보강한다. integrations import 규칙에 "소유 모듈의 `api`" 허용을 더한다. middleware의 정의는 로봇에 대해 유지하고, 사이트 장치 펌웨어·owner는 operations로 옮긴다. §3 표를 판단 층 표(§1)로 확장한다. D-427 본문에 "부분 보강" 표기를 추가했다 |
| D-392 §4 (Accepted) | 금지 목록에 사이트 장치 구동(신호·문·컨베이어·PLC 출력)을 명시적으로 더한다. §3의 후보 제안 경로는 후속 ADR이 정하기 전까지 열리지 않는다 |
| D-399 (Proposed) | 후속 1(엔벌로프 스킬)과 후속 5(Motion Intent·Arbiter)를 이 ADR의 후속 1과 연결한다. §2의 AI 두 부류를 §1 표가 계승한다 |
| D-163, D-337 | 유지한다. 관측은 읽기 전용, 로봇의 제2 신호 소스는 실측뿐, 신호 순서는 Fleet |
| D-200, D-349, D-350, D-351 | 유지한다. 로봇 쪽 도킹 판단은 middleware에 남는다 |
| D-12 | 유지한다. Mission과 신호 순서는 Fleet 전용 |
| D-2, D-38 | 유지한다. 단일 최종 writer. ControlBackend는 그 writer 뒤의 포트다 |
| D-357, D-358 | 유지한다. 사이트 장치 후보도 같은 turn·fence·stop 무효화를 받는다 |
| D-413 §3 | 소유 모듈 API 원칙을 integrations import 규칙의 근거로 쓴다 |
| D-231 | 패키지·코드 이름을 유지한다. `core_features/decision`은 이름을 바꾸지 않고 문서 이름만 붙인다 |
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
- 모델 도구 금지 목록이 사이트 장치까지 넓어진다. 시험 매개변수를 늘리는 후속이 필요하다.
- integrations의 의존 역전이 규칙이 된다. OMX 어댑터 위반 중 1건만 바로 허용 edge가 되고, 2건은 api 추출 작업이 남는다.
- D-427 이전 계획의 wave 구성이 바뀐다(아래).

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, D-427 부분 보강 표기, 번호 충돌 부재, harness lint 0 error, `test/architecture` 통과다. 코드·폴더·매니페스트·wire 변경은 없다.

**D-427 이전 계획(`docs/plans/2026-10-03-d427-source-migration.md`) 영향.** 계획 문서는 이 ADR이 Accepted된 뒤 갱신한다.

- **Wave 0:**
  - 매니페스트 `concern:` 태그를 넣는다.
  - 사이트 장치 목적지를 바꾼다. `firmware/signal`·`firmware/dock` → `operations/site_devices/{signal,dock}`(part: operations). `firmware/signal/observer`는 별도 root로 떼어 operations 관측 평면으로 둔다.
  - import 규칙 시험에 "integrations → 소유 모듈 `api`" 허용을 더한다. api 판정 기준(경로 또는 `import_prefix`가 `.api`로 끝남)을 매니페스트에 명시한다.
  - KNOWN_VIOLATIONS를 다시 판정한다. `integrations/robots/omx → modules/skills/api` 1건이 빠진다(set equality이므로 같은 변경에서 지운다).
- **Wave 3:** `fleet/ai`를 `operations/decision`으로 떼어 낸다. `fleet.server.proposal_store`와의 트랜잭션 결합(D-358 §4)은 같은 파트 안 import로 유지한다. 신호 관측기도 이 wave에서 옮긴다.
- **Wave 4a:** `firmware/{dock,signal}`(23파일)이 빠진다. 4a는 `modules/skills/*`·`apps/agent`만 남는다.
- **위반 잔량:** 계획 문서의 "모든 wave 뒤에도 위반 5건"은 4건이 된다(OMX 어댑터 3건 중 skills/api 1건 해소).

**후속 ADR:**

1. **Motion Intent + ControlBackend 포트.** D-399 후속 5와 합친다. Motion Intent 공통 스키마, 장치별 Arbiter 우선순위표, MANUAL 선점, Pinky·OMX 구현 대응, `skills/manipulation`·`omx_adapter`의 포트를 `api`로 추출하는 범위.
2. **`rosy.site-device/1`.** 공통 바탕(식별·상태·heartbeat·semantic 명령·failsafe), kind별 명령, 감독 상실 timeout, 측정/주장 구분, 물리 E-stop·safety PLC 독립.
3. **ER2 사이트 장치 후보 제안.** 후보 스키마, 감사 기록, 운영자 승인 UI, 무효화 규칙. 착지 전에는 catalog에 도구가 없다. 같은 변경에서 도구 거부 시험에 사이트 장치 구동 이름을 넣는다.
4. **PLC 인터록.** PLC/Modbus 컨베이어를 첫 비-ROS 대상으로, ROSY 감독 신호와 safety PLC 회로의 경계.
5. **로컬 VLA 배치(D-399 §2).** VLA를 반응형 정책으로 옮길 때의 호스트·엔벌로프·D-231 §4 개정 여부.

**References:** [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-326](D-326-agent-loop-boundary.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-357](D-357-er2-mission-feedback-loop.md), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md), [D-163](D-163-signal-observation-readonly-plane.md), [D-337](D-337-robot-signal-source-measured-light.md), [D-200](D-200-docking-owns-the-docking-mode.md), [D-349](D-349-dock-auto-charge-code-readiness.md), [D-350](D-350-dock-hardware-phase-tiers.md), [D-351](D-351-docking-retry-by-failure-kind.md), [D-12](D-12-mission-fleet.md), [D-2](D-2-cmd-vel.md), [D-38](D-38-core.md), [D-413](D-413-platform-modules-integrations-apps-profiles.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-427 이전 계획](../plans/2026-10-03-d427-source-migration.md), [소유 매니페스트](../../tools/harness/platform_parts.yaml)
