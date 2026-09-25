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
