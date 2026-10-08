# core_api_web logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-22 이전 이력은 `git log -- src/core/core_api_web`를 본다.

## 2026-09-22 · uncommitted · docs(harness): register core_api_web under D-168
- 변경: `AGENTS.md`(없던 경우), `progress.md`, `logs.md` 추가, `harness.yaml` 등록
- 증거: `python -m pytest src/core/core_api_web/test -q` — 9 passed (2026-09-22 Windows)
- gate 변화: 없음(신규 기록). SOURCE/LOCAL GO, 나머지 N/A(라이브러리 등급)
- 결정: D-168
- 교훈: 없음

- 같은 세션 T10: app.py 버전 표기 v1.16 정렬(근거·증거는 core_common 로그와 동일 세션 기록)

## 2026-09-23 · uncommitted · feat(api): `/metrics` 에 `rosy_audit_dir_sync_failures_total`, 계약 v1.17
- 변경: `api/v1/observability.py` — 감사 로그 정리의 바꿔 끼우기 뒤 디렉터리 fsync 실패 카운터(`FileAuditLog.health()["dir_sync_failures"]`). `api/app.py` description 을 계약 v1.17 로
- 증거: `src/core/core/test/test_diagnostics_api.py::test_the_audit_metric_names_are_the_ones_the_contract_tells_operators_to_alert_on` 에 이름 추가, `test_protocol_version_alignment.py` 통과
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음

## 2026-09-24 · uncommitted · refactor(core): D-168 미사용 `core_events` 선언 제거

- 변경: `package.xml`의 `<depend>core_events</depend>` 제거(생산 import 0). `AGENTS.md` Key Files·Internal 선언 목록에서 `core_events` 제거.
- 증거: 커밋 직전 `python -m pytest test/ -q` 초록 — D-168 구조 시험 포함 (2026-09-24 Windows).
- gate 변화: 없음. SOURCE HOLD(자체 test/) 유지.
- 결정: module-coupling-scorecard §6 과제 4 (D-168 P3 "선언한 결합이 실제로 쓰이는지" 정리).
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(dashboard): 하드웨어가 없거나 모를 때 사실대로 보인다 (US-010), 계약 v1.18
- 변경: `web/dom.js` `number`/`percent` 가 `null` 을 0 으로 읽지 않는다(배터리 0% / 0.00 V 오경보). `web/app.js` 안전 회로 영웅 표시가 서버 `evidence.safety` 를 읽어 배너와 같은 판정을 쓴다 — fresh 일 때만 READY, CORE-only 는 `HW OFF` + "하드웨어 런타임 꺼짐 (CORE-only)". 역할은 `GET /system/info` 의 `caller_role` 로 알아내고 `/logs/audit` 를 찔러 보지 않는다(viewer 403 제거). `web/triage.js` `runtime_mode:core` 차단 descriptor 다섯을 색 없는 관측 사실 하나로 접는다. `api/v1/system.py` `caller_role`, CAP-001 `withheld`. `api/app.py` 계약 v1.18.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py -q` 21 passed (신규 2건: CORE-only viewer, 하드웨어 모드 안전 출처 무음). `src/core/core/test/test_dashboard.py` 구조 단언 갱신. 실기 근거: rosy-pinky-e4us 릴리스 005 헤드리스 점검 (2026-09-24).
- gate 변화: 없음 (DEVICE 재검증 필요 — 새 이미지에서 대시보드 재확인).
- 결정: D-32, D-161, D-82 Law 0 적용. 신규 ADR 없음.
- 교훈: `Number(null) === 0` — 결측 표시는 캐스트 전에 걸러야 한다.

## 2026-09-24 · uncommitted · docs(api): 계약 v1.18 — 도킹·라인 추종 거부 코드

- 변경: `ROSY API & Protocol Reference` v1.17 → **v1.18**, `app.py` `version`/description 동기화. ERR-102 에 `LINE_FOLLOW_ACTIVE`(409)·`NO_ODOMETRY`(409) 추가. `POST /docking/dock`·`/docking/undock` 에 409 사유(`LINE_FOLLOW_ACTIVE`·`MODE_CONFLICT`·`NO_ODOMETRY` 등), `PUT /line-follow/mode` 에 409 `DOCKING_ACTIVE`, `POST /docking/types` 에 주차형 선택 필드. Corrective: 내비게이션 `DOCKING_ACTIVE` 가 400 으로 나가던 것을 문서대로 409 로 고친 브랜치 수정(88702af7)을 변경 이력에 `409≠400` 으로 기록.
- 증거: `python -m pytest src/core/core/test/test_protocol_version_alignment.py -q` 초록 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: Additive(MINOR) + Corrective. envelope `protocol_version` 1.0 유지.
- 교훈: 없음

## 2026-09-24 · uncommitted · docs(api): contract v1.20 — lane-network docking rows renumbered on merge
- 변경: origin의 US-010(v1.18)·D-193(v1.19)과 로컬 lane-network 도킹 변경(원래 v1.18)이 같은 번호를 썼다. 도킹 행을 v1.20으로, `api/app.py` 버전과 API Ref 헤더, `test_line_follow_contract_docs.py` 고정값을 v1.20으로 맞췄다
- 증거: 머지 후 host pytest (sync/origin-main)
- gate 변화: 없음
- 결정: PRT-006
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(web): 운용 조작 열 적합 회복과 정책 편집 이동 (D-201, D-203)

- 변경: (1) 조작 열 분쇄 방지 ? 고정 프레임 flex 자식 `flex: none`(모드 분절 제어가 44px→2px로 눌리던 것 실측). (2) 교통 정책 편집 UI(입력 6종·검토본·적용·SIM 신호)를 점검 뷰 현장 설정 카드로 이동, id는 그대로라 바인딩 생존. (3) 차선·교통 계기값 dl을 감지 영역 패널로 이동(사실은 감지, 조작은 조작). (4) 공용 라벨 규칙에 line-follow-copy h3 보강(16.38px 누수), 나이 접미 em→토큰. (5) region-act 잔존 inset sheen 제거(D-158 정신).
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py -q` → 43 passed(신규 게이트 5종 포함, 변이 증명 완료). 단위 60+54 passed.
- gate 변화: 콘솔 G1에 적합 게이트(2뷰포트×2상태)·계산 척급 센서스 게이트 추가.
- 결정: D-201, D-203
- 교훈: 스크롤이 금지된 문법에서 flex-shrink는 넘침을 조용한 분쇄로 바꾼다 ? 게이트는 분쇄도 재야 한다.

## 2026-09-24 · uncommitted · fix(dashboard,api): 무동작 하드웨어 런타임을 사실대로 — 구동 꺼짐, 이동 광고 없음, API 정지 문구, 맵 404 없음, 계약 v1.21
- 증상(실기 rosy-pinky-e4us, release 2026.09.24-010): CORE-only 이미지에서 `rosy-io` 를 무동작 모드로 켜자 배터리·오도메트리가 들어오고 `motor/ready` 는 false 였는데, 대시보드는 SAFETY "HW OFF — 하드웨어 런타임 꺼짐 (CORE-only)", 기능 가용성 5 / 5, `capabilities` 는 withheld 없음·teleop true 였다. 하드웨어가 꺼져 있을 때는 차단 이유가 `device_state:SAFE_STOP`(실제는 `runtime_mode:core`)였고, API 정지(`api:operator`)에 "모터 전원이 끊겼습니다. 현장에서 해제해야 합니다" 를 보였다. `/api/v1/map`·`/map/costmap?scope=global` 404 가 콘솔 오류로 남았다.
- 변경: `api/v1/system.py` `capabilities` 가 `runtime_truth` 로 플래그를 내리고 additive `runtime`(`hardware`·`evidence`·`drive`·`navigation`·`maps`)을 싣는다. `web/app.js` 안전 회로 영웅 표시는 `capabilities.runtime` 으로 `HW OFF`/`HW SILENT`/`NO DRIVE`("하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)")/`NO SOURCE` 를 가른다(구 서버는 `runtime_mode` 로 폴백). descriptor 이유는 `reasons` 전부를 운용자 말로 잇는다. teleop 안내에 보류 이유. `fieldMap.refresh()` 는 capabilities 뒤에 돈다. `web/map.js` 는 `runtime.maps` 가 false 인 스냅샷을 묻지 않는다. `web/triage.js` 이유 문구 표, 구성 이유(CORE-only·무동작·내비게이션 없음)는 각각 색 없는 관측 사실 하나, `estopFault(source)` — CORE 의 모든 정지는 소프트웨어 정지이므로 전원 차단을 말하지 않는다. `api/app.py` 계약 v1.21.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py -q` 40 passed(신규 3: 무동작, 맵 요청, API 정지 문구), `src/core/core/test` 포함 1553 passed (2026-09-24 Windows).
- gate 변화: 없음 (DEVICE 재검증 필요 — overlay 후 무동작 `rosy-io` 로 대시보드 확인).
- 결정: D-32, D-192, D-82. 신규 ADR 없음.
- 교훈: 브라우저의 404 콘솔 오류는 JS 로 삼킬 수 없다 — 없는 자원은 서버가 "없다"고 먼저 말하고 클라이언트가 묻지 않아야 한다.

## 2026-09-25 · uncommitted · fix(web): 점검 머신 태그의 위험은 채움 (D-214)

- 변경: [data-status=ERROR]·[data-status=UNAVAILABLE]을 crit 글자(점검 패널 위 2.68:1)에서 종이 잉크+위험 채움으로. 회차 1 warm 스캔이 operate만 봐서 못 잡은 D-202 잔존분을 바닥 게이트가 적발.
- 증거: ROSY_RUN_BROWSER_TESTS=1 pytest test/test_dashboard_browser.py -q → 45 passed(전 텍스트 바닥 게이트 2종 신설 — F-19가 그 자체로 변이 증명: 적색→수정→녹색).
- gate 변화: 콘솔 G1에 전 텍스트 대비 바닥 게이트 추가(양 뷰×2상태).
- 결정: D-214
- 교훈: warm 스캔의 뷰 범위가 곧 게이트의 눈이었다 — 점검 뷰는 별개 세계다.

## 2026-09-25 · uncommitted · refactor(runtime): move core_api_web under src/runtime (D-231)

- 변경: src/runtime/core_api_web로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-25 · 96654ed1 · feat(api): board device card API and motion reason (D-247)

- 변경: `GET /api/v1/host/hardware`(viewer)가 root probe 결과를 엄격히 읽고(O_NOFOLLOW·정규 파일·64 KiB·스키마 1) `age_s`·`stale`을 더하며, rosy-io가 쥔 행은 토픽 신선도(odom·scan·battery)로 덮는다. `POST /api/v1/host/hardware/refresh`(admin)는 요청 파일만 쓴다(10 s 디바운스, subprocess 없음). `/commissioning`에 `motion_reason`. API Ref v1.22.
- 증거: `src/runtime/gateway/test/test_host_hardware.py` 28 passed 1 skipped
- gate 변화: 없음
- 결정: D-247
- 교훈: 없음

## 2026-09-26 · 8e6902fd · feat(api): buzzer and lamp test and the person's answer (D-247 6)

- 변경: `POST /api/v1/host/hardware/test`(admin, 10 s 쿨다운 `HW_TEST_COOLDOWN` 429, `HW_TEST_UNAVAILABLE` 503)는 `/run/rosy/hw-test.request`만 쓴다. `POST /api/v1/host/hardware/confirm`(admin, 엄격한 bool)은 `~/.rosy/hw-confirmations.json`에 원자적으로 기록한다(`HW_CONFIRM_UNAVAILABLE`). `GET /host/hardware`에 `test` 필드와 `needs_human` 부저·램프 행의 사람 확인 덮기(`source:"human"`)를 더했다. API Ref v1.23.
- 증거: `src/runtime/gateway/test/test_host_hardware.py` 57 passed 1 skipped
- gate 변화: 없음
- 결정: D-247
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(api): serve the device hardware panel through the UI registry

- 변경: `panels.yaml`의 관리자 `host.hardware` 항목이 JS/CSS 자산과 패널 순서를 선언한다. API 자산 허용목록은 registry에서 파생한다.
- 증거: `test_ui_route.py`가 자산 HTTP 응답과 관리자 패널 등록을 확인한다.
- gate 변화: 없음. host API 시험은 실제 Pi probe 응답을 증명하지 않는다.
- 결정: 새 REST 경로·필드는 추가하지 않았다.
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(core_api_web): D-260 GET /api/v1/host/status-summary (API Ref v1.25)
- 변경: `api/v1/host.py`에 `read_boot_status`(엄격 읽기)와 `status-summary` 라우트. 장치 행은 `/host/hardware` 덮기를 그대로 거친다. `app.py` 설명 v1.25, 대시보드 자산 allowlist에 `status-summary.js`
- 증거: `python -m pytest src/runtime/gateway/test/test_host_status_summary.py -q` 16 passed, 1 skipped(POSIX 링크); 2026-09-26 Windows, `feat/d260-status-signals`: 호스트 묶음(foundation·gateway·api_web·hmi web/dashboard/face·lamp·boot display·hw-test·hw-probe·boot-status·native systemd·device surface·image customization·lamp image·harness) 2051 passed, 32 skipped, 2 failed — 둘 다 main의 `src/hmi/dashboard/logs.md` 두 항목(`- 근거:`)이 원인이고 깨끗한 main worktree에서도 같게 실패한다. `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 62 passed
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: 없음

## 2026-09-26 · uncommitted · fix(core_api_web): D-260 review M1 status inputs hand-over
- 변경: `api/v1/host.py`에 `status_inputs`·`write_status_inputs`(`/run/rosy/status-inputs.json`, 원자적 교체). `core/node.py` 타이머가 10 s마다 쓴다
- 증거: `python -m pytest src/runtime/gateway/test/test_host_status_summary.py -q` 27 passed, 1 skipped
- gate 변화: 없음
- 결정: D-260 Proposed
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(core_api_web): bounded operator camera evidence storage

- 변경: 인증된 카메라 파일 POST/목록/다운로드 API, 엄격한 메타데이터와 JPEG/WebM/MP4 검사, 원자 기록, 파일·총량·남은 공간 상한을 추가했다.
- 증거: 저장 스트림·인증·다운로드 시험을 `src/runtime/api_web/test/`와 `src/runtime/gateway/test/test_vision_evidence_api.py`에서 검증했다.
- gate 변화: 없음. PC 시험은 SD 수명·용량·실장 동작을 증명하지 않는다.

## 2026-09-26 · uncommitted · feat(core_api_web): add D-283 action group manifest metadata

- 변경: panel registry validates optional console-act `action_group`; surface descriptors and structural revision carry the field. Role/CAP-001/inventory filtering still removes unsupported panels before groups are built.
- 근거: `python -m pytest src/runtime/api_web/test -q` 63 passed, 3 skipped; dashboard/CORE browser group also passed.
- gate 변화: 없음. REST path is unchanged; additive optional descriptor field is documented in API Ref v1.36.
- 결정: D-283 Accepted.
- 교훈: 없음

## 2026-09-27 · uncommitted · test(ui): verify real CORE role surfaces at desktop and mobile widths

- 변경: 실제 TestClient 라우트로 설치·정비 화면의 패널 교차, 래퍼 구성, 가로 넘침과 브라우저 오류를 검증한다. 운용 화면은 카메라가 상태 영역에 있는지 확인한다.
- 증거: `test_d283_console_browser.py` 5 passed 및 절차 4셀 변경 후 재실행 통과. 캡처는 X:에 보관한다.
- gate 변화: LOCAL 근거 보강. API 계약 및 장치 수용 변화 없음.

## 2026-09-27 · uncommitted · feat(host): judge status age from Host Agent UTC

- 변경: CORE가 Host Agent `network.status`·`release.status`의 원본 조회 완료 UTC를 검증하고 `evidence`·`age_s`를 추가한다. 누락·잘못된·미래 시각과 거부는 unavailable, 미연결·타임아웃은 disconnected, 15초 초과는 delayed다.
- 근거: Host Agent/CORE 계약과 브라우저 회귀. 정상 원본 시각 없는 오래된 Agent의 데이터는 표시하지 않는다.
- gate 변화: SOURCE/LOCAL 계약 근거 추가. 실제 Host Agent 서비스와 장치 적용은 별도 HOLD다.

## 2026-09-28 · uncommitted · add optional navigation attempt correlation

- 변경: CORE `/api/v1/navigation/goal`이 선택적 `correlation_id` metadata를 받으며 기존 x/y/yaw/waypoint 요청은 유지한다. NavigationManager는 같은 attempt ID를 started/canceled/final result event data에 싣는다.
- 증거: api_web 70 passed, 13 skipped; gateway navigation/API/event focused coverage 통과. Fleet task API 자체의 공개 intent 필드는 바뀌지 않는다.
- Gate: SOURCE/LOCAL only; ROS-SIM, artifact, device, field acceptance 없음.

## 2026-09-29 · uncommitted · point the API description at the live contract version

- 변경: `app.py` FastAPI `description`의 `(v1.41)`을 API Ref 헤더가 선언하는 `v1.47`로 맞췄다. `test_app_description_names_the_live_contract_version`이 요구하는 값이다.
- 증거: `test_protocol_version_alignment` 포함 api_web 70 passed, 13 skipped. 문서 참조 표기만 바뀌었다.
- gate 변화: 없음. 계약 필드·경로·버전 정책은 그대로이고 FastAPI 문서에 보이는 설명 문자열만 갱신했다.

## 2026-09-29 · uncommitted · docs(contract): follow API Ref v1.48 in the description

- 변경: API Ref v1.48(Site Fleet 정책 적격 증거 계약 추가)에 맞춰 설명 문자열을 `(v1.48)`로 갱신했다.
- 증거: api_web 70 passed, 13 skipped(버전 정렬 시험 포함).
- gate 변화: 없음. 로봇 측 계약 필드·경로는 무변경이고 표기만 따라갔다.

## 2026-09-29 · uncommitted · web-surface-hardening: 역할 표면 CSP, manifest allowlist

- 변경: 대시보드 CSP를 `OPERATOR_PAGE_CSP` 상수 하나로 빼고 `/{surface}`(`/console`·`/setup`·`/device`)도 같은 CSP와 `Cache-Control`을 보낸다. `dashboard_assets`의 중복 키(client.js·dom.js)를 지웠다. `/common` 목록은 web_common `manifest.json`을 읽는다(share에 manifest가 있을 때만 share, 아니면 소스 트리).
- 증거: `python -m pytest src/runtime/api_web/test -q` 71 passed 13 skipped(브라우저 게이트). 새 시험 `test_role_surface_pages_carry_the_dashboard_csp`.
- gate 변화: 없음. 장치 수용은 주장하지 않는다.
- 결정: D-23, D-157.

## 2026-09-29 · uncommitted · fix(api): FastAPI 설명 문구를 계약 v1.56으로 맞춘다

- 변경: core_api_web/api/app.py의 description에 적힌 ROSY-API-REF-001 버전 표기를 v1.52에서 v1.56으로 올렸다. API Reference 헤더는 병행 traffic 회차에서 이미 v1.56까지 올라와 있고 test_protocol_version_alignment가 설명 문구의 버전 정합을 검사한다.
- 증거: src/runtime/gateway/test/test_protocol_version_alignment.py 3 passed. test_line_follow_contract_docs 핀도 v1.56으로 같이 정렬(문서 계약 트리).
- gate 변화: 없음.
- 교훈: 없음.

## 2026-09-29 · uncommitted · fix(api): 계약 문구를 v1.57로 재정렬

- 변경: 병행 회차들이 API Reference를 v1.57까지 올린 뒤 설명 문구가 다시 뒤처졌으므로 `ROSY-API-REF-001 v1.57`로 맞췄다. 버전을 올리는 회차는 문구와 계약서 헤더를 같은 변경에 담아야 정합 시험이 붉지 않는다.
- 증거: `python -m pytest src/runtime/gateway/test/test_protocol_version_alignment.py src/runtime/api_web/test/ -q` 통과(omx 경주 수정 회차와 같은 실행, 160 passed 16 skipped).
- gate 변화: 없음.
- 교훈: 버전 정합은 게이트가 아니라 습관이다 — 다음 범프 회차가 또 깨뜨린다.

## 2026-09-30 · uncommitted · fix(api): 계약 문구 v1.59 — D-348 회차가 놓친 버전 핀 마무리

- 변경: app.py docstring과 FastAPI description의 ROSY-API-REF-001 표기를 v1.58 → v1.59로. D-347이 정한 "버전 핀 3곳 한 변경 단위"(ref 헤더·app.py·line-follow 핀)에서 D-348 회차가 ref 헤더만 올리고 나머지를 놓쳤다. line-follow 핀도 같은 회차에 갱신했다.
- 증거: test_protocol_version_alignment 3 passed, test_line_follow_contract_docs 1 passed (2026-09-30 Windows).
- gate 변화: 없음.
- 교훈: v1.57 정렬 때와 같은 누락이 재발했다 — 범프 회차 체크리스트에 핀 3곳이 들어가야 한다.

## 2026-09-30 · ff6938e4 · D-359 US-002 device 패널 목록에 system.display

- 변경: `test_ui_route.py`의 기본 표면 패널 id 집합에 `system.display`(화면 테마)를 더했다. 서버 코드는 바뀌지 않는다 — panels.yaml 레지스트리가 새 패널을 싣는다.
- 증거: `python -m pytest src/runtime/api_web/test -q` 통과.
- gate 변화: 없음.

## 2026-09-30 · uncommitted · fix(api): 계약 문구 v1.60 — 세 번째 연속 핀 누락 마무리

- 변경: D-354 필드 제안 회차가 API Ref을 v1.60으로 올리면서 핀 3곳(app.py docstring·FastAPI description·line-follow 핀)을 다시 놓쳤다. D-347의 같은 변경 단위 규칙대로 세 곳을 맞췄다.
- 증거: test_protocol_version_alignment 3 passed, test_line_follow_contract_docs 1 passed (2026-09-30 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: v1.57→v1.59→v1.60 세 번 연속 같은 누락이다 — 이제 습관이 아니라 구멍이다. 범프 회차가 핀을 스스로 갱신하지 못한다면, 버전 핀 시험이 실패를 push 이전(pre-push)에 잡는 지금 구조가 유일한 안전망이다.

## 2026-09-30 · uncommitted · feat(host): D-375 status-inputs 핸드오버에 robot_mode 추가

- 변경: `status_inputs()`가 `_robot_mode()`(덕타이핍)로 `svc.state.snapshot().mode`를 검증해 `robot_mode`로 실었다. 모르는 모드는 없음이 된다.
- 증거: test_host_status_summary.py 39 passed, 1 skipped (키 셋·없음 기록 변이 증명: 필드를 빼면 키 셋 시험이 빨개진다).
- gate 변화: 없음.

## 2026-09-30 · uncommitted · docs(adr): D-375 에서 D-380 으로 개명

- 변경: 병합 시점에 main 이 D-375 를 feat/overhead-map-auto-register 예약으로 adr_gaps 에 넣은 것이 확인됐다(선례 D-324→D-325). 이 작업의 결정 번호를 다음 빈 번호 D-380 으로 개명하고 코드 주석·시험·설계 문서의 D-375 표기를 함께 바꿨다. 앞선 항목의 D-375 표기는 역사 기록으로 그대로 둔다.
- 증거: rosy_harness lint 오류 0. 본문 참조는 docs/adr/D-380-lamp-mode-patterns-from-core-status-inputs.md.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(host): D-381 status-inputs에 nav_state 추가

- 변경: `_nav_state()`(덕타이핍)가 `snapshot().navigation`을 검증해 핸드오버에 실었다.
- 증거: test_host_status_summary.py (키 셋·없음 기록). 변이 증명은 D-380과 같은 기제.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(host): D-380/D-381 hunk 복원 — 인코딩 복구가 떨어뜨린 status_inputs 확장

- 변경: 32da44f0(D-375)부터 d0323181(D-381)까지의 커밋이 `api/v1/host.py`를 손실 인코딩(UTF-8 바이트를 CP949로 재해석 + BOM 삽입)으로 다시 써, 문서화 문자열과 `reason`/`absent_detail`/`detail` 문자열 전부가 깨졌다 — 카탈로그 시험의 `ast.parse`가 U+FEFF로 죽고 `/host/commissioning` 이 깨진 문구를 실었다. c5ed4f5d가 003a7c1f 판본 복원으로 인코딩은 치유했으나 그 복원이 D-380/D-381의 정당 변경(`_robot_mode`, `_nav_state`, `status_inputs`의 `robot_mode`/`nav_state`)을 함께 떨어뜨렸다. 이 변경이 그 hunk를 다시 적용해 인코딩 복구와 부팅 표시 기능을 모두 갖춘다.
- 증거: 복구 전 gateway 21 실패(event_catalogue 13, host_cards 2, host_hardware 1, triage_contract 2, console_layout 3) → 0. core 도메인 전체 2014 passed, 29 skipped (2026-10-01 Windows).
- gate 변화: 없음.
- 교훈: 인코딩 사고를 "옛 판본으로 되돌리기"로 고칠 때는 그 판본 이후의 정당 커밋이 사라지는지 diff 전체를 읽어야 한다 — 이번 복원은 고장(hunk 없음)을 다른 고장(기능 상실)으로 바꿨다.

## 2026-10-01 · uncommitted · feat(host): D-383 status-inputs에 swarm_role 추가

- 변경: _swarm_role()가 snapshot().swarm.role 를 검색·검증해 핸드오버에 실었다. none·모르는 값은 없음.
- 증거: test_host_status_summary.py 40 passed (키 셋·none 부재 포함).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · D-390 Pilot asset and API version alignment
- Change: Serve the new OMX driver and arm screen modules through the existing Pilot asset allowlist; update API description to v1.67.
- Evidence: Pilot driver/link/route tests 26 passed and API version alignment tests 4 passed.
- Gate: CORE command ownership unchanged.

## 2026-10-01 · a527920a · feat(api): /api/v1/calibration/session 과 CALIBRATION_ACTIVE 차단
- 변경: `v1/calibration.py`(GET/POST session, POST heartbeat, DELETE). `common.require_calibration_owner()` 를 `/mode`·`/teleop`·`/line-follow/mode`(OFF 제외)·`/line-follow/hold` 에 걸었다 — 다른 토큰은 409 `CALIBRATION_ACTIVE`, E-Stop 은 보지 않는다. `deps` 재수출에 `CalibrationSessionError`, `CoreServicesLike.calibration`.
- 증거: test_calibration_session.py 13 passed(수명, 만료, 비소유자 409, owner teleop D-342 한도, E-Stop, robot/state·ws activity).
- gate 변화: 없음.

## 2026-10-01 · 1a1a2c3a · docs(api): API Ref v1.67 과 버전 핀
- 변경: app.py 가 calibration 라우터를 포함하고, docstring·description 핀을 v1.64(낡음) → v1.67 로. pilot 자산 allowlist 에 `calibration.js`(5db3391d).
- 증거: test_protocol_version_alignment, test_line_follow_contract_docs, test_task_contract_docs, test_pilot_route 통과.
- gate 변화: 없음.

## 2026-10-01 · 1ae6b239 · fix(core): 보정 차단을 navigation·docking·swarm 까지, IDLE 은 열어 둔다
- 변경: 리뷰가 찾은 구멍 — 비소유자가 `navigation/goal`·`home`, `docking/dock`·`undock`, `swarm/follow` 로 여전히 구동할 수 있었다. `enter_navigation_mode` 가 lease 를 먼저 보고(goal·home·swarm·line-follow), dock·undock·swarm follow 는 첫 줄에서 본다. `/mode` IDLE 은 멈춤뿐이라 e-stop 처럼 누구에게나 연다. 만료가 lock 안에서 발행하므로 lease lock 을 RLock 으로.
- 증거: test_calibration_session.py 15 passed(새 docking·IDLE 시험, 비소유자 409 목록 확장). 전체 core 도메인 2318 passed; 실패 3건은 main 에도 있는 test_core_node_teardown·test_module_criteria C6(D-385 ros_bridge getattr), 부하 때만 나는 test_line_follow_api IR 증거 stale(단독 통과).
- gate 변화: 없음.

## 2026-10-01 · 4f54dc54 · fix(core): 리뷰 반영 — 시작 조건, 차단 확대
- 변경: `POST /calibration/session` 은 IDLE·MANUAL 이고 navigation·mapping·도킹·line-follow·swarm 이 없을 때만 연다(409 MODE_CONFLICT). `/ws/swarm/reference` 는 lease 중 비소유자 프레임을 버린다(4f54dc54). 1ff0ba6b: 비소유자의 `PUT /safety/limits`, initialpose, SLAM start/stop/reset, `/power/mode` 409, host release install·rollback·reboot 는 `override_calibration: true` 없이는 409. `/power/wake`·`/slam/save` 는 연다.
- 증거: test_calibration_session.py 42 passed(시작 조건, reference 버림, 한도·host·pose·slam·power, viewer e-stop, cancel 열림, /api/v1/do 차단, 16 스레드 동시 시작 1건만). gateway·api_web·services 1955 passed, 새 실패 0 — test_module_criteria C6 는 main 의 D-385 ros_bridge getattr 에서 온 기존 실패.
- gate 변화: 없음.

## 2026-10-01 · 76c70e20 · merge(main) + API Ref v1.68 로 재번호, 검증 틈 시험 3건
- 변경: main 이 v1.67 을 D-390(OMX-AI Gazebo Pilot)에 먼저 썼다. 보정 변경을 v1.68 로 옮겼다 — 헤더, main v1.67 행 위의 새 변경 이력 행, 본문 표기, app.py·schemas.py·핀 시험(test_mission_progress·test_task_contract_docs·test_line_follow_contract_docs)·guard·D-321 부록. pilot sw.js 캐시 `-9`(calibration.js 유지), styles.css 는 main 의 arm/sim 블록과 보정 판 블록을 둘 다 둔다. 틈 시험: engage 실패 후 나가기는 IDLE 없음(modeHeld 고정), guard HTTP 500 은 FAILED, 비소유자 `slam/save` 는 열림.
- 증거: gateway·api_web·services·guard·release-push·핀 1969 passed, 실패 1(test_module_criteria C6, main 에서도 실패). ROSY_RUN_BROWSER_TESTS=1 pilot 전체 + dashboard 칩 71 passed. rosy_harness lint 0 errors.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · docs(api): WS 인증은 첫 메시지가 기본 — Fleet도 D-370 S7부터

- 변경: `core_api_web/api/AGENTS.md`의 "WebSocket auth is `?token=`"을 첫 메시지 `{"type":"auth","token":...}` 우선(대시보드·Pilot·Fleet), `?token=`은 `contract_version` 관문 전까지 수락으로 고쳤다. 코드 변경 없음 — `ws.py:_authorize`는 그대로.
- 증거: Fleet 쪽 `src/site/fleet/test/test_transport.py` 첫 프레임 시험.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · docs(api): 계약 버전 핀 v1.69 (D-395 1단계)
- 변경: `app.py` 독스트링·FastAPI description의 계약 버전 v1.68 → v1.69(D-347 세 핀 중 하나). 코드 경로 변화 없음.
- 증거: `test_protocol_version_alignment.py`.
- gate 변화: 없음.

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

## 2026-10-01 · uncommitted · feat(api): D-395 P2-4/P2-5 위치 확정 경로·capability, 계약 v1.70

- 변경: 새 `api/grants.py`(`NAVIGATE`·`LOCALIZE_ASSIST`, 역할에서 정해짐), 새 `v1/localization.py`(`GET /localization/candidates`, `POST /localization/decision|suspect`, lease 423, STALE 409, D-395 이전 로봇 501). 레거시 `POST /localization/initialpose` 는 D-395 로봇에서 `source: human` 결정으로 간다(응답 그대로, 이전 로봇은 `/initialpose`). `navigation/goal`·`home`·`line-follow/mode`(OFF 제외)는 D-395 로봇이 LOCALIZED 가 아니면 409 `NOT_LOCALIZED`. `app.py` 핀 v1.70.
- 증거: `src/runtime/gateway/test/test_localization_api.py`(capability 행렬·lease·stale·재경로·게이트·이벤트), `test_api.py`·`test_calibration_session.py` 그대로 통과, 변이(게이트·재경로 제거 → 4 빨강).
- gate 변화: 없음.

## 2026-10-01 · uncommitted · feat(api): 도킹·swarm follow 시작도 LOCALIZED 게이트

- 변경: `docking/dock`·`swarm/follow` 에 `require_localized` — D-395 로봇이 LOCALIZED 가 아니면 409 `NOT_LOCALIZED`, `localization` null 로봇은 그대로.
- 증거: `src/runtime/gateway/test/test_localization_api.py` 게이트·pre-D-395 시험.
- gate 변화: 없음.

## 2026-10-01 · uncommitted · fix(api): D-395 리뷰 — 시작은 localization 잠금 안에서, odom 프레임 거부

- 변경: `common.localized_start` — `require_localized` 검사와 시작(goal·home·line-follow·dock·swarm follow)을 `localization.gate` 안에서. `require_localized` 는 `pose_frame: odom` 이면 LOCALIZED 라도 409 `NOT_LOCALIZED`. 도킹 `NOT_LOCALIZED` → 409 매핑.
- 증거: `src/runtime/gateway/test/test_localization_api.py`.
- gate 변화: 없음.

## 2026-10-01 · 3d323ade · feat(host): D-406 T1 status-inputs schema 2 — 업데이터 유휴 판정 입력
- 변경: `status_inputs()`가 schema 2를 쓴다. schema-1 키는 그대로 두고 `velocity_linear`·`velocity_angular`·`battery_percent`·`battery_charging`·`docking_state`·`line_follow_mode`·`line_follow_state`·`swarm_active`·`estop`·`activity_kind`를 더했다. 모든 상태 키는 `GET /robot/state`와 같은 StateSnapshot 한 장에서 읽는다(`_snapshot`, 쓰기 한 번에 한 번). 모르는 값·형식이 틀린 값은 null이고 쉬는 기본값으로 채우지 않는다. 배터리는 요약줄 규칙대로 신선하지 않으면 null. root `rosy-boot-status.py`는 schema 1·2(int만)를 받고 출력은 그대로다.
- 증거: test_host_status_summary.py 53 passed 1 skipped. gateway 1611 passed 1 failed(test_module_criteria C6, 변경 전에도 실패·bridge 파일), api_web 73 passed, 루트 boot_status·boot_display·native_systemd_contract 287 passed. 변이 증명 7종(쓰기 schema 1, 읽기 schema 1만, int 검사 제거, bool 강제, 배터리 신선도 무시, 스냅샷 두 번, 문자열 강제) 모두 빨강.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(api): D-395 P2-7 `POST`·`GET /localization/mission`, API Ref v1.72

- 변경: `v1/localization.py` 에 `POST /mission`(`LOCALIZE_ASSIST`, 202 또는 409 `localized`·`busy`·`estop`·`path_not_clear`·`calibration_lease`·`unsupported`, 범위 위반 400, D-395 이전 501, readiness HOLD 503)과 `GET /mission`(Viewer). `MissionRefused` 는 `deps` 재수출 면으로. `app.py` 계약 버전 v1.72 ×2.
- 증거: `gateway/test/test_localization_mission.py` (권한·lease·거부 코드).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · chore(api): D-395 P2-7 계약 버전 v1.72 → v1.73

- 변경: 통합 브랜치가 main 을 받으며 v1.72 를 가져갔다(D-400 이 v1.71). P2-7 행과 `app.py` ×2·핀 네 곳을 v1.73 으로.
- 증거: `test/test_line_follow_contract_docs.py`, `src/site/fleet/test/test_task_contract_docs.py`, `test_mission_progress.py`.
- gate 변화: 없음.

## 2026-10-02 · 4e99d92e · feat(core_api_web): D-411 A /api/v1/recordings 와 Pilot 녹화 자산
- 변경: `api/v1/recordings.py`(목록 viewer·active·시작/정지 operator·archive operator; 정지 상태에서만, 한 번에 한 수신, 블록마다 정지 조건 재확인 후 짧은 본문으로 끊기, 마지막 바이트 뒤에만 fetched), 오류 코드 5개(`errors.py`), `control.py` 사전 거부도 intent·수락 시 seat 변경 통지, `ws.py` `/ws/state` 열림·닫힘을 가드에 알림, `deps.py`·`routes.py`, API v1.76 핀. Pilot 자산 allowlist 에 `recording.js`·`screens/robot-recording.js`.
- 증거: `python -m pytest src/runtime/api_web/test -q` → 73 passed, 13 skipped (2026-10-02 Windows).
- gate 변화: SOURCE 유지. ROS-SIM HOLD — 계획 Verification ROS-SIM 체크리스트(WSL Ubuntu) 미실행, DEVICE 증거 없음.
- 결정: D-411 A.

## 2026-10-02 · 7322d1e2 · fix(host): D-406 T1 리뷰 반영 — 속도 신선도, 유한수, 충전 플래그
- 변경: 독립 리뷰(REQUEST CHANGES) 반영. `velocity_*`는 velocity 증거가 fresh일 때만 쓰고 아니면 둘 다 null(끊긴 오도메트리의 마지막 0.0은 멈춤이 아니다). `_number`가 NaN·Inf를 null로. `battery_percent`가 null이면 `battery_charging`도 null(도크 래치). 64자를 넘는 자유 문자열(`docking_state`, `line_follow_*`)은 null. 크기 시험은 64자 id 64행 최악 경우로 쓰고 root 읽기기로 읽어 결과를 단언한다. 안전·도킹은 변화 시에만 찍히므로 게이트하지 않는다.
- 증거: test_host_status_summary.py 64 passed 1 skipped. gateway 1622 passed 1 failed(C6, 기존). api_web 73 passed, 루트 boot·systemd·architecture 363 passed. 변이 증명 14종(신규 6: 속도 무게이트, 증거 없음 통과, 유한 검사 제거, 충전 분리, 길이 상한 제거·off-by-one; 기존 7 재확인; 숫자 형 검사 제거) 모두 빨강.
- gate 변화: 없음.

## 2026-10-02 · 7f0bc0af · feat(api): D-418 로봇 SSH 접속 API, 계약 v1.80

- 변경: `api/v1/host_ssh.py` — administrator 전용 `GET /host/ssh/host-keys`, `GET|POST /host/ssh/keys`, `DELETE /host/ssh/keys/{label}`, `GET|POST|DELETE /host/ssh/password`. 본문은 `schemas.py`의 `Ssh*`로 검사하고 어긋나면 422 `SSH_INVALID`(CORE 기본 400 `VALIDATION_ERROR`가 아니라 계약대로). `added_by`는 요청 토큰의 라벨(없으면 id). host key는 `/etc/ssh/ssh_host_*_key.pub`만 직접 읽는다.
- 변경: `api/v1/ssh_handoff.py`(표준 라이브러리만) — 요청 파일을 쓰고 root `rosy-ssh-access`의 답을 최대 10 s 기다린다(설정으로 늘릴 수 없음). 답은 링크·FIFO 없이, 크기 상한, 같은 `request_id`, 허용 status·code일 때만 받고 읽자마자 지운다. 시간 안에 답이 없으면 요청을 거둬들이고 503 `SSH_ACCESS_UNAVAILABLE`. 요청 파일이 하나라 교환은 잠금으로 한 번에 하나.
- 변경: `errors.py`에 `SSH_*` 여섯. API Reference §5.8과 ERR-102 행, v1.79 → v1.80(문서 머리, `app.py` 두 곳, `test_line_follow_contract_docs.py`). native systemd 계약의 CORE 쓰기·읽기 선언에 `/run/rosy/ssh-access.request`·`.response`, `/etc/ssh`.
- 증거: `src/runtime/gateway/test/test_host_ssh.py` 36 passed — 실제 `rosy-ssh-access.py`(명령만 가짜)를 요청 파일이 생길 때마다 돌려 두 프로그램을 함께 지난다. 버전 정렬 시험 통과. 기기 쌍둥이 `ssh` 시나리오가 HEAD의 `ssh_handoff.py`를 rosy-core로 돌려 PASS.
- gate 변화: 없음
- 결정: D-418, D-18, D-347
- 교훈: 없음

## 2026-10-02 · 8dd300c52 · feat(safety): `GET /safety/state` 에 `fleet_link` (D-415, API v1.80)
- 변경: `_safety_payload` 가 `svc.fleet_loss.status()` 를 `fleet_link` 로 싣는다(없으면 null). `CoreServicesLike` 에 `fleet_loss`. PUT 이 받는 정책 값은 그대로. 계약 버전 v1.80(app.py).
- 증거: `src/runtime/gateway/test/test_fleet_loss_wiring.py`, `test_api.py` 안전 경로 통과.
- gate 변화: 없음.

## 2026-10-02 · 758f9878e · feat(safety): `PUT /safety/limits` RETURN_HOME 경고 (D-419, 구 D-415)
- 변경: `fleet_loss_policy: RETURN_HOME` 을 받으면 로그 경고와 응답 선택 필드 `warning`(사이트 Fleet 이 죽으면 모든 로봇이 교통정리 없이 동시에 귀환). 거절하지 않는다.
- 증거: `src/runtime/gateway/test/test_fleet_loss_wiring.py::test_put_return_home_is_accepted_with_a_warning`.
- 번호: 앞 항목들의 D-415(SAF-003)는 **D-419** 로 바뀌었다 — main 에 다른 D-415(콘솔 운영 가시성)가 먼저 들어왔다. ADR 파일 `docs/adr/D-419-saf003-fleet-link-loss-policy.md`.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · docs(api): D-419 계약 버전 v1.86
- 변경: main 이 v1.80(D-407)·v1.81(D-421)·v1.82(D-403 정리)·v1.83(D-411 A)·v1.84(D-422)·v1.85(D-413 Cell 목표 증거)을 먼저 써서 D-419 는 v1.86. `app.py` docstring·description, `v1/safety.py` 주석.
- 증거: `test_line_follow_contract_docs.py`, `test_task_contract_docs.py`, `test_mission_progress.py` 의 버전 고정을 v1.86 로.
- gate 변화: 없음.

## 2026-10-02 · uncommitted · feat(pilot): D-411 B 자산과 `autonomy` 문구
- 변경: `pilot_assets` 에 `controls.js`·`arm-stick.js`·`screens/compose.js`·`widgets/joint_jog.js`. capabilities `controls` 주석 — `autonomy: ["line"]` 은 CORE 가 line-follow 서비스를 가질 때 낸다(런타임 준비 증거 아님, API Ref §9.1).
- 증거: `python -m pytest src/runtime/api_web/test/test_pilot_route.py src/runtime/gateway/test/test_capabilities_controls.py -q` (2026-10-02 Windows).
- gate 변화: 없음.
- 결정: D-411 B, 구현 부록 5.

## 2026-10-03 · uncommitted · docs(api): align contract description with v1.84
- Change: Update the existing API app contract description to API Reference v1.84 for the additive site Fleet Cell evidence route. The route belongs to the site Fleet app.
- Evidence: Protocol alignment is included in foundation/alignment 427 passed/1 skipped; final legacy and contract-document checks 64 passed.
- Gate: SOURCE/LOCAL version alignment only; no deployment or device claim.

## 2026-10-03 · uncommitted · merge(main): D-411 B+C 계약을 API Ref v1.87 로 재번호
- 변경: main(D-411 A 는 v1.83 으로 먼저 착지, 현재 v1.86)을 `feat/d411bc-pilot-controls-gripper` 에 병합. 브랜치의 B·C 문구(`controls`, `/sim/omx/gripper`, `OmxSimGripperGoal`, `/state` `gripper`, 시연 `action.gripper`)를 v1.76 에서 v1.87 로 다시 매기고 새 §11 행을 더했다. `app.py` 계약 문자열과 버전 핀(`test/test_line_follow_contract_docs.py`, `test_task_contract_docs.py`, `test_mission_progress.py`)을 v1.87 로.
- 증거: 병합 커밋의 host pytest 묶음(보고서), `rosy_harness.py lint` 0 errors.
- gate 변화: 없음.
- 결정: D-411 구현 부록 15.

## 2026-10-03 · b84e72c55 · feat(api): D-423 `GET /api/v1/vision/models`(viewer, 읽기 전용), API Ref v1.83

- 변경: `api/v1/vision.py` 경로, `app.py` pilot 자산 `models.js`(09553e730), 설명의 계약 판 v1.83(714e0f90c). 쓰기 API 없음.
- 증거: `test_vision_preview.py`(API·405), api_web 묶음 739 passed(services·pilot 포함).
- gate 변화: 없음.

## 2026-10-03 · uncommitted · merge(main): D-418 SSH 접속 계약을 API Ref v1.89 로 재번호
- 변경: main(v1.84 D-422 … v1.88 D-423)을 `feat/d418-ssh-access` 에 병합. 브랜치가 v1.84 로 적은 D-418 §5.8·ERR-102 `SSH_*` 행·변경 이력·`schemas.py` 주석을 v1.89 로. `app.py` 계약 문자열과 버전 핀(`test/test_line_follow_contract_docs.py`, `test_task_contract_docs.py`, `test_mission_progress.py`)을 v1.89 로.
- 증거: 병합 커밋의 host pytest 묶음(보고서), `rosy_harness.py lint`.
- gate 변화: 없음.
- 결정: D-418.

## 2026-10-03 · 0e244456c · docs(api): D-418 재번호 항목의 커밋 기록 정정
- 변경: 앞의 `2026-10-03 · uncommitted · merge(main): D-418 SSH 접속 계약을 API Ref v1.89 로 재번호` 항목은 병합 커밋 96a7d57b6 에 들어갔다. logs 는 append-only 라 머리말은 그대로 두고 여기 적는다. API·코드 변화 없음.
- 증거: `git log --oneline` (feat/d418-ssh-access).
- gate 변화: 없음
- 결정: D-418

## 2026-10-03 · uncommitted · feat(link): D-432 주소 없는 장비 접속

- 변경: API Ref v1.89: connection/dev session LAN 진입, 기본 paired·명시적 개발 operator 세션·1h 만료·모드 종료 회수·Host/Origin 제한. SSH 관리자는 전용 Host Agent로 승인한다.
- 증거: 관련 Python 계약 시험·실제 loopback TLS HTTP/WS 시험을 실행했다. Pilot Android 설치·화면과 실제 로봇 연결·현장 트래픽 수용은 서로 다른 증거다.
- gate 변화: 실제 장비의 제어·FIELD 관문은 이동하지 않는다.
- 결정: D-432 2026-10-03 추가 결정.

## 2026-10-03 · uncommitted · fix(link): 현재 접속과 후속 코드 규약 구별

- 변경: 사용자 보정으로 4자리 코드 발급·Cam 표시 별칭은 이번 적용에서 제외했다. 현재 로봇 8자·Cam 6자리 규약을 유지하며 D-432에 추후 통합을 기록했다. 실제 Pinky 접속 수정은 진행한다.
- 증거: 영향받는 Python 2345 passed/84 skipped, quick tier 459 passed/2 skipped, Pilot PWA 87 passed/58 skipped. 코드 규약 보정 뒤 해당 인증·페어링 시험을 다시 실행한다. 공개 검증 기록은 docs/validation/discovery-link-2026-10-03/README.md.
- gate 변화: Android 설치·실제 CORE 인증 확인은 실제 주행·Cam 화면 off 연속 송출·현장 트래픽 수용과 별개다. DEVICE/FIELD 이동 없음.
- 결정: D-432 후속 결정: 접속은 지금, 짧은 코드 통합은 추후 적용.

## 2026-10-03 · uncommitted · fix(integration): D-418 SSH와 D-432 연결/UI 계약 통합

- 변경: API Ref는 D-418 v1.89 뒤 D-432 v1.90을 보존하고 app 설명과 문서 pin을 맞췄다. 배포 서비스 목록은 두 SSH 소유자를 모두 포함하면서 기존 1000줄 hard tier를 유지한다. sandbox 시험은 공개 키 helper의 실제 write/read IPC와 양의 디렉터리 시작 조건을 검사한다. 권한을 넓히지 않았다.
- 증거: native systemd/버전 문서/구조 시험 199 passed/1 skipped. 최종 quick tier와 SSH 영향 범위는 별도 재실행한다.
- gate 변화: 장치 활성화·물리 주행·FIELD 이동 없음.
- 결정: D-418와 D-432를 각각의 경로/opt-in 소유권으로 보존한다.

## 2026-10-04 · uncommitted · D-442 U1 MANUAL 보호

- 변경: 살아 있는 수동 세션의 NAVIGATION 전환을 ModeMachine에서 거부한다. teleop 입력과 watchdog 갱신은 같은 모드 잠금 안에서 다시 확인한 뒤 반영한다. API의 자율 진입은 부작용 전에 409 MODE_CONFLICT로 거부한다. 정지와 만료된 세션은 기존 전환을 유지한다.
- 증거: 신규 회귀 시험에서 탈취 5 failed, 경합 1 failed, line-follow 취소 부작용 1 failed를 수정 전에 재현했다. 관련 시험 167 passed, known_failures 비교 NEW 0, lint 0 errors. 독립 재리뷰에서 경합 양방향과 교착 부재를 확인했고 코드 차단 사항 없이 승인했다. 근거는 docs/validation/d427-source-migration/manual-ownership-review-2026-10-04.md.
- gate 변화: 없음. 호스트 검증이며 sim·장치·실주행 수용은 미실행이다.

## 2026-10-04 · uncommitted · feat(api): D-438 `stuck_resolver` 역할과 `STUCK_DECIDE` 권한, API Ref v1.90
- 변경: `api/grants.py` `STUCK_DECIDE`, `api/deps.py` 역할 순위, `api/v1/line_follow.py` 막힘 답 경로가 `STUCK_DECIDE` 를 요구(`stuck_resolver` 의 `MANUAL` 은 403), `api/v1/auth.py`·`system.py` 역할 목록 문구, `api/app.py` 계약 표기 v1.90
- 증거: `python -m pytest src/runtime/gateway/test -q` 2025 passed, 16 skipped (2026-10-04 Windows; 첫 실행의 1 failed 는 app.py 계약 표기를 v1.90 으로 올리기 전의 `test_protocol_version_alignment.py` 였고 표기 정정 뒤 통과); `python -m pytest test/test_harness_contracts.py -q` 59 passed
- gate 변화: 없음
- 결정: D-438
- 교훈: 없음

## 2026-10-04 · uncommitted · feat(api): stationary lane perception selection
- 변경: GET/PUT `/api/v1/line-follow/perception`, viewer 조회/admin 변경, closed paint_source body와 Host Agent 릴레이. 실제 ModeMachine IDLE 예약으로 변경 중 주행 시작을 거부하며 실패 시에도 finally 해제한다. CORE status handover는 fresh sensor velocity와 calibration_active를 1초마다 기록한다.
- 증거: host/API/systemd/status/line-follow 관련 395 passed, 2 skipped (Windows). concurrent Host apply 동안 mode/teleop/line-follow 거부 및 예약 해제 회귀 시험 포함. live 배포와 주행은 이 기록의 증거가 아니다.
- gate 변화: SOURCE/LOCAL, DEVICE/FIELD 별도 검증.
- 결정: `docs/plans/2026-10-04-learned-lane-driving-modes.md`
- 교훈: 기존 Host Agent는 설치 경로가 없어 API만 추가하면 503이었다. signed native helper/unit 설치와 실제 status producer 주기를 함께 연결해야 한다.

## 2026-10-04 · uncommitted · fix(api): serialize calibration and perception admission
- 변경: 실제 ModeMachine의 shared idle_admission RLock으로 보정 busy_check+start와 perception calibration.current+IDLE reservation을 하나의 admission 결정으로 묶었다. 보정 session이나 activity를 생성하지 않는다. 내부 mode lock과 분리해 docking listener 잠금 순서를 보존한다.
- 증거: calibration.start를 busy_check 직후 정지시킨 경쟁 시험은 변경 전 Host 설정이 통과해 실패했다. 수정 후 pending admission을 기다리고 실제 보정 session이 생기면 CALIBRATION_ACTIVE로 거부하며 Host 호출은 0회다. perception/calibration/command/line-follow/swarm focused 82 passed (Windows).
- gate 변화: SOURCE/LOCAL. 실제 장치·주행 증거는 별도.
- 결정: 독립 safety review 지적의 admission race 수정.

## 2026-10-04 · uncommitted · feat(api): fresh keeper source readback
- 변경: read-only `line/keep_debug` source를 기존 svc.vision latest cache로 수신한다. CORE perception 응답은 configured source와 실제 threshold/denoise/learned/denoise_fallback을 구분하고 receipt-monotonic age 및 producer의 실제 mask revision을 제공한다. 2초 초과·malformed·설정 불일치·clock reset 및 재시작 전 증거는 null이다. 주행 판단이나 privileged Host 경로를 바꾸지 않는다.
- 증거: 신규 source/bridge/vision/API focused 33 passed. fallback·malformed·stale·model mismatch·stamp reset을 검증했다. 전체 CORE의 host card fake fixture는 실제 ModeMachine으로 보완했고 IR revision 거부 시험은 주입 clock으로 HTTP 지연과 분리했다. 최종 확장 시험 진행 중.
- gate 변화: SOURCE/LOCAL. 기기에서 actual source 비율 및 실제 주행은 별도 확인.
- 최종 증거: readback/API/bridge wiring/vision/host cards/line-follow 확장 102 passed (Windows), fresh fallback와 재시작 cache reset의 API 통합 시험 포함.
- Review 보완: 실제 learned 표시는 요청 source와 served-mask revision이 모두 있어야 한다. bridge는 ROS camera-header clock으로 이미지 나이 0..2초를 검증한 뒤 receipt-monotonic TTL 2초를 적용한다. pure cache 시험은 services/test 소유 경로로 이동했다.

## 2026-10-04 · uncommitted · feat(recording): 원본과 검토 전 주석 옵션

- 변경: POST recordings는 optional closed preview_mode(raw/annotated)를 받고 생략은 raw다. typed start 서비스와 신선한 recorder status가 확인될 때만 annotated capability를 표시한다. 요청한 mode와 실제 성공 응답이 다르면 소유권을 만들지 않고 거절한다. 기존 SetBool raw/stop은 유지한다.
- 변경: 기존 front frame API에 overlay=false 원본 variant와 동일 capture provenance header를 더한다. video upload는 pair_group_id32hex와 mode를 함께 검증하며 원본이 먼저 보존된 동일 group/time/count에서만 주석을 저장한다. 주석은 model_unreviewed로서 사람이 검토한 라벨이 아니다. API ref/app v1.91, envelope1.0 유지.
- 증거: recording-api-red.txt 9 failed로 기존 미구현 경로를 확인한 뒤 focus162 passed,1 skipped; malformed evidence/API import boundary 최종 검증 통과. 모든 시험 scratch는 X:/DevTemp/rosy-lane-device-20261004.
- gate 변화: SOURCE/LOCAL. 실제 장치 녹화와 브라우저 영상 파일 검증은 별도다.

## 2026-10-04 · uncommitted · feat(ui): 기본 dashboard 진입 자산 허용

- 변경: dashboard 정적 허용 목록에 entry-router.js, dashboard-entry.js, dashboard-entry.css 세 자산만 추가했다. CMake 설치 목록과 맞추며 인증·안전 API의 서버 권한 계약은 변경하지 않았다.
- 증거: API·구조 묶음 106 passed/13 skipped (38.42s), 후속 인증·구조 묶음 64 passed/2 skipped (31.08s). CORE TestClient의 실제 정적 경로·CSP로 새 진입 브라우저를 검증했고 운용 요청은 fixture로만 응답했다. 두 묶음은 중복 대상이 있어 합산하지 않는다.
- gate 변화: SOURCE/LOCAL 자산 계약만 보완했다. 실제 안전 명령이나 장치 배포 증거는 없다.
- 결정: D-439. 기본 진입의 역할 링크는 기존 서버 manifest와 로컬 경로 허용 목록을 함께 따른다.

## 2026-10-04 · uncommitted · feat(ui): 어휘 갤러리 작업 선택 자산 허용

- 변경: styleguide_assets에 실제 공용 작업 선택 견본 styleguide.js 한 자산과 JavaScript MIME을 등록해 CMake 설치 목록과 맞췄다. API 권한과 안전 명령은 바꾸지 않았다.
- 증거: 실제 UI 경로·CSP와 구조 예산 16 passed (8.21s). 공용 템플릿 CSS는 기존 shared-assets.json 소비 경로를 따른다.
- gate 변화: SOURCE/LOCAL 정적 자산 계약만 보완했다.
- 결정: D-439 Task5. 동작 소유자는 공용 작업 선택이며 서버 요청을 보내는 견본이 아니다.

## 2026-10-04 · uncommitted · feat(power): fresh battery evidence and idle saving

- 변경: 반복 저배터리 표본의 wake를 단계 변화로 제한하여 기존 IDLE/STANDBY 타이머가 동작한다. Viewer GET /api/v1/power/health와 공유 typed 응답에 배터리·충전 확인 age, 정책 상한·wake 근거, shutdown 요청, 진단 요약을 제공한다. API Ref v1.92, envelope 1.0 유지.
- 검증: injected clock 회귀와 auth/read-only API, 기존 배터리·정지·sentinel 경로 검증. 최종 근거는 docs/plans/2026-10-04-power-health-and-wake.md. OS halt·EEPROM·GPIO·기본 LiDAR 모터 정책 변경 없음.
- gate 변화: SOURCE/LOCAL; 실제 소비전력·충전·RTC/외부 버튼 wake와 배포는 미검증.

## 2026-10-04 · uncommitted · fix(api): 현재 문서 버전 설명 정렬

- 변경: FastAPI 설명과 module docstring의 v1.93을 현재 API Ref v1.94에 맞췄다. runtime endpoint·envelope·권한은 변경하지 않는다.
- 증거: 최종 fast gate의 버전 불일치 실패를 재현했고 관련 계약 검사를 재실행한다. 공개 APK SHA-256·commit 값은 원값을 유지하며 같은 줄에 출처 표기를 명확히 했다. secret scanner 예외는 추가하지 않는다.
- gate 변화: SOURCE 정렬이며 LOCAL 재검증·원격 CI·DEVICE·FIELD는 별도다.

## 2026-10-04 · uncommitted · feat(api): D-343 로비 잔여 — `GET /api/v1/site/rooms`

- 변경: `api/v1/rooms.py` 신설 — Viewer 인증 없이 읽는 공개 방 목록(Avahi `_rosy._tcp` 탐색 + `discovery_txt.classify`, 행은 hostname/address/port/kind/url만, 토큰·비밀 없음 D-193). URL은 그 기기의 pilot 진입(`http://<hostname>.local:<port>/pilot/#join`, CORS를 열지 않는다). Avahi 없음은 503 `DISCOVERY_UNAVAILABLE`(왜 없는지를 숨기지 않는다). routes 애그리게이터·`app.py` 등록. API Ref §5.11 신설(D-18 문서 주기).
- 증거: `test/test_site_rooms.py` 4 passed(방 모양·분류기 거절·200·503). api_web 전체 77 passed/13 skipped, gateway 비ROS 수집 오류는 휠 부재(main 동일). flake8 0.
- gate 변화: 없음. 호스트 계약. 운전석 임대(2.4)·MJPEG(2.3)·PWA 로비 화면(2.1)은 뒤 작업.
- 결정: D-343 계획 §4 순서 2. PWA 화면·관전 모드·좌석은 D-343 §2.1·2.5의 뒤 작업.

## 2026-10-04 · uncommitted · fix(discovery): bounded LAN rooms와 TLS/FQDN 계약 정합

- 변경: 공용 발견 cache를 먼저 사용하고 optional adapter가 없을 때만 5초 success/error singleflight Avahi fallback을 쓴다. stdout128KiB·4초/유한 종료 회수, actual service/domain/role, canonical FQDN·TLS 링크, 64행·초과 identity 충돌을 검증한다. 공개 미승인 힌트 typed 계약을 schemas와 API Ref1.98에 함께 기록하고 기존1.97 중앙 GET와 envelope1.0을 유지한다.
- 증거: 원본8c의 double.local·TLS HTTP·중복100·8동시 scan8 결함 재현 후 후보22 PASS, 65번째 identity 경계 RED→GREEN, 독립 SPEC·Quality·Safety PASS. 실제 적용 API/schema/P6 검사는 별도 root 수행 중이다.
- gate 변화: SOURCE/LOCAL 후보. 실제 LAN/Avahi/장치/멀티worker 트래픽 수용과 서명 배포는 별도다.

## 2026-10-04 · uncommitted · fix(api): 실제 계약 판과 rooms 내부 저장 표현 정합

- 변경: FastAPI 설명의 이전1.96 판을 현재 API Ref1.98로 맞췄다. rooms 내부의 목록 tuple/dict 저장을 명시적 signature/room record로 바꿔 이벤트 발행 검사기의 구조 오인을 피한다. 검사기/이벤트 목록/분류 규칙은 바꾸지 않는다.
- 증거: 정상 pre-push3 실패 중 protocol/event2 원인을 실제로 확인하고 해당 검사·secret provenance·rooms22를 합친 실제114 PASS로 재검증했다.
- gate 변화: SOURCE/LOCAL gate 수리. 원격 push/CI/서명 배포·장치 수락은 별도다.

## 2026-10-04 · uncommitted · docs(api): D-457 site display contract v1.97

- 변경: 사이트 표시 전용 추적 계약과 FastAPI 설명 버전을 일치시켰다. 로봇 endpoint·wire envelope·주행 행위 변경 없음.
- 증거: protocol_version_alignment 시험 통과. DEVICE/FIELD 변화 없음.
- gate 변화: 없음. 사이트 표시 계약 문서 정합이며 로봇 wire/주행 경계는 유지한다.

## 2026-10-05 · uncommitted · feat(auth): LAN 수신 승인과 키 결속 로그인

- 변경: 인증된 기존 관리자가 상대 화면에서 요청을 승인하고, client P256 증명으로 최대 1시간의 기존 로그인 세션을 발급한다. 지속 승인은 명시한 연결 기억과 만료 없는 기존 card/manual 관리자에 한정한다. 관계 generation·발급자 digest·session marker로 폐기·저장소 누락·발급자 변경을 차단한다. API Reference는 v1.100이다.
- 증거: 통합본의 실제 암호화·owner 승인·HTTP·replay·issuer/관계 폐기·전체 overlay 삭제를 포함한 32 PASS. 요청 수·본문·poll·익명 증명 예산은 제한하며 네트워크 발견 자체는 승인이나 제어 admission이 아니다.
- gate 변화: SOURCE/LOCAL 추가 증거. 정상 HTTPS·기존 named 권한·CORE 최종 명령 경계를 유지한다. 서명 ARM64·실기 수신 승인·앱 재연결과 Fleet/Cam 별도 owner 경로는 미완료다.

## 2026-10-05 · uncommitted · feat(vision): D-368 운전자 MJPEG 스트림 라우트와 teleop 훅

- 변경: `api/v1/vision.py`에 `GET /api/v1/vision/front/stream`(operator, multipart boundary `frame`, `?overlay=`) 추가 — 새 sequence만 내보내고, 운전자 교체·클라이언트 끊김에 슬롯 해제. `deps.py`에 `VisionStreamRefused` 재수출과 `CoreServicesLike.vision_stream` 추가. `control.py` teleop 수락 뒤 `vision_stream.on_teleop` 훅(pilot_recording 훅과 같은 실패 무시 규약).
- 증거: `middleware/core/gateway/test/test_vision_stream.py` 8 PASS(401·미운전 409·BUSY·새 sequence만·운전자 교체·관전 폴링 불변·연결 종료 해제·driver 불투명 id). API Ref v1.100(D-18).
- gate 변화: SOURCE. 발행 주기 상항(12 fps 요청)은 로봇 측 ROS-SIM/DEVICE 사항으로 이 경로 밖.

## 2026-10-05 · uncommitted · docs(api): 무마커 시작점 계약 v1.103 표시

- 변경: Fleet 전용 시작점 API의 additive 계약 버전 v1.103을 API reference와 CORE 앱 설명 metadata에 맞춘다. CORE route/envelope/로봇 동작 변경 없음.
- 증거: 현행 버전 pin과 Fleet API 관련 검증 묶음 149 passed, known_failures 신규 0. 전체 CORE/ARM/현장 수용은 별도다.
- gate 변화: 계약 설명 정합만 보강한다.

## 2026-10-05 · uncommitted · fix(api): 통합 계약 v1.104 설명 정합

- 변경: Cam peer와 시작점 통합 후 FastAPI 설명을 현행 계약 v1.104에 맞춘다. 라우트·인증·envelope 1.0 변경 없음.
- 증거: 정상 pre-push의 버전 설명·변경 이력 두 실패를 재현하고 관련 계약 시험으로 확인한다. TLS CI 의존성 복구와 별도로 실행 상태를 기록한다.
- gate 변화: SOURCE 정합 수리. 실기 승인·재연결 수용은 배포 후 별도다.

## 2026-10-05 · uncommitted · fix(pairing): 구버전 TLS 검증 거절 순서

- 변경: 체인 verifier 부재를 인증서의 신규 날짜 API 접근 전에 거절한다. 검증할 수 없는 CA를 공개하지 않으며 기존 49.0.0 체인·호스트·만료 검증을 유지한다.
- 증거: verifier와 신규 날짜 속성이 없는 구버전 형태에서 AttributeError를 재현했다. 수리 후 CI 의존성·TLS·버전 관련 19 passed, 실패 0이다.
- gate 변화: SOURCE/LOCAL. 구버전 지원이 인증서 신뢰나 연결 승인을 대신하지 않는다.

## 2026-10-05 · uncommitted · fix(api): align description with Fleet CAP-001 contract version

- 변경: app factory metadata names API Ref v1.105; routes, envelope 1.0 and control behavior stay unchanged.
- 증거: version alignment RED 1 FAIL then GREEN 3 PASS; X:/DevTemp/rosy-fleet-browser/api-description-green.txt.
- gate 변화: none; source metadata only, no robot release activation.

## 2026-10-05 · uncommitted · fix(peer-pairing): 관계당 활성 세션 상한 4→8

- 변경: receiver_repository.issue 의 활성 세션 상한을 4에서 8로 올리고, 계약 스키마(Relationship.session_ids max_length)와 API 레퍼런스의 같은 문장을 한 커밋에 맞췄다(D-18). 현장 태블릿이 연결마다 새 세션을 발급받는데 종료 시 반납하지 않아 1시간 세션 수명 창 안에 재연결 4회면 승인이 일시 잠겼다(2026-10-05 실기 - 재설치 시험 4회로 재현, 세션 토큰 삭제로 복구). 8은 기존 개발 세션 상한(살아 있는 세션 8개)과 같은 규모다.
- 증거: test_peer_pairing + contracts/foundation 전체 761 passed 5 skipped, known_failures NEW 0(X:/DevTemp/peer-sessions/run.txt). 시험 \	est_explicit_revoke_cancels_issued_sessions_and_eight_session_limit\이 9번째 발급 거부로 갱신.
- gate 변화: SOURCE. 기존 로봇(구 이미지)에는 새 릴리스로 배포되기 전까지 반영되지 않고, 구 이미지가 5개 이상 저장된 overlay를 읽으면 관계 기록이 무효로 보이는 다운그레이드 주의는 남는다.

## 2026-10-05 · uncommitted · fix(api): D-468 계약 버전 표시 정렬

- 변경: 앱 설명의 API 계약 버전을 문서의 v1.106과 맞췄다.
- 증거: 계약 버전 정렬 검사 통과. 장치 배포는 하지 않았다.
- gate 변화: 없음.

## 2026-10-06 · uncommitted · 식별 LED CORE 요청

- 변경: Operator 전용 `POST /api/v1/host/lamp/identify`가 blue/amber만 받아 기존 호스트 하드웨어 요청 큐로 전달한다. 응답은 영상 확인 대기 상태다.
- 증거: API 입력·쿨다운 호스트 테스트 통과. 장치 적용과 실제 점멸은 미확인.
- gate 변화: SOURCE/LOCAL만 확인. DEVICE/FIELD 상태는 그대로 둔다.

## 2026-10-06 · uncommitted · chore(core_api_web): 계약 문서 버전 v1.109 동기

- 변경: FastAPI docstring/설명의 라이브 계약 버전을 v1.109로 갱신(D-484 additive 행). 동작 변화 없음.
- 증거: `test_protocol_version_alignment.py`가 문서 헤더·변경 이력·설명 일치를 검증.
- gate 변화: 없음.

## 2026-10-06 · uncommitted · feat(api): D-483 로봇 화면 승인 코드로 피어 요청 승인

- 변경: D-456 요청마다 6자 승인 코드를 만들고 hash만 비교한다. `POST /api/v1/auth/peer-pairing/requests/{id}/confirm`(인증 없음, `X-Request-Secret`, `{approval_code}`)이 맞으면 같은 요청을 승인한다. 5회 틀리면 rejected, 출처별 30회/분 한도 공유, 요청 역할이 operator를 넘으면 403. 화면 코드 관계는 `screen-code` 출처·168 h·persistent=false이고 `_grant`·`issue`·세션 정책이 발급자 token 대신 관계 자체의 만료·폐기·수신 키만 본다. 기다리는 가장 최근 요청을 `/run/rosy-peer-display/approval.json`(0640, tmp+rename)으로 rosy-face에 넘기고 끝나면 지운다. 쓰기 실패는 한 번만 기록하고 요청 흐름은 그대로다. 계약 v1.109.
- 증거: `test_peer_pairing.py` 신규 `ScreenCodeApproval` 10건(응답·pending·로그에 코드 없음, 5회 거절, 비밀 없이 승인 불가, 콘솔·코드 경합 단일 승인, 종료 상태별 파일 삭제, 168 h·challenge/session, 403, 속도 한도) 포함 api_web·foundation 867 passed. 장치 배포는 하지 않았다.
- gate 변화: SOURCE/LOCAL만. DEVICE(9dfk LCD 코드·태블릿 입력)는 서명 릴리스 뒤 별도.
- 결정: D-483

## 2026-10-07 · uncommitted · fix(api): D-483 보안 검토 반영(M1·M2·L1·L2·L4·L6)

- 변경: 대기 한도 16개는 살아 있는 pending만 세고 출처별 동시 대기를 2개로 묶었다. hand-over 파일은 살아 있는 요청을 최신순 최대 3개 `{"requests": [...]}`로 싣는다(새 요청이 먼저 온 코드를 가리지 않음). 관계 128개 상한에서 만료·폐기되었고 살아 있는 세션이 없는 관계를 지우고 `relationship_pruned` 감사 행을 남긴다(overlay의 grants를 통째로 바꿔 디스크에서도 지워진다, `patch_local_config(replace=...)`). CORE 시작 때 남은 approval.json을 지운다. 화면 코드 관계는 `approved_at`을 갖고 모델이 168 h 상한을 강제한다. 토큰 id `screen-code`는 읽지 않는다.
- 증거: `test_peer_pairing.py` 38 passed(신규: 3개 동시 표시·출처별/전체 한도·시작 시 삭제·폐기 뒤 세션 거부(HTTP·소켓)·모델 거부 10종·예약 id·상한 정리와 디스크 반영, 속도 한도 시험은 코드 값과 무관). 장치 배포는 하지 않았다.
- gate 변화: SOURCE/LOCAL만.
- 결정: D-483

## 2026-10-07 · uncommitted · fix(api): D-483 재검토 반영(R1~R5)

- 변경: 관계 행을 저장할 때 값이 없는 `approved_at`은 쓰지 않아 소유자 승인 행이 D-483 이전 릴리스 모델(Strict, extra 금지)로도 읽힌다(R1, ADR에 롤백 시 screen-code 행 정리 기록). 살아 있는 대기 요청은 LCD 목록과 같은 3개까지, 출처별 2개(R2). `approved_at`이 60초 넘게 미래인 screen-code 행은 `_grant`·`repo.issue`·세션 정책에서 거부(R3). approval.json에 label을 넣지 않는다(R4). 요청 취소도 출처별 속도 한도에 세고, 보관 행이 가득 차면 승인되지 않은 끝난 요청만 먼저 비운다(R5).
- 증거: `test_peer_pairing.py` 42 passed(신규: 이전 릴리스 모델로 저장 행 검증, 미래 approved_at 거부, 취소 속도 한도, 승인 결과 보관, 상한 정리에서 살아 있는 세션을 가진 만료 행과 살아 있는 행이 남음). 장치 배포는 하지 않았다.
- gate 변화: SOURCE/LOCAL만.
- 결정: D-483

## 2026-10-07 · uncommitted · fix(api): D-483 N1 전체 틀린 코드 예산

- 변경: 끝난 요청이 대기 한도에 세지 않아 출처를 바꿔 가며 코드를 맞혀 볼 수 있었다. 모든 출처를 합친 틀린 승인 코드를 10분에 20회까지만 받고, 넘으면 창이 지날 때까지 `confirm`은 맞는 코드에도 429(콘솔에서 승인하라는 안내)를 돌려준다. 콘솔 승인은 영향이 없다.
- 증거: `test_peer_pairing.py` 43 passed(신규: 출처 4곳 × 틀림 5회 뒤 맞는 코드도 429, 콘솔 승인은 됨, 10분 뒤 다시 열림). 장치 배포는 하지 않았다.
- gate 변화: SOURCE/LOCAL만.
- 결정: D-483

## 2026-10-07 · uncommitted · feat(api): D-494 1 capabilities가 trip 능력 필드를 채운다

- 변경: `GET /api/v1/system/capabilities`의 `base_velocity`에 `robot_kind`(`robot.model`, 없으면 `DEFAULT_ROBOT`)·`drive_modes`(line-follow 서비스가 있으면 `lane`, 보류 뒤 `navigation.goal_navigation`이 참이면 `free`)·`trip_max_linear`(safety `max_linear`·`fleet_linear`·line-follow `max_linear` 중 최솟값)를 싣는다. FastAPI 설명 문구를 계약 v1.112로 올렸다.
- 증거: gateway `test_capabilities_controls.py` 새 시험 2개, api_web 스위트 통과.
- gate 변화: 없음. SOURCE 호스트 시험만. 서명 릴리스 전에는 로봇에 닿지 않는다.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(api): D-495 capabilities의 junction_turn

- 변경: `base_velocity.junction_turn`은 line-follow 매니저의 `supports_junction_turn` 훅이 `True`일 때만 true다. 회전 동작은 `feat/d491-core-junction-action` 가지에 있어, 이 가지는 훅이 없으면 false를 낸다(가지 사이 의존 없음).
- 증거: gateway `test_capabilities_controls.py` 10 PASS(훅 없음 false, 훅 true, line-follow 없음 false).
- gate 변화: 없음.
- 결정: D-495 (Proposed)

## 2026-10-07 · uncommitted · fix(api): D-494 검토 — 잘못된 robot.model이 capabilities를 500으로 만들지 않는다

- 변경: `robot.model`이 로봇 패키지 이름(`ROBOT_NAME_PATTERN`, 64자 이하)이 아니면 `robot_kind`를 빼고 한 번만 경고한다. 전에는 "Pinky" 같은 값이 `GET /system/capabilities` 500이었다.
- 증거: `test_capabilities_controls.py` "Pinky"·"pinky-pro"·65자·숫자 4건 PASS.
- gate 변화: 없음.
- 결정: D-494 (Proposed)

## 2026-10-07 · uncommitted · feat(api): D-494 POST /api/v1/line-follow/junction
- 변경: operator + 보정 lease. CAMERA_LINE·IR_LINE이 아니면 409 `LINE_FOLLOW_NOT_ACTIVE`. 응답 `{accepted, junction_seq, state}`. API Ref v1.112, `app.py` 버전 문구 v1.112
- 증거: `test_line_junction.py` 18 PASS, `test_line_junction_api.py` 8 PASS. services·api_web·contracts/foundation·line-follow 문서 시험 1859 PASS·18 skip, gateway 2187 PASS·17 skip, Fleet 버전 고정 시험 90 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. 실기·SIM 미실행(Gazebo는 이 노트북에서 돌리지 않음)
- 결정: D-494 (Proposed) 4항, 구현 부록 2026-10-07
- 교훈: 오늘 인식은 CORE에 분기 후보를 주지 않는다. 좌·우 주행은 분기 계약 ADR이 먼저다

## 2026-10-07 · uncommitted · feat(api): D-495 junction turn_deg·advance_m
- 변경: `POST /line-follow/junction`이 `turn_deg`(left +, right −, 0<|θ|≤150)와 `advance_m`(0–0.30)을 받는다. 동작 중 새 지시는 `accepted: false`. API Ref 행·변경 이력 갱신(v1.112 유지, 착지 때 재번호)
- 증거: `test_line_junction.py` 44 PASS, `test_line_junction_api.py` 9 PASS. services·api_web·contracts/foundation·line-follow 문서·perception 배선 1968 PASS·18 skip, gateway 2188 PASS·17 skip, perception 2704 PASS·109 skip, `test/known_failures.py` 0 new (2026-10-07 Windows)
- gate 변화: 없음. SOURCE 호스트 시험만. SIM(모델 PC map_v2_fleet_real)·DEVICE 미실행
- 결정: D-495 (Proposed), 구현 메모 2026-10-07
- 교훈: 기본값을 켜는 ADR은 그 값의 전제(`recovery_local_enabled`, keep 모드)와 되돌리기 경로를 코드로 확인해야 한다

## 2026-10-07 · uncommitted · fix(api): D-495 검토 L6 junction 수동 해제와 409 코드
- 변경: `require_manual_released`(409 `MODE_CONFLICT`), IR_LINE은 409 `JUNCTION_CAMERA_ONLY`, OFF는 `LINE_FOLLOW_NOT_ACTIVE`. API Ref 행·에러 표 갱신
- 증거: services·api_web·contracts/foundation·line-follow 문서·perception 배선/lane_keep·Gazebo launch 고정 시험 2007 PASS·18 skip, gateway 2192 PASS·17 skip, 문서 시험 1 PASS, `test/known_failures.py` 0 new (2026-10-07 Windows). 검토 탐침 `probe_lag.py`·`probe_junction.py` 재실행
- gate 변화: 없음. SOURCE 호스트 시험만. SIM·DEVICE는 D-495 수용 점검표
- 결정: D-495 (Proposed) 독립 안전 검토 반영 2026-10-07
- 교훈: 지연이 있는 odom 위의 닫힌 고리는 지연 보정과 머무름 확인이 있어야 허용 오차를 지킨다

## 2026-10-07 · uncommitted · docs(api): D-498 v1.118
- 변경: `junction_turn` 능력 뜻, 중단 사유 `turn_basis_lost`, 설정 행. v1.117은 다른 브랜치가 먼저 잡음. 버전 고정 시험 갱신
- 증거: `test_junction_turn_site_basis.py` 15 PASS, `test_line_junction.py` 73 PASS. services·api_web·contracts/foundation·문서·perception 배선/lane_keep·test/architecture·Fleet 버전 고정 2297 PASS·19 skip, gateway 2212 PASS·17 skip, `test/known_failures.py` 0 new (2026-10-07 Windows). core_features 15050 (판정 14934+150=15084 안)
- gate 변화: 없음. SOURCE 호스트 시험만. 현장 설정·SIM·DEVICE는 D-498 순서
- 결정: D-498 (Proposed)
- 교훈: 없음

## 2026-10-07 · uncommitted · docs(api): D-494 6 v1.119
- 변경: Fleet 주행 가르치기 행(`/api/fleet/teach*`)과 이력 행, `core_api_web/api/app.py` 계약 버전 두 문자열, 버전 고정 시험 다섯 곳
- 증거: `test/architecture`·`test/test_line_follow_contract_docs.py`·`middleware/core/api_web` 271 passed·14 skipped(크기 판정 1건은 Fleet 패키지), Fleet 버전 고정 시험 포함 `operations/fleet/test` 통과
- gate 변화: 없음. Robot API·envelope 1.0 변경 없음
- 결정: D-494 6
- 교훈: 없음

## 2026-10-07 · uncommitted · docs(api): app docstring names API Ref v1.124 (D-507 7)
- 변경: `core_api_web/api/app.py` 첫 줄 계약 버전 v1.122 → v1.124(main 은 문서 v1.123 과 어긋나 `test_protocol_version_alignment` 실패 중이었다).
- 증거: `python -m pytest middleware/core/gateway/test/test_protocol_version_alignment.py -q` 3 passed.
- gate 변화: 없음.
- 결정: D-507 7
- 교훈: 없음

## 2026-10-07 · uncommitted · docs(api): app docstring names API Ref v1.133 (D-507 7)
- 변경: `core_api_web/api/app.py` 첫 줄 계약 버전 v1.122 → v1.133(main 은 문서 v1.123 과 어긋나 `test_protocol_version_alignment` 실패 중이었다).
- 증거: `python -m pytest middleware/core/gateway/test/test_protocol_version_alignment.py -q` 3 passed.
- gate 변화: 없음.
- 결정: D-507 7
- 교훈: 없음

## 2026-10-08 · uncommitted · docs(api): v1.124 version pin

- Change: Align CORE app contract version docstring with API Reference v1.124.
- Evidence: Related contract and Fleet tests 99 PASS; device check remains separate.
- Gate change: None.

## 2026-10-08 · uncommitted · docs(api): D-509 v1.124 follow-up

- 변경: CORE app contract version now matches API Reference v1.124.
- 증거: Contract and Fleet focus tests passed; hardware remains unverified.
- gate 변화: None.

## 2026-10-08 · uncommitted · docs(api): merged contract v1.125

- 변경: CORE app contract docstring follows API Reference v1.125 after D-513 merge.
- 증거: Pinned version test included in merged tree verification.
- gate 변화: None.

## 2026-10-08 · uncommitted · feat(api): D-472 식별 색 설정과 v1.129/v1.130
- 변경: `POST /host/lamp/identify`의 `color`를 생략하면 CORE 설정 `lamp_identify.color`, 없으면 D-472 4항 기본(`rosy_26` blue, `rosy_60` amber)을 쓴다. 둘 다 없으면 409 `IDENTIFY_COLOR_UNSET`. `requested_at`을 ms로 쓴다. 앱 설명의 계약 버전을 v1.130으로 맞췄다
- 증거: `test_lamp_identify_api.py`, `test_protocol_version_alignment.py`
- gate 변화: 없음. 장치 적용과 실제 점멸은 미확인
- gate 변화: None.

## 2026-10-08 · uncommitted · fix(api): D-507 pivot_past_line_m [−0.30, 0.30]과 v1.133
- 변경: `LineJunctionRequest.pivot_past_line_m` 범위를 ge=−0.30으로 넓혔다. 앱 설명의 계약 버전을 v1.133으로 맞췄다(v1.131·v1.132는 다른 브랜치).
- 증거: `test_line_junction_api.py` −0.31 400, −0.30 200 `armed`.
- gate 변화: SOURCE.
- 결정: D-507 2 개정

## 2026-10-08 · uncommitted · fix(api): D-507 2·4 부호 있는 pivot의 API Ref 번호를 v1.135로 옮김
- 변경: main 병합으로 v1.133·v1.134가 다른 브랜치(D-507 7)에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.135로 옮겼다. 앞 항목의 v1.133은 그 때의 번호다.
- 증거: `test/test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` 버전 핀 통과.
- gate 변화: 없음.

## 2026-10-08 · uncommitted · feat(api): `POST /line-follow/junction` action `bend`와 능력 `lane_bend` (v1.137)
- 변경: `LineJunctionRequest` action `bend`, 선택 필드 `bend_in_m`(0, 2]·`bend_tol_m`(0, 0.30]·`bend_radius_m`(0, 0.5]. `bend`는 `turn_deg`(0 < |θ| ≤ 90)·`map_id`·세 필드가 필수이고 창·pivot·advance와 함께 둘 수 없으며, 세 필드는 다른 action에 둘 수 없다(400). `system.py` 능력 `lane_bend`(line-follow 매니저의 `supports_lane_bend`). API Ref v1.137, `app.py` 버전.
- 증거: `test_line_junction_api.py::test_d507_bend_fields_validation`, `test_capabilities_controls.py` `lane_bend` 참·line-follow 없으면 거짓. gateway 2266 passed.
- gate 변화: SOURCE.
- 결정: D-507 보충

## 2026-10-08 · uncommitted · fix(api): D-507 보충 굽이 지시의 API Ref 번호를 v1.141로 옮김
- 변경: main 병합으로 v1.137–v1.140이 다른 브랜치(D-519, D-507 2 개정, D-512)에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.141로 옮겼다. 앞 항목의 v1.137은 그 때의 번호다.
- 증거: `test/test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` 버전 핀 통과.
- gate 변화: 없음.

## 2026-10-08 · uncommitted · fix(api): D-507 보충 굽이 지시의 API Ref 번호를 v1.142로 옮김
- 변경: main 병합으로 v1.141이 D-517 M1a에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.142로 옮겼다. 앞 항목의 v1.141은 그 때의 번호다.
- 증거: `test/test_line_follow_contract_docs.py`, `test_protocol_version_alignment.py` 버전 핀 통과.
- gate 변화: 없음.

## 2026-10-08 · b570504a2 · feat(api): POST /line-follow/authority, 능력 line_follow_authority, v1.142
- 변경: operator·수동 해제·보정 lease seat, 409 `LINE_FOLLOW_NOT_ACTIVE`·`AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`, 강제 중에만 `GET /line-follow` `authority`. 앱 설명 v1.142.
- 증거: 모델 PC gateway 2208 통과(17 오류는 `rosy` wheel 없는 ROS bridge 모듈 수집 실패, 변경 무관), `test_line_authority_api.py`·`test_capabilities_controls.py` 통과.
- gate 변화: SOURCE.
- 결정: D-517 4항 (M2)

## 2026-10-08 · 887abb1a9 · feat(core): D-517 M2 능력 line_follow_authority_required
- 변경: `base_velocity` 능력에 `line_follow_authority_required`(설정 `line_follow.authority_required` 가 참이면 true, line-follow 없으면 false).
- 증거: 모델 PC 수정 전 `test_d491_trip_caps_follow_robot_package_services_and_limits` 실패, 수정 뒤 통과.
- gate 변화: SOURCE.
- 결정: D-517 4항 독립 리뷰 3 (E-Stop·CORE 재시작 뒤 첫 통행권 전 강제). API v1.142.

## 2026-10-08 · uncommitted · fix(api): D-517 M2 통행권의 API Ref 번호를 v1.143으로 옮김
- 변경: main 병합으로 v1.142가 D-507 보충(굽이 지시)에 쓰여, 이 브랜치의 API Ref 행·`app.py`·버전 핀을 v1.143으로 옮겼다. 앞 두 항목의 v1.142는 그 때의 번호다. `base_velocity` 능력은 `lane_bend`와 `line_follow_authority`·`line_follow_authority_required`를 함께 낸다.
- 증거: `test/test_line_follow_contract_docs.py`, fleet 버전 핀 시험, `test_capabilities_controls.py`.
- gate 변화: 없음.
