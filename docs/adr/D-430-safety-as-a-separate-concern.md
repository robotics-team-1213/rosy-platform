## D-430 안전은 판단·제어와 분리된 여섯째 관심사이며, 층별 안전 체인과 분리 불변식으로 지킨다

**Status:** Proposed (2026-10-03, 사용자 요청 — 안전을 별도 관심사로). [D-429](D-429-five-concerns-control-port-and-site-devices.md)(Accepted 2026-10-03)의 다섯 관심사 view에 `safety`를 더하고, D-429 §1 표의 "중재·안전" 층에서 안전을 떼어 별도 체인으로 기술한다. 독립 리뷰와 사용자 승인 뒤 Accepted로 올린다. 이번 변경은 문서뿐이다. 코드·폴더 이전·매니페스트 수정·wire 변경·실기 gate 변화는 없다. D-400 집행, 물리 E-stop, DEVICE/FIELD 수용을 승인하지 않는다.

### Context

사용자는 2026-10-03 "무언가를 제어할 때 안전을 고려하고 있는가"를 물었다. 고려는 하고 있다. 다만 층마다 흩어져 있다.

- 로봇 위: CORE `SafetyManager`(SAF-001 E-stop 래치, SAF-004 속도 상한, SAF-005 배터리, SAF-003 Fleet 상실, SAF-006 사람 자문; `src/runtime/services/core_features/safety/manager.py:278`), D-400 센서 정책(`shadow.py`, 기본 off), D-422·D-424 몸 기준 근접 정지(`core_features/line_follow/body_stop.py`, `core_common/robot_body.py`), Arbiter 우선순위(`core_features/command/arbitration.py:17-24`), 단일 writer(`src/runtime/gateway/core/bridge/ros_bridge.py:3,84`, D-2·D-38).
- 팔 위: OMX `ArmCommandOwner`의 HOLD 래치(`src/products/omx/adapter/omx_adapter/command_owner.py:415,464`)와 `local_stop.py`의 rearm(`:177`).
- 사이트: Fleet 정지 세대 래치(D-330), 후보 fence(D-358 §4), 래치 없는 전체 주행 취소와 래치형 전체 비상 정지의 분리(D-421, `src/site/fleet/fleet/server/console.py:897`, `cancel_all.py`), 모델 도구 금지(D-392 §4·§7).
- 사이트 장치: 신호등 펌웨어의 부팅·감독 상실 failsafe(`firmware/signal/firmware/rosy_signal/rosy_signal.ino:66,118`), 도크 리밋스위치 인터록과 부팅 시 0 V(`firmware/dock/firmware/rosy_dock/rosy_dock.ino:58-65,117,172`, D-349).
- 물리 E-stop은 원칙만 있다(D-369 §5, D-399 §1).

D-429는 이것을 "로봇 제어" 관심사와 "중재·안전" 판단 층으로 묶었다. 그러면 안전이 판단(Arbiter)과 제어(단일 writer) 사이의 한 칸으로 읽힌다. 사용자는 안전을 판단과 제어 양쪽에서 떼어 별도 ADR로 세우는 쪽을 골랐다.

외부 근거(2026-10-03 조사 정리. 표준 원문은 유료라 이번에 직접 대조하지 못했다. 아래 1·2는 **미확인(2차 출처)**이다):

1. IEC 61508은 안전 기능과 비안전 기능 사이의 독립성을 물리적 또는 논리적 분리로 요구한다. *(미확인 — 2차 출처)*
2. ISO/IEC TR 5469는 기능 안전에서 AI를 쓰는 지침이다. AI 요소가 실패해도 안전 기능이 유지되도록 AI와 안전 기능을 분리하는 구성을 권한다. *(미확인 — 2차 출처)*
3. 학습 정책을 안전 기능으로 인정하는 표준 근거는 찾지 못했다(D-427 Context와 같은 결론).
4. Gemini Robotics-ER 문서는 안전 책임을 통합자(integrator)에 둔다. 모델은 사용자 정의 함수를 부르는 오케스트레이터다(https://ai.google.dev/gemini-api/docs/robotics-overview, D-429 외부 근거와 같은 출처).

### Decision

#### 1. 안전은 여섯째 관심사다

D-429 §1의 `concern:` 값에 `safety`를 더한다. 값은 `learning | decision | control | safety | contracts | other`다. 파트(D-427)와 폴더는 바꾸지 않는다. **안전 코드는 자기가 지키는 장치 옆에 남는다.** 로봇 안전은 middleware에, 사이트 장치 안전은 사이트 장치 펌웨어(D-429 §2의 `operations/site_devices/<kind>`)에, 사이트 정지는 Fleet에 있다. 안전을 한 폴더로 모으면 장치 위에서 Fleet·네트워크 없이 돌아야 하는 안전 기능이 원격 소유가 된다(D-399 대안 1의 기각 사유와 같다).

D-429의 매니페스트 root는 디렉터리 단위이고 가장 깊은 root가 이긴다. 안전 코드는 일부만 자기 디렉터리를 갖는다. 그래서 태그 방식은 둘이다.

- **디렉터리 root(하위 carve-out):** 안전만 담은 디렉터리는 하위 root로 떼어 `concern: safety`를 단다. part는 부모와 같다.
- **모듈 목록(`safety_modules:`):** 섞인 디렉터리 안의 안전 파일은 매니페스트의 모듈 경로 목록으로 태그한다. 폴더를 쪼개지 않기 위해서다. 시험(§3)은 이 목록을 safety로 본다.

현재 대응(wave 0 매니페스트 리뷰에서 확정):

| 대상 | 방식 | part (변경 없음) |
|---|---|---|
| `src/runtime/services/core_features/safety/` (`manager.py`, `fleet_loss.py`, `shadow.py`) | 하위 root, `import_prefix: [core_features.safety]` | middleware |
| `core_features/command/arbitration.py`, `core_features/command/manager.py` (E-stop·EMERGENCY 차단과 clip을 출력 선택에 거는 자리) | 모듈 목록 | middleware |
| `core_features/line_follow/body_stop.py`, `core_features/line_follow/clearance.py` | 모듈 목록 | middleware |
| `src/runtime/gateway/core/bridge/cmd_vel.py` (`cmd_vel_cycle`, 단일 writer 직전 경로) | 모듈 목록 | middleware |
| `src/contracts/foundation/core_common/robot_body.py` (D-424 몸) | 모듈 목록 | contracts |
| `src/products/omx/adapter/omx_adapter/command_owner.py`, `local_stop.py` | 모듈 목록 | middleware |
| `src/site/fleet/fleet/server/{dispatch_admission,cancel_all,cancel_all_store,local_stop_transport}.py`와 `console.py`의 정지 경로 | 모듈 목록. `console.py`는 섞인 파일이므로 wave 0에서 정지 경로를 떼어 낼지 리뷰한다(떼기 전에는 목록에 넣지 않는다) | operations |
| `firmware/signal/firmware`, `firmware/dock/firmware` | 하위 root (펌웨어 전체가 failsafe 소유자다) | operations (D-429 §2) |
| `src/runtime/sensing`의 레거시 `safety_node` | 태그하지 않는다. D-208의 단독 모드 예외이며 운영 경로가 아니다 | middleware |

`concern: safety`는 D-429의 다른 concern과 달리 **읽기 전용 view가 아니다.** §3의 분리 불변식과 §5의 변경 통제가 이 태그에 걸린다.

#### 2. 안전 체인

층마다 무엇을, 어떤 결정적 장치로, 누가 지키는지와 지금 상태를 적는다. "AI·네트워크 상실에 살아남는가"는 그 층이 모델·Fleet·Wi-Fi 없이 동작하는지다. 위에서 아래로 갈수록 장치에 가깝다. 아래 층은 위 층의 실패를 가정한다.

| 층 | 지키는 것 | 결정적 장치 | 소유 | AI·네트워크 상실에 살아남는가 | 증거 (ADR · 코드) | 현재 상태 |
|---|---|---|---|---|---|---|
| 7. 모델 도구 제한 | 모델이 움직임·정지·rearm·사이트 장치를 직접 일으키는 것 | 닫힌 도구 catalog(D-392 §3), 구동·안전 도구 금지(§4), `POLICY_DISPATCH_ENABLED=False`(§7) | Fleet (`operations/decision`) | 예. 제한은 모델 행동에 기대지 않는다. 모델이 끊기면 제안이 없을 뿐이다 | D-392, D-326, D-429 §3 · `src/site/fleet/fleet/server/task_service.py:24`, `src/site/fleet/test/test_model_tool_adapter_conformance.py:157` | 로봇 구동 이름 8개는 거부 시험에 있다. 사이트 장치 구동 이름(D-429 §3)은 아직 시험에 없다(D-429 wave 0) |
| 6. Fleet 정지·래치·fence·admission | 사이트 전체의 새 발행과 진행 중 동작, 늦은 모델 결과 | 단조 증가 stop generation 래치(D-330 §2), 발행 직전 세대 재확인, 후보 가시화와 stop 확인의 공유 SQLite 트랜잭션(D-358 §4), 래치 없는 취소와 래치형 비상 정지의 분리(D-421), 명시 rearm(`/api/fleet/dispatch/rearm`) | Fleet | AI 상실: 예. 네트워크 상실: **아니오**. Fleet 정지는 링크가 있어야 장치에 닿는다. 링크가 끊긴 장치는 층 3·4가 맡는다 | D-330, D-358, D-421, D-105, D-369 §5, D-298 · `console.py:897` `estop_all`, `cancel_all.py`, `dispatch_admission.py`, `local_stop_transport.py`, `test_dispatch_stop_latch.py`, `test_cancel_all.py` | SOURCE·호스트 시험. 응답(HTTP 200·`stopped` 수)은 물리 정지 증거가 아니다(D-298, D-369 §5). D-421은 Proposed |
| 5. Arbiter + MANUAL 선점 | 여러 명령 출처가 한 장치에서 다투는 것 | 장치당 Arbiter 하나, EMERGENCY > SAFETY > MANUAL > DOCKING > NAVIGATION > FLEET > IDLE, 모드 전이 표(EMERGENCY에서는 IDLE로만), 단일 최종 writer, 감지 프로파일은 속도를 내지 않음 | 장치 middleware (Pinky CORE, OMX 로컬 owner) | 예. 장치 위 순수 로직이다 | D-2, D-38, D-208, D-399 §1, D-104 · `arbitration.py:17-24,44-50`, `ros_bridge.py:3,84` | Pinky는 동작 중. OMX의 우선순위 표와 MANUAL phase 선점, Motion Intent 공통 스키마는 없다(D-399 후속 5, D-429 후속 1) |
| 4. 반응형 정책 엔벌로프 | 학습 정책(ACT·Diffusion·RL)과 미래 로컬 VLA의 출력 | 작업 영역·시간·속도·스텝 상한, 이탈·시간 초과는 HOLD, RL에서는 `terminated=True`(D-427 §5) | 장치 middleware (`middleware/skills`) | 예(같은 호스트 추론, D-399 §2) | D-399 §2, D-427 §5 | **없다.** 엔벌로프 스킬 계약(D-399 후속 1)이 쓰이지 않았다. 지금 장치에서 도는 학습 행동 정책도 없다. 이 층이 생기기 전에는 학습 정책을 실물에 연결하지 않는다 |
| 3. 장치 Safety Guard + D-400 정책 | 단일 writer로 나가는 모든 명령 | Pinky: E-stop 래치(SAF-001, 관리자 release), 속도 clip(SAF-004), teleop watchdog, 배터리(SAF-005), Fleet 상실 STOP/HOLD(SAF-003, D-419), 사람 자문은 상한을 **낮추기만**(SAF-006), 몸 기준 근접 정지(D-422·D-424), D-400 센서 정책(off·shadow·enforce). OMX: owner HOLD 래치, `StopLocal`·`RearmLocal`, 불명 결과 자동 재발행 금지(D-369 §3) | 장치 middleware | 예. ROS 무의존 결정적 코드이고 Fleet·모델 없이 돈다. Fleet 상실 자체가 이 층의 입력이다(D-419) | D-400, D-419, D-422, D-424, D-105, D-104, D-369 §3, D-336 · `safety/manager.py:278,421,479`, `safety/fleet_loss.py`, `safety/shadow.py`, `bridge/cmd_vel.py`, `command_owner.py:415,464`, `local_stop.py:177` | E-stop 래치·clip·watchdog·SAF-003(D-419 Accepted)은 동작 중. **D-400 센서 정책은 어느 로봇에서도 off이고, 구현은 그림자(계획 1)까지다. 집행은 켜지지 않았다.** G-sim은 호스트 부하로 미결이다. D-422·D-424는 Proposed. OMX 로컬 owner 수용(D-299)은 Proposed이고 실물 정지 수용은 없다 |
| 2. 사이트 장치 로컬 failsafe | 감독(Fleet)이 끊기거나 장치가 막 켜졌을 때의 사이트 장치 출력 | 신호등: 부팅 상태가 `failsafe`, 감독 상실 시 `failsafe`로 복귀, 토큰 없는 장치는 어떤 명령도 받지 않음. 도크: 리밋스위치가 안 눌리면 0 V(단일 개폐점 `setOutput`), 부팅 시 무전원, 폴트 래치는 부하 제거까지 | 사이트 장치 펌웨어 (`operations/site_devices/<kind>`) | 예. 펌웨어가 스스로 한다 | D-337 §3, D-349, D-350, D-351, D-429 §2·§4 · `rosy_signal.ino:45,66,118`, `firmware/signal/README.md`, `rosy_dock.ino:58-65,117,124,172` | 신호·도크 펌웨어는 계약 시험 수준이다. 현장 수용은 없다. 컨베이어·문·PLC는 아직 없다(D-429 후속 2·4) |
| 1. 물리 E-stop · 안전 회로 | 모든 동작 에너지 | 하드웨어 E-stop, 안전 relay·drive enable, safety PLC 회로. 소프트웨어와 무관 | 장치 하드웨어와 통합자 | 예(설계 의도). 소프트웨어 무관 | D-369 §5, D-399 §1, D-429 §4, D-427 §5 · (코드 없음, 의도) | **원칙만 있다.** Pinky·OMX의 독립 E-stop 회로가 저장소 증거로 확인되지 않았고 독립 E-stop 실측도 없다(D-427 §5 선행 조건 6). safety PLC는 없다 |

D-105의 호스트 정지(스페이스·보드 `/stop`)는 층 3의 E-stop 래치로 들어가는 사람 입력이다. 별도 층이 아니다.

#### 3. 분리 불변식 (wave 0 시험)

다음 불변식은 시험으로 강제한다. 시험이 들어오기 전에는 규칙이 발효되지 않는다(D-429 §4의 원칙과 같다). 대상은 `concern: safety` root와 `safety_modules:` 목록이다.

1. **안전은 판단·학습에 기대지 않는다.** safety 코드는 `decision`·`learning` 태그 코드, 모델 SDK(`google.genai`, `anthropic`, `openai`, `lerobot`, `torch`, `onnxruntime` 등), `integrations/models`를 import하지 않는다. 계약(`core_common.protocol.detections` 같은 contracts)은 import할 수 있다. 그 입력은 상한을 낮추거나 정지를 더하는 쪽으로만 쓴다(지금 SAF-006 사람 자문이 그렇다).
2. **판단·학습은 안전을 우회하지 않는다.** `decision`·`learning` 코드는 safety 내부를 import하지 않는다. 정지·rearm·한도 변경은 소유자의 공개 경로(CORE API, Fleet API, OMX UDS)로만 요청한다. 우회 경로(단일 writer 직접 호출, `cmd_vel` 발행, 래치 상태 쓰기)가 없어야 한다.
3. **모든 DeviceControlPort binding(D-429 §4)은 그 장치의 Safety Guard와 Arbiter 뒤에 있다.** 새 백엔드는 둘 없이 배선될 수 없다. 시험은 binding의 호출 사슬을 단정한다. Pinky는 `cmd_vel` publisher를 부르는 곳이 `ros_bridge.py`의 `_send_twist` 하나(`:431-435`)이고, 그것은 `cmd_vel_cycle`이 `CommandManager.select_output`(Arbiter 모드와 `SafetyManager`의 E-stop·clip·정책을 거친 값) 뒤에만 부른다. OMX는 `ActionPort.send_goal`을 부르는 곳이 `ArmCommandOwner`의 래치 확인 뒤 하나다.
4. **학습 정책(ACT·RL·VLA)과 모델 출력은 안전 기능으로 인정하지 않는다.** 안전 기능에 의해 제한될 수만 있다. 학습 인식(LaneUNet·YOLO 등)의 evidence가 안전 층에 들어오는 것은 더 보수적으로 만드는 입력일 때뿐이다. 학습 출력이 정지를 해제하거나, 상한을 올리거나, 결정적 판정(D-422 몸 기준 정지 등)을 대신하지 않는다.
5. **물리 E-stop은 소프트웨어에 기대지 않는다. ROSY는 안전 코일에 쓰지 않는다.** ROSY는 E-stop·safety PLC 상태를 읽을 수 있으나, 그 회로나 안전 코일·레지스터에 쓰거나 우회하지 않는다(D-429 §4와 같다). 미래 Modbus/PLC 어댑터는 안전 영역 주소를 쓰기 대상으로 갖지 않는다.

#### 4. fail-closed 규칙

Fleet·네트워크·모델·감독 중 무엇을 잃어도 장치는 안전 상태로 내려간다.

| 잃는 것 | 로봇 | 신호등 | 도크 |
|---|---|---|---|
| Fleet·네트워크 | D-419 SAF-003: 진행 중 Fleet 주행 목표를 취소(STOP 기본, HOLD는 물리적으로 같고 기록만 다름). 래치 없음 | 감독 상실 → `failsafe`(전 기능 적색 점멸, 진입 불허, D-337 §3) | 해당 없음. 도크에는 감독 링크가 없다(D-429 §2). 인터록은 국소다 |
| 모델 | 영향 없음. 모델은 동작 권한이 없다(층 7). 진행 중 턴은 stale | 영향 없음 | 영향 없음 |
| 장치 센서·정책 평가 | D-400 집행 시 HOLD(첫 판정 전, `stale_hold_s` 미만) → 그 이상은 E-stop 래치. 집행 전에는 이 규칙이 없다(층 3 상태) | — | 리밋 미눌림·폴트 → 0 V, 폴트 래치 |
| 장치 재부팅 | 정지 상태로 시작 | `failsafe`로 시작 | 0 V로 시작 |

- **자동 재개 없음.** 복귀는 기존 rearm 규칙만 쓴다. CORE E-stop은 관리자 `POST /api/v1/safety/release`, Fleet 래치는 `POST /api/fleet/dispatch/rearm`, OMX는 `RearmLocal`, SAF-003 뒤는 새 명령(D-419 §3)이다. 신호등은 인증된 감독의 명시 명령으로만 failsafe를 벗어난다. 도크 폴트는 부하 제거로만 풀린다. 링크가 돌아왔다는 사실만으로 동작이 재개되지 않는다.
- **`CONTINUE_CURRENT_NAVIGATION`.** D-419는 운영자가 고를 수 있는 이 정책을 둔다. 기본값(STOP)은 바꾸지 않는다. 이 값은 현재 목표를 끝내는 것뿐이며 새 목표·재개를 허용하지 않는다. 그래도 엄격한 fail-closed는 아니다. 이 ADR은 이를 예외로 기록하고, 사이트 프로필에서 쓸지 여부는 G-dev 증거와 함께 별도로 정한다.

#### 5. 변경 통제

safety 태그 코드(§1의 root와 모듈 목록)를 바꾸는 변경은 다음을 지킨다. 지금 저장소 관행에 맞춘 가벼운 규칙이다. 새 절차를 만들지 않는다.

- **독립 리뷰:** 작성 세션이 아닌 리뷰어(code-reviewer 또는 verifier 레인, D-172의 독립 리뷰와 같은 방식)가 승인한다. 같은 세션의 자기 승인은 인정하지 않는다.
- **gate 증거:** 해당 층의 기존 gate를 붙인다. 예: D-400 G-sim/G-dev/G-enforce, D-419 호스트 시험, Fleet 정지 래치 시험(`test_dispatch_stop_latch.py`·`test_cancel_all.py`), 펌웨어 계약 시험. 호스트 pytest 통과는 장치·실주행 수용이 아니다.
- **교훈 기록:** 리뷰가 안전 결함 종류를 잡으면 `docs/solutions/`에 `ce-compound` 노트를 남긴다(`design-patterns/`).
- **시험 표시:** §3 시험이 들어온 뒤에는 safety 태그 파일을 바꾸는 커밋이 그 시험을 통과해야 한다. 매니페스트에서 safety 태그를 빼는 변경도 같은 리뷰를 받는다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-429 (Accepted 2026-10-03) | `concern:` 값에 `safety`를 더한다. §1 표의 "중재·안전" 층은 판단 층으로 남되, 안전 체인은 이 ADR이 정본이다. D-429 본문의 안전 관련 자리(§1 중재·안전 행, §2 로봇의 소비·인터록 우선, §4 failsafe 의무·장치 로컬 failsafe·물리 E-stop/safety PLC 독립, 후속 2·4)에 D-430 포인터만 추가했다. 내용은 바꾸지 않았다. DeviceControlPort(§4)에 불변식 3을 건다 |
| D-427 (Accepted) | 파트·폴더·import 규칙을 바꾸지 않는다. §5의 실물 RL 선행 조건(엔벌로프, MANUAL 선점, 독립 E-stop 실측)은 이 체인의 층 4·5·1 상태와 같은 목록이다 |
| D-399 (Proposed) | §1 Safety Guard가 단일 writer 바로 앞이라는 배치와 "정지 계열이 모든 동작 출처보다 위"를 층 3·5로 계승한다. §2 엔벌로프를 층 4로 둔다. 후속 1·5가 이 ADR의 층 4·5를 채운다 |
| D-400 (Proposed) | 층 3의 센서 정책이다. off·shadow·enforce 모드와 gate를 바꾸지 않는다. 집행은 여전히 로봇별 사용자 승인이다 |
| D-369 (Accepted) | 역할 분리와 §5 물리 E-stop 독립을 층 1·3·6으로 계승한다. 응답이 정지 증거가 아니라는 규칙을 유지한다 |
| D-330, D-358, D-421 | 층 6이다. 유지한다 |
| D-419 (Accepted) | 로봇의 Fleet 상실 fail-closed 규칙이다. `CONTINUE_CURRENT_NAVIGATION`은 §4의 기록된 예외다 |
| D-392 (Accepted), D-326 | 층 7이다. 금지 목록과 밸브를 유지한다 |
| D-2, D-38, D-208 | 단일 writer와 감지 프로파일 무속도를 층 5로 유지한다 |
| D-104, D-105 | 호스트 arm의 한도 설정과 호스트 정지 입력을 층 3의 입력으로 둔다 |
| D-337 §3, D-349, D-351, D-200 | 층 2와 로봇 쪽 도킹. 신호 fail-closed 융합, 도크 리밋 인터록, 재시도 규칙, DOCKING 모드를 유지한다 |
| D-422, D-424 (Proposed) | 층 3의 결정적 근접 정지다. 불변식 4에 따라 학습 인식이 이 판정을 대신하지 않는다 |
| D-336, D-299 | OMX 로컬 stop·rearm 경계를 층 3으로 둔다 |
| D-172 | 독립 리뷰 관행을 §5에 쓴다 |

### Alternatives

- **D-429 그대로(안전은 control 관심사와 중재·안전 층):** 문서가 하나 덜 생긴다. 하지만 안전이 판단(Arbiter)·제어(writer)와 같은 칸에 묶여, 판단이나 제어를 바꾸는 변경이 안전 변경인지 보이지 않는다. 사용자 요청과 맞지 않는다. 기각.
- **최상위 `safety/` 폴더:** 폴더만 봐도 안전이 보인다. 하지만 장치 위에서 Fleet 없이 돌아야 하는 Safety Guard와 펌웨어 failsafe를 장치에서 떼게 된다. 설치 단위와도 어긋난다. 기각.
- **학습 정책을 안전 감시자로 인정(예: 학습 충돌 예측이 정지를 결정):** 인정할 표준 근거를 찾지 못했다. 보수 쪽 입력으로만 허용한다(불변식 4). 기각.
- **무거운 안전 절차(별도 안전 위원회, 서명 문서):** 지금 저장소 규모에 맞지 않고 지켜지지 않을 규칙이 된다. 독립 리뷰와 기존 gate 증거로 시작한다. 기각.
- **safety를 읽기 전용 view로만 둠(D-429의 다른 concern과 같게):** 태그만 있고 강제가 없으면 분리가 문서에만 남는다. 불변식 시험을 건다.

### Consequences

- 안전이 여섯째 관심사로 보이고, 층별 체인 표 하나로 "무엇이 무엇을 지키는가"와 "지금 어디가 비었는가"를 읽을 수 있다.
- safety 태그 코드의 변경은 독립 리뷰와 gate 증거가 필요해진다.
- 체인의 빈칸이 드러난다. 층 1(물리 E-stop)·층 4(엔벌로프)는 없고, 층 3의 D-400 센서 정책은 집행 전이며, 층 5의 OMX 선점과 층 7의 사이트 장치 이름은 시험 전이다.
- 매니페스트에 `safety_modules:` 목록이 생긴다. 디렉터리 root만으로는 섞인 파일을 태그할 수 없기 때문이다.

### Validation and Follow-up

이번 문서의 수용 조건은 ADR·Log 행의 일치, D-429 포인터 한 줄, 번호 충돌 부재, harness lint 0 error, `test/architecture` 통과다. 코드·폴더·매니페스트·wire 변경은 없다.

**Wave 0 (D-429 wave 0과 함께, 시험 이름은 제안):**

1. 매니페스트에 `concern: safety` 하위 root와 `safety_modules:` 목록을 넣는다(§1 표). `console.py` 정지 경로 분리 여부를 리뷰한다.
2. `test/architecture/test_safety_separation.py`
   - `test_safety_does_not_import_decision_learning_or_model_sdks` — 불변식 1
   - `test_decision_and_learning_do_not_import_safety_internals` — 불변식 2
   - `test_device_control_port_bindings_sit_behind_arbiter_and_safety_guard` — 불변식 3. Pinky `cmd_vel` publisher 호출자가 `_send_twist` 하나이고 그 호출자가 `cmd_vel_cycle` 하나, OMX `send_goal` 호출자가 `ArmCommandOwner` 하나임을 AST로 단정
   - `test_safety_manifest_tags_cover_named_modules` — §1 표의 경로가 모두 태그되어 있고 실재함
3. `src/runtime/services/test/` 또는 해당 시험 폴더의 `test_learned_inputs_only_tighten_limits` — 불변식 4. 사람 자문·인식 evidence가 상한을 올리거나 래치를 풀지 못함
4. 불변식 5는 지금 쓸 코드가 없다. PLC/Modbus 어댑터 ADR(D-429 후속 4)이 `test_plc_adapter_never_writes_safety_addresses`를 함께 정한다.
5. D-429 wave 0의 사이트 장치 도구 거부 이름 추가(층 7)를 그대로 한다.

**후속:**

1. 물리 E-stop 실측: Pinky·OMX 회로 확인과 독립 E-stop 시험(D-427 §5 선행 조건 6). 결과에 따라 층 1 상태를 갱신한다.
2. D-400 계획 2·3: G-sim 재실행(유휴 호스트), G-dev, 로봇별 G-enforce.
3. D-399 후속 1(엔벌로프 스킬 계약)과 후속 5(Motion Intent·Arbiter·MANUAL 선점, D-429 후속 1과 합침).
4. `CONTINUE_CURRENT_NAVIGATION`을 사이트 프로필에서 허용할지(§4).

**References:** [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-400](D-400-core-safety-policy-off-shadow-enforce.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-105](D-105-stop-safety-stop.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md), [D-421](D-421-fleet-cancel-all-driving-separate-from-latched-estop.md), [D-422](D-422-line-follow-body-referenced-obstacle-stop.md), [D-424](D-424-one-robot-body-for-every-near-check.md), [D-104](D-104-arm-manual-put-safety-limits.md), [D-2](D-2-cmd-vel.md), [D-38](D-38-core.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-326](D-326-agent-loop-boundary.md), [D-337](D-337-robot-signal-source-measured-light.md), [D-349](D-349-dock-auto-charge-code-readiness.md), [D-351](D-351-docking-retry-by-failure-kind.md), [D-200](D-200-docking-owns-the-docking-mode.md), [D-419](D-419-saf003-fleet-link-loss-policy.md), [D-208](D-208-sensing-profile-publishes-no-velocity.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-172](D-172-archived-branch-port-closure.md), [소유 매니페스트](../../tools/harness/platform_parts.yaml)
