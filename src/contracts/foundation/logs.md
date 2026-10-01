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
