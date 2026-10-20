# Fleet Frontend Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 이 계획은 Native 실행을 추천하며 실행 방식은 사용자 검토에서 선택한다.

**Goal:** 공개 레포 하나와 기존 운영 배포를 유지하면서 Fleet 프런트를 백엔드 없이 실행·시험하고, 지원 기능의 샘플 대표 흐름과 같은 화면의 실제 API 연결을 제공한다.

**Architecture:** 앱 개발 HTTP 호스트가 동일 origin으로 자산과 API를 제공하고 sample 또는 connected 어댑터를 선택한다. 화면은 기존 HTTP 계약을 사용하고 음성·영상 브라우저 의존성만 runtime provider로 공급받는다. Fleet은 운영 인증·원장·admission·dispatch와 기존 배포를 계속 소유한다.

**Tech Stack:** 기존 vanilla ES modules, Python 3.12 표준 라이브러리 개발 호스트, 기존 Fleet FastAPI, 원격 pytest·Chromium, 기존 Node 시험. 새 프런트 프레임워크·Node 빌드는 도입하지 않는다.

**Spec:** [프런트 독립 개발 설계](2026-10-21-fleet-frontend-development-design.md). API 조사 입력은 [현재 대응표](2026-10-21-fleet-frontend-api-coverage.md)다. 상태는 검토용 실행 계획이며 구현 완료가 아니다.

## Global Constraints

- 프런트 담당자는 Fleet 백엔드·ROS·장치·운영 DB 없이 앱을 실행한다. sample은 기본 모드이고 upstream을 만들거나 접속하지 않는다.
- 현재 Fleet 진입 화면 8개와 현재 지원 기능을 대상으로 한다. 기능·요청·시나리오·시험 누락을 감춘 채 완료하지 않는다.
- 같은 화면 업무 코드를 sample/connected/운영에 사용한다. 운영 패키지는 native runtime provider만 제공한다.
- `/console`, `/api/fleet/*`, `fleet.server.web`, `rosy-app-gateway`, `rosy-site-gateway` 신원을 유지한다.
- 자산 경로 거절·운영 CSP·권한·쿠키·Origin·TLS 검증을 보존한다. 실제 자격 증명·장치 설정은 private에 둔다.
- sample은 인증·원장·장치 실행 엔진을 복제하거나 import하지 않는다. 미등록 요청은 개발 오류로 실패한다.
- 별도 프런트 운영 배포·외부 도메인 인증·Robot/Pilot/Face/Learning 전체 앱 이전은 이번 범위가 아니다.

## Review Focus

1. 실제로 미설정인 capability를 빈 성공 응답으로 숨기는 경우: Task 1·3에서 활성/비활성·거절 시나리오를 검사한다.
2. 샘플 요청이 빠져 실제 네트워크·마이크·음성 팩·미디어에 접속하는 경우: Task 3·4에서 upstream 미생성 및 브라우저 외부 요청/실장치 호출 0을 검사한다.
3. 세션·Origin이 프록시에서 잘못 매핑되는 경우: Task 5에서 로그인→변경→로그아웃과 외부 Origin·Host·TLS 거절을 검사한다.
4. 작업 요청 재전송·과거 polling·초기화가 서로 다른 상태를 덮는 경우: Task 3에서 ID·revision·세션·시나리오 초기화의 일관성을 검사한다.
5. 자산 목록·설치 패키징이 개발과 운영에서 달라지는 경우: Task 2·7에서 같은 alias·본문·경로 거절과 wheel/sdist·사이트 이미지 입력을 검사한다.

## 소유와 진행 방식

각 Task는 다른 리뷰가 가능한 착지 단위다. 실행 시 현재 main에서 전용 워크트리를 `tools/worktrees.py new`로 만들고, 해당 Task의 파일만 소유한다. Task 6은 독립 분리 과제로 별도 브랜치에서 진행할 수 있다. Task 1→2→3→4→5→7은 앞 단계 인터페이스를 소비하므로 순서대로 진행한다. 공동 작업자는 다른 세션의 변경을 되돌리지 않는다.

각 Task의 시험 사이클은 아래 순서다. 노트북 pytest는 실행하지 않는다.

1. 명시한 실패 시험을 작성하고 해당 시험 파일만 명시적으로 스테이징해 커밋한다.
2. 해당 Task의 명령을 원격 runner로 실행해 의도한 assertion 실패를 확인한다. 환경·collection 오류를 red 증거로 대체하지 않는다.
3. 최소 구현을 하고 소유 파일을 명시적으로 커밋한다. 생성 기록이 바뀌면 기준 지침대로 생성·검사한다.
4. 같은 원격 명령을 다시 실행하고 `python test/known_failures.py <외부 로그>`로 NEW 0을 확인한다. 기존 기능 회귀·정적 검사는 Task에 지정한 범위로 수행한다.
5. 독립 검토 후 사용자가 허용한 범위에서만 표준 `tools/land.py`로 착지한다. selector의 FULL을 좁은 명령으로 대신하지 않는다. push·배포는 별도다.

시험 로그의 `<log-dir>`는 `$ROSY_SCRATCH` 또는 시스템 임시 폴더 아래 Task별 경로로 정한다. 아래 명령은 구현 후 생길 시험 경로를 포함하며 현재 실행 가능한 기능을 주장하지 않는다.

## Task 1: 지원 기능과 HTTP 계약의 완료 표 만들기

**Files:** Create `applications/fleet/test/feature_matrix.json`, `applications/fleet/test/test_feature_matrix.py`; Modify `applications/fleet/README.md`. 계약 누락이 실제로 발견되면 소유 서비스 구현·live API reference·기존 모델/시험을 별도 작은 변경으로 보완한다.

**Interfaces:** Produces JSON feature 목록. 각 항목은 `id`, `entrypoints`, `consumers`, `availability`, `requests`, `flows`. request는 `id`, `method`, `path`, `implementation`, `contract_tests`, `expected_statuses`, `status`를 갖는다. flow는 `id`, `steps`, `scenario_id`, `browser_test`; step은 request ID와 화면 assertion을 갖는다. `status`는 `verified` 또는 `unverified`이며 이 값은 실제 계약 시험 근거로만 바꾼다. 기존 응답 schema는 참조한다.

- [ ] 8개 HTML과 하위 기능을 대응표에서 세분화한다. 동적 URL·pairing prefix·공통 클라이언트 호출을 method/path까지 추적한다.
- [ ] 실패 시험 `test_all_supported_features_have_contracts_and_flows`를 작성한다. 중복 ID·없는 경로·끊긴 request 참조·대표 흐름 누락·`unverified` 항목이 있으면 완료 판정이 실패해야 한다.
- [ ] 위 사이클의 red를 확인한 뒤 기존 서버의 활성 조건·역할·revision·접수/진행/결과·오류를 계약 시험과 대조해 표를 채운다. 실제 API 누락과 아직 미확인인 항목을 구분한다.
- [ ] Green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- applications/fleet/test/test_feature_matrix.py` 및 참조한 소유 서비스 계약 시험. 모든 항목이 검증된 상태가 Task의 종료 조건이다.

## Task 2: 앱 자산 목록과 백엔드 없는 정적 fixture

**Files:** Create `applications/fleet/web/assets.json`, `applications/fleet/web/asset_registry.py`, `applications/fleet/test/test_asset_registry.py`; Modify `operations/fleet/fleet/server/console/static_routes.py`, `test/console_browser_site.py`, `operations/fleet/setup.py`, `tools/packaging/fleet_sources.py`, 사이트 이미지 입력과 해당 계약 시험.

**Interfaces:** Produces `load_registry(root: Path) -> dict`와 `resolve_entry(root: Path, entries: Mapping, name: str) -> tuple[Path, str] | None`. JSON은 `pages`와 `assets`의 공개 이름→`path`·`media_type` 매핑이다. 순수 표준 라이브러리이며 Fleet·ROS를 import하지 않는다. 설치 시 `fleet.server.web.asset_registry`로 포함하고 앱 도구는 소스 파일을 직접 로드할 수 있다.

- [ ] `test_registry_preserves_all_existing_aliases`, `test_registry_rejects_escape_missing_and_duplicate_entries`를 작성한다. 기존 asset key·media type·8개 페이지가 정확히 보존되고 `../`·root 밖 symlink·없는 파일·중복 key가 거절돼야 한다.
- [ ] red 확인 후 현재 사전을 JSON으로 옮기고 두 소비자가 같은 loader를 사용하게 한다. 페이지별 기존 헤더·CSP·인증·health/root 동작은 유지한다. 새 기능을 섞지 않는다.
- [ ] `test_registry_loads_without_fleet_or_ros`는 격리 subprocess에서 loader를 읽어 Fleet 설치 없이 동작함을 확인한다. fixture의 `fleet.server.static_routes` import를 제거한다.
- [ ] Green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- applications/fleet/test/test_asset_registry.py test/test_site_candidate.py test/test_platform_installed_entrypoints.py`; 기존 asset/설치/브라우저 fixture 회귀와 selector가 요구한 FULL을 별도 수행한다.

## Task 3: 샘플 HTTP 실행과 대표 상태 전환

**Files:** Create `applications/fleet/dev/{serve.py,http_host.py,response.py}`, `applications/fleet/dev/sample/{engine.py,sessions.py,work.py,spatial.py,installation.py,governance.py,assistant.py}`, `applications/fleet/dev/sample/fixtures/`, `applications/fleet/test/{test_sample_server.py,test_sample_flows.py}`. fixture는 Task 1에서 검증한 계약별 JSON·로컬 미디어를 사용한다.

**Interfaces:** `DevResponse(status: int, headers: list[tuple[str, str]], body: bytes | Iterable[bytes])`와 공급자 `handle(method: str, target: str, headers: Mapping[str, str], body: bytes) -> DevResponse`. `SampleEngine(scenario_id: str)`는 `handle`, `reset(scenario_id: str) -> None`, `advance(flow_id: str, event: str) -> None`를 제공한다. 서로 다른 기능군은 같은 engine 상태의 ID·revision을 공유한다.

- [ ] `test_sample_starts_without_backend_and_never_creates_upstream`, `test_unknown_request_is_error`, `test_flow_ids_revisions_and_reset_are_consistent`를 작성한다. 알 수 없는 요청은 501 개발 오류, 잘못된 시나리오/전환은 409로 거절하고 actual API의 거절과 구분한다.
- [ ] red 확인 후 loopback 개발 호스트, 자산 제공, JSON body와 status·header를 보존하는 API 공급을 구현한다. sample HTTP 세션은 별도 이름 `rosy_sample_session`을 쓰며 실제 Fleet 쿠키를 무시한다.
- [ ] 기능군별로 Task 1 flow를 구현한다. 정상·권한/미설정 거절·충돌·취소·보류·복구·terminal 조회를 계약값과 맞춘다. 성공/실패 진행은 명시적인 `advance` 이벤트로 제어하고 실제 시각이나 장치에 맡기지 않는다.
- [ ] 개발 전용 `POST /__dev/reset`, `POST /__dev/advance`는 동일 origin 요청만 받고 sample에서만 동작한다. production·connected에는 샘플 상태 제어를 제공하지 않는다.
- [ ] Green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- applications/fleet/test/test_sample_server.py applications/fleet/test/test_sample_flows.py`; 표의 모든 sample flow ID를 실행하고 미등록 API 요청 0을 확인한다.

## Task 4: 같은 화면의 샘플 브라우저·음성·영상 흐름

**Files:** Create `applications/fleet/web/runtime.js`, `applications/fleet/dev/web/{runtime-sample.js,browser-platform.js,media-session.js,controls.js,controls.css}`, `applications/fleet/test/{test_sample_browser.py,test_browser_adapters.py}`; Modify `applications/fleet/web/assistant/panel.js`, `applications/fleet/web/shared/robot-video.js`, Task 2 자산 목록과 기존 Node 자산 loader. `assistant-voice.js`와 공유 WebRTC 내부 구현은 유지한다.

**Interfaces:** native `runtime.js`와 sample provider는 같은 exports `voicePlatform`, `openRobotCamera`를 제공한다. native는 `globalThis`와 `/common/webrtc.js`의 `openCamera`를 그대로 제공한다. 공개 alias는 `/console/assets/app-runtime.js`다. panel은 `createVoice({platform: voicePlatform, ...})`, robot-video의 기존 `open` 기본값은 `openRobotCamera`를 사용한다. sample 개발 호스트는 이 등록된 runtime alias에만 sample provider를 선택한다. 다른 화면 업무 파일은 복제하지 않는다.

- [ ] `test_eight_pages_and_feature_flows_use_same_frontend`, `test_sample_voice_and_video_need_no_browser_devices_or_external_network`를 작성한다. 모든 네트워크 요청은 개발 origin 또는 로컬 data/blob 자원이어야 한다.
- [ ] red 확인 후 voice platform과 카메라 세션을 주입한다. sample의 음성 준비·입력·중지·거절은 합성 이벤트로, 영상은 로컬 프레임과 stale/unavailable 이벤트로 재현한다. sample `openRobotCamera(options)`는 native open과 같은 `close(reason)` 세션과 `onState`·renew/revoke 수명을 제공한다. 전역 API나 공유 WebRTC를 monkeypatch하지 않는다.
- [ ] 개발 호스트가 외부 JS/CSS로 sample 표시와 시나리오 제어를 제공한다. 운영 HTML/CSP에 inline 예외를 추가하지 않는다. 초기화·역할/페이지 전환·늦은 polling 응답이 과거 상태를 되살리지 않아야 한다.
- [ ] Green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- ROSY_RUN_BROWSER_TESTS=1 applications/fleet/test/test_sample_browser.py applications/fleet/test/test_browser_adapters.py`; Task 1의 모든 `browser_test`와 sample 흐름을 실행한다. sample 결과는 DEVICE/FIELD 증거로 쓰지 않는다.

## Task 5: 실제 Fleet 연결 어댑터

**Files:** Create `applications/fleet/dev/connected.py`, `applications/fleet/test/test_connected_proxy.py`; Modify 개발 HTTP 호스트·CLI와 `applications/fleet/README.md`. 기존 Fleet 인증·권한 코드를 바꾸지 않는다.

**Interfaces:** `ConnectedAPI(upstream: str, ssl_context: ssl.SSLContext, local_origin: str)`는 Task 3의 `handle`을 제공한다. local origin 검사를 먼저 하고 설정된 단일 upstream에만 전달한다. 응답의 JSON·바이너리·상태·세션/삭제 쿠키를 보존하며 스트림 body는 반복자로 전달한다.

- [ ] `test_login_write_logout_and_revocation`, `test_foreign_origin_host_and_spoofed_forwarding_are_rejected`, `test_tls_error_binary_cancellation_and_redirect`를 작성한다. 가짜 TLS upstream을 사용하고 자격 증명·오류 내용을 로그에 노출하지 않는다.
- [ ] red 확인 후 설계의 origin/header/cookie 규칙을 그대로 구현한다. HTTPS connected에 private 인증서·키를 명시하고 upstream TLS를 검증한다. missing/foreign Origin 변경 요청은 upstream 호출 0이어야 한다. Domain 쿠키·외부 redirect·sample 자동 fallback을 허용하지 않는다.
- [ ] 원격 green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- applications/fleet/test/test_connected_proxy.py`. JSON·이미지·스트림 전달과 연결 종료/취소의 자원 회수, backend 401/403/409/5xx 보존을 확인한다.
- [ ] connected 영상은 기존 클라이언트가 승인된 media grant의 HTTPS origin으로 연결하며 `credentials: omit`을 유지함을 확인한다. Fleet 세션을 media origin에 전달하지 않고, 개발 프록시를 임의 외부 URL 프록시로 확장하지 않는다.
- [ ] 이후 개발 Fleet 통합은 별도 명시한 대상에서 실제 로그인→변경→진행/결과→로그아웃을 확인한다. sample이나 fake-upstream 통과를 실제 Fleet 통합 통과로 적지 않는다. 장치 접근·물리 동작 승인은 이 계획이 부여하지 않는다.

## Task 6: gateway의 공개 실행 인터페이스

**Files:** Modify `operations/fleet/fleet/cli.py`, `applications/fleet/gateway/src/rosy_gateway/compose.py`, `test/test_platform_installed_entrypoints.py`, 필요한 CLI 기존 시험. 후속 ADR은 이 변경 전에 예약·기록한다.

**Interfaces:** Fleet이 `run(argv: Optional[Sequence[str]] = None) -> None`를 공개한다. 기존 구현을 이 이름으로 정리하고 `fleet.cli.main`과 `rosy_gateway.compose.main`이 이를 사용한다. Fleet은 gateway를 import하지 않는다. 기존 CLI 이름·인자·KeyboardInterrupt 의미를 유지한다.

- [ ] 기존 위임 시험을 바꿔 `test_fleet_cli_runs_without_gateway`와 `test_gateway_calls_public_fleet_run_once`로 만든다. argv가 한 번만 전달되고 gateway 없는 설치에서도 Fleet이 실행됨을 검증한다.
- [ ] red 확인 후 역방향 import와 `_main_impl` 사용을 제거한다. 공정/장치 owner·인증·DB 변경은 섞지 않는다.
- [ ] Green: `python tools/remote/remote_pytest.py --log-dir <log-dir> -- test/test_platform_installed_entrypoints.py test/test_platform_minimal_install.py test/architecture/test_platform_dependency_boundaries.py` 및 기존 CLI 시험. 실제 설치 profile 회귀와 독립 소유권 검토를 포함한다.

## Task 7: 개발 명령·시험 선택·운영 포장 마무리

**Files:** Modify `applications/fleet/README.md`, `applications/fleet/dev/serve.py`, `tools/harness/platform_parts.yaml`, `tools/harness/platform_dependencies.yaml`, `tools/harness/affected_tests.py`, `test/browser_scope.py`, `test/test_affected_tests.py`, `test/test_browser_scope.py`, `test/test_site_candidate.py`, `test/test_platform_installed_entrypoints.py`, 필요한 `.github/workflows/ci.yml` 입력. selector가 이미 인식하는 경로에는 불필요한 규칙을 더하지 않는다. 기존 Python/Node UI 시험은 책임별로 분류하며 일괄 이동하지 않는다.

**Interfaces:** sample 명령은 `python applications/fleet/dev/serve.py --mode sample --scenario normal --port 4173`. connected는 `--mode connected --origin https://localhost:4174 --upstream https://<fleet-host> --cert <private-cert> --key <private-key>`이며 필요 시 `--ca <private-ca>`로 검증 CA를 공급한다. sample과 connected의 origin/포트를 구분하고 예제에 실제 대상·비밀을 넣지 않는다.

- [ ] `test_app_changes_select_app_contracts_and_browser_tests`, `test_installed_fleet_contains_native_assets_only`를 기존 selector/설치 시험에 추가한다. dev/sample 파일이 운영 패키지에 섞이지 않고 자산 목록·native provider는 wheel/sdist·이미지에 포함돼야 한다.
- [ ] red 확인 후 테스트 선택·포장을 연결한다. 앱 담당자가 README 한 곳에서 설치/실행·샘플 초기화·연결·시험 명령을 찾을 수 있게 한다.
- [ ] Green: 새 앱 계약·시나리오·브라우저와 기존 설치/CLI·자산·인증 회귀를 원격 실행한다. 로컬 lint·size-range·safety-review와 독립 리뷰를 통과하고 표준 착지 도구가 선택한 FULL을 완료한다.
- [ ] 최종 인수: 8개 화면, Task 1의 지원 기능 전부, sample 외부 연결 0, connected 인증/오류/진행·결과, 기존 운영 자산 신원이 각각 증거를 가져야 한다. skip·미검증 실제 Fleet 통합·장치/배포는 결과에서 따로 적는다.

## 실행 검토

이 계획의 완료는 실제 코드·API 충족·sample 기능의 완료가 아니다. 먼저 문서의 목표·기능 범위·인증/브라우저 어댑터·착지 단위를 검토한다. 순차 인터페이스가 많으므로 Native 실행과 단계별 독립 검토를 추천한다. 다른 실행 방식을 원하면 각 Task의 파일 소유와 전달 인터페이스를 유지한다.
