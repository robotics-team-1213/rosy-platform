## D-430 안전은 판단·제어와 분리된 여섯째 관심사이며, 층별 안전 체인과 분리 불변식으로 지킨다

**Status:** Proposed (2026-10-03, 사용자 요청 — 안전을 별도 관심사로). [D-429](D-429-five-concerns-control-port-and-site-devices.md)(Accepted 2026-10-03)의 다섯 관심사 view에 `safety`를 더하고, D-429 §1 표의 "중재·안전" 층에서 안전을 떼어 별도 체인으로 기술한다. 독립 리뷰와 사용자 승인 뒤 Accepted로 올린다. 이번 변경은 문서뿐이다. 코드·폴더 이전·매니페스트 수정·wire 변경·실기 gate 변화는 없다. D-400 집행, 물리 E-stop, DEVICE/FIELD 수용을 승인하지 않는다.

### Context

사용자는 2026-10-03 "무언가를 제어할 때 안전을 고려하고 있는가"를 물었다. 고려는 하고 있다. 다만 층마다 흩어져 있다.

- 로봇 위: CORE `SafetyManager`(SAF-001 E-stop 래치, SAF-004 속도 상한, SAF-005 배터리, SAF-003 Fleet 상실, SAF-006 사람 자문; `src/runtime/services/core_features/safety/manager.py:278`), D-400 센서 정책(`shadow.py`, 기본 off), D-422·D-424 몸 기준 근접 정지(`core_features/line_follow/body_stop.py`, `core_common/robot_body.py`), Arbiter 우선순위(`core_features/command/arbitration.py:17-24`), 단일 writer(`src/runtime/gateway/core/bridge/ros_bridge.py:3,84`, D-2·D-38).
- 팔 위: OMX `ArmCommandOwner`의 HOLD 래치(`src/products/omx/adapter/omx_adapter/command_owner.py:415,464`)와 `local_stop.py`의 rearm(`:177`).
- 사이트: Fleet 정지 세대 래치(D-330), 후보 fence(D-358 §4), 래치 없는 전체 주행 취소와 래치형 전체 비상 정지의 분리(D-421, `src/site/fleet/fleet/server/console.py:897`, `cancel_all.py`), 모델 도구 금지(D-392 §4·§7).
- 사이트 장치: 신호등 펌웨어의 부팅·감독 상실 failsafe(`firmware/signal/firmware/rosy_signal/rosy_signal.ino:66,118`), 도크 리밋스위치 인터록과 부팅 시 0 V(`firmware/dock/firmware/rosy_dock/rosy_dock.ino:58-65,117,172`, D-349).
- 물리 E-stop은 원칙만 있다(D-369 §5, D-399 §1).

D-429는 이것을 "로봇 제어" 관심사와 "중재·안전" 판단 층으로 묶었다. 그러면 안전이 판단(Arbiter)과 제어(단일 writer) 사이의 한 칸으로 읽힌다. 실제로 Arbiter 안에도 두 성격이 섞여 있다. EMERGENCY 전이 표와 출력 선택 때의 E-stop·clip은 안전이고, 출처 우선순위 등록(teleop·nav·line follow 순서)은 제어다. 사용자는 안전을 판단과 제어 양쪽에서 떼어 별도 ADR로 세우는 쪽을 골랐다.

외부 근거(2026-10-03 조사 정리. 표준 원문은 유료라 이번에 직접 대조하지 못했다. 아래 1·2는 **미확인(2차 출처)**이다):

1. IEC 61508은 안전 기능과 비안전 기능 사이의 독립성을 물리적 또는 논리적 분리로 요구한다. *(미확인 — 2차 출처)*
2. ISO/IEC TR 5469는 기능 안전에서 AI를 쓰는 지침이다. AI 요소가 실패해도 안전 기능이 유지되도록 AI와 안전 기능을 분리하는 구성을 권한다. *(미확인 — 2차 출처)*
3. 더 구체적인 제품 표준: 이동 로봇은 ISO 3691-4(무인 산업 트럭)·ISO 13482(개인 돌봄 로봇), 팔은 ISO 10218(산업용 로봇). *(미확인 — 이번에 내용을 대조하지 않았다)*
4. 학습 정책을 안전 기능으로 인정하는 표준 근거는 찾지 못했다(D-427 Context와 같은 결론).
5. Gemini Robotics-ER 문서는 안전 책임을 통합자(integrator)에 둔다. 모델은 사용자 정의 함수를 부르는 오케스트레이터다(https://ai.google.dev/gemini-api/docs/robotics-overview, D-429 외부 근거와 같은 출처).

표준 인용은 설계 방향의 **맥락**이다. ROSY가 어떤 표준을 준수한다는 주장이 아니며, 이 ADR은 인증·적합성 평가를 하지 않는다.

### Decision

#### 1. 안전은 여섯째 관심사다

D-429 §1의 `concern:` 값에 `safety`를 더한다. 값은 `learning | decision | control | safety | contracts | other`다. 파트(D-427)와 폴더는 바꾸지 않는다. **안전 코드는 자기가 지키는 장치 옆에 남는다.** 로봇 안전은 middleware에, 사이트 장치 안전은 사이트 장치 펌웨어(D-429 §2의 `operations/site_devices/<kind>`)에, 사이트 정지는 Fleet에 있다. 안전을 한 폴더로 모으면 장치 위에서 Fleet·네트워크 없이 돌아야 하는 안전 기능이 원격 소유가 된다(D-399 대안 1의 기각 사유와 같다).

D-429의 매니페스트 root는 디렉터리 단위이고 가장 깊은 root가 이긴다. 안전 코드는 일부만 자기 디렉터리를 갖는다. 그래서 태그 방식은 둘이다.

- **디렉터리 root(하위 carve-out):** 안전만 담은 디렉터리는 하위 root로 떼어 `concern: safety`를 단다. part는 부모와 같다.
- **모듈 목록(`safety_modules:`):** 섞인 디렉터리 안의 안전 파일은 매니페스트의 모듈 경로 목록으로 태그한다. 폴더를 쪼개지 않기 위해서다. 시험(§3)은 이 목록을 safety로 본다.

현재 대응(wave 0 매니페스트 리뷰에서 확정). part는 **현재 매니페스트 값**이다. `firmware/dock`·`firmware/signal`은 지금 part `middleware`(`tools/harness/platform_parts.yaml`의 두 항목, `d427_target: middleware/firmware/{dock,signal}`)이고, D-429 §2의 operations 재지정은 wave 0 매니페스트 변경에서 일어난다.

| 대상 | 방식 | part (현재) | 심볼 앵커 (모듈 경로로 한정) |
|---|---|---|---|
| `src/runtime/services/core_features/safety/` (`manager.py`, `fleet_loss.py`, `shadow.py`) | 하위 root, `import_prefix: [core_features.safety]` | middleware | `core_features.safety.manager.SafetyManager`, `core_features.safety.fleet_loss.FleetLossMonitor`, `core_features.safety.shadow.ShadowLog` |
| `src/runtime/gateway/core/fleet_loss_wiring.py` | 모듈 목록 | middleware | (모듈 수준 배선 함수) |
| `core_features/command/manager.py` (출력 선택에서 E-stop·EMERGENCY 차단과 clip 적용) | 모듈 목록 (U1: safety) | middleware | `core_features.command.manager.CommandManager` |
| `core_features/command/arbitration.py` | 모듈 목록 (U1: 섞인 파일. EMERGENCY 전이는 safety, 출처 우선순위 등록은 control) | middleware | safety 앵커: `core_features.command.arbitration.ModeMachine`, `core_features.command.arbitration._ALLOWED`. 이름만으로는 안 된다. `_ALLOWED`는 `fleet/server/policy_evidence_config.py:17`·`sightings_config.py:19`에도 있다. control 심볼 `Priority`·`DEFAULT_SOURCES`·`SourceRegistry`는 앵커가 아니다 |
| `core_features/line_follow/body_stop.py`, `core_features/line_follow/clearance.py` | 모듈 목록 | middleware | `core_features.line_follow.body_stop.BodyStopMixin` |
| `src/runtime/gateway/core/bridge/cmd_vel.py` (`cmd_vel_cycle`, 단일 writer 직전 경로) | 모듈 목록 | middleware | `core.bridge.cmd_vel.cmd_vel_cycle` |
| `src/runtime/api_web/core_api_web/api/v1/safety.py` (E-stop·release `:33-38`, PUT limits `:124`) | 모듈 목록 | middleware | `core_api_web.api.v1.safety.safety_release`, `core_api_web.api.v1.safety.safety_limits` |
| `src/contracts/foundation/core_common/robot_body.py` (D-424 몸) | 모듈 목록 | contracts | `core_common.robot_body.RobotBody` |
| `src/products/omx/adapter/omx_adapter/command_owner.py`, `local_stop.py`, `action_api.py`의 `LocalStopApi` | 모듈 목록 (`action_api.py`는 섞인 파일) | middleware | `omx_adapter.command_owner.ArmCommandOwner`, `omx_adapter.local_stop.LocalStopController`, `omx_adapter.action_api.LocalStopApi`(`.dispatch`가 처리기). `StopLocal`·`RearmLocal`은 심볼이 아니라 UDS 연산 문자열(`action_api.py:206,228`)이므로 **문자열 앵커**로 따로 적고, 시험은 그 리터럴이 `LocalStopApi` 안에 있는지 본다 |
| `src/site/fleet/fleet/server/{dispatch_admission,cancel_all,cancel_all_store,local_stop_transport}.py`, `task_dispatch_routes.py`의 rearm 처리기, `console.py`의 `estop_all` | 모듈 목록. `console.py`·`task_dispatch_routes.py`는 섞인 파일이다. 파일 전체가 태그되므로 그 파일의 decision import는 §3 동결 목록에 들어가고, 정지 경로를 하위 root로 떼는 carve로 줄인다(Validation) | operations | `fleet.server.console.FleetConsole.estop_all`(`console.py:897`), `fleet.server.task_dispatch_routes.dispatch_rearm` — 라우트 팩토리 안의 **중첩 함수**다(`task_dispatch_routes.py:122`). 앵커 탐색은 모듈 최상위만이 아니라 중첩 정의까지 AST로 걷는다 |
| `firmware/signal/firmware`, `firmware/dock/firmware` | 하위 root (펌웨어 전체가 failsafe 소유자다) | middleware (D-429 §2 재지정 대기) | — (펌웨어, Python 앵커 없음) |
| `src/runtime/sensing`의 레거시 `safety_node` | 태그하지 않는다. D-208의 단독 모드 예외이며 운영 경로가 아니다 | middleware | — |

- **섞인 파일.** 모듈 목록은 파일 단위이므로 섞인 파일은 파일 전체가 §5 변경 통제를 받는다. 앵커는 그 파일이 safety인 이유가 되는 심볼만 적는다.
- **하위 root의 `d427_target`.** 부모와 같은 part·`d427_target`을 가진 하위 root는 `test_nested_roots_change_part_or_target`(`test/architecture/test_platform_parts.py`)에 걸린다. 그래서 safety 하위 root는 부모와 다른 자기 `d427_target`을 가진다(예: `middleware/core/safety`, `middleware/firmware/signal/firmware`).
- **드리프트 방지.** `safety_modules:`는 파일 경로라서 파일이 쪼개지거나 이름이 바뀌면 조용히 낡는다. 매니페스트는 레거시 경로 스캔에서도 빠져 있다. 그래서 각 항목에 심볼 앵커(위 표)를 둔다. wave 0 시험이 앵커마다 정의 파일을 찾아(root 기준 상대 경로) 그 파일이 safety로 태그됐는지 단정한다.

`concern: safety`는 D-429의 다른 concern과 달리 **읽기 전용 view가 아니다.** §3의 분리 불변식과 §5의 변경 통제가 이 태그에 걸린다.

#### 2. 안전 체인

층마다 무엇을, 어떤 결정적 장치로, 누가 지키는지와 지금 상태를 적는다. "AI·네트워크 상실에 살아남는가"는 그 층이 모델·Fleet·Wi-Fi 없이 동작하는지다. 위에서 아래로 갈수록 장치에 가깝다. 아래 층은 위 층의 실패를 가정한다.

| 층 | 지키는 것 | 결정적 장치 | 소유 | AI·네트워크 상실에 살아남는가 | 증거 (ADR · 코드) | 현재 상태 |
|---|---|---|---|---|---|---|
| 7. 모델 도구 제한 | 모델이 움직임·정지·rearm·사이트 장치를 직접 일으키는 것 | 닫힌 도구 catalog(D-392 §3), 구동·안전 도구 금지(§4), `POLICY_DISPATCH_ENABLED=False`(§7) | Fleet (`operations/decision`) | 예. 제한은 모델 행동에 기대지 않는다. 모델이 끊기면 제안이 없을 뿐이다 | D-392, D-326, D-429 §3 · `src/site/fleet/fleet/server/task_service.py:24`, `src/site/fleet/test/test_model_tool_adapter_conformance.py:157` | 로봇 구동 이름 8개는 거부 시험에 있다. 사이트 장치 구동 이름(D-429 §3)은 아직 시험에 없다(D-429 wave 0) |
| 6. Fleet 정지·래치·fence·admission | 사이트 전체의 새 발행과 진행 중 동작, 늦은 모델 결과 | 단조 증가 stop generation 래치(D-330 §2), 발행 직전 세대 재확인, 후보 가시화와 stop 확인의 공유 SQLite 트랜잭션(D-358 §4), 래치 없는 취소와 래치형 비상 정지의 분리(D-421), 명시 rearm(`/api/fleet/dispatch/rearm`) | Fleet | AI 상실: 예. 네트워크 상실: **아니오**. Fleet 정지는 링크가 있어야 장치에 닿는다. 링크가 끊긴 장치는 층 3·4가 맡는다 | D-330, D-358, D-421, D-105, D-369 §5, D-298 · `console.py:897` `estop_all`, `cancel_all.py`, `dispatch_admission.py`, `local_stop_transport.py`, `test_dispatch_stop_latch.py`, `test_cancel_all.py` | SOURCE·호스트 시험. 응답(HTTP 200·`stopped` 수)은 물리 정지 증거가 아니다(D-298, D-369 §5). D-421은 Proposed |
| 5. Arbiter + MANUAL 선점 | 여러 명령 출처가 한 장치에서 다투는 것 | safety 부분: EMERGENCY 전이 표(어디서든 진입, 해제는 `release_emergency`로만 IDLE; `ModeMachine`, `_ALLOWED`)와 출력 선택 시 E-stop·clip 적용(`CommandManager`). control 부분: 출처 우선순위 등록 EMERGENCY > SAFETY > MANUAL > DOCKING > NAVIGATION > FLEET > IDLE(`Priority`, `DEFAULT_SOURCES`, `SourceRegistry`). 단일 최종 writer, 감지 프로파일은 속도를 내지 않음 (사용자 결정 U1) | 장치 middleware (Pinky CORE, OMX 로컬 owner) | 예. 장치 위 순수 로직이다 | D-2, D-38, D-208, D-399 §1, D-104 · `arbitration.py:17-24,44-50`, `ModeMachine`·`release_emergency`, `command/manager.py`, `ros_bridge.py:3,84` | Pinky는 동작 중. OMX의 우선순위 표와 MANUAL phase 선점, Motion Intent 공통 스키마는 없다(D-399 후속 5, D-429 후속 1) |
| 4. 반응형 정책 엔벌로프 | 학습 정책(ACT·Diffusion·RL)과 미래 로컬 VLA의 출력 | 작업 영역·시간·속도·스텝 상한, 이탈·시간 초과는 HOLD, RL에서는 `terminated=True`(D-427 §5) | 장치 middleware (`middleware/skills`) | 예(같은 호스트 추론, D-399 §2) | D-399 §2, D-427 §5 | **없다.** 엔벌로프 스킬 계약(D-399 후속 1)이 쓰이지 않았다. 지금 장치에서 도는 학습 행동 정책도 없다. 이 층이 생기기 전에는 학습 정책을 실물에 연결하지 않는다 |
| 3. 장치 Safety Guard + D-400 정책 | 단일 writer로 나가는 명령. 단, 항목마다 적용 범위가 다르다 | Pinky, 모든 출처: E-stop 래치(SAF-001, 관리자 release), 속도 clip(SAF-004), 배터리(SAF-005). MANUAL: teleop watchdog(SAF-002). Fleet 주행 목표: Fleet 상실 정책(SAF-003, D-419; 기본 STOP, `RETURN_HOME`·`CONTINUE`는 §4의 기록된 예외이며 로봇별 승인 필요). 상한 조이기: 사람 자문(SAF-006, 낮추기만). **라인 추종만:** 몸 기준 근접 정지(D-422 `BodyStopMixin`은 `LineFollowManager` mixin이다, `body_stop.py:1`, `line_follow/manager.py:12`. teleop·Nav2 주행은 막지 않는다. D-424의 몸은 다른 근접 판정과 공유). 집행 시 모든 출처: D-400 센서 정책(off·shadow·enforce). OMX: owner HOLD 래치, `StopLocal`·`RearmLocal`, 불명 결과 자동 재발행 금지(D-369 §3) | 장치 middleware | 예. ROS 무의존 결정적 코드이고 Fleet·모델 없이 돈다. Fleet 상실 자체가 이 층의 입력이다(D-419) | D-400, D-419, D-422, D-424, D-105, D-104, D-369 §3, D-336 · `safety/manager.py:278,421,479`, `safety/fleet_loss.py:29`, `safety/shadow.py`, `core/fleet_loss_wiring.py`, `command/manager.py`, `bridge/cmd_vel.py`, `core_api_web/api/v1/safety.py`, `command_owner.py:415,464`, `local_stop.py:177` | E-stop 래치·clip·watchdog·SAF-003(D-419 Accepted)은 동작 중. **D-400 센서 정책은 어느 로봇에서도 off이고, 구현은 그림자(계획 1)까지다. 집행은 켜지지 않았다.** G-sim은 호스트 부하로 미결이다. D-422·D-424는 Proposed. Nav2·teleop 경로에는 몸 기준 근접 정지가 없다(D-400 집행 전까지 센서 기반 정지 없음). OMX 로컬 owner 수용(D-299)은 Proposed이고 실물 정지 수용은 없다 |
| 2. 사이트 장치 로컬 failsafe | 감독(Fleet)이 끊기거나 장치가 막 켜졌을 때의 사이트 장치 출력 | 신호등: 부팅 상태가 `failsafe`, 감독 상실 시 `failsafe`로 복귀, 토큰 없는 장치는 어떤 명령도 받지 않음. 도크: 리밋스위치가 안 눌리면 0 V(단일 개폐점 `setOutput`), 부팅 시 무전원, 폴트 래치는 부하 제거까지 | 사이트 장치 펌웨어 (`operations/site_devices/<kind>`) | 예. 펌웨어가 스스로 한다 | D-337 §3, D-349, D-350, D-351, D-429 §2·§4 · `rosy_signal.ino:45,66,118`, `firmware/signal/README.md`, `rosy_dock.ino:58-65,117,124,172` | 신호·도크 펌웨어는 계약 시험 수준이다. 현장 수용은 없다. 컨베이어·문·PLC는 아직 없다(D-429 후속 2·4) |
| 1. 물리 E-stop · 안전 회로 | 모든 동작 에너지 | 하드웨어 E-stop, 안전 relay·drive enable, safety PLC 회로. 소프트웨어와 무관 | 장치 하드웨어와 통합자 | 예(설계 의도). 소프트웨어 무관 | D-369 §5, D-399 §1, D-429 §4, D-427 §5 · (코드 없음, 의도) | **원칙만 있다.** Pinky·OMX의 독립 E-stop 회로가 저장소 증거로 확인되지 않았고 독립 E-stop 실측도 없다(D-427 §5 선행 조건 6). safety PLC는 없다 |

D-105의 호스트 정지(스페이스·보드 `/stop`)는 층 3의 E-stop 래치로 들어가는 사람 입력이다. 별도 층이 아니다.

#### 3. 분리 불변식 (wave 0 시험)

다음 불변식은 시험으로 강제한다. 시험이 들어오기 전에는 규칙이 발효되지 않는다(D-429 §4의 원칙과 같다). 대상은 `concern: safety` root와 `safety_modules:` 목록이다.

**safety 공개 API와 내부.** 다른 코드는 safety의 **공개 진입점**만 부를 수 있다. 공개 진입점은 매니페스트의 앵커 목록에 `public: true`로 표시한다. 판정 기준: 호출자가 부르거나 처리해야 하는 진입점·예외·fence 타입·사유 상수는 공개다. 스키마 생성·입력 정규화 같은 구현 보조는 내부다. 시작 목록:

- CORE: `SafetyManager`의 `trigger_estop`·`release`·`clip`·`set_session_speed`·`set_person_advisory`, `ModeMachine.release_emergency`·`is_emergency`, `FleetLossMonitor.tick`
- Fleet `dispatch_admission`: `reserve`, `release`(admission claim 진입점)
- Fleet `cancel_all`: `cancel_all_driving`, `DriveCancelFence`(fence 타입), `DispatchCanceled`·`DispatchWithdrawn`(호출자가 처리할 예외)
- Fleet `cancel_all_store`: `CANCEL_ALL_REASON`(사유 상수), `matching_tag`(fence 표시 일치 판정, D-421 HOLD 투영이 부름)
- Fleet `local_stop_transport`: `UnixLocalStopTransport`(앱 조립이 만드는 전송)
- Fleet `console.estop_all`, rearm 처리기
- OMX: `LocalStopController`, `LocalStopApi`의 `StopLocal`·`RearmLocal`

내부(래치 필드, 정책 바인딩, 그림자 기록, 저장소 행 쓰기, `cancel_all_store.ensure_schema`, `dispatch_admission.normalize_resources`)는 safety 코드끼리만 쓴다.

**현재 위반의 동결.** D-429는 `src/site/fleet` 전체를 `decision`으로 태그한다. 그래서 첫날부터 edge가 있다. 2026-10-03 이 브랜치 기준 grep 결과다(edge = importer 파일 → import 대상 모듈).

- **허용(공개 진입점):** `app.py:32,38`(`DriveCancelFence`, `UnixLocalStopTransport`), `task_dispatch_routes.py:22`(`DriveCancelFence`, `cancel_all_driving`), `task_results.py:11-13`(`CANCEL_ALL_REASON`, `matching_tag`, `release`), `task_service.py:12-13`(`DispatchCanceled`, `DispatchWithdrawn`, `CANCEL_ALL_REASON`), `task_store.py:16-17`(`release`, `reserve`), `mission_store.py:21-22`(`release`, `reserve`), `cell_job_store.py:15-16`(`release`, `reserve`).
- **`KNOWN_SAFETY_VIOLATIONS`에 고정(18건):**
  - decision → safety 내부 (2): `task_store.py:15` → `cancel_all_store.ensure_schema`; `cell_job_store.py:17` → `dispatch_admission.normalize_resources`
  - safety → decision, `cancel_all.py` (2): `:28` → `fleet.server.console_view`; `:29` → `fleet.swarm.transport`
  - 섞인 파일 `console.py` → decision (9): `:31` `fleet.formation.geometry`, `:32` `fleet.hub.hub`, `:33` `fleet.localization`, `:34` `fleet.server.bays`, `:34` `fleet.server.traffic`, `:35` `fleet.server.console_view`, `:38` `fleet.swarm.session`, `:44` `fleet.swarm.robots`, `:45` `fleet.swarm.transport`
  - 섞인 파일 `task_dispatch_routes.py` → decision (5): `:21` `fleet.hub.hub`, `:23` `fleet.server.http_errors`, `:24` `fleet.server.site_auth`, `:25` `fleet.server.task_store`, `:26` `fleet.swarm.transport`
- 로봇 쪽 safety 태그 파일은 지금 decision 태그 코드를 import하지 않는다(0건).

목록은 `test_platform_parts.py`의 `KNOWN_VIOLATIONS`와 같은 방식(집합 동등, 줄이기만)으로 검사한다. 그래서 wave 0 시험은 첫날 녹색이고 줄어들기만 한다. 섞인 파일 14건과 `cancel_all.py` 2건은 Fleet 정지 경로를 자기 하위 root로 떼는 carve로 줄인다(Validation wave 0 2). 내부 edge 2건은 공개 진입점 뒤로 옮겨 줄인다.

**로봇 쪽 대상.** 지금 `core_features` 안에는 decision 태그 root가 없어서 불변식 2가 아무것도 검사하지 않는다. wave 0에서 `core_features/decision`(D-429 §1의 "장치 지역 규칙")에 `concern: decision`을 달아 로봇 쪽 검사 대상을 만든다. 각 불변식 시험은 검사한 importer가 하나 이상인지도 단정한다(공허한 통과 방지).

1. **안전은 판단·학습에 기대지 않는다.** safety 코드는 `decision`·`learning` 태그 코드, 모델 SDK(`google.genai`, `anthropic`, `openai`, `lerobot`, `torch`, `onnxruntime` 등), `integrations/models`를 import하지 않는다(`KNOWN_SAFETY_VIOLATIONS` 제외). 계약(`core_common.protocol.detections` 같은 contracts)은 import할 수 있다. 그 입력은 상한을 낮추거나 정지를 더하는 쪽으로만 쓴다(SAF-006, §4 인식 규칙).
2. **판단·학습은 안전을 우회하지 않는다.** `decision`·`learning` 코드는 safety의 공개 진입점만 부른다. 정지·rearm·한도 변경은 소유자의 공개 경로(CORE API, Fleet API, OMX UDS)로만 요청한다. 단일 writer 직접 호출, `cmd_vel` 발행, 래치 상태 쓰기 경로가 없어야 한다.
3. **모든 DeviceControlPort binding(D-429 §4)은 그 장치의 Safety Guard와 Arbiter 뒤에 있다.** 호출 그래프 AST로 "뒤에 있음"을 증명하려 하지 않는다. 그런 시험은 거짓 안심을 준다. 대신 둘로 나눈다.
   - (a) **구조:** 대상은 **운영 소스**다. `test/` 디렉터리(가짜 그래프를 만드는 시험, 예: `src/runtime/gateway/test/test_absorption_output_graph.py:81`)와 Gazebo 벤치 도구 `src/runtime/sensing/tools/gz/`(예: `driver.py:91`)는 경로로 명시해 뺀다. 둘 다 장치 운영 경로에서 최종 명령을 내지 않기 때문이고, 패턴이 아니라 경로 목록으로 빼서 새 예외가 조용히 생기지 않게 한다. 그 범위에서 `"cmd_vel"` 문자열로 publisher를 만드는 곳이 `ros_bridge.py` 하나이고, `cmd_vel_pub`을 만지는 함수가 `_send_twist`(`ros_bridge.py:431-435`) 하나다. 리터럴 검사만으로는 파라미터 기본값을 못 본다. 그래서 검사를 **`declare_parameter(..., "cmd_vel")`처럼 기본값이 `"cmd_vel"`인 선언까지 넓힌다.** 그러면 레거시 `src/runtime/sensing/control/safety/node.py:89`(`cmd_out` 기본 `cmd_vel`, D-208 단독 모드 예외)가 잡히고, 그것만 allowlist에 둔다. OMX는 `ActionPort.send_goal` 호출자가 `ArmCommandOwner` 하나다.
   - (b) **행동:** E-stop이 걸리면 모든 출처(MANUAL·NAVIGATION·DOCKING·FLEET·swarm)의 출력이 0이고, 래치 해제 전 어떤 출처도 0이 아닌 값을 못 낸다. E-stop이 없으면 clip이 적용된다.
   - **리뷰 전용 규칙(기계 검사 아님):** 파라미터·launch remap으로 다른 노드의 출력 토픽을 `cmd_vel`로 바꾸는 변경은 safety 변경으로 보고 §5 리뷰를 받는다.
4. **학습 정책(ACT·RL·VLA)과 모델 출력은 안전 기능으로 인정하지 않는다.** 안전 기능에 의해 제한될 수만 있다. 학습 인식 evidence가 안전 층에 들어오는 것은 더 조이는 입력일 때뿐이다. 학습 출력이 정지를 해제하거나 기본 프로필보다 상한을 올리지 않는다(시험 가능, Validation wave 0 4). 학습 출력이 결정적 판정(D-422 몸 기준 정지 등)을 **대신하지 않는다**는 부분은 리뷰 전용 규칙이다.
5. **물리 E-stop은 소프트웨어에 기대지 않는다. ROSY는 안전 코일에 쓰지 않는다.** ROSY는 E-stop·safety PLC 상태를 읽을 수 있으나, 그 회로나 안전 코일·레지스터에 쓰거나 우회하지 않는다(D-429 §4와 같다). 미래 Modbus/PLC 어댑터는 안전 영역 주소를 쓰기 대상으로 갖지 않는다. 이 시험은 이 ADR이 소유한다(Validation).

#### 4. fail-closed 규칙

Fleet·네트워크·모델·감독 중 무엇을 잃어도 장치는 안전 상태로 내려간다. 예외는 아래에 기록한 것뿐이다.

| 잃는 것 | 로봇 | 신호등 | 도크 |
|---|---|---|---|
| Fleet·네트워크 | D-419 SAF-003: 정책은 `STOP`(기본)·`HOLD`·`RETURN_HOME`·`CONTINUE`(`fleet_loss.py:29` `POLICIES`). STOP·HOLD는 진행 중 Fleet 주행 목표를 취소한다(물리적으로 같고 기록만 다름). 래치 없음. `RETURN_HOME`·`CONTINUE`는 아래 기록된 예외 | 감독 상실 → `failsafe`(전 기능 적색 점멸, 진입 불허, D-337 §3) | 해당 없음. 도크에는 감독 링크가 없다(D-429 §2). 인터록은 국소다 |
| 모델 | 영향 없음. 모델은 동작 권한이 없다(층 7). 진행 중 턴은 stale | 영향 없음 | 영향 없음 |
| 인식(사람 자문 등) | 자문을 버리고 상한이 **기본 프로필로 돌아간다**(`PersonAdvisoryFeed`, `manager.py:218-274`). fail-closed가 아니다. 아래 인식 규칙 | 해당 없음 | 해당 없음 |
| 장치 센서·정책 평가 | D-400 집행 시: 첫 판정 전과 `stale_hold_s` 미만은 HOLD(자동 재개), 그 이상은 E-stop 래치. **D-400이 off인 지금은 규칙 없음**(층 3 상태) | 해당 없음 | 리밋 미눌림·폴트 → 0 V, 폴트 래치 |
| 장치 재부팅 | 정지 상태로 시작 | `failsafe`로 시작 | 0 V로 시작 |

- **래치된 정지는 자동으로 풀리지 않는다.** 대상은 래치 정지다: CORE E-stop(관리자 `POST /api/v1/safety/release`), Fleet 발행 래치(`POST /api/fleet/dispatch/rearm`), 사이트 정지(D-330·D-421 `estop`), OMX owner HOLD 래치(`RearmLocal`), 신호등 failsafe(인증된 감독의 명시 명령), 도크 폴트(부하 제거). 링크가 돌아왔다는 사실만으로 이것들이 풀리지 않는다.
- **래치 없는 HOLD는 자기 조건이 풀리면 스스로 풀릴 수 있다.** 예: D-400 stale HOLD(`stale_hold_s` 미만), `cmd_vel.py:65`의 준비 전 0 출력, teleop watchdog(SAF-002). 이것은 래치가 아니며 이 규칙의 위반이 아니다. SAF-003 STOP·HOLD 뒤의 재출발은 새 명령뿐이다(D-419 §3).
- **인식 규칙.** (1) 기본 프로필은 인식 없이도 안전해야 한다. 상한·E-stop은 인식 없이 성립한다. (2) 인식을 잃으면 기본 프로필로 돌아간다. 이것은 fail-closed가 아니라 "더 조이지 않음"이다. (3) SAF-006 사람 자문은 안전 기능이 아니라 조이기다. 기본 프로필을 대체하지 않는다.
- **Fleet 상실 기본은 `STOP`이다(사용자 결정 U2, 2026-10-03).** 아래 두 값은 fail-closed의 기록된 예외다. D-419 정의를 그대로 옮긴다.
  - **예외 1 — `CONTINUE`(`CONTINUE_CURRENT_NAVIGATION`):** 목표를 그대로 두고 이벤트만 낸다. 끊긴 동안 들어오는 새 Fleet 목표도 막지 않는다(D-419 §3, 결정 1과 같은 이유). 로봇은 Fleet 교통정리 없이 계속 달린다.
  - **예외 2 — `RETURN_HOME`:** Fleet 목표를 취소하고 `nav.home(source="fleet_loss")`로 `__home__`에 간다. `__home__`이 없거나 지역화가 안 됐거나 목표가 거부되면 선 채로 남는다(D-419 §3). 사이트 Fleet 하나가 죽으면 이 정책의 로봇이 모두 동시에 교통정리 없이 home으로 달리는 공통 모드 위험이다(D-419 Consequences).
  - **켜는 조건:** 어느 한 로봇에서 `STOP`이 아닌 값을 쓰려면 그 로봇 단위의 승인이 필요하다. 근거는 그 로봇의 G-dev 증거다. 승인은 로봇 프로필(또는 로봇별 overlay)에 승인자와 증거 참조를 함께 기록한다. 승인 기록이 없는 비-STOP 값은 프로필 검증에서 거부한다(Validation wave 0 6). 지금 D-419의 PUT 경고 동작은 그 시험이 들어올 때까지 그대로다. `HOLD`는 물리적으로 STOP과 같으므로 이 승인 대상이 아니다.

#### 5. 변경 통제

safety 태그 코드(§1의 root, 모듈 목록, 앵커 파일)를 바꾸는 변경은 다음을 지킨다. 지금 저장소 관행에 맞춘 가벼운 규칙이다.

- **독립 리뷰 + `Safety-Review:` trailer:** 작성 세션이 아닌 리뷰어(code-reviewer 또는 verifier 레인, D-172의 독립 리뷰와 같은 방식)가 승인한다. safety 태그 경로를 건드린 커밋은 `Safety-Review: <리뷰어·레인> <근거 링크>` trailer를 가져야 한다.
  - **강제는 CI다.** CI 작업이 PR·push 범위의 커밋을 매니페스트의 safety 경로와 대조해 trailer가 없으면 실패한다(Validation wave 0 5).
  - **`tools/hooks/pre-push`는 선택형 로컬 조기 경고다.** `tools/hooks/install.sh`로 설치해야 돌고 `--no-verify`로 건너뛸 수 있으므로 강제 수단이 아니다.
  - 같은 세션의 자기 승인을 trailer 근거로 쓰지 않는 것은 리뷰 판단이며 기계 검사가 아니다.
- **gate 증거:** 해당 층의 기존 gate를 trailer 근거에 붙인다. 예: D-400 G-sim/G-dev/G-enforce, D-419 호스트 시험, Fleet 정지 래치 시험(`test_dispatch_stop_latch.py`·`test_cancel_all.py`), 펌웨어 계약 시험. 호스트 pytest 통과는 장치·실주행 수용이 아니다.
- **교훈 기록:** 리뷰가 안전 결함 종류를 잡으면 `docs/solutions/design-patterns/`에 `ce-compound` 노트를 남긴다.
- 매니페스트에서 safety 태그·앵커를 빼는 변경도 같은 trailer가 필요하다.

### 기존 결정과의 관계

| 기록 | 처리 |
|---|---|
| D-429 (Accepted 2026-10-03) | `concern:` 값에 `safety`를 더한다. §1 표의 "중재·안전" 층은 판단 층으로 남되, 안전 체인은 이 ADR이 정본이다. D-429 본문의 안전 관련 자리(§1 중재·안전 행, §2 로봇의 소비·인터록 우선, §4 failsafe 의무·장치 로컬 failsafe·물리 E-stop/safety PLC 독립, 후속 2·4)에 D-430 포인터만 추가했다. 내용은 바꾸지 않았다. DeviceControlPort(§4)에 불변식 3을 건다 |
| D-427 (Accepted) | 파트·폴더·import 규칙을 바꾸지 않는다. §5의 실물 RL 선행 조건(엔벌로프, MANUAL 선점, 독립 E-stop 실측)은 이 체인의 층 4·5·1 상태와 같은 목록이다 |
| D-399 (Proposed) | §1 Safety Guard가 단일 writer 바로 앞이라는 배치와 "정지 계열이 모든 동작 출처보다 위"를 층 3·5로 계승한다. §2 엔벌로프를 층 4로 둔다. 후속 1·5가 이 ADR의 층 4·5를 채운다 |
| D-400 (Proposed) | 층 3의 센서 정책이다. off·shadow·enforce 모드와 gate를 바꾸지 않는다. 집행은 여전히 로봇별 사용자 승인이다 |
| D-369 (Accepted) | 역할 분리와 §5 물리 E-stop 독립을 층 1·3·6으로 계승한다. 응답이 정지 증거가 아니라는 규칙을 유지한다 |
| D-330, D-358, D-421 | 층 6이다. 유지한다 |
| D-419 (Accepted) | 로봇의 Fleet 상실 규칙이다. 기본 STOP과 HOLD는 fail-closed, `CONTINUE`와 `RETURN_HOME`은 §4의 기록된 예외다. 비-STOP 값에 로봇별 승인 기록(승인자, G-dev 증거)을 요구하는 것은 이 ADR이 더한다(사용자 결정 U2). 승인 검증 시험 전까지 D-419 동작은 바꾸지 않는다 |
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

1. **매니페스트.** `concern: safety` 하위 root(각자 `d427_target`)와 `safety_modules:` 목록(파일 경로 + 심볼 앵커)을 넣는다(§1). `core_features/decision`에 `concern: decision`을 단다(불변식 2의 로봇 쪽 대상).
2. **Fleet 정지 경로 carve 계획.** `dispatch_admission`·`cancel_all`·`cancel_all_store`·`local_stop_transport`와 `console.py`의 `estop_all`, `task_dispatch_routes.py`의 rearm 경로를 Fleet 안 하위 root(예: `fleet/server/stop/`)로 떼는 계획을 쓴다. 이동은 D-427 wave 3 순서를 따른다. 그 전까지 이 파일들은 `safety_modules:`로만 태그된다.
3. `test/architecture/test_safety_separation.py`
   - `KNOWN_SAFETY_VIOLATIONS`: §3의 18건을 그대로 고정한다. `test_platform_parts.py`의 `KNOWN_VIOLATIONS`와 같이 집합 동등으로 검사하고 줄이기만 한다
   - `test_safety_does_not_import_decision_learning_or_model_sdks` — 불변식 1
   - `test_decision_and_learning_use_only_safety_public_api` — 불변식 2. 공개 진입점 목록(§3) 밖의 safety 심볼 import 금지
   - `test_each_separation_rule_checks_at_least_one_importer` — 불변식 1·2·3a가 실제 import edge·파일을 하나 이상 검사했는지 단정한다. 대상이 비면 실패한다(공허한 통과 방지)
   - `test_cmd_vel_publisher_is_single_and_only_send_twist_touches_it` — 불변식 3a. 운영 소스 범위(`test/`·`sensing/tools/gz/` 경로 제외), 리터럴과 `declare_parameter` 기본값 `"cmd_vel"`을 함께 검사, allowlist는 `src/runtime/sensing/control/safety/node.py:89` 하나
   - `test_safety_anchors_live_in_safety_tagged_files` — §1 심볼 앵커(모듈 경로로 한정, 중첩 정의 포함)와 문자열 앵커마다 정의 파일을 찾아(root 기준 상대 경로) 그 파일이 safety로 태그됐는지 단정한다. 파일이 쪼개져 앵커가 옮겨가면 실패한다
4. `src/runtime/services/test/test_safety_behaviour.py`(이름 제안)
   - `test_estop_zeroes_every_source_and_clip_applies` — 불변식 3b
   - `test_learned_inputs_only_tighten_limits` — 불변식 4·§4. 사람 자문이 있으면 상한이 기본 프로필 이하이고, 자문이 stale·무효·없음이면 상한이 정확히 기본 프로필로 돌아가며, 어떤 자문도 기본 프로필보다 높이지 못하고 래치를 풀지 못함
5. **CI의 `Safety-Review:` trailer 검사**(`.github/workflows/ci.yml`에 작업 추가)와 같은 검사의 `tools/hooks/pre-push` 로컬 조기 경고 — §5.
6. **프로필 검증 시험** `test_non_stop_fleet_loss_policy_requires_approval_record` — `safety.fleet_loss_policy`가 `STOP`이 아닌 프로필·overlay에 승인 기록(승인자, G-dev 증거 참조)이 없으면 거부한다(§4, 사용자 결정 U2).
7. D-429 wave 0의 사이트 장치 도구 거부 이름 추가(층 7)를 그대로 한다.

불변식 5의 시험 `test_plc_adapter_never_writes_safety_addresses`는 **이 ADR이 소유한다.** 지금은 쓸 코드가 없으므로 첫 PLC/Modbus 어댑터와 같은 변경에서 들어온다. D-429 후속 4(PLC 인터록 ADR)는 이 시험을 참조할 뿐 다시 정의하지 않는다.

**후속:**

1. 물리 E-stop 실측: Pinky·OMX 회로 확인과 독립 E-stop 시험(D-427 §5 선행 조건 6). 결과에 따라 층 1 상태를 갱신한다.
2. D-400 계획 2·3: G-sim 재실행(유휴 호스트), G-dev, 로봇별 G-enforce.
3. D-399 후속 1(엔벌로프 스킬 계약)과 후속 5(Motion Intent·Arbiter·MANUAL 선점, D-429 후속 1과 합침).
4. `arbitration.py`를 safety 심볼(`ModeMachine`, `_ALLOWED`)과 control 심볼(`Priority`, `DEFAULT_SOURCES`, `SourceRegistry`)로 나눌지는 파일 크기 예산과 함께 나중에 정한다. 나누기 전에는 파일 전체가 safety 변경 통제를 받는다(§1).

**References:** [D-429](D-429-five-concerns-control-port-and-site-devices.md), [D-427](D-427-platform-three-parts-middleware-operations-learning.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-400](D-400-core-safety-policy-off-shadow-enforce.md), [D-369](D-369-control-authority-and-stop-evidence.md), [D-105](D-105-stop-safety-stop.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md), [D-421](D-421-fleet-cancel-all-driving-separate-from-latched-estop.md), [D-422](D-422-line-follow-body-referenced-obstacle-stop.md), [D-424](D-424-one-robot-body-for-every-near-check.md), [D-104](D-104-arm-manual-put-safety-limits.md), [D-2](D-2-cmd-vel.md), [D-38](D-38-core.md), [D-392](D-392-provider-neutral-model-tool-contract.md), [D-326](D-326-agent-loop-boundary.md), [D-337](D-337-robot-signal-source-measured-light.md), [D-349](D-349-dock-auto-charge-code-readiness.md), [D-351](D-351-docking-retry-by-failure-kind.md), [D-200](D-200-docking-owns-the-docking-mode.md), [D-419](D-419-saf003-fleet-link-loss-policy.md), [D-208](D-208-sensing-profile-publishes-no-velocity.md), [D-298](D-298-mission-action-and-stop-evidence-terminology.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md), [D-299](D-299-omx-lerobot-development-and-command-ownership.md), [D-172](D-172-archived-branch-port-closure.md), [소유 매니페스트](../../tools/harness/platform_parts.yaml)
