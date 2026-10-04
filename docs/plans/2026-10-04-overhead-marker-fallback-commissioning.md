# 천장 카메라 마커 우선·무마커 폴백과 실제 지도 좌표 실행 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 관제 PC에서 두 등록 로봇과 카메라를 연결하고, 마커 우선·무마커 폴백 위치를 지도 및 X/Y(m)로 표시하며 실물 기준점으로 정확도를 검증한다.

**Architecture:** Vision은 모서리 마커 또는 승인 사각형·차선 보정으로 위치를 계산한다. Fleet은 source token과 1초 lease를 확인하고 명시적 로봇 마커 대응 또는 신뢰 가능한 map pose로 이름을 대조한다. 추론은 표시 전용이며 주행·localization 입력과 연결하지 않는다.

**Tech Stack:** Python/FastAPI/Pydantic/OpenCV, vanilla ES modules, signed Linux amd64 site candidate, 기존 SQLite 등록·보정 기록.

## 범위와 승인

- D-457과 사용자 지시가 구현을 승인한다. 2026-10-04 사용자가 main 착지·푸시·검증된 후보 배포를 명시적으로 승인했다. 같은 범위를 다시 묻지 않는다.
- UI/UX 리팩터링은 보류한다. 기존 로봇 등록·camera credential·SQLite를 보존한다.
- SOURCE/호스트 검증·CI·ARTIFACT·현장 DEVICE/FIELD를 구분한다. 지도 좌표의 소수점 표시는 실측 정확도 증거가 아니다.

## Task 1: 마커 우선과 무마커 폴백 구현 — 완료, 재검증 중

**Files:** `contracts/foundation/core_common/protocol/overhead_detections.py`, `operations/vision/rosy_vision/track/`, `operations/fleet/fleet/server/tracking*.py`, `operations/fleet/fleet/server/web/tracking-*.js`.

1. 공유 payload, calibration 우선순위, 마커 없는 설정, marker_id 인증 대응, LEARNING 중 마커 전송, 인접 로봇 중복 제거의 실패 사례를 시험으로 고정한다.
2. 모서리 마커 측정 우선/승인 추론 보정 폴백과 로봇별 마커 우선/익명 blob 폴백을 구현한다. 하나의 marker에 대해 중복 blob 최대 한 개를 Fleet에서만 제거한다.
3. source/map/revision·future/stale·순서·명시적 marker 대응을 검사한다. 익명 검출의 실명 대조에 odom을 쓰지 않는다.
4. 관련 pytest와 known_failures 비교를 수행한다. X:에 로그·basetemp를 두고 SOURCE/LOCAL만 기록한다.

## Task 2: 좌표·관측 기준·표시 만료 — 완료

**Files:** `operations/fleet/fleet/server/web/index.html`, `tracking-layer.js`, `tracking-view.js`, `map-view.js`; **Test:** `test/test_overhead_tracking_browser.py`, `test/test_console_lifetime_browser.py`.

1. X/Y(m), 마커 관측/무마커 추론/이름 미확정 표를 추가한다. 신원 불확실한 점에 실제 robot_id를 임의로 붙이지 않는다.
2. 서버 age와 조회 지연을 뺀 최대 1초 수명 뒤 지도·좌표를 지운다. 다음 polling이 멈추어도 독립 timeout이 지운다.
3. Node 계산 시험, Chromium 마커→익명→만료, 토큰 재인증·pagehide/BFCache 시험을 실행한다.

## Task 3: main 통합·푸시 — 진행

**Files:** `docs/reference/ROSY ADR Log.md`, `ROSY API & Protocol Reference.md`, 모듈 logs/index, `test/architecture/test_module_structure.py`.

1. 작업 브랜치에서 main을 통합하고 양쪽 문서·schema export를 보존한다. 새 API Ref는 기존 LAN/중앙 GET 계약을 유지하며 v1.99로 기록한다. D-456이 main에 들어왔으므로 번호 gap 예약을 제거한다.
2. 규모를 실제 통합 코드로 재판정한다. 관련 시험·quick tier·affected tier를 실행하고 known_failures와 비교한다. 새 실패는 브랜치에서 수정한다.
3. origin/main fetch·작업 브랜치 rebase·harness generate·검사를 수행하고, main에 ff-only 착지한다. 동료의 미커밋·list.txt 때문에 거절되면 원본을 그대로 두고 이유를 알린다.
4. 정상 push 뒤 정확한 SHA의 CI를 확인한다. force push·hook 우회는 하지 않는다.

## Task 4: 서명 후보 검증과 관제 PC 배포 — 대기

**Files:** `.github/workflows/build-site-candidate.yml`, `deploy/site/{compose.yaml,auto_sign_candidates.py,verify_candidate.py,rosy_site_autoupdate.py}`; 실제 config는 저장소 밖 현장 구성이다.

1. 정확한 main SHA의 GitHub candidate build·provenance와 release.json을 확인한다.
2. 기존 signing station의 자동 서명과 현장 trust key를 유지하고 release.json.sig를 검증한다. 후보가 제공한 verifier로 자기 자신을 인증하지 않는다.
3. 승인된 기존 site updater로 적용한다. 실제 preflight가 거절되면 이유를 고친다. E-Stop을 풀거나 안전 상태를 가짜로 바꾸어 통과하지 않는다.
4. 현장 관리자 인증을 통해 중복 정적 로봇 항목만 제거하고 카메라 대상을 등록된 두 신원으로 바꾼다. 영속 등록·토큰·DB는 지우지 않는다. 확인되지 않은 marker 번호는 대응에 넣지 않는다.
5. 실제 이미지 SHA, /api/fleet/tracking 200, 로봇 online 2대와 camera sequence 증가를 readback한다. REST 연결과 robot outbound FleetAgent 증거는 별도로 기록한다.

## Task 5: 추론 보정과 배경 학습 — 현장 협조 필요

1. /console/install에서 현 렌즈·현재 프레임의 사각형·차선 맞춤을 확인한다. 맞춤 수락 뒤 **추적 보정 적용**으로 서버 calibration을 승인한다.
2. 사용자가 트랙의 로봇·물건을 치운 상태에서 **배경 다시 학습**을 실행하고 30프레임/최소 10초를 확인한다.
3. marker 없는 프레임의 status OK와 두 위치를 확인한다. CORE에 신뢰 가능한 map pose가 없으면 익명 좌표까지만 수용하고 이름 확정은 보류한다.

## Task 6: 실제 위치 정확도와 장애 복구 — 미실행

1. 지도에서 식별 가능한 실제 기준점들을 고르고 같은 좌표 원점·축·단위를 확인한다.
2. 사용자가 로봇을 각 기준점에 놓는다. 관측 X/Y 대비 실측 오차의 중앙값·최대값을 기록하며 카메라 추정과 CORE pose를 구분한다.
3. 한 로봇 마커를 가렸다 복원하여 우선순위 전환과 중복 제거를 확인한다. 마커가 없는 현장에서는 우선 합성 전환 시험과 실제 무마커 위치 증거를 구분한다.
4. 두 로봇 인접, 카메라 단절/복구, 브라우저 잠금/복귀, 서버 재시작의 보정 유지·위치 만료를 확인한다.
5. 실측 전에는 정확도 합격·DEVICE/FIELD 완료를 주장하지 않는다. 주행이 필요하면 별도 현장 안전 확인과 기존 CORE 실행 계약을 따른다.

## 현재 증거와 의존성

- 로컬 기능·통합 시험 602 passed. Node 34 passed. 좌표·scope Chromium 14 passed. 세부 기록은 `docs/validation/2026-10-04-overhead-marker-fallback-local.md`.
- 실제 사이트는 등록 로봇 2대 online과 천장 영상 수신을 조회했다. 추적은 기존 버전에서 아직 404다.
- 현재 로봇 map_id/localization이 없다. 익명 검출의 실명 대응에는 별도 localization commissioning 또는 확인된 marker 대응이 필요하다.
- SSH 계정의 sudo는 대화형 인증을 요구한다. 관리자 권한을 우회하지 않으며 현장 설정 단계에 필요한 정확한 실행 내용을 준비한다.
