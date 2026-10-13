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

### 2026-10-12 최종 실행 결과

기능 릴리스 `5f4040f306`의 착지 회귀 16,523 PASS/NEW 0, Node 312 PASS, pre-push 292 PASS 및 동일 SHA FULL CI 15 jobs 성공을 확인했다. 기존 운영자 서명·사이트 updater 설치 종료 0, Fleet/Vision/proxy immutable image identity와 healthy, 실제 사이트 desktop/mobile 검증을 완료했다. 기존 활성 지도·본문·profile·draft는 배포 전 baseline과 동일하다.

G1/G2는 원격 저장·검증 및 실제 사이트 로컬 작성, G3는 좌표·근거·연속성/CAS 원격 검증, G4/G5는 선택·기록·대형 패널의 사이트 연결과 명령 충돌·개입 원격 검증, G6는 동일 SHA CI/서명/설치/UI 근거다. 로봇 두 대 오프라인으로 실물 G3/G5·교정 정확도는 미확인이다. [최종 검증 기록](../validation/2026-10-12-mapless-fleet-control.md)에 근거 경로·제한·다음 실물 확인 순서를 고정했다.

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

현재 착수 순서: 선택 로봇에서 기존 지도 기록 화면으로 ID를 전달하고, 기존 대형 패널을 작업 맥락에서 연다. 선택은 명령을 발행하지 않는다. 대형의 실제 리더·팔로워 및 목적지를 받을 리더를 표시하며 기존 권한·준비 조건·확인·상태 조회를 재사용한다. 이 연결 뒤 Task 5 개입/충돌 회귀, Task 6 통합·배포·실제 사이트 확인으로 진행한다.

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
| 현재 기능·공백 조사 | 완료 | camera lane·teach·profile·formation 소유 경로 추적 후 Task 1~5에서 연결·검증 |
| Task 1 초기 계약·검증 | 완료 | D-655/API v1.206, shared survey·facility 모델, 기존 body 보존·근거 활성화 거절·금지 영역 충돌 차단; fb3c1a8c8 원격 88 PASS, NEW 0 |
| Task 2 빈 지도 입력·편집 | 완료 · source/remote | 기준·장소·도로·신호등·정지선·금지 영역 입력 연결; Node 22 PASS, 전체 지도 Chromium 36+25=61 PASS/NEW 0. 실제 배포 수용은 Task 6 |
| Task 3 상대 주행 조사 | 완료 · source/remote | 지도 UNKNOWN에서도 신선한 odom으로 시작·선 누적·초안 확정 API/UI 구현; frame/continuity 독립 검토 수정 뒤 원격 55 PASS/NEW 0, Node 28 PASS. 아래 카메라 누적과 함께 Task 3을 구성하며 실물 주행 수용은 별도 |
| Task 3 카메라 관측 누적 | 완료 · source/remote | 누적·근거 보존·검토/재검토·기준/CAS/중복 방어 및 명시적 endpoint 연결 구현. 연결·비동기 경합 원격 16 PASS/NEW 0, Node 29 PASS. main 통합·배포·실물 정확도는 Task 6 |
| Task 4 선택 로봇·기록·대형 맥락 | 완료 · source/remote/site | 선택 ID로 기록 화면 이동, 기존 대형 패널 진입·리더/팔로워 표시, 제출 전 단독 폼 취소, 기록 대상 유지·제거/오프라인 안내 구현. a1b850f7d 자원 기준 통과 역할/배정/대형/기록 대상/지도/구조 30 PASS/NEW 0. Task 6에서 사이트 연결도 확인; 실물 대형 수용은 미확인 |
| Task 5 개입·작업 충돌 | 완료 · source/remote | 활성화 busy·조회 경합·대형/운행 명령 사유·복구 수락 표시 보강. 최종 d6abc8e863 원격 140 PASS, 개입 253 PASS, Node 301 PASS/NEW 0. 독립 검토 수용; Task 6 사이트 완료, 실물 개입 수용은 별도 |
| Task 1–5 구현·검증 | 완료 · source/remote | 각 단계의 새 source·원격 근거를 아래 기록. main 통합·CI·배포·실제 사이트 수용은 Task 6에서 별도 확인 |
| Task 6 통합·배포·사이트 확인 | 완료 · 사이트 범위 | `5f4040f306` 원격 회귀·FULL CI·서명 릴리스·불변 image readback 및 실제 desktop/mobile 검증. [최종 기록](../validation/2026-10-12-mapless-fleet-control.md) |
| 실제 주행·측량·대형 수용 | 미확인 | 로봇 연결·측량·현장 조건이 갖춰졌을 때 별도 확인; 자동 이동으로 조건 만들지 않음 |

이 계획 작성은 구현·배포 완료가 아니다. 기존 배포 `367f6a90f41e`는 이전 지도 안정화와 작업 영역 변경의 증거이며 이번 지도 없는 조사 기능의 배포 증거로 쓰지 않는다.

### 2026-10-11 실행 근거

- 이전 goal turn: 계획 작성·격리 worktree·baseline 실행으로 progress.
- baseline aa1e1ad9c: 원격 51 PASS, NEW 0; 초기 harness 0 errors/23 stale verification warnings.
- RED cdd8a77c2: 새 요구의 세 시험이 survey/facilities 미지원으로 실패했다. 첫 RED의 lane 필수 필드 누락은 fixture에서 고쳤으며 검증된 RED는 별도 `logs/survey-red-retry/run-1.txt`다.
- 구현 fb3c1a8c8: 모델 PC 원격 88 PASS, NEW 0 (`logs/survey-green-model/run-1.txt`). AI PC SSH banner timeout은 시험 실패와 별도로 기록하고, 종결된 실패 runner 대신 연결 가능한 모델 PC에서 실행했다. GREEN 실행은 23.6 free cores/8.6 GB 기준 통과.
- 공유 ADR D-654가 다른 active branch에 있어 현재 snapshot에 없음을 gap으로 기록했다. D-655 index row는 기존 table 안에 둔다. 다음 main 동기화에서 실제 ADR 도착 여부를 확인하고 해당 gap을 제거한다.
- 순수 UI helper Node 20 PASS; 아직 실제 입력 화면이나 새 기능 배포 수용은 아니다.
- 입력 화면 48a2fbfc1: 원격 Chromium 4 PASS, NEW 0. 빈 지도 생성·도로와 신호등 추가·수정·저장·재조회 및 기존 축구장 프로필을 1440/390 px에서 검증했다. 전체 회귀에서 예전 임의 예제 도로·관리자 안내 기대값을 발견해 빈 지도 시작 계약에 맞춰 수정했다. 시험 수정의 잘못된 동일 문자열 매칭은 9e68d078b에서 바로잡았다. 실패는 기존 실패로 분류하지 않는다.
- 935306768: 기존 장소·차로 편집기에서도 조사 검토를 무효화한다. 통행 방향·주행 방식·속도 변경 뒤 재검토를 거치며, 원본 입력과 과거 지도 본문을 보존한다. Node 22 PASS, harness 0 errors/23 기존 검증 시점 경고.
- 9e68d078b 최종 전체 브라우저 실행은 43개 진행 표시 뒤 SSH connection reset(exit 255)으로 종결됐다. 이는 전체 통과 증거가 아니며 `logs/site-map-regression-final/run-1.txt`에 남겼다. 자원·접속 가능한 호스트를 다시 고르는 terminal 실행에서 전체 결과를 얻어야 한다. 문서 변경 ea44178ce 이후 harness generate는 차이를 만들지 않았다.
- ea60284994: World의 신선한 상대 odom `(pose, stamp, epoch)` 읽기와 Fleet 서비스 포트를 구현했다. pin·운행 MapPose는 만들지 않는다. 새로운 세 시험의 remote RED 뒤 World wheel/compatibility와 Fleet map pose/service/pin 전체 remote GREEN 88 PASS, NEW 0 (`logs/survey-odom-green-retry/run-1.txt`, 현장 PC 5.0 cores/8.3 GB 기준 통과). 최초 GREEN shipping SSH timeout은 별도 종결이며 재시도 결과로 대체했다.
- ea44178ce 전체 브라우저 재시도도 59개 진행 표시 뒤 SSH reset으로 종결돼 미확인이다. 동일 source의 전체 선택을 `robot or reconnect or slow or pending or empty or late or changed` 및 그 부정식으로 나눠 각 묶음의 terminal receipt와 합계 61개를 확인한다. partial dot 출력은 PASS 증거로 사용하지 않는다.
- 전체 지도 브라우저 분할 검증: ea60284994에서 A 36 PASS/25 deselected, 6b89d6cb38에서 부정식 B 25 PASS/36 deselected, 각각 NEW 0. 두 SHA 사이에는 브라우저가 쓰는 소스·fixtures·브라우저 시험 변경이 없고, 두 선택의 합집합은 61개 전체다. B는 runner의 non-site fallback 경고가 있어 자원 기준 통과로 보고하지 않는다. 통합 착지 전에는 current main과 함께 검사한다.
- 기존 trusted-map 주행 기록 불연속: 6b89d6cb38의 새 세 시험은 UNKNOWN/DEGRADED/bridge 초과 뒤 도로를 잇는 동작으로 RED. 7bf0f597dc에서 기록 중단/유효 앞부분만 pending 유지와 API reason pose_lost를 구현했다. 최초 GREEN은 잘못 지정한 시험 파일로 exit 4, 실행된 시험 없음이다. 실제 경로 test_teach/test_routing_teach/test_fleet_place_markers로 다시 실행 중이다.
- 7bf0f597dc 불연속 수정의 GREEN: 위 실제 경로 원격 26 PASS, NEW 0 (`logs/teach-gap-green-paths/run-1.txt`, 모델 PC 23.5 cores/8.7 GB 기준 통과). 기존 teach API auth/audit, 순수 계산과 마커 장소 회귀를 포함한다. 지도 없는 상대 조사 시작/확정과 화면 연결은 다음 구현 단계다.

### Task 3 구현 전 확인한 연결 범위

- World `MapPoseTracker`가 odom freshness·속도/회전 불연속과 epoch를 이미 소유한다. 최신 odom과 epoch의 읽기 전용 조사 포트를 추가해 재사용하며, map pin이나 operational MapPose를 만들지 않는다. CORE OdomPose에는 reset ID가 없으므로 관측 가능한 불연속 감지의 한계를 현장 검증과 구분한다.
- Fleet `MapPoseService` → `TeachService` → `teach_routes.StartRequest` → `site-map-teach.js` 및 API reference를 함께 연결한다. 조사 시작은 저장된 draft revision/map_id/reference revision과 명시적 기준을 요구한다. 상대 odom을 기준에 투영한 선은 observed evidence이며, 검토 전 활성화할 수 없다.
- 기록 중 odom gap/reset·지도 기준 변경이면 유효한 앞부분만 남기고 기록을 중단한다. 기존 trusted-map 기록의 untrusted pose 건너뛰기 역시 불연속을 자동 잇지 않도록 수정하고 관련 시험을 갱신한다. 기록 중단은 로봇 정지 명령이 아니다.
- 확정은 현재 초안 기준의 동일성을 확인한 뒤 기존 expected_revision CAS로 저장한다. 주행·카메라 기록의 원본 근거와 연결 후보를 유지하고, 관측되지 않은 연결은 자동 도로로 승격하지 않는다.

### 2026-10-11 상대 주행 조사 API·화면 근거

- ac95a2c756: 8개 remote RED로 mode/basis/relative recording 미지원 확인. e0c6de8616 구현 뒤 33 PASS/1 NEW는 기존 points list 형식 회귀이며 시험을 완화하지 않고 dab3453776에서 배열 형식을 복구했다. HTTP auth/audit/no-motion, stale odom, confirm CAS, 검토 무효화를 추가해 원격 37 PASS/NEW 0.
- 1a14e9705a: 현재 source API 37 PASS/NEW 0 (`logs/teach-survey-api-final/run-1.txt`), Node 24 PASS. 초안 revision/map_id/reference 확인, 출발 때 odom 기준 고정, 단절/reset/초안 수정 시 유효 앞부분만 유지, 상대 좌표를 운행 MapPose로 승격하지 않음.
- UI는 기록 방식 선택과 매 시작의 실제 시작점·방향 확인을 요구한다. 로봇·방식·저장 revision이 바뀌면 확인을 초기화하고, 동일 조사 snapshot인 지도에만 선을 표시하며 다른 기준의 초안 확정을 막는다. 기록 중단 표시는 로봇 정지를 뜻하지 않는다고 명시한다.
- 3c8a1fe713 browser RED는 teach-frame 미존재다. 1a14e9705a Chromium 6 PASS/NEW 0으로 1440/390 px UNKNOWN 로봇 상대 기록→초안 확정과 기존 수동 지도/축구장 프로필을 확인했다. adb94d9097 추가 미리보기 시험은 멈춘 뒤 점 개수를 좌표 배열로 오인한 동작으로 RED였고 8596f7042b에서 수정했다. 최종 실행과 현재 main 통합 회귀 결과는 별도로 기록한다.
- 이번 구현은 기존 teach의 단일 기록/pending 10분/초안 CAS/감사 경로를 사용한다. 새 이동 명령·새 detector·새 AI 서비스·CORE 계약 변경은 없다. 카메라 누적·선택 로봇의 작업/대형 연결·개입·배포·현장 수용까지 남아 있어 goal은 active다.
- 8596f7042b 최종 지도 브라우저 6 PASS/NEW 0 (`logs/teach-survey-preview-green/run-1.txt`, 현장 PC 자원 기준 통과). 멈춘 조사 선이 초안 위에 남는 것도 확인했다. 1bde13e444 HTTP/desktop/mobile 읽기 전용 호출 허용 목록 강화는 원격 3 PASS/NEW 0 (`logs/teach-survey-read-only-retry/run-1.txt`, AI PC 자원 기준 통과)다.

### 2026-10-11 독립 검토 수정

- `requesting-code-review`에 따른 `survey_feature_review` 독립 검토는 기존 정상 teach/place의 조사 초안 좌표계 혼입, 거절된 odom 뒤 조사 기록 재개, 분류 간 같은 ID 편집의 삭제 위험을 발견했다. remote RED 5 FAIL/11 PASS와 Node RED 1 FAIL/24 PASS로 재현했다. 실패를 known failure에 추가하지 않았다.
- 일반 teach는 시작의 map_id·전체 조사 기준·활성 버전을 고정한다. 샘플·확정·pose/마커 장소 저장에서 프레임을 비교하고 다른 프레임은 거절한다. 지도 변경 뒤 기록을 중단하며 내부 변환을 운행 pose로 승격하지 않는다. 거절된 odom은 조사 연속성만 끊고 기존 운행 앵커/epoch는 보존한다. 분류+ID로 편집·삭제하므로 기존 프로필의 분류 간 같은 ID를 보존한다.
- 추가 검토에서 일반 기록 미리보기가 다른 프로필 위에 표시되는 경로도 고쳤다. 공개 map_id와 선택 survey_reference는 시작 snapshot이며 현재 초안 기준으로 덮어쓰지 않는다. 같은 조사 지도의 정상 teach 확정·pose/마커 추가/이동도 검토를 무효화하고 새/변경 도로에 observed 근거를 붙인다.
- 2c3f28a10f 원격 API·기록·마커·공통 계약 122 PASS/NEW 0 (`logs/survey-review-final/run-1.txt`). 첫 GREEN의 잘못된 시험 경로는 exit 4/시험 없음으로 기록한다. 추가 정상 동작 fixture의 중복 장소 두 실패는 서로 다른 실제 위치로 고쳤으며 7476837977 주행·활성 버전 변경·World 서비스 55 PASS/NEW 0 (`logs/survey-frame-final/run-1.txt`). Node 26 PASS다.
- 표시 회귀의 첫 browser 실행은 새 프로필 작성 폼만 열고 지도 전환을 기대한 두 fixture 실패였다. 저장된 프로필 선택까지 포함해 다시 검증한다. 기존 입력·상대 조사·축구장 6개는 해당 실행에서 통과했다.
- 73295afa26 최종 desktop/mobile Chromium 8 PASS/57 deselected, NEW 0 (`logs/survey-review-browser-final/run-1.txt`). 수동 요소·상대 조사·축구장 프로필과 일반 기록의 다른 지도 표시 거절을 포함한다. d871a9842e 구조 검사 3 PASS/35 deselected, NEW 0 (`logs/survey-structure-final/run-1.txt`). 두 실행은 AI PC 자원 기준 통과다. 전체 65개 browser 회귀는 최종 통합 단계에서 확인한다.
- 순수 초안 편집을 기존 UI source owner의 site-map-edit.js로 분리해 지도 모델은 770줄이다. HostStatusEvidence는 기존 evidence.py로 옮기고 public schemas alias·wire defaults 시험을 유지했다. 독립 검토를 근거로 Fleet 52,840줄을 재판정했으며 +150 허용량·observe/server/UI 분리 의무·개별 파일 상한은 유지한다. 다음 카메라 추출 구현은 Vision이 소유한다.
- 이 단계는 source/remote이며 카메라 누적·선택 작업/대형·개입·main 통합·CI·배포·실제 사이트 수용까지 전체 목표는 계속 active다.
- 최종 독립 검토 `survey_feature_review`는 d871a9842e 소스와 terminal 55/8/3 PASS 로그를 확인해 보고된 Important 사항 해결과 Fleet 재판정을 수용했다. 전체 목표 수용이 아닌 수동 조사/상대 기록 범위의 검토다.

### 다음 카메라 누적 구현의 확인된 연결점

- Vision `lane_map.generate_map`은 측정 homography·lane width·road seed로 초안을 만들고 별도 evidence 파일에 calibration·frame_sha256·proposal_only를 남긴다. 현재 UI import-camera-map은 초안을 교체하므로 누적 경로가 아니다.
- 기존 추출기를 재사용하고 관측 근거를 지도 간선까지 연결한다. 누적은 기존 map_id와 전체 survey 기준의 동일성 및 명시적 좌표 정합이 선행돼야 한다. ID 충돌을 보존하고 관측되지 않은 장소/간선 연결을 자동 생성하지 않는다. 저장은 기존 bounded draft PUT/CAS/named operator를 사용하며 활성 지도와 source lineage를 교체하지 않는다.

### 2026-10-11 카메라 관측 누적 구현

- 7ed46c1f54 remote RED는 출력 survey/도로 근거 누락이며 Node RED는 mergeCameraMap 미구현이다. Vision의 기존 extractor에 optional calibration.survey 정규화와 camera/observed 근거를 연결했다. calibration SHA256과 CLI frame SHA256을 간선 note에 보존한다. 기준·도로 검토 전 활성화는 기존 저장소 가드로 거절한다. 975de95358 원격 추출/구조 7 PASS/NEW 0.
- 기존 replace import와 별도 누적 버튼을 제공한다. 저장된 초안의 전체 survey 기준과 map_id가 같아야 하며 기존 시설·규칙은 보존한다. 새 장소/간선 ID를 재배정하고 동일 geometry/운행 속성은 중복 생성하지 않는다. 초안 수정/교체와 CAS를 확인한다. 입력 metadata를 복사하는 것만으로 image_to_map의 실제 정합이 성립하지 않으므로 기준점 측정 확인을 유지한다.
- Browser 첫 RED는 fixture 속도 필드 누락이라 수정했고 실제 RED는 merge control 미존재다. 7d3a93d0f2 누적 desktop/mobile·기존 카메라·Vision·구조 9 PASS/NEW 0 (`logs/camera-accumulate-browser-green/run-1.txt`, AI PC 자원 기준 통과). Node 28 PASS.
- `survey_feature_review`는 조사 metadata 없는 camera map의 marker 편집 재검토 누락, 수동 도로/장소 교정의 원본 근거 삭제, 반복 관측의 새 프레임 근거 누락을 발견했다. marker remote RED로 재현하고 b80fa42817에서 수정했다. 반복의 새 note를 보존해 검토를 무효화하며 동일 파일은 idempotent다. 합계 1000자를 넘으면 원본을 버리지 않고 거절한다. Node는 도로/장소 교정·다른 프레임 반복·overflow·원본 보존을 확인한다. 독립 source 재검토는 해당 수정 범위를 수용했으며 terminal remote GREEN을 확인한다.
- 일반 camera 초안도 기존 검토 메모로 검토할 수 있다. 간선 운행 속성 수정과 marker 끝점 수정은 camera/observed가 아닌 operator/observed로 재검토하고 기존 프레임 지문을 보존한다. review는 원본 note에 근거를 덧붙인다. UI 검토 fixture에서 닫힌 disclosure를 열지 않은 두 실패는 실제 사용자 조작을 추가해 다시 실행한다. NEW를 known failure로 넣지 않는다.
- 가까운 기존 장소(0.05 m 이내)를 자동 접합하지 않는다. Task 3의 중첩 경로 연결 후보 표시·검토는 미완료이며 다음 구현에서 명시적 endpoint mapping과 근거 상태를 연결한다. 카메라 누적 slice의 시험 통과를 Task 3 전체·최종 관제·배포 완료로 사용하지 않는다.
- ebf05b9811 최종 원격 카메라/Vision/marker/desktop/mobile/구조 12 PASS/122 deselected, NEW 0 (`logs/camera-review-final-retry/run-1.txt`, AI PC 자원 기준 통과). Node 28 PASS. 독립 검토자는 소스와 해당 terminal 영수증을 확인해 누적/근거 보존 범위를 수용했다. 전체 browser 69개와 main 통합 회귀는 Task 6에서 확인한다.

### Task 3 endpoint 연결 검토 종결

- 78d642317b 연결 화면 시험은 통과했으나 구조 시험에서 Fleet 52995 > 52840+150 NEW가 발생했다. 독립 검토에서 같은 좌표의 다른 장소 ID를 무시하는 중복 처리와 파일/확인 창 대기 중 바뀐 선택·편집이 저장되는 경합을 발견했다.
- 962fa15277은 명시적 endpoint ID와 robot_kinds까지 중복 비교하고, 클릭 당시 선택을 고정하며 파일·초안·미저장 편집·선택·접속 변경 시 대기 중 저장을 취소한다. Node 29 PASS와 AI PC 자원 기준 통과 원격 Chromium 16 PASS/63 deselected, NEW 0. 독립 검토 수용. package 53010 재측정과 split 재판정을 기록하며 +150·파일 상한·기존 observe/server/UI 분리 의무를 유지한다.
- 1ea4f4c2c 최종 연결/구조 원격 19 PASS/98 deselected, NEW 0 (`logs/camera-connect-final/run-1.txt`, 모델 PC 23.2 cores/8.5 GB 기준 통과). 연결은 inferred로 보존하며 별도 검토 전 활성화를 거절한다. 이 증거는 실물 연결 정확도·main 통합·CI·배포·실제 사이트 수용이 아니다.

### Task 4 선택 로봇의 기록·대형 진입과 대상 유지

- 6d655ecce 원격 RED 3 FAIL은 선택 카드 진입과 요청 ID 안내 부재다. 0d9adef961은 현재 로봇 ID를 지도 기록 링크로 전달하고 대형 관리에서 실제 리더·팔로워를 보여 준다. 관리 진입은 기존 대형 리더를 바꾸지 않고, e6081fcc70에서 제출 전 확인/운행 폼/목표/위치 지정만 취소한다. 로봇 정지나 시작 명령은 보내지 않는다.
- e6081fcc70 넓은 역할/운행/기록/지도/구조 회귀는 158 PASS, 새 시험 2 FAIL(지원하지 않는 가짜 로봇의 목표 주행 버튼 클릭)이었다. 실제 지원하는 운행 배정 폼으로 시험을 고쳤으며 제품 capability 거절을 완화하지 않았다. NEW로 기록하고 기존 실패 목록에는 넣지 않았다.
- a9f5eaf35 기록 대상 RED는 오프라인 안내가 없었다. a1b850f7d은 사용자 선택을 새로고침에서 유지하고 기록 중에는 서버가 보고한 robot_id에 선택을 고정한다. 등록에서 사라진 기록 로봇을 다른 로봇으로 바꾸지 않고 기록 중단은 유지한다. 잘못된 URL ID는 빈 선택과 대상 안내로 표시한다.
- a1b850f7d 원격 대상/desktop/mobile/기존 지도 편집/구조 10 PASS/131 deselected, NEW 0 (`logs/selected-context-final/run-1.txt`). 이 실행은 자원 부족 fallback 경고가 있으므로 자원 기준 통과 수용으로 쓰지 않는다. 동일 소스의 전체 역할/운행 및 대상/지도/구조 acceptance를 AI PC 18 cores/7 GB 기준 통과 상태에서 실행 중이다.
- Task 5에서 대형 팔로워 목표·대형 참여자 단독 운행·문제 개입의 기존 서버 거절과 화면 사유를 대조한다. Task 6은 이동 중 폴더 소유/현재 main 통합, 원격 회귀, CI, 서명 배포, 실제 사이트 확인을 계속 요구한다.
- 동일 a1b850f7d 최종 acceptance: AI PC 18 cores/7 GB 기준 통과, 전체 역할/카드 운행과 대상/지도 편집/구조 30 PASS/111 deselected, NEW 0 (`logs/selected-context-acceptance/run-1.txt`). 독립 검토는 기록 대상 수정과 기존 권한 보존을 수용했다. Task 5 점검에서 app.py의 site-map 활성화 busy 주입이 진행 중 trip만 확인하고 formation/teach는 확인하지 않는 공백을 찾았다. 이 공백을 보강하기 전 통합·배포 완료로 판정하지 않는다.

## 2026-10-11 · d6abc8e863 · D-655 map activation and command conflicts

- 변경: trip뿐 아니라 진행 중 대형과 지도 기록에서도 활성화를 거절한다. 일반 기록 시작·pose 장소 저장은 위치 조회 전후 map_id·전체 조사 기준·활성 버전을 비교해 이전 위치의 새 지도 저장을 막는다. 팔로워 목표와 참여자 개별 운행, 진행 중 trip의 개별 목표를 기존 admission에 맞춰 설명하며 확인 직전 재검사한다. 충돌 작업을 자동 해제하거나 이동 명령을 추가하지 않는다. 재개·후진 수락과 실제 로봇 진행을 구분한다.
- 증거: busy RED 4 FAIL, start 경합 RED 뒤 131 PASS, place fixture의 같은 위치로 SITE_MAP_INVALID가 난 경우를 구분하고 distinct pose에서 실제 DID NOT RAISE를 재현했다. 공통 수정 a4a9e2f9e 132 PASS/NEW 0. 대형 화면/서버/구조 68 PASS, 개입·부분 취소·불명 응답·운행 권한·위치 손실 253 PASS/NEW 0. 최종 d6abc8e863 Chromium 역할/대형 및 teach/활성화/구조 140 PASS/NEW 0, 모델 PC 22 cores/7.9 GB 기준 통과. UI Node 301 PASS. 넓은 Node 첫 실행의 누락 loader 오류는 기존 loader를 지정해 해결했다.
- 근거 위치: X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/task5-command-final/run-1.txt; logs/task5-intervention/run-1.txt; logs/task5-node-final.txt. 독립 survey_feature_review가 shared guard·모든 UI 호출자·권한 보존을 수용했다.
- gate 변화: Task 4/5 source·원격 범위 완료. main 폴더 이동 통합·전체 회귀·CI·서명 릴리스·배포·실제 사이트 확인은 Task 6이며 목표는 active다. 실제 로봇 주행·측량·대형 개입 수용은 미확인이다.

## Task 6 · 최신 main 통합과 회귀 수정

- `ed901a0249`에서 main `4bcfc55d88`을 작업 브랜치에 합쳤다. 새 사건 계약과 조사 계약의 export를 모두 보존하고, API 문서 번호 충돌은 v1.208로 정리했다. Fleet 재측정 52790 및 별도 incident 360은 기존 +150·파일 상한·분리 의무를 유지한다. 아직 공유 main에 착지하지 않았다.
- 첫 넓은 원격 회귀는 세 호출에서 9232/3542/3638 PASS와 각각 4/3/7 NEW였다. 자원 부족 fallback 실행이므로 수용 증거로 승격하지 않았다. NEW는 v1.208 헤더 정합성, 신규 자산 설치 목록, 분리된 확인 창 소유 목록, 비활성 이유, 문서 import 소유 목록, 거절 odom의 조사 연속성 기대값을 수정했다. 기존 실패 목록에 추가하지 않았다.
- `e9fd1c42fe`에서 자원 기준 통과 AI PC 원격 계약·Chromium·설치 회귀 275 PASS/NEW 0 (`logs/merged-contracts-final/run-1.txt`), Node 302 PASS (`logs/merged-node-final.txt`). 이전 잘못된 시험 경로 실행은 exit 4/시험 없음이며 수용 증거가 아니다. 독립 검토는 수정 소스를 수용했다.
- 전체 회귀 재실행·착지·CI·서명 사이트 배포·실제 desktop/mobile 화면 확인은 남아 있다. 현장 설치는 `5cfd0b7cd36a`이며 이번 브랜치 설치가 아니다. 기본 브라우저 연결 없음과 Windows Application Control 차단을 우회하지 않고 기존 원격 Chromium 경로를 사용한다. 공개 HTTPS 접속의 시간 초과도 아직 해결·확인 대상이다.

### 2026-10-12 · D-664 통합과 현장 비교 기준

- `0508f92b0`에서 작업 현황 읽기를 포함한 main을 합쳤다. D-664의 v1.208 이력을 보존하고 D-655와 현재 API 헤더를 v1.209로 구분했다. 두 계약의 export 및 70개 설치 자산을 유지한다. 독립 검토 Fleet 53012, 별도 incidents 360으로 재판정했으며 +150·파일 상한·두 기능의 기존 분리 의무는 유지한다. 이어 `868934dea`에서 main `e7558c7d4d`을 합쳤고, 실제 존재하는 D-655의 되살아난 gap 행만 제거했다.
- `35a8bbd0a` 회귀는 AI PC 22 cores/9 GB, 모델 PC 23.9 cores/8.6 GB 기준 통과로 시작했다. 핵심 계약·Vision·공통 UI·구조 9320 PASS/582 SKIP, Fleet 3651 PASS/211 SKIP. 설치/Perception/root 3551 PASS/113 SKIP의 1 NEW는 이 계획의 이전 현장 릴리스 SHA 전체 표기가 high-entropy 검사에 걸린 것이다. 문서 표기를 짧은 commit ID로 바꾸고 정확한 값은 기존 X: readback에 보존한다. 비밀 검사 규칙·allowlist는 바꾸지 않는다. 해당 실패로 착지는 거절됐으며 수정 후 검증은 진행 중이다.
- 배포 전 실제 사이트를 기존 원격 Chromium으로 desktop 1440 px/mobile 390 px에서 확인했다. Console/site-map HTTP 200, JS 오류 0, 가로 넘침 없음. 활성 지도는 map_v2_fleet v5, draft 없음, 저장 profile map_v2_fleet-v5를 읽어 `logs/site-baseline-map-state.json`에 보존했다. 로봇 2대 오프라인이며 실제 이동·대형 개입 수용을 주장하지 않는다.
- 현장 인증서는 호스트 이름 SAN만 포함하고 Tailscale IP SAN은 없다. 외부 8443은 시간 초과이고 현장 loopback은 CA/SAN 검증을 통과한다. 화면 확인은 SSH 터널과 검증한 인증서 공개키에 한정한 Chromium 신뢰로 수행했다. 일반 사용자 IP 접속 해결·이번 소스 배포 증거로 승격하지 않는다. 로컬 GitHub 연결은 SSH SOCKS 경유로 복구했으며 인증서 검사를 유지한다. 기존 main e7558c7d4d의 CI 성공은 이번 브랜치의 CI 증거가 아니다.
