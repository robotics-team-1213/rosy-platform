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

## 2026-10-02 · uncommitted · feat(api): D-395 P2-7 `POST`·`GET /localization/mission`, API Ref v1.72

- 변경: `v1/localization.py` 에 `POST /mission`(`LOCALIZE_ASSIST`, 202 또는 409 `localized`·`busy`·`estop`·`path_not_clear`·`calibration_lease`·`unsupported`, 범위 위반 400, D-395 이전 501, readiness HOLD 503)과 `GET /mission`(Viewer). `MissionRefused` 는 `deps` 재수출 면으로. `app.py` 계약 버전 v1.72 ×2.
- 증거: `gateway/test/test_localization_mission.py` (권한·lease·거부 코드).
- gate 변화: 없음.

## 2026-10-02 · uncommitted · chore(api): D-395 P2-7 계약 버전 v1.72 → v1.73

- 변경: 통합 브랜치가 main 을 받으며 v1.72 를 가져갔다(D-400 이 v1.71). P2-7 행과 `app.py` ×2·핀 네 곳을 v1.73 으로.
- 증거: `test/test_line_follow_contract_docs.py`, `src/site/fleet/test/test_task_contract_docs.py`, `test_mission_progress.py`.
- gate 변화: 없음.
