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

## 2026-09-24 · uncommitted · fix(dashboard,api): 무동작 하드웨어 런타임을 사실대로 — 구동 꺼짐, 이동 광고 없음, API 정지 문구, 맵 404 없음, 계약 v1.21
- 증상(실기 rosy-pinky-e4us, release 2026.09.24-010): CORE-only 이미지에서 `rosy-io` 를 무동작 모드로 켜자 배터리·오도메트리가 들어오고 `motor/ready` 는 false 였는데, 대시보드는 SAFETY "HW OFF — 하드웨어 런타임 꺼짐 (CORE-only)", 기능 가용성 5 / 5, `capabilities` 는 withheld 없음·teleop true 였다. 하드웨어가 꺼져 있을 때는 차단 이유가 `device_state:SAFE_STOP`(실제는 `runtime_mode:core`)였고, API 정지(`api:operator`)에 "모터 전원이 끊겼습니다. 현장에서 해제해야 합니다" 를 보였다. `/api/v1/map`·`/map/costmap?scope=global` 404 가 콘솔 오류로 남았다.
- 변경: `api/v1/system.py` `capabilities` 가 `runtime_truth` 로 플래그를 내리고 additive `runtime`(`hardware`·`evidence`·`drive`·`navigation`·`maps`)을 싣는다. `web/app.js` 안전 회로 영웅 표시는 `capabilities.runtime` 으로 `HW OFF`/`HW SILENT`/`NO DRIVE`("하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)")/`NO SOURCE` 를 가른다(구 서버는 `runtime_mode` 로 폴백). descriptor 이유는 `reasons` 전부를 운용자 말로 잇는다. teleop 안내에 보류 이유. `fieldMap.refresh()` 는 capabilities 뒤에 돈다. `web/map.js` 는 `runtime.maps` 가 false 인 스냅샷을 묻지 않는다. `web/triage.js` 이유 문구 표, 구성 이유(CORE-only·무동작·내비게이션 없음)는 각각 색 없는 관측 사실 하나, `estopFault(source)` — CORE 의 모든 정지는 소프트웨어 정지이므로 전원 차단을 말하지 않는다. `api/app.py` 계약 v1.21.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py -q` 40 passed(신규 3: 무동작, 맵 요청, API 정지 문구), `src/core/core/test` 포함 1553 passed (2026-09-24 Windows).
- gate 변화: 없음 (DEVICE 재검증 필요 — overlay 후 무동작 `rosy-io` 로 대시보드 확인).
- 결정: D-32, D-192, D-82. 신규 ADR 없음.
- 교훈: 브라우저의 404 콘솔 오류는 JS 로 삼킬 수 없다 — 없는 자원은 서버가 "없다"고 먼저 말하고 클라이언트가 묻지 않아야 한다.
