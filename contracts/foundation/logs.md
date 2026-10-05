# core_common logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/core_common`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register core_common under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `python -m pytest src/core/core_common/test -q` — 1 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, 나머지 N/A(라이브러리 등급)
- 결정: D-168
- 교훈: config.py가 core share를 역참조한다 — D-168 KNOWN_CHAIN_BACK_EDGES

## 2026-09-22 · uncommitted · core_common+fleet_agent(identity): hello 신원 실값 공급 (T6)
- 변경: `RobotIdentity` 에 device_uid(빈 문자열 기본)·device_name(미지정 시 robot_name 폴백) 파라미터와 model/profile_model·hardware_serial/serial hello 필드명 property 를 additive 추가, from_config 가 robot.device_uid/device_name 을 읽음. `fleet_agent/agent.py` 는 hello 본문 생성을 hello_payload() 로 추출하고 hasattr 폴백 "" 제거 — 신원을 모르면 지어내지 않는다. SiteHub 방어 시험 2건(DUPLICATE_IDENTITY/IDENTITY_DRIFT)을 test_hub.py 에 신규(기존 무시험).
- 증거: `python -m pytest src/core/core/test/test_fleet_agent.py src/core/core/test/test_runtime_config.py src/site/fleet/test/test_hub.py src/core/core/test/test_protocol_schemas.py -q` 52 passed(신규 6건 적색 후 초록). 근거: communication-protocol-report.md §5 편차 ②.
- gate 변화: 없음.
- 결정: 없음 — D-170 과 같은 방향(계약 필드에 실값).
- 교훈: 없음.

## 2026-09-22 · uncommitted · core_common+api_web(protocol): 버전 표기 3원 정렬 + API Ref v1.16 (T10)
- 변경: ① schemas.py docstring 두 곳의 "MINOR 상승" 약속을 "envelope 1.0 고정, additive 는 문서 MINOR" 규칙으로 정정(API Ref v1.8 노트와 동일한 답) ② app.py FastAPI version 1.0.0→1.16.0, description "(v1.2)"→"(v1.16)" ③ API Ref v1.16: §10 미구현 표기(시드는 :8090 /api/fleet/*), §1 Deprecation/Sunset 구현 시점 명시, §2 AUTH-103 CORS 미제공, §4 enum 대소문자 표. 신규 계약 시험 test_protocol_version_alignment.py(3건 — docstring 규칙/앱 표기·문서 버전 동기/이력 행 존재).
- 증거: `python -m pytest src/core/core/test/test_protocol_version_alignment.py src/core/core/test/test_protocol_schemas.py -q` 초록(신규 2건 적색 후 초록). 근거: communication-protocol-report.md §8-I 3원 불일치.
- gate 변화: 없음.
- 결정: 없음 — 문서 v1.8 노트가 이미 정한 규칙을 코드·앱 표기에 반영.
- 교훈: 버전 규칙은 규칙을 말하는 세 장소(docstring/앱 description/문서)가 같은 문장을 공유해야 드리프트가 계약 시험에 걸린다.

## 2026-09-24 · uncommitted · fix(core_common): 결측은 결측으로, 신원은 프로비저닝에서, 광고는 지킬 수 있는 만큼 (US-010)
- 변경: `protocol/schemas.py` `Battery.percent` 기본 `None`(≠0.0). `config.py` 오버레이에 이름이 없고 기본값 `Rosy 01` 뿐이면 `robot.name` 을 `ROSY_DEVICE_NAME`(없으면 `Rosy NN` ← `ROSY_ROBOT_NUMBER`)에서 유도, `robot.device_name` 도 기록. `domain/capabilities.py` `hardware_runtime_reason`(CORE-only 이고 오도메트리 표본이 없으면 `runtime_mode:core`), `withhold_hardware_flags`, descriptor `blocked` 이유. `domain/model.py` 이유 전달.
- 증거: `src/core/core/test/test_truthful_core_only.py` 16 passed; 전체 core+fleet+대상 루트 1966 passed, 53 skipped (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: D-32, D-161. API Ref v1.18 (Corrective `percent: null`, Additive `withheld`·`caller_role`).
- 교훈: 기본 설정의 자리표시 값은 신원이 아니다.

## 2026-09-24 · uncommitted · feat(robots): CORE loads the robot profile from robots/<model> (D-196)

- 변경: `profile.py`에 `DEFAULT_ROBOT = "pinky_pro"`와 `robot_config_dir(robot)`(ament share 우선, 소스 트리 `src/robots/<robot>/config` 폴백). `config.py` `load_config`가 `ROSY_ROBOT`을 `robot.model`로 싣고, 패키지 이름(`[a-z][a-z0-9_]*`)이 아니면 `ConfigError`. 호스트 pytest용 `test/conftest.py`(D-61 선례) 추가.
- 증거: `test/test_robot_selection.py` 신규 8건 포함 `src/core/core_common/test` 9 passed (2026-09-24 Windows). 구현 전에는 `ImportError: cannot import name 'DEFAULT_ROBOT'`로 수집 실패.
- gate 변화: 없음.
- 결정: D-196 Proposed. `DEFAULT_ROBOT`의 `pinky` 리터럴은 P6까지 `test/robot_literal_backlog.txt`에 명시적으로 둔다.
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(core,robots): clear error for a missing robot package; ship robots in docker/ci (D-196 review)

- 변경: `robot_config_dir`가 `ImportError`(ament 없음)와 ament `PackageNotFoundError`만 소스 폴백으로 보내고, 그 밖의 예외는 그대로 올린다. 소스 폴백은 `src/robots/<robot>/config`가 있을 때만 쓰고, 없으면 로봇 이름·`robot.model`·`ROSY_ROBOT`·`colcon build --packages-up-to core <name>`을 담은 `ConfigError`를 낸다(`core_common.config`는 `profile`을 import하지 않아 순환 없음).
- 증거: 실패 먼저 — `test_unknown_robot_names_the_package_and_how_to_fix_it` 1 failed(ConfigError 미발생). 수정 후 `src/core/core_common/test` 11 passed (2026-09-24 Windows). WSL Jazzy 설치 트리에서 `robot_config_dir('pinky_pro')` = `install/pinky_pro/share/pinky_pro/config`, `no_such_robot` → ConfigError 확인.
- gate 변화: 없음
- 결정: D-196 Proposed
- 교훈: 폴백은 대상이 실제로 있을 때만 폴백이다 — 없는 경로를 돌려주면 오류가 파일 읽기 시점의 엉뚱한 곳에서 난다.

## 2026-09-24 · uncommitted · fix(core_common): no-ament-env falls back too; path tests hold on a sourced ROS box (D-196 review)

- 변경: `robot_config_dir`가 ament는 import되지만 `AMENT_PREFIX_PATH`가 없어 `get_package_share_directory`가 `OSError`를 낼 때도 소스 폴백(없으면 `ConfigError`)으로 간다. `test/conftest.py`에 가짜 `ament_index_python.packages`를 까는 `fake_ament`·`no_ament_share` fixture를 두고, 소스 경로를 단언하는 시험을 그 위에서 돌려 호스트·ROS 소싱 환경 모두에서 결정적으로 만들었다. 신규 3건: OSError → 폴백, PackageNotFoundError → 폴백, share 반환 → share 우선.
- 증거: 실패 먼저 — `test_unsourced_ament_falls_back_to_the_source_tree` 1 failed(OSError 전파). 수정 후 Windows host `src/core/core_common/test`·`test_core_node_robot_paths.py`·`src/robots/pinky_pro/test`·`test/test_module_structure.py` 48 passed; WSL Jazzy 소싱 상태(`ros2 pkg prefix pinky_pro` = install/pinky_pro)에서 같은 core_common·core·robots 시험 20 passed (2026-09-24).
- gate 변화: 없음
- 결정: D-196 Proposed
- 교훈: 경로 폴백 시험은 ament를 가짜로 고정해야 한다 — 소싱된 상자에서는 진짜 share가 이겨 같은 시험이 붉어진다.

## 2026-09-24 · uncommitted · fix(core_common): 하드웨어 존재·구동 준비를 살아 있는 증거로 판정 (D-32, D-192), 계약 v1.21
- 변경: `domain/capabilities.py` `hardware_runtime_reason` → `runtime_truth(config, state, readiness)`. 하드웨어 존재는 `runtime.mode` 문자열이 아니라 오도메트리(pose·velocity)·배터리 표본의 나이(15 s)로 `on`/`silent`/`off`, 구동은 readiness 게이트의 `motor_adapter` 보고(`motor/ready`)로 `ready`/`disabled`/`stale`/`unknown`, 내비게이션은 게이트가 required 이거나 bringup 이 보고했을 때만 lifecycle 로 `ready`/`absent`. 플래그별 이유 `runtime_mode:core` > `hardware_silent` > `drive_disabled:no_motion`·`drive_lease_expired`·`drive_absent` > `navigation_absent`. `withhold_hardware_flags` 는 플래그별 이유를 받고 `withheld.reasons` 를 싣는다. descriptor 는 런타임 이유를 `device_state` 보다 먼저 두고 `reasons` 에 둘 다 싣는다. `domain/model.py` `runtime_reasons` 전달, descriptor `reasons`.
- 증거: `src/core/core/test/test_hardware_runtime_truth.py` 19 passed, `python -m pytest src/core/core/test src/core/core_events/test src/core/core_features/test src/core/web_common/test -q` 1553 passed, 14 skipped (2026-09-24 Windows).
- gate 변화: 없음 (DEVICE 재검증 필요 — 무동작 `rosy-io` 에서 overlay 로 확인).
- 결정: D-32, D-192, D-161. API Ref v1.21. 신규 ADR 없음.
- 교훈: 네이티브 이미지에서 `runtime.mode` 는 unit 을 켜고 끄지 않는다(D-192) — 설정 문자열로 하드웨어 존재를 추론하면 운용자가 손으로 켠 런타임을 못 본다.

## 2026-09-25 · uncommitted · refactor(contracts): move core_common under src/contracts (D-231)

- 변경: `src/contracts/core_common`로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 core_common 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(core_common): D-260 robot state rule table
- 변경: `core_common/robot_state.py` 신규 — 상태 다섯 개와 우선순위, 한국어·LCD(ASCII) 이유 줄, 할 일 규칙, 장치 요약. 표준 라이브러리만. D-247 7의 `MOTION_REASON`을 이리로 옮김. `test/test_robot_state.py` 36건
- 증거: `python -m pytest src/contracts/foundation/test/test_robot_state.py -q` 36 passed; 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed (구현, DEVICE 확인 남음)
- 교훈: 부팅 화면 프로그램(rosy-display)과 CORE가 한 표를 쓰려면 패키지 `__init__`이 아무것도 import하지 않아야 한다 — 시험으로 고정

## 2026-09-26 · uncommitted · feat(core_common): D-257 SiteSightingPayload

- 변경: image/policy/client source identity를 담지 않는 파생 pose schema 추가. seq, 유한 좌표·quality, map/calibration/processor revision과 4개 고유 코너 ID를 검증한다.
- 증거: `python -m pytest src/runtime/gateway/test/test_site_sightings.py -q -p no:cacheprovider` 14 passed; gateway 전체 1325 passed/16 skipped.
- gate 변화: 없음. D-257/D-268 Proposed.
- 결정: schema는 operator sighting을 위한 것이며 automatic policy input이 아니다.
- 교훈: source identity는 요청 본문이 아니라 Fleet credential configuration에서 결정한다.

## 2026-09-26 · uncommitted · feat(core_common): camera evidence response schemas

- 변경: `VisionEvidenceRecord`와 `VisionEvidenceList`를 API Ref v1.36에 맞춰 추가했다.
- 증거: 카메라 저장 API의 응답 모델과 저장·조회 시험.
- gate 변화: 없음.

## 2026-09-26 · uncommitted · feat(core_common): add optional UI action group descriptor

- 변경: `UiPanelDescriptor.action_group` optional field를 추가해 console operation tabs를 API schema로 표현한다.
- 근거: `python -m pytest src/contracts/foundation/test -q` 50 passed; API Ref v1.36와 동기화했다.
- gate 변화: 없음. ROS/API runtime/device acceptance는 포함하지 않는다.
- 결정: D-283 Accepted.
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(core_common): publish and validate Fleet intent grammar

- 변경: `core_common.intent.request_schema()` now generates the `/api/fleet/do` one-step or bounded-sequence OpenAPI grammar from the shared verb table. The interpreter rejects mismatched numeric, string, integer, and string-array values before scatter.
- 증거: gateway intent tests 18 passed; Fleet API suite 507 passed, 5 skipped; touched Python files pass flake8.
- gate 변화: SOURCE/LOCAL contract evidence only; this library has no runtime/device gate of its own.
- 결정: D-288 API intent boundary; public robot PRT envelope remains unchanged.
- 교훈: generated schemas and runtime interpretation must share the same verb and field definitions.

## 2026-09-27 · uncommitted · own default configuration
- Change: moved both default YAML files into core_common, installed them in its package share, and removed the reverse CORE lookup.
- Evidence: 1,812 gateway/config/image tests passed with 28 skipped; 51 architecture tests passed; the built core_common wheel contains both YAML files.
- Gate: SOURCE/LOCAL evidence only; Pi installation and device launch remain unverified.

## 2026-09-27 · uncommitted · feat(protocol): type Host Agent status evidence

- 변경: 네트워크·릴리스 조회의 증거 상태, 원본 시각, 나이, 임계, 사유를 `HostStatusEvidence`로 추가했다. 기존 Fleet envelope 버전과 필드는 유지한다.
- 근거: CORE Host API 계약 시험과 API Ref v1.42.
- Gate: SOURCE/LOCAL 계약 근거이며 장치 상태 판정이 아니다.

## 2026-09-29 · uncommitted · feat(protocol): add PolicyEvidencePayload (D-268 ladder T1)

- 변경: 정책 적격 증거(작업 발의 자격, D-268)의 와이어 계약을 추가했다 — `evidence_id`, `asset_kind`(robot/workcell/object, D-330 자원 어휘), `task_kind`(v1 닫힌 집합 navigate), `captured_at`, revision 삼종(map·calibration·model), 닫힌 `observation` 봉투(kind만, 등록부는 서버 쪽). 클라이언트가 `source`·`source_id`·`token`·`policy`·`satisfied`를 보내면 거부한다(출처는 자격 증명에서 결정, `satisfied`는 D-328 목표 판정 전용 어휘).
- 근거: [설계](../../../docs/plans/2026-09-29-policy-evidence-contract-design.md)·[실행 계획](../../../docs/plans/2026-09-29-policy-evidence-contract.md) T1. 기존 필드·sighting 무변경, API Ref v1.48 개정은 T6가 한다.
- Gate: SOURCE/LOCAL 계약 시험 75 passed (2026-09-29 Windows). 서버 등록부·발의 binding·밸브는 fleet 작업(T3/T4)이고 자동 실행은 여전히 HOLD다.

## 2026-09-29 · uncommitted · feat(protocol): define OMX Device Action and software-stop schemas (D-333/D-336)

- Change: added immutable typed contracts for pixel-level target evidence, Fleet grants, local Action journal receipts/read/cancel, and software-stop request/query/snapshot. Distinct IDs, observation consistency, digest, revisions, generation, expiry, and aware timestamps are validated; no receipt can claim independent goal or physical stop proof.
- Evidence: full `src/contracts/foundation/test` suite: 101 passed on Windows; includes `test_device_action_contracts.py` and existing protocol schema tests. API Reference v1.48 describes the same-host UDS contract and explicitly says no endpoint/runtime is implied.
- Gate: SOURCE/LOCAL contract only. No UDS listener, physical stop, action runtime, ROS-SIM, DEVICE, or FIELD acceptance.

## 2026-09-29 · uncommitted · feat(protocol): TrafficPolicyStatus.junction_rule (API Ref v1.54)

- Change: additive `junction_rule: str = "signal_controlled"` on `TrafficPolicyStatus` — surfaces the operator-declared stop-line rule (`signal_controlled` | `stop_and_go`, unsignalized stop-and-go) alongside the existing policy revision. Existing fields untouched.
- Evidence: foundation suite green within the traffic-policy change run (2026-09-29 Windows, 101 passed); API Reference bumped to v1.54 with the field, example, and semantics in the same change (D-18).
- Gate: SOURCE/LOCAL contract only; no device or FIELD acceptance.

## 2026-09-29 · uncommitted · feat(protocol): traffic policy signal-source status fields (API Ref v1.56)

- Change: additive `signal_source_kind: str = "camera"`, `signal_head_age_s: Optional[float]`, `signal_head_frozen: bool = False` on `TrafficPolicyStatus` — the D-337 measured-light fusion's observability (fused only while the observed head is usable). `rosy_default.yaml` documents the empty `traffic_policy.signal_observer` binding (overlay-only). API Reference v1.56 with example, prose, the `nav.traffic_policy_signal_source_stale` §8 row, and history entry in the same change (D-18).
- Evidence: foundation suite green within the T3 combined run (501 passed); event catalogue green against the new emit site.
- Gate: SOURCE/LOCAL contract only; no live observer, device, or FIELD acceptance.

## 2026-09-29 · uncommitted · feat(domain): capability lifecycle 단일 어휘 (D-347)

- 변경: core_common/domain/capabilities.py에 CapabilityLifecycle(ready/unavailable/activating[예약]) enum과 lifecycle_from(advertised, runtime_reasons)을 추가했다. 판정은 새로 만들지 않는다 — 모드 마스킹의 withheld 사유(선과 같은 값이므로 우선)와 runtime_truth 사유, 플래그 참/거짓을 한 어휘로 합칠 뿐. §7 위반 없음: 프로파일과 런타임 어느 쪽도 true로 말하지 않는 플래그는 결과에 없다.
- 증거: gateway/test/test_capability_lifecycle.py 6 passed(유도 3·일관성 2·wire 1 — withheld.flags == unavailable 집합 핀 포함). 이웃 185 passed(truth·truthful_core_only·api·foundation).
- gate 변화: 없음.
- 결정: activating 진입은 후속 ADR(온디맨드 B레인) 없이 금지 — 시험이 핀으로 지킨다.
- 교훈: 정찰이 설계를 바꿨다 — "상태 계약이 없다"가 아니라 "두 표면이 다른 어휘를 쓰고 있었다"가 진짜 갭이었다.

## 2026-09-30 · uncommitted · feat(discovery): D-358 S1 공유 TXT 벡터와 정본 분류기

- 변경: `core_common/protocol/discovery_txt.py`(표준 라이브러리만)를 새로 두었다. `parse_txt_pairs`, `classify(service_type, host, address, port, txt) -> Accepted|Rejected(reason)`, 옛 로봇 광고의 `legacy` 표시. 기계 원천은 `test/fixtures/protocol/discovery-txt.v1.json`(28 사례, 거절 사유 9종 전부)이다. FleetAgent(`core_features/fleet_agent/discovery.py`)의 복사 `TXT`/판정을 이 모듈 import로 바꿨다.
- 증거: `test_discovery_txt_vectors.py` 31 passed, 프로필 대조 2 passed. 변이 증명: 벡터 사유 하나(`overhead_tls_host_mismatch`)를 바꾸면 Python·Kotlin이 모두 적신, 프로필 값 하나를 바꾸면 대조 시험 적신.
- gate 변화: 없음. SOURCE/LOCAL.
- 결정: D-358 5.1.
- 교훈: 없음.

## 2026-09-30 · uncommitted · docs(adr): D-358 앱 역할 ADR을 D-370으로 재번호

- 변경: 이 모듈의 D-358 앱 역할·이름·아이콘 주석과 시험 문서 문자열을 D-370으로 바꿨다. 동작 변경 없음.
- 증거: 번호만 바꾼 diff. 시험은 병합 뒤 회차에서 다시 돌린다.
- gate 변화: 없음.
- 결정: 이 항목 앞의 "D-358 S1/S2/S3"·"D-358 N항"은 D-370을 가리킨다(main의 D-358 ER2 피드백 outbox와 다름). 옛 항목은 고치지 않는다.
- 교훈: 없음.

## 2026-09-30 · uncommitted · docs(protocol): DeviceActionLookup 의미를 실제 사용에 맞춤

- 변경: DeviceActionLookup은 attempt 범위 연산(현재 취소)의 identity pair라는 docstring으로 정정했다. OMX UDS v1 GetAction의 요청은 action_id만이며 응답에서 Fleet이 attempt/grant를 검증한다. API Reference §10.12를 함께 정정했다.
- 증거: Fleet–OMX 결합 시험과 인접 suite 21 passed. Pydantic field·validation·wire·runtime 동작은 바뀌지 않았다.
- gate 변화: 없음.

## 2026-09-30 · uncommitted · feat(robot_state): D-375 운용 모드 축 — 램프 패턴 중재와 LCD 접미

- 변경: `ROBOT_MODES`/`OPERATING_MODES`/`MODE_LAMP` 상수와 `valid_robot_mode()`·`mode_suffix()`·`lamp_pattern()`를 추가했다. `evaluate()`는 `robot_mode`를 받아 검증해 결과에 실으며, 다섯 건강 상태 판정은 바꾸지 않는다. 우선순위: 실패 > 비상정지 > 주의 > 부팅 > 도킹 > 내비게이션 > 수동 > 준비.
- 증거: test_robot_state.py 69 passed (우선순위 전 표 변이 증명: EMERGENCY를 주의 아래로 내리면 해당 행이 빨개진다).
- gate 변화: 없음.

## 2026-09-30 · uncommitted · docs(adr): D-375 에서 D-380 으로 개명

- 변경: 병합 시점에 main 이 D-375 를 feat/overhead-map-auto-register 예약으로 adr_gaps 에 넣은 것이 확인됐다(선례 D-324→D-325). 이 작업의 결정 번호를 다음 빈 번호 D-380 으로 개명하고 코드 주석·시험·설계 문서의 D-375 표기를 함께 바꿨다. 앞선 항목의 D-375 표기는 역사 기록으로 그대로 둔다.
- 증거: rosy_harness lint 오류 0. 본문 참조는 docs/adr/D-380-lamp-mode-patterns-from-core-status-inputs.md.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(robot_state): D-381 nav_state 축 — blocked 세부 패턴

- 변경: `NAV_STATES`·`NAV_STUCK`·`valid_nav_state()` 추가. `lamp_pattern()`이 세 번째 인자 `nav_state`를 받아 NAVIGATION 안에서 BLOCKED/FAILED를 `blocked`로 구분한다(다른 우선순위는 불변).
- 증거: test_robot_state.py 90 passed (변이 증명: blocked 규칙을 빼면 해당 2행이 빨개진다).
- gate 변화: 없음.

## 2026-10-01 · 423e4d2f · feat(core_common): 버전 보정 저장소 (D-47 부록)
- 변경: `core_common/calibration_store.py` — 실행마다 불변 레코드 하나(종류·로봇·세션·방법·값·구간·sha256), 상태는 append-only events.jsonl, 현재값 = 고정된 승인 레코드 또는 최신 승인 레코드, `resolve()` 는 없으면 정적 값과 로그용 출처 문장을 준다. 자동 승인 경로 없음.
- 증거: `test_calibration_store.py` 9 passed — 이력 보존·덮어쓰기 거부, 후보는 현재값이 아님, 최신 승인 우선·superseded, 고정/해제 롤백, 최신 거부 롤백, 변조 레코드 배제, 정적 대체 (2026-10-01 Windows).
- gate 변화: SOURCE.

## 2026-10-01 · ddede2f8 · fix(core_common): 보정 저장소 리뷰 수정 (H3·M1·M2·L3)
- 변경: events.jsonl 의 깨진 줄·형식 불량 이벤트는 기록하고 건너뛴다. load 는 dict values 와 문자열 created_at 을 요구한다. current/resolve 는 어떤 실패든 잡아 정적 값으로 물러난다. 현재값은 created_at 이 아니라 마지막 승인 이벤트 순서다. `check_values`(장착 yaw 150–210° 또는 손값 ±15°, 바퀴 ±10 %, 숫자만) 를 런타임·승인에 같이 쓴다. `merge_from` 은 없는 레코드 파일만 복사(같은 id 는 바이트 동일해야 함)하고 없는 이벤트만 덧붙인다.
- 증거: test_calibration_store.py 25 passed(깨진 줄, 형식 불량 레코드, 재승인 순서, 저장소 예외 대체, check_values 12 경우) (2026-10-01 Windows).
- gate 변화: SOURCE.

## 2026-10-01 · 90cac516 · fix(core_common): 2차 리뷰 — 찢긴 꼬리, 양쪽 결정 충돌, 원자적 쓰기, 그룹 권한
- 변경: events.jsonl 이 개행 없이 끝나면 덧붙이기 전에 개행을 먼저 쓴다(F1). 양쪽 저장소가 서로 모르는 승인/거부/고정을 가지면 병합을 거부하고, 모든 종류를 먼저 검사한 뒤에만 쓴다(F2·F8). 레코드는 임시 파일 + os.replace, 디렉터리 0o2775·파일 0o664(F4). camera_profile 의 width/height/fx/cx/cy/max_range_m 는 유한 양수(F7).
- 증거: test_calibration_store.py 35 passed + 1 skip(Windows), 권한 시험은 WSL Linux 에서 통과 (2026-10-01).
- gate 변화: SOURCE. 로봇 쪽 rosy-calib 디렉터리 생성은 열린 커미셔닝 항목.

## 2026-10-01 · uncommitted · feat(robot_state): D-383 swarm_role 축 — LCD 역할 접미

- 변경: SWARM_ROLES·valid_swarm_role()·role_suffix()(ASCII " - LEADER") 추가. mode/nav 와 같은 부재 규칙, evaluate 판정은 그대로.
- 증거: test_robot_state.py (변이 증명: 접미를 없애면 해당 2행 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-390 OMX Pilot simulation wire contract
- Change: Add typed sim-only target, jog and goal contracts in core_common.protocol.omx_sim; document the additive v1.67 routes in the API reference.
- Evidence: focused contract and adapter tests passed; API version alignment test 4 passed after the document bump.
- Gate: SOURCE only; no physical profile admission.

## 2026-10-01 · a527920a · feat(protocol): StateSnapshot.activity (v1.67 additive)
- 변경: `RobotActivity`·`ActivityOwner` 모델과 `StateSnapshot.activity: Optional[RobotActivity] = None`. 보정 lease 가 살아 있을 때만 객체, 아니면 null.
- 증거: test_calibration_session.py 의 robot/state·/ws/state 시험, test_protocol_version_alignment 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(core_common): robot package core.yaml config layer (D-196)

- 변경: `load_config` 가 rosy_default 위, 로컬 오버레이/ROSY_CONFIG 아래에 로봇 패키지의 `config/core.yaml` 을 병합한다(모델: ROSY_ROBOT > 오버레이 robot.model > 기본값). 파일이 없거나 패키지를 못 찾으면 아무것도 더하지 않는다. 첫 사용: Pinky Pro `line_follow.lidar_forward_deg: 180`.
- 증거: gateway `test_pinky_lidar_forward_device.py` 5 passed; gateway+foundation+profile+test/ 6 failed 4763 passed — 5개는 기준 0476060b 에서도 같은 내용으로 실패(known_failures.txt 미등재), 1개(test_pinky_user_validation ssh timeout)는 단독 재실행 통과(부하 flaky). services 265 passed.
- gate 변화: 없음.

## 2026-10-01 · 078d0978 · fix(core_common): robot core.yaml layer fails closed (review of 9966e57b)

- 변경: 21224829 패키지가 있는 로봇의 `core.yaml` 이 없으면 ConfigError, 모르는 모델·패키지 없음은 경고 한 줄. 37b439bf 최상위 null·기본 매핑 자리의 비매핑 값은 ConfigError(파일 이름). 078d0978 깨진 YAML 은 경로를 담은 ConfigError(CORE 기동 거부). 이어서 docstring 네 층, `ROBOT_NAME_PATTERN` 공용 상수, D-196 추가·운영 수용 기준 병합 순서.
- 증거: `test_robot_core_layer.py` 8 passed; gateway `test_pinky_lidar_forward_device.py` 5 passed(3b525bb6: 가짜 ament 로 소스 트리 고정).
- gate 변화: 없음.
- 결정: D-196 추가 2026-10-01.

## 2026-10-01 · uncommitted · feat(protocol): D-391 4.1 공유 벡터 — device_kind·실패 분류·사이트 연결 기록

- 변경: `core_common/protocol/`에 표준 라이브러리만 쓰는 세 모듈을 두었다. `device_kind.py`(`OVERHEAD_CAMERA`·`ROBOT`·`ALL`), `failure_class.py`(`classify(*, ws_close, reason, http_status, transport, discovery) -> str`, 입력은 정확히 한 종류), `site_link.py`(`validate(record) -> str | None`). 기계 원천은 `test/fixtures/protocol/failure-classes.v1.json`(26 사례, 분류 11종 전부)과 `site-link.v1.json`(33 사례, 사유 12종 전부)이다.
- 결정: WS 4400의 재시도 사유(빈 사유·`no hello` 등, ingest 벡터 `close_4400_reasons.retry`와 같은 목록)는 D-341 11항 전환 규칙대로 `busy`로 둔다(`auth_retry` 아님 — 자격은 의심받지 않는다). 표에 없는 WS 코드는 `unreachable`, HTTP 4xx는 `protocol_mismatch`, 5xx는 `busy`. `tls_host`는 `.local` 이름만(IP면 `ip_as_tls_host`), `expires_at`은 `Z` 붙은 UTC만, 모르는 최상위 필드는 무시한다. CA 판정은 최소 DER 탐색으로 basicConstraints `cA`만 읽는다(서명·유효기간·체인은 TLS 몫). 벡터의 인증서는 공개 fixture이고 44자로 줄바꿈해 비밀 스캔의 50자 엔트로피 기준 아래에 둔다. 개인 키는 작성 때 버렸다.
- 증거: `test_site_link_vectors.py` 71 passed, foundation 전체 279 passed. 변이 증명: CA 판정을 항상 참으로 바꾸면 `ca_pem_is_leaf`·`ca_pem_leaf_then_ca_bundle` 2건이 빨개진다.
- gate 변화: 없음(LOCAL). Kotlin 쪽 로더는 rosy-84 몫.

## 2026-10-01 · uncommitted · fix(protocol): site_link 비밀 스캔 오탐·ruff 정리

- 변경: `site_link.py`의 지역 변수 `has_secret`가 비밀 스캔 `credential` 규칙에 걸려 `inline`으로 바꿨다(D-256: 스캐너가 아니라 호출 자리를 고친다). `expires_at` 달력 검사는 `%z`를 붙인 aware datetime으로(DTZ007), 새 시험의 import 정렬을 맞췄다. 동작 변경 없음.
- 증거: `test/test_release_boundary_guards.py` 73 passed(수정 전 `test_no_secrets_in_tracked_files` 1 failed), foundation 279 passed, 새 파일 ruff 통과.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(protocol): D-391 벡터 — 4400 사유 정규화, manual_host는 IP만

- 변경: rosy-84 Kotlin 대조에서 나온 두 차이. ① 4400 사유는 공백 제거·casefold 뒤 비교한다(" No Hello " → busy, "NO HELLO extra" → protocol_mismatch 사례 추가). ② `manual_host`는 IPv4/IPv6 리터럴만 받는다(D-391 1항 "rosyov 링크의 IP, DNS 없이 연결"과 일치) — 이름·`ip:port`는 `bad_manual_host`, IPv6 허용 사례 추가.
- 증거: foundation 시험 329 passed; Kotlin 쪽은 rosy-84 브랜치 `feat/cam-d391-shared-vectors`가 같은 벡터로 대조.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(protocol): D-391 site-link 경계 규칙 — fullmatch, IPv6 zone 거절

- 변경: rosy-84 Kotlin 독립 리뷰가 찾은 차이. `tls_host`·`expires_at` 정규식을 `match`(`$`가 끝 줄바꿈을 허용)에서 `fullmatch`로 바꿨다. `manual_host`에 IPv6 zone id(`%`)가 있으면 `bad_manual_host`(폰에서 다이얼 불가). 사례 7건 추가: 끝 줄바꿈 두 건·zone id(옛 코드에서 통과하던 결함), 0년 날짜·pathLen 없는 CA·CA 뒤 leaf 묶음·END 뒤 쓰레기(기존 동작 고정, 런타임 공통).
- 증거: foundation 336 passed; 새 사례 중 3건은 옛 `site_link.py`에서 실패함을 직접 대조. 새 CA 인증서는 공개 인증서만 저장, 키는 버렸다.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(protocol): D-341 rosy-pair/1 공유 벡터와 순수 로직

- 변경: `core_common/protocol/pairing.py`(표준 라이브러리만) — 확인 코드 `confirmation_code`, `commit`, 사이트 지문 `site_fingerprint`·`fingerprint_from_sha256`, leaf/CA DER 해시 `der_sha256`, 요청·공개 본문 검사(`validate_request_bytes`·`validate_reveal_bytes`, 4096바이트 초과는 파싱 전에 `too_large`, 모르는 필드 거절), 결과 검사 `validate_result`(CA는 site_link 규칙: leaf면 `leaf_not_ca`, 모르는 필드는 무시), 발견 기록의 페어링 가능 판정 `pairable`(discovery_txt 판정 위에 `not_overhead`·`no_pair`). 기계 원천은 새 `test/fixtures/protocol/pairing.v1.json`(코드 4건 — leaf만 다른 쌍 포함, 지문 2건, 요청 16·공개 5·결과 14·발견 6건).
- 결정: 계획이 열어 둔 바이트 배열은 길이 접두(필드마다 4바이트 big-endian 길이 + UTF-8)로 정했다 — 등록 저장소 AAD와 같은 방식이고 구분 문자를 예약하지 않는다. `decimal6`은 digest 앞 8바이트 big-endian mod 1,000,000. nonce·poll 비밀·토큰은 32바이트 base64url 무패딩 43자, `client_commit`·`poll_secret_sha256`은 그 ASCII 텍스트의 소문자 hex SHA-256. 지문은 CA DER SHA-256 앞 16 hex를 대문자로 4자씩 `-`. 벡터 생성기는 모듈과 별도로 쓴 참조 계산이다(저장소 밖 스크래치). 긴 hex는 `sha256` 이름이 붙은 줄에만 두어 비밀 스캔이 무결성 값으로 읽는다.
- 증거: `test_pairing_vectors.py` 53 passed(모듈 작성 전 수집 단계 실패 확인). foundation 전체·비밀 스캔은 커밋 기록 참조 — `test_no_secrets_in_tracked_files`의 `docs/logs.md:4077`·`docs/plans/2026-10-01-gemini-robotics-samples-research.md:5` 실패와 `fleet` 크기 판정 실패는 main에 이미 있던 것이다(이 변경 파일 아님).
- gate 변화: 없음(LOCAL). Kotlin 로더는 Rosy Cam 세션 몫.

## 2026-10-01 · edca9b2e · feat(geometry): calibration_store 중심값과 운영자 층 (D-397)
- 변경: `calibration_store` 바퀴 기준 0.027/0.0961 → URDF NOMINAL 0.028/0.0971(±10 %), `LIDAR_NOMINAL_DEG` 180, 창 180 ± 30. `resolve(..., override=)` — URDF NOMINAL < 승인 레코드 < 운영자 덮어쓰기, 덮어쓰기도 `check_values`를 통과해야 하고 실패하면 경고·거부. `config.local_overlay()`가 운영자 오버레이만 읽는다(`overlay_path()`).
- 증거: `test_calibration_store.py` 세 종류 순서·거부 테스트, `tools/calibration/test/test_urdf_nominal.py` 드리프트.
- gate 변화: SOURCE/LOCAL. DEVICE HOLD(배포 전 사용자 승인).
- 결정: D-397 Proposed, D-47 addendum 개정.

## 2026-10-01 · uncommitted · feat(protocol): D-395 위치 확정 모델과 스냅샷 `localization` (API Ref v1.69)
- 변경: `core_common/protocol/localization.py` — `LocState`, `PoseFrame`(map|odom), `Cue`, `DecisionSource`, `LocalizationStatus`, `LocCandidate`, `RobotPoint`, `SquareSighting`, `CandidateReport`, `LocalizationDecision`(인덱스 또는 직접 좌표 정확히 하나, `candidate` 출처는 인덱스와만, `cues`, 받은 때부터 재는 `ttl_s` 기본 5 s — D-395 개정 3에 따라 계획의 절대 `expires_at` 대신). `StateSnapshot.localization` 선택 필드(D-395 이전 로봇은 null). 모두 추가 전용(API-002, PRT-006).
- 증거: `test_localization_contracts.py` 18 passed, `test_protocol_schemas.py`, `test_protocol_version_alignment.py`, `test_line_follow_contract_docs.py`.
- gate 변화: 없음(SOURCE). 아직 아무 경로도 이 모델을 보내거나 받지 않는다.
- 결정: D-395 Proposed(개정 3), D-18, D-347.

## 2026-10-01 · uncommitted · feat(omx): record SIM demonstrations and export LeRobot v3
- 변경: D-390 부록·API v1.69·Pilot 기록 패널·SIM 카메라·원본 recorder·오프라인 exporter. ROS 수락 전에 목표를 등록하고, recording I/O는 별도 writer로 분리.
- 증거: adapter/Pilot/network 259 passed, 28 skipped; quick tier 95 passed; Chromium recording retry/outcome/stale/dispose 1 passed; 실제 LeRobot 0.4.4 reader 3 passed. Gazebo 원본 15프레임 및 동일 원본 export 재독출 PASS. docs/validation/omx-demonstration-lerobot-2026-10-01/README.md 참조.
- gate 변화: 물리·ARTIFACT/FIELD 승격 없음. 짧은 SIM 시연/데이터 형식 증거만 추가.
- 결정: D-390 부록; D-18 typed API와 reference 동시 갱신.
- 교훈: LeRobot 0.4.4는 explicit timestamp를 거부; source ns를 int64로 유지. Windows shared recording mount는 프레임 누락을 만들 수 있으므로 Linux volume 사용.

## 2026-10-01 · uncommitted · fix(omx): fence recording closure and isolate storage faults
- 변경: 리뷰의 중요 문제 3개 해소 — recording 오류로 lease watcher 종료 금지, hidden 중 늦은 seat 획득 즉시 반납, 종료 저장 중 interruption을 manifest에 반영.
- 증거: 리뷰 수정 race/runtime/recorder 21 passed; Chromium 2 passed; 최종 adapter/foundation/assets/network 624 passed, 6 skipped. 최종 tree와 같은 해시의 실제 Gazebo 12프레임→LeRobot 재독출 PASS; 같은 실행 lease 만료 incomplete. 독립 리뷰 재검토 완료.
- gate 변화: 기존 gate 유지; DEVICE/FIELD 승격 없음.
- 결정: D-390 부록.
- 교훈: 파일 쓰기 완료 전 들어온 interruption과 logical closure 경계를 구분한다.

## 2026-10-01 · uncommitted · feat(core_common): D-400 SafetyPolicyStatus on the state snapshot
- 변경: `SafetyPolicyStatus`/`StateSnapshot.safety_policy`(API v1.71, 소문자 평문 mode·verdict는 캐싱 규칙 예외), `rosy_default.yaml`은 `mode`를 두지 않고(주석만) `stale_hold_s`를 더했다.
- 증거: 전체 시험(gateway+services+foundation+api_web+test/) `5 failed, 5919 passed, 249 skipped, 31 warnings, 4 errors in 3428.70s`; `known_failures.py`는 exit 1: 9건 모두 이 브랜치가 건드리지 않은 시험이며(main 4804d417에서도 test_module_separation, test_release_boundary_guards, test_robot_literals, test_dashboard_drive 4건이 같게 실패, test_module_criteria C6와 test_behavior_test_ownership은 main이 이후 고쳤고 이 브랜치는 그 이전 기준) 이 브랜치 기인 실패는 0건.
- gate 변화: 없음. SOURCE만. 그림자는 어느 로봇에서도 켜지 않았다(기본 off).

## 2026-10-02 · 34bac08a · feat(core_common): D-395 `CHECKING` 사유
- 변경: `core_common.protocol.localization.CHECKING = "checking"` — 로봇의 3 s 주입 검사 중 `LocalizationStatus.reason`(상태 CANDIDATES). 스키마 변화 없음(64자 제한 안의 값). API Reference 의 `reason` 목록과 ERR-102 `busy` 설명을 함께 고쳤다.
- 증거: `test/test_localization_contracts.py` +1.
- gate 변화: 없음.

## 2026-10-02 · dbe014f4 · feat(contracts): D-395 LOCALIZED 로봇의 `unmapped_objects` (API v1.74)
- 변경: `LocalizationStatus` 에 선택 필드 `unmapped_objects`(≤16, `RobotPoint`, 기본 `[]`)와 `objects_stamp`(유한 실수, 기본 null)를 더했다. ADR 개정 4 5항 후속(S1 재실행 R1). API Reference v1.73→v1.74, 판 고정 6곳(머리말, `app.py` ×2, `test_line_follow_contract_docs.py`, `test_task_contract_docs.py` ×2, `test_mission_progress.py`). `schemas.py` 는 손대지 않았다.
- 증거: `test/test_localization_contracts.py` +1(왕복, 17개·NaN·inf 거부).
- gate 변화: 없음.

## 2026-10-02 · f341e9fd · feat(core_common): D-411 A 녹화 계약·CORE 가드·읽기 전용 저장소
- 변경: `protocol/recording.py`(경로·토픽·서비스 상수, `TeleopIntent`·`RecorderStatus`(boot_id·seq)·`ManifestFile`·`RecordingManifest`(bag_returncode·writer_killed)·`RecordingSummary`, `recording_id_ok`·`safe_member`), `domain/pilot_recording.py`(소유 토큰·`/ws/state` 링크 5 s·seat 변경 정지, 순번 상태 채택, 확인된 정지만 이벤트), `domain/pilot_recording_store.py`(목록·manifest 검증·경로 탈출 차단·USTAR 스트림). `config/rosy_default.yaml` 에 `recording.pilot_root`.
- 증거: `python -m pytest src/contracts/foundation/test/test_pilot_recording_contract.py src/contracts/foundation/test/test_pilot_recording_guard.py src/contracts/foundation/test/test_pilot_recording_store.py -q` → 65 passed, 2 skipped (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · uncommitted · feat(contracts): additive D-403 CELL_TRANSFER grant

- 변경: 기존 `FleetActionGrant`의 `PICK_PLACE` 제약은 유지하고 `FleetCellTransferGrant` 합집합 변형을 추가했다. 새 payload는 job/recipe/cell hash, ordered step index, item/pallet/layer, robot-base home/pick/place pose와 approach/carry height를 요구한다.
- 증거: `test_device_action_contracts.py`에서 새 grant 왕복 및 잘못된 kind/hash/frame/높이/비유한 pose 거부를 추가했다. 전체 core_common SOURCE suite 424 passed/1 skipped; API Reference를 v1.78로 함께 올렸다.
- gate 변화: 없음. 새 grant schema는 아직 producer/consumer dispatch 경로에서 사용되지 않는다.

## 2026-10-02 · 8dd300c52 · config: `safety.fleet_loss_timeout_s` (D-415)
- 변경: `rosy_default.yaml` 에 `fleet_loss_timeout_s: 3.0`(1–60 s), `fleet_loss_policy` 주석에 네 값, `fleet.enabled` 주석을 "읽히지 않는다"로 정정. 스키마 변경 없음(`safety/state` 는 dict 응답).
- 증거: `src/runtime/gateway/test/test_fleet_loss_wiring.py`(범위 밖 값은 빌드 실패).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · config: SAF-003 주석의 ADR 번호
- 변경: `rosy_default.yaml` 의 `fleet_loss_*`·`fleet.enabled` 주석이 D-419 를 가리킨다.
- 번호: 앞 항목들의 D-415(SAF-003)는 **D-419** 로 바뀌었다 — main 에 다른 D-415(콘솔 운영 가시성)가 먼저 들어왔다. ADR 파일 `docs/adr/D-419-saf003-fleet-link-loss-policy.md`.
- 증거: `git log --all` 의 D-415~D-418 점유 확인(2026-10-02), 번호 변경 뒤 리뷰 시험 묶음 통과.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · config: SAF-003 판정 시간 5 s, 하트비트 답 시한 (D-419)
- 변경: `safety.fleet_loss_timeout_s` 기본 5.0(4–60, ≥ 1 + 답 시한 + 1), 새 `fleet.heartbeat_reply_timeout_s: 2.0`(0.5–10).
- 증거: `src/runtime/gateway/test/test_fleet_loss_wiring.py`(어기면 빌드 실패).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · docs(controls): D-411 B `autonomy` 는 "제공함"이다
- 변경: `BaseVelocityControl`·`pinky_controls` docstring — `autonomy` 는 기기가 제공하는 모드이고 지금 시작할 수 있다는 증거가 아니다(쉬는 동안 차선 준비를 보이는 신호가 없다).
- 증거: 문서만. `test_controls_contract.py` 변화 없음.
- gate 변화: 없음.
- 결정: D-411 구현 부록 5.

## 2026-10-03 · uncommitted · feat(protocol): publish strict Cell goal submission contract
- Change: Move the bounded Cell goal envelope to protocol/cell_goal_evidence.py and re-export CellGoalEvidenceSubmission from schemas.py. Keep envelope protocol_version 1.0 and record additive API Reference v1.84. Re-judge the one-line schemas export at 1240 with unchanged zero-growth allowance.
- Evidence: Foundation and protocol alignment 427 passed/1 skipped; final HTTP producer/consumer and legacy/version checks 64 passed; changed contract Python passes flake8.
- Gate: SOURCE/LOCAL contract evidence; no installed artifact or physical acceptance.

## 2026-10-03 · uncommitted · feat(core_common): D-411 C `OmxSimGripperGoal`
- 변경: `protocol/omx_sim.py` `OmxSimGripperGoal{instance_id, seat_id, request_id, position, duration_s, state_sequence, expires_at_ms}` — 유한한 절대 위치, 길이 `GRIPPER_GOAL_MIN_DURATION_S`–`GRIPPER_GOAL_MAX_DURATION_S`(0.2–2.0 s), 다른 필드 거부. 위치 한계는 런타임(셀 프로필)이 판정한다.
- 증거: `python -m pytest src/contracts/foundation/test/ -q` → 498 passed, 3 skipped (2026-10-03 Windows).
- gate 변화: 없음.
- 결정: D-411 C 결정 12.

## 2026-10-03 · uncommitted · feat(controls): D-411 C 검토 — `GripperControl.max_velocity`
- 변경: 선택 필드 `max_velocity`(rad/s, >0, 유한). 이보다 빠른 그리퍼 목표는 기기가 거절한다.
- 증거: `python -m pytest src/contracts/foundation/test/ -q` 통과 (2026-10-03 Windows).
- gate 변화: 없음.
- 결정: D-411 구현 부록 10.


## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: 공통 TXT에 Dock·Signal 역할, LinkPolicy·접속/페어링 모델·4자리 Cam 표시 별칭을 추가했다. 발견 캐시 BOM을 정리하고 멀티 NIC/충돌·TTL 수명을 고정했다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.


## 2026-10-03 · uncommitted · fix(link): 현재 접속과 후속 코드 규약 구별

- 변경: 사용자 보정으로 4자리 코드 발급·Cam 표시 별칭은 이번 적용에서 제외했다. 현재 로봇 8자·Cam 6자리 규약을 유지하며 D-432에 추후 통합을 기록했다. 실제 Pinky 접속 수정은 진행한다.
- 증거: 영향받는 Python 2345 passed/84 skipped, quick tier 459 passed/2 skipped, Pilot PWA 87 passed/58 skipped. 코드 규약 보정 뒤 해당 인증·페어링 시험을 다시 실행한다. 공개 검증 기록은 docs/validation/discovery-link-2026-10-03/README.md.
- gate 변화: Android 설치·실제 CORE 인증 확인은 실제 주행·Cam 화면 off 연속 송출·현장 트래픽 수용과 별개다. DEVICE/FIELD 이동 없음.
- 결정: D-432 후속 결정: 접속은 지금, 짧은 코드 통합은 추후 적용.
## 2026-10-03 · e021264e6 · feat(face): D-433 상황표 `core_common.face_screen`

- 변경: LCD 상황표 `screen_for`(D-433 1–18행), D-394 주행 카드 주기(`drive_due`, `drive_card_visible` — `core.bridge.display`에서 이동), `face-inputs.json` 엄격 읽기(`read_face_inputs`, `validate_face_inputs`: 링크·FIFO·16 KiB·소유자·schema 1·3 s). 표준 라이브러리만.
- 증거: `python -m pytest src/contracts/foundation/test/test_face_screen.py -q` 77 passed 2 skipped(POSIX 전용 링크·FIFO).
- gate 변화: 없음.
- 결정: D-433 (Proposed)

## 2026-10-04 · uncommitted · feat(protocol): lane perception selection v1.90
- 변경: `LanePerceptionRequest`(closed paint_source enum), `LanePerceptionStatus`(configured selection, signed model integrity, applied service state, nullable live source) 추가. API ref v1.90; WS envelope protocol_version 1.0 유지.
- 증거: protocol version alignment 및 lane perception API 7 passed; API/import/calibration/command 관련 53 passed (Windows).
- gate 변화: SOURCE/LOCAL. 실제 모델 추론·주행은 별도 DEVICE/FIELD 증거.
- 결정: `docs/plans/2026-10-04-learned-lane-driving-modes.md`

## 2026-10-04 · uncommitted · feat: 저조도 face handover 신선도

- 변경: 카메라 수신 나이와 face 파일 나이를 합산해 2초까지만 조명 근거를 신뢰한다. IDLE standby 조명은 명시 opt-in이며 경보·보정·시험·충전·저전압이 우선한다.
- 증거: face table/native loop/PIL/lamp/package/CORE face handover 317 passed, 4 skipped (Windows).
- gate 변화: SOURCE/LOCAL. ARM64/device/field verification pending.

## 2026-10-04 · uncommitted · feat: 명시적 저조도 보조 조명 수동 모드

- 변경: opt-in 저조도 보조 조명을 IDLE뿐 아니라 MANUAL에서도 허용한다. 자동 navigation, 경보, 시험, 보정, 충전, 낮은 배터리는 보조 조명보다 우선한다.
- 증거: native/face table/PIL 299 passed, 3 skipped.
- gate 변화: SOURCE/LOCAL. ARM64/device/field evidence remains separate.

## 2026-10-04 · uncommitted · feat(protocol): recording start 옵션과 capture provenance

- 변경: 중앙 schemas import에 closed RecordingStartRequest를 re-export한다. VisionPreviewStatus에는 pair availability/sequence와 effective quality_age_ms, VisionEvidenceRecord에는 optional raw/annotated group 및 model_unreviewed 출처를 추가한다. body 없는 legacy start는 raw이며 envelope protocol_version1.0은 유지한다.
- 증거: protocol version alignment와 Guard 실제 옵션 확인·실시간 capability·타입 검증·CORE 통합 포함162 passed,1 skipped.
- gate 변화: SOURCE/LOCAL. annotations는 human-reviewed ground truth가 아니다.

## 2026-10-04 · uncommitted · fix(vision): preserve fresh overexposed quality
- 변경: 원본 조도 invalid reason overexposed를 preview store, API protocol, face handover sanitizer에 전달한다. low_light 조명 허용 범위와 2초 촬영·수신·handover 신선도는 유지한다.
- 검증: 과다 노출 관측을 버리는 RED 3 failed; API·handover·stale 회귀 포함 GREEN은 X:/DevTemp/rosy-lane-device-20261004/overexposed-api-green.txt. 배포·실주행 미검증, 명령 전송 없음.
- 추가 검증: face handover integration RED 1 failed로 display whitelist 누락을 확인·수정. 최종 focused 129 passed, 3 skipped (overexposed-api-green.txt).

- gate 변화: SOURCE/LOCAL. 실기 노출·조명·주행은 별도 검증이다.


## 2026-10-04 · uncommitted · feat(power): fresh battery evidence and idle saving

- 변경: 반복 저배터리 표본의 wake를 단계 변화로 제한하여 기존 IDLE/STANDBY 타이머가 동작한다. Viewer GET /api/v1/power/health와 공유 typed 응답에 배터리·충전 확인 age, 정책 상한·wake 근거, shutdown 요청, 진단 요약을 제공한다. API Ref v1.92, envelope 1.0 유지.
- 검증: injected clock 회귀와 auth/read-only API, 기존 배터리·정지·sentinel 경로 검증. 최종 근거는 docs/plans/2026-10-04-power-health-and-wake.md. OS halt·EEPROM·GPIO·기본 LiDAR 모터 정책 변경 없음.
- gate 변화: SOURCE/LOCAL; 실제 소비전력·충전·RTC/외부 버튼 wake와 배포는 미검증.


## 2026-10-04 · uncommitted · feat(power): long testing dwell with low battery saving

- 변경: 정상 IDLE/STANDBY 기준을 600/1800초로 늘리고 warning60/300, critical/deep30/120초와 min을 취한다. YAML override·API effective timers에 연결한다. 기존 이동·정보 hold·disabled와 배터리 정지/종료 권한을 유지한다.
- 증거: 주입 시계·설정 parser RED3 failed, 전원/배터리/bridge GREEN180 passed. 구조 재판정은 docs/plans/2026-10-04-power-health-and-wake.md에 기록한다.
- gate 변화: SOURCE/LOCAL. 기기 소비전력·물리 wake·배포 검증은 별도다.

## 2026-10-04 · uncommitted · D-452 역할 발견과 승인 directory 계약

- 변경: 실제 모델 SSH의 여섯 번째 TXT profile과 공용 PeerObservation/PeerSummary/PeerCatalogue를 추가한다. 발견·승인·접속 검증을 분리하고 credential 및 listener 없는 앱의 가짜 endpoint를 거부한다. mDNS의 .local/RFC1918와 승인 directory의 DNS/VPN·현재 미해결 주소를 구분한다. API Ref v1.94, envelope 1.0 유지.
- 검증: metadata RED collection(미구현) 뒤 focused252 passed/2 Linux skipped. directory 신원·미해결·VPN 및 mDNS 외부 host 거부 회귀12 PASS. 독립 source review에서 발견한 directory 제한을 수정했다.
- gate 변화: 없음; provider/consumer 구현과 CI·컨테이너 namespace·실제 모델/로봇·다른 망 수락은 별도다. 이 focused 계약 검증으로 전체 module gate를 새로 승격하지 않는다.

## 2026-10-04 · uncommitted · feat(protocol): 공개 LAN rooms typed snapshot

- 변경: access의 RoomDiscoveryHint/SiteRoomsSnapshot을 schemas로 재노출한다. 공개 로봇 힌트 기존5필드와64행 상한·extra 금지·port/FQDN 형식을 API Ref1.98과 맞춘다. CORE 성공응답은 실제 model 검증을 거친다.
- 증거: producer의 canonical service/role/TLS/identity 분류는 그대로이며 body에 secret/승인/제어 권한을 추가하지 않는다. 실제 producer·구조 검사는 root 수행 중이다.
- gate 변화: 통신 typed 계약. 신원 승인·제어 포트·장치 수락 변경 없음.

## 2026-10-04 · uncommitted · fix(site): D-457 마커 우선·무마커 폴백

- 변경: 현행 모듈에 source-token 표시 추적과 승인 보정을 통합. 마커 명시 대응 우선, 없으면 익명 검출·신뢰 가능한 map pose 대조. UI/UX 리팩터링 없음.
- 증거: 공유 벡터·Vision·Fleet·브라우저 전환 조건을 호스트에서 검증. 실제 사이트는 두 등록 로봇과 S21 영상 연결 조회만 확인. 후보 배포·빈 트랙 학습·실물 위치 오차는 미완료.
- gate 변화: 없음. SOURCE/LOCAL 변경이며 DEVICE/FIELD 완료 주장 없음. 기존 등록·credentials 보존.

## 2026-10-05 · uncommitted · feat(pairing): 승인 관계 계약과 설정 쓰기 경계

- 변경: D-456의 typed 요청·승인·키 증명·단기 세션 계약을 공용 protocol에 두고 설정 overlay의 쓰기를 파일 잠금과 원자적 교체로 직렬화한다. CORE 전용 보조 Python 경로는 설치된 서명 release의 소유권·권한·경로·startup hook을 확인한다.
- 증거: 통합본의 실제 P256·API·파일 삭제·서로 다른 프로세스 설정 쓰기·보조 경로 검사 32 PASS. 승인 저장 파일 전체 삭제 시 메모리 기록을 복구하지 않는 회귀 검사를 포함한다. subprocess에는 공용 패키지 PYTHONPATH를 명시했고 첫 환경 누락 실패를 원본으로 보존했다.
- gate 변화: 이 변경의 SOURCE/LOCAL 확인. Linux 실권한·ARM import·서명 payload·실기 승인은 별도이며 과거 DEVICE 증거를 이번 연결 수용으로 사용하지 않는다.

## 2026-10-05 · uncommitted · fix(test): config transaction 하위 프로세스의 현행 package 경로

- 변경: config_transaction 동시 프로세스 시험이 contracts/foundation 경로를 자식 PYTHONPATH에 전달하며 기존 환경을 보존한다. config writer와 locking 구현 변경 없음.
- 증거: main CI core-domain의 ModuleNotFoundError를 호스트에서 재현했다. 수리 후 config transaction·source encoding·시작점·review dataset·P6 묶음 42 passed, known_failures 신규 0.
- gate 변화: LOCAL fixture 복구만. 실물 설정·주행·배포 수용 변경 없음.

## 2026-10-05 · uncommitted · fix(protocol): peer 관계 활성 세션 상한 8

- 변경: peer_pairing.Relationship.session_ids max_length 4에서 8 - 발급부(receiver_repository.issue)·API 레퍼런스와 동시 변경(D-18). 저장 레코드 검증 상한만 같은 값으로 올랐고 필드·모양은 그대로다.
- 증거: contracts/foundation + peer pairing 시험 761 passed 5 skipped, known_failures NEW 0.
- gate 변화: 없음(계약 문서·스키마 동시 정합).
