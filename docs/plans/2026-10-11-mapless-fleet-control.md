# 지도 없이 시작하는 지도 생성과 통합 관제 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 완성된 지도 파일 없이 기준점·도로 요소·카메라 관측·로봇 주행으로 검토 가능한 지도 초안을 만들고, 로봇 선택 → 작업·대형 배정 → 진행·문제 확인 → 개입·결과 확인을 같은 관제 흐름으로 제공한다.

**Architecture:** 기존 Fleet 지도 초안·프로필·teach·formation·incident 경로를 확장한다. 관측과 초안은 운행용 지도·확정 위치와 구분하고, 생성 중인 지도는 별도 활성화 전까지 현재 작업의 지도 버전을 바꾸지 않는다. Vision은 관측, World는 좌표 투영, Fleet은 검증·배정·개입 원장, CORE는 최종 주행과 안전을 소유한다.

**Tech Stack:** Python/FastAPI/Pydantic/SQLite, 기존 OpenCV/NumPy, vanilla JavaScript ES modules, 공유 web UI, 원격 pytest 및 Chromium.

---

## 사용자 요구와 완료 기준

사용자가 주 작업을 로봇 선택 → 목적지·작업 배정 → 진행·문제 확인으로 지정했다. 지도 파일이 없어도 도로 요소를 등록하고 관측으로 나머지 도로를 그릴 수 있어야 하며, 로봇 주행으로 지도 쌓기도 포함한다. 개별 로봇뿐 아니라 대형과 문제 상황의 개입도 이번 범위다. 추가 확인을 기다리며 구현을 멈추지 않는다.

| 목표 | 완료를 판정할 시나리오 |
|---|---|
| G1 지도 없이 시작 | 활성 지도·초안이 없는 사이트에서 원점·방향·축척 근거를 등록하고 빈 초안을 생성한다. 실제로 관측하지 않은 예제 도로를 자동으로 넣지 않는다. |
| G2 시설·도로 등록 | 장소·차로·교차로·정지선·신호등을 등록하고 어떤 진입 차로에 어떤 시설이 적용되는지 확인한다. 물리 장치·가상 시설·관측 결과를 혼동하지 않는다. |
| G3 카메라·주행 기록 | 확인된 카메라 기준과 로봇 주행 기록을 같은 좌표 기준의 초안에 추가한다. 위치 손실·odom 재시작·기준 변경·관측 공백을 도로 연결로 만들지 않는다. |
| G4 통합 작업 배정 | 로봇 선택을 바꾸어도 명령을 보내지 않는다. 목적지 이동·차선 작업·지도 기록·대형 작업의 대상, 실행 조건, 접수, 진행, 종료를 확인한다. |
| G5 대형·문제 개입 | 리더·팔로워와 대형 상태를 작업 맥락에서 보고, 개별 명령 충돌·위치 손실·교착에 맞는 조치를 기존 계약으로 수행하고 결과를 읽는다. |
| G6 현장 화면 확인 | exact SHA의 CI·서명 릴리스·설치 image를 확인한 뒤 실제 사이트 desktop/mobile에서 원래 지도·프로필 유지, 크기 안정, 명령 잠금·결과 표시를 확인한다. |

물리 로봇이 오프라인이면 G3/G5의 원격 가짜 transport 검증과 실제 주행 수용을 별도로 기록한다. 오프라인을 통과 상태로 바꾸거나 검증을 위해 E-Stop을 풀거나 움직이지 않는다. 사이트 배포가 곧 실물 측량 정확도 수용은 아니다.

## 착수 시점의 확인된 코드

- D-488: `fleet.site_map`, `server/site_map_store.py`, `server/site_map_routes.py`에 지도 초안·불변 활성 버전·revision 검사가 있다.
- D-497: `operations/vision/rosy_vision/lane_map.py`는 보정과 측정 차로 폭, 선택 도로 기준점으로 관측된 흰 경계의 중심선을 추출한다. 독립 CLI와 파일 가져오기이며 카메라 관측 공백을 연결하지 않는다.
- D-494 6: `server/teach_service.py`는 확인된 map pose만 기록하고 결과를 지도 초안에 추가한다. 지도 없는 `_base()`는 존재하지만 시작에는 LOCALIZED pose가 필요하다. 무기준 odom을 운행 map pose로 승격해서 이 제한을 풀지 않는다.
- D-593: 로봇 map pin은 운행 위치 앵커에도 영향을 준다. 지도 조사용 원점 설정과 동일시하지 않는다.
- D-635/636/651: 지도 프로필·교정 도구·선택 로봇 작업 영역을 재사용한다. `profile-new`는 현재 예제 A/B 도로를 만들므로 G1의 빈 시작과 구분해야 한다.
- `operations/ui/console/formation.js`와 backend formation은 이미 존재하지만 현재 주 화면에서는 운영 도구 탭에 있다. 새 대형 API를 만들기 전에 선택 작업 영역과 연결한다.
- 기존 incident/attention 큐와 전체 정지 경로를 유지하고 대형·지도 기록 중에도 접근 가능하게 한다.
- `map_v2_fleet / 260919 MAP FILE.STL` 활성 지도 계보를 보존한다. 새 조사 결과로 이를 자동 교체하지 않는다.

## Task 1: 계약과 좌표·시설 근거 정의

**Files:**
- Read: `docs/adr/D-488-fleet-site-map-address-routes.md`, `docs/adr/D-497-camera-lane-map-draft.md`, D-494/D-593/D-635/D-636/D-651.
- Read: `docs/reference/ROSY API & Protocol Reference.md`, `operations/fleet/fleet/server/teach_routes.py`, `operations/fleet/fleet/server/signal_config.py`, `operations/fleet/fleet/server/signals.py`.
- Modify when required: API reference and the existing canonical protocol schemas resolved from the ownership manifest.
- Create: a reserved ADR under `docs/adr/`; same commit adds its `docs/reference/ROSY ADR Log.md` row.

1. Trace active map, calibration source/revision, robot pose/odom epoch, teach, physical/virtual signals and formation callers.
2. Define a survey coordinate reference and evidence status without changing operational MapPose authority. Record origin, orientation, units, source and revision; measurements remain optional only for a clearly relative draft, never for metre-qualified operational coordinates.
3. Define input-to-road relationships: stop line and approach direction, signal id/type and controlled lanes, destination and exclusion polygon. Reuse existing contracts where supported; document a contract extension before adding fields or routes.
4. Reserve the ADR immediately before writing it with `python tools/harness/adr_reserve.py next "지도 없는 조사와 통합 관제"`; preserve Log BOM/CRLF. State D-427/D-429/D-430 relations if folder/authority changes become necessary.
5. Commit only named owned paths. Run harness lint and remote contract checks.

## Task 2: 빈 지도 시작·시설 입력·프로필 저장

**Files:**
- Modify: `operations/ui/console/site-map.html`, `site-map.js`, `shared/site-map-model.js`.
- Modify only as contract requires: `operations/fleet/fleet/site_map.py`, `server/site_map_routes.py`, `server/site_map_store.py`.
- Test: `operations/fleet/test/test_map_profiles.py`, `test_site_map_api.py`, `test_site_map_browser.py`, relevant `test/web/*` suites.

1. Add meaningful tests for no active map/draft, no fake road, invalid/nonfinite coordinates, viewer lock and revision conflict.
2. Offer an explicit empty survey draft in the existing editor; keep saved profile loading and soccer rules intact.
3. Add only contract-supported facilities and lane relations; reject dangling references. Keep device enrollment separate from drawing a facility.
4. Save/reload without activating or replacing a running task's map. Preserve existing profile metadata and unknown map display.
5. Commit, remote-test, compare logs with `test/known_failures.py`; fix NEW failures in this branch.

## Task 3: 카메라와 로봇 주행의 지도 축적

**Files:**
- Modify as needed: `operations/vision/rosy_vision/lane_map.py`, `operations/fleet/fleet/server/teach_service.py`, `teach_routes.py`, `fleet/routing/teach.py`.
- Modify: `operations/ui/console/site-map-teach.js`, `site-map.html`, `shared/site-map-model.js`.
- Test: `operations/vision/test/test_lane_map.py`, `operations/fleet/test/test_teach.py`, `test_routing_teach.py`, relevant browser suites.

1. Test missing coordinate reference, stale pose, frame/revision mismatch, odom reset, observation gap, cancellation, repeated traversal and concurrent draft edits.
2. Reuse camera line extraction rather than introducing another detector. Keep its evidence file linked to its source/capture/calibration and draft result.
3. Record trusted map-coordinate traversal through existing teach. If only relative odom exists, store it as explicitly relative survey evidence behind the new reviewed contract; do not feed it to trip/formation/operational MapPose.
4. Split or stop a record on lost/restarted coordinate continuity. Never simplify across an unobserved gap into a drivable edge.
5. Compare overlapping observed routes and present possible connections for review. Keep ambiguous or unobserved completion separate from accepted edges. Do not require a new AI model service to complete the deterministic core workflow.
6. Confirm record into the draft with revision checking; activation remains separate. Test remote, update evidence and commit.

## Task 4: 선택 로봇 작업 영역에 지도 기록·대형 연결

**Files:**
- Modify: `operations/ui/console/index.html`, `console.js`, `roster.js`, `formation.js`, `shared/styles.css`.
- Reuse: existing teach routes, formation routes and trip/goal handlers.
- Test: existing selected-workspace, formation, named-command, role-lock and browser suites.

1. Test selection without command writes, selection change while a form is armed, viewer access and stale/offline member handling.
2. Make selected robot/group and current mode visible. Expose map recording and existing formation operations in task context; preserve source camera and stable map size.
3. Keep group member selection separate from a solo goal. Identify the leader receiving the destination and the followers receiving the existing formation command contract.
4. Show requested/accepted/active/held/completed/unknown from actual existing readback; do not infer physical success from HTTP 200.
5. Use small map icons and paths, with names/details outside the plane; verify 390 px mobile and desktop, keyboard focus, reasons for disabled controls and no overflow.
6. Commit and run explicit remote Chromium tests, not only the default suite that may skip browsers.

## Task 5: 문제 개입과 대형·지도 기록 충돌 처리

**Files:**
- Read/modify when necessary: `operations/ui/console/incident-view.js`, `roster.js`, `formation.js`, `operations/fleet/fleet/server/console.py`, `server/teach_service.py`, existing stuck/formation transaction handlers.
- Test: formation, teach, stuck, server-console and browser command receipt/readback suites selected by harness affected.

1. Trace actual running operation before changing safety code. Changes to safety-tagged paths require independent review and `Safety-Review:` trailer under D-430.
2. Test line loss, unknown position, stuck robot within a group, expired observations and a partial command response.
3. Present only supported interventions and explain unavailable actions. Apply the existing group teardown/cancel ordering before a conflicting solo action.
4. Keep attention/intervention queues and global stop available during any task view. Preserve failed and unknown recipients and require readback before resume is presented as running.
5. Map edits create a draft/version; do not silently swap the map/frame beneath an active recording or group.
6. Run affected remote tests and independent review where required; commit with evidence.

## Task 6: 통합·배포·실제 화면 증거

**Files:**
- Update: this plan's execution state, owned module logs/progress, dated validation result under `docs/validation/`.
- Reuse: `tools/land.py`, remote pytest, harness generation, existing site release pipeline.

1. Merge current main into this worktree, preserve moving-folder ownership and unrelated WIP, resolve only owned conflicts, rerun affected tests.
2. Use `python tools/land.py --tests auto`; classify logs with known_failures. No NEW failures or unreachable-test-host exceptions to the gate.
3. Fetch/update on current origin ancestry according to repository push rules, generate harness docs, pass pre-push, push without force. Do not remove colleagues' main WIP to make landing succeed.
4. Wait for terminal CI and exact-SHA release build; use the existing signing/deployment path. Verify installed SHA, image identity, health and updater terminal result.
5. Visit the actual Console and site-map page. Verify old active-map hash/profile preservation, empty-map setup using isolated test transport or disposable draft without overwriting live map, 2D/overlay/raw source stability, selected robot/group, visible interventions and request/readback workflow.
6. Store desktop/mobile screenshots and bounded API/geometry evidence in the X: session. Keep physical accuracy/real formation drive separately UNVERIFIED when robot/camera conditions prevent it.

## 검증 명령과 증거 위치

All pytest runs remotely for committed HEAD. Paths below are selected per task; duplicate test basenames remain separate invocations.

```powershell
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/task-2 -- operations/fleet/test/test_map_profiles.py operations/fleet/test/test_site_map_api.py
python test/known_failures.py X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/task-2/run-1.txt
python tools/harness/rosy_harness.py lint
```

Browser suites use the existing remote runner and CI browser environment. Node tests use existing `operations/fleet/test/web/*.test.mjs`. A local unit result, source commit, merge, CI, deployment and physical acceptance are distinct evidence tiers.

## 실행 상태

| 항목 | 상태 | 근거/다음 행동 |
|---|---|---|
| 목표 등록 | 완료 | 현재 대화의 active goal; 예산 제한 없음 |
| 격리 작업 위치 | 완료 | `.worktrees/wt-mapless-control-384416`, `feat/mapless-fleet-control`; X: session과 연결 |
| 현재 기능·공백 조사 | 진행 | camera lane CLI, LOCALIZED-only teach, profile example roads, tools-tab formation 확인 |
| Task 1–5 구현·검증 | 미완료 | 이 계획으로 차례대로 실행; 기존 기능 존재를 새 목표의 PASS로 쓰지 않음 |
| Task 6 통합·배포·사이트 확인 | 미완료 | 이번 변경의 exact SHA 증거 필요 |
| 실제 주행·측량·대형 수용 | 미확인 | 로봇 연결·측량·현장 조건이 갖춰졌을 때 별도 확인; 자동 이동으로 조건 만들지 않음 |

이 계획 작성은 구현·배포 완료가 아니다. 기존 배포 `367f6a90f41e`는 이전 지도 안정화와 작업 영역 변경의 증거이며 이번 지도 없는 조사 기능의 배포 증거로 쓰지 않는다.
