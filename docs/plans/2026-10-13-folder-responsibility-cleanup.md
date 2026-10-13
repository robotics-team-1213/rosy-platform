# 폴더 중복·책임 정리 실행 계획

> 실행자는 `executing-plans` 스킬로 한 작업씩 진행한다. 이 계획 작성과 제품 정리 실행은 별도다.

**Goal:** 현재 경로를 정확히 안내하고, D-738 순서에 따라 서로 다른 권한을 이름으로 구분하며, 생성물과 진행 작업을 보존한다.

**Architecture:** 기존 manifest·source mapping·설치 identity를 유지한 채 바깥 holder와 내부 책임을 단계별로 정리한다. CORE 최종 명령, Fleet 단일 SQLite 원장, 순수 판단·관측·학습의 권한은 바꾸지 않는다. 새 런타임 서비스나 dependency를 만들지 않는다.

**Tech Stack:** Git worktree, Python/setuptools·ament, ROS 2 Jazzy, 기존 원격 pytest/harness, PowerShell workspace 관리 도구.

**상태:** P0 안내 적용 · P1 분류/부분 이관 · S1 source·원격 검사 PASS, S2~S10·P2·P3 PLANNED · **날짜:** 2026-10-13 · **작성 브랜치:** `docs/folder-responsibility-audit`.

**P0 실행 기록 (2026-10-13, `docs/folder-guidance-p0`):** 현재 Control/Fleet/UI 안내와 root Docker source 설명을 정정하고 관리 도구로 `.worktrees` 안내를 설치했다. 우산 README·archive의 현재 소스 안내는 제품 Git 밖에서 수정하며 X: 세션 `folder-guidance-p0`에 전후 근거를 보존한다. 원격 시험과 local main 착지 결과는 Git 및 해당 세션 로그로 확인한다. 공유 main의 `reference/AGENTS.md`, `reference/src/AGENTS.md` 삭제는 owner 의도 근거가 없어 HOLD로 보존한다. P1·S1~S10·P2·P3는 아직 PLANNED다.

**P1 실행 기록 (2026-10-13, `docs/folder-artifacts-p1`):** 19곳을 분류하고 Graphify 생성물 4곳/418파일/33.22 MiB를 X:로 이관했다. 전체 hash·크기, source 부재, CLI 읽기 동등성을 확인했다. [처리 결과](../validation/folder-artifacts-p1-2026-10-13/result.md)와 [출력 안내](../reference/analysis-artifact-locations.md)에 보존/복구/후속 설정을 기록했다. 나머지 15곳은 actor·참조 미확정 또는 별도 overlay 범위로 HOLD다. S1~S10·P2·P3는 PLANNED다. HOLD를 제거 완료로 집계하지 않는다.

**P1 HOLD 재확인 (2026-10-13, `docs/artifact-hold-review`):** 사용자 지정 15곳을 재조사하여 비활성 orphan bytecode/cache/시험 자료 1,847개·40.54 MiB를 X:로 이관했다. [검증 기록](../validation/artifact-hold-review-2026-10-13/result.md)의 결과는 8곳 정리/2곳 부분 정리/5곳 유지다. 남은 협업 상태·lock·미확정 기록, 자격/producer 미확정 `pidA/wsA.json`, 참조되는 build/install/log는 보존한다. 15곳 전체 제거로 집계하지 않는다. S1~S10·P2·P3는 계속 PLANNED다.

근거: [조사 보고서](../assessments/2026-10-13-folder-responsibility-audit.md), Accepted [D-738](../adr/D-738-folder-one-authority.md), [현재 폴더 책임](../reference/platform-folder-responsibilities.md), [platform_parts.yaml](../../tools/harness/platform_parts.yaml). 조사 SHA `a967ab11a`는 과거 스냅샷이다. 각 작업 시작 시 최신 main에서 현재 경로와 이미 완료된 단계를 다시 확인한다. 다른 세션이 완료한 이동을 다시 실행하지 않는다.

**구조 토론 후 S1:** [D-743](../adr/D-743-drive-holder-promotion.md)과 [S1 실행 계획](2026-10-13-drive-holder-s1.md)에 따라 안쪽 Drive를 middleware/drive로 승격한다. S6의 signal_observer 범위는 실행 전에 따로 확정한다. 단계 순서는 유지한다.

**S2 범위 확정·착지 HOLD:** [D-747](../adr/D-747-perception-judgment-holders.md)에 따라 판단과 전용 adapter 14개를 출력별 기능 holder에 배치하는 SOURCE 구현·독립 검토를 완료했다. 통합 후보의 시험 PC 3곳 SSH 불가로 원격 재검증은 600초 대기 뒤 NOT RUN이며 local main에는 착지하지 않았다. S3는 S2 착지 뒤에 연다. ROS-free 파일 IO나 보정 명령을 순수 판단으로 간주하지 않는다. 실행·검증·착지는 [S2 계획](2026-10-13-perception-judgment-s2.md)과 [기록](../validation/perception-judgment-s2-2026-10-13/result.md)에서 구분한다.

**S2 후속 사용자 지시:** 위 HOLD 뒤에 사용자가 주소/VPN 변경을 확인하고 local merge까지만 요청했다. 원격 재검증 NOT RUN을 유지하고 lint·ff-only까지만 수행한다. push·다음 구조 단계는 이번 요청 범위 밖이다. 실제 착지는 Git와 검증 기록의 X landing readback으로 확인한다.

## 범위·책임·순서

| 묶음 | 담당 책임 | 실행 순서 | 완료 결과 |
|---|---|---|---|
| P0 현재 안내 | 문서/워크스페이스 안내 owner | 먼저 | 현재 작업 입구의 경로·링크 일치 |
| P1 생성물 분류 | 산출물 생산 세션 owner | P0 이후, 소스 이동과 별도 | 보존/이관/보류 manifest와 X: 출력 설정 |
| S1~S10 구조 | 해당 manifest root 유지보수자 | D-738 순서, 앞 단계 착지 후 다음 단계 | 소스·설치·호출자·안내·원격 시험 일치 |
| P2 proof 중복 | CORE peer/Fleet camera 유지보수자 | P0 이후 별도 주제 | 동등성 검사와 복제 이유, runtime 경계 보존 |
| P3 worktree | 작업 소유 세션/checkout 관리자 | 마지막에 별도 최신 조사 | 안전 조건을 통과한 명시적 후보와 제거 readback |

일정은 작업 슬롯과 시험 PC 가용성에 따라 잡는다. 첫 실행 묶음은 P0로 진행했으며, 후속은 사용자 요청에 따라 한 묶음씩 처리한다. 이 계획의 착지는 파일 이동·삭제, 장치 재시작·주행 또는 실물 수용 승인이 아니다.

## P0: 현재 작업 입구 정정

**수정 경로:** 우산 `F:\Dev\Control\Robot\Rosy\README.md`, `archive/AGENTS.md`의 현재 소스 안내, 제품 `middleware/core/api/core_api_web/api/AGENTS.md`, `operations/fleet/fleet/server/AGENTS.md`. 필요하면 root `AGENTS.md`의 현재 의존 경로를 함께 정정한다. 우산 파일은 제품 Git에 포함되지 않으므로 제품 commit과 별도 변경 기록을 남긴다.

1. `src/runtime/sensing`, `src/site/fleet`, 기존 UI `web` 안내를 찾고 실제 source mapping/serving 소비자를 읽는다. 역사 ADR·날짜 로그·payload 내부 안내는 수정하지 않는다.
2. 현재 Control은 `middleware/perception`, Fleet은 `operations/fleet`, UI 원본은 `middleware/robot_ui/robot`, `operations/site_ui/console`으로 안내한다. 오래된 계획 링크는 역사로 표시하고 현재 작업 입구는 현행 책임 안내로 연결한다.
3. 공유 main의 `reference/AGENTS.md`, `reference/src/AGENTS.md` 삭제는 소유 세션의 의도를 확인한다. 무단 restore나 가짜 zip/holder 생성으로 링크를 맞추지 않는다.
4. `.worktrees/AGENTS.md`, `.worktrees/README.md`가 여전히 없으면 관리 도구 `InitWorktrees`로 안내를 설치한다. tool state와 task checkout 내부 안내를 일괄 갱신하지 않는다.
5. 수정한 현재 안내의 로컬 링크를 검사하고 아래 문서 시험·lint를 실행한다. 제품 문서만 정확한 파일 목록으로 커밋한다. 우산 변경은 파일 목록·전후 근거를 X:에 기록한다.

**검증:** `test/architecture/test_folder_layout.py`, `test/architecture/test_document_placement.py`, `test/test_harness_contracts.py`, `test/test_network_topology_contracts.py`를 원격 실행하고 `known_failures.py`로 비교한다. 정상 종료와 NEW 0, 로컬 링크 오류 0이어야 한다. 역사 경로의 존재 여부를 현재 링크 실패로 판정하지 않는다.

## P1: 생성물·옛 경로 잔여물 분류

**검토 경로:** `src`, `apps`, `modules`, `firmware`, `signal`, `middleware/core/api_web`, `middleware/apps/device`; 우산/제품/`middleware`/`middleware/core`의 `graphify-out`; `.pytest-tmp-control`, `.pytest_cache`, `.ruff_cache`; 우산 `pidA`, `wsA.json`.

1. 현재 파일 수·tracked/ignored 상태·reparse target·생산 세션·활성 프로세스·실행 참조를 다시 조사한다. 보고서의 1,803개 수치를 삭제 목록으로 쓰지 않는다.
2. X: 세션 `evidence`에 각 항목의 `source`, `owner`, `purpose`, `active`, `references`, `decision`, `destination`, `rollback`을 기록한다. 알 수 없는 항목은 HOLD다. 자격·지속 DB·협업 상태는 임시 캐시로 분류하지 않는다.
3. 종료가 확인된 분석 결과는 해당 세션의 `export/evidence`, 임시 캐시는 `scratch`로 이관한다. 도구의 다음 출력 위치도 X:로 바꾼다. Native PowerShell `-LiteralPath`와 검증한 절대 경로를 사용하고 junction target을 따라 재귀 이동/삭제하지 않는다.
4. 이관한 보존 파일의 SHA-256·개수·사용 참조를 destination에서 읽어 확인한다. 정리 전/후 목록과 되돌릴 경로를 남긴다. 프로세스를 강제 종료해서 후보를 만들지 않는다.

**완료 기준:** 생산자가 확인된 처리 목록만 완료, 미확인은 HOLD로 남는다. `build/install/log`는 활성 overlay·source 참조 확인이 필요한 별도 생성물이다. 이번 묶음에 광범위 제거를 섞지 않는다. 내용만 이동한 작업에는 가짜 pytest를 추가하지 않고 manifest/hash/readback으로 검증한다.

## S1~S10: D-738 구조 실행

각 행은 **별도 단계 커밋**이다. 실제 대상 파일은 시작 시 `git ls-files <현재 경로>`로 고정하고 X: `evidence/step-N-files.txt`에 기록한다. 모든 공통 소비 경로는 `platform_parts.yaml`, `tools/harness`의 folder/package 매핑, 해당 `setup.py`·`_source_layout.py`, `tools/packaging/fleet_sources.py`, `deploy` closure, import/launch/시험/현재 안내다. 목록 밖의 기능 변경을 섞지 않는다.

| 단계 | 현재 → 목표/판정 | 반드시 보존할 경계 | 집중 검증 경로 |
|---|---|---|---|
| S1 | `middleware/control/drive` → `middleware/drive` (D-743) | 설치 import, CORE `core/drive` 조립은 별도 | `middleware/perception/test/test_responsibility_layout.py`, `test/architecture/test_folder_package_names.py` |
| S2 | `middleware/perception/control/loc_assist.py`, `watch.py` 및 나머지 순수 판단을 출력별 기능 holder로 판정 | facts/lease/command/graph 판단을 구분; 이미 이전된 Drive runtime은 다시 옮기지 않음 | `middleware/perception/test/`의 해당 adapter·순수 판단 시험 |
| S3 | S2 뒤 남은 `middleware/perception/control` 조립 → `middleware/perception/nodes` | `control` ROS package와 다섯 호환 설치 initializer | `middleware/perception/test/test_responsibility_layout.py`, `test/architecture/test_colcon_roots.py` |
| S4 | `middleware/robot_execution` → `middleware/robot_execution`; `operations/site_execution` → `operations/site_execution` | local policy/receipt와 site goal/progress, `rosy.execution.*` | `middleware/robot_execution/local/test/`, `test/test_judgment_extraction.py`, gateway/palletizing 소비 시험; 이동 뒤 시험 경로로 실행 |
| S5 | `middleware/robot_ui` → `middleware/robot_ui`; `operations/site_ui` → `operations/site_ui` | 기존 dashboard/Pilot/Face 및 Fleet Console/Cam serving, CSP, 앱 identity | `test/architecture/test_app_roles.py`, `test/architecture/test_app_identity.py`, 이동된 UI 시험과 Fleet console 시험 |
| S6 | `operations/overhead` → `operations/overhead`; `middleware/perception/front_camera` → `middleware/perception/front_camera` | display-only ceiling 관측과 로봇 앞 카메라 evidence, `rosy_vision`, wire 이름 | 현재 `operations/overhead/test/`, `middleware/perception/test/` 해당 perception 시험; 이동된 경로로 실행 |
| S7 | 로컬 decision/safety/preview/Drive 후보 제한 구현 → `lane_rules`, `safety_gate`, `preview`, `motion_limits` | `core_features.decision/safety/vision`, `control.safety` 옛 import를 유지; CORE 최종 `/cmd_vel` | `middleware/core/services/test/`, `test/architecture/test_safety_separation.py`, `test/architecture/test_cmd_vel_publisher_identity.py` |
| S8 | `operations/fleet/fleet/server` → 원장/채널/셀 어댑터/콘솔 조립/peer 책임 하위 폴더 | 한 SQLite·한 프로세스·기존 auth/claim/admission 거래; `app.py`는 조립 | `operations/fleet/test/`, `test/test_judgment_extraction.py`, source image/외부 설치 검사 |
| S9 | `middleware/perception/tools`의 호스트 도구 → 기존 `tools/sim`, `tools/calibration` | `device` 측정 도구는 host/소비 확인 후 개별 판정 | 도구를 언급하는 추적 시험·문서 검색 및 해당 suite; 보정 입력 보존/기존 destination 거절 |
| S10 | Fleet MapPose 소비자 → `rosy.world.state.projections.map_pose`; 모두 이전 후 alias 제거 | import/monkeypatch identity와 World observation/odom 의미 | `operations/world/test/`, `operations/fleet/test/test_map_pose.py`, `test_map_pose_service.py`, trip/swarm 관련 suite와 `tools/sim` 소비 |

**각 단계의 실제 작업:**

1. 앞 단계가 local main에 포함되었는지 확인한다. 최신 main에서 새 task worktree를 만들고 해당 모듈 AGENTS·ADR·소비자·시험·설치 closure를 읽는다.
2. 현재 동작을 고정하는 최소 시험을 먼저 확인한다. 기존 source layout·설치/identity 시험이 범위를 충분히 다루면 재사용한다. 새 경계를 검사해야 할 때만 작은 시험을 추가하고 먼저 실패를 확인한다.
3. 파일 이동과 source mapping을 함께 고친다. 새 runtime 구현 복사본이나 빈 future holder를 만들지 않는다. S2/S7/S8의 세부 기능 경로는 실제 입력/출력을 판정한 후 해당 단계에서 확정한다.
4. import·entrypoint·launch·배포 closure·시험 경로·현재 안내를 갱신한다. historical ADR/log/payload는 현재 경로로 소급 수정하지 않는다.
5. exact-path 커밋 후 원격 집중 pytest와 `known_failures`를 실행한다. source holder 밖의 wheel/sdist 설치와 명령 entrypoint, 필요한 Node/browser/Jazzy 검증을 확인한다. 단순 Git 이동은 설치 독립성 증거가 아니다.
6. `tools/land.py --tests auto`로 최신 main 통합과 affected 검증 후 ff-only 착지한다. 동료 WIP 때문에 거절되면 그대로 보존하고 거절 원문을 남긴다. 실패는 브랜치에서 고치고 다시 검사하며 `known_failures.txt`에 숨기지 않는다.
7. 착지 SHA·시험 exit·NEW·남은 image/device/field gate를 기록한다. 앞 단계가 착지되지 않으면 다음 구조 단계는 시작하지 않는다.

## P2: 동일 proof 코드의 최소 유지보수 조치

**기존 파일:** `middleware/core/api/core_api_web/api/peer_pairing/peer_crypto.py`, `operations/fleet/fleet/server/camera_peer_crypto.py`.

**기존 시험/소비자:** `middleware/core/api/test/test_peer_pairing.py`, `operations/fleet/test/test_camera_peer_vectors.py`, `operations/fleet/test/test_camera_peer_service.py`; CORE `receiver_service.py`, Fleet `camera_peer_service.py`, `camera_peer_store.py`, `camera_peer_routes.py`.

1. 동일 proof helper를 두 owner가 사용하는 이유와 각 package dependency/closure를 확인한다. approval principal·rate budget·DB·scope는 공유하지 않는다.
2. 첫 선택은 기존 architecture 시험에 두 파일 바이트 동등성 검사 하나를 두고, 파일에 복제 이유와 동시 갱신 위치를 한 줄로 기록하는 것이다. runtime 이동이나 dependency 추가 없이 한쪽만 수정한 실패를 검출한다.
3. dependency를 늘리지 않는 기존 shared holder가 실제로 있으면 한 구현+호환 import가 더 작은 완결 변경인지 비교한다. `contracts`에 crypto runtime dependency를 끌어들이거나 CORE/Fleet 내부 간 역방향 import를 만들지 않는다. 공유화가 별도 계약 변경을 요구하면 이번 단계에서는 동등성 검사까지만 한다.
4. golden vectors와 signature tampering·identity-file 보존 시험을 양쪽에서 원격 실행한다. 바이트 동등성은 보안 정확성 인증이 아니며 기능 시험을 대체하지 않는다.

**완료 기준:** 동등성 실패를 재현한 작은 시험과 양쪽 기존 기능 시험의 terminal 결과. 새 abstraction·서비스·library는 기본 범위 밖이다.

## P3: worktree 정리 — 별도 승인된 실행 묶음

1. `workspace.ps1 -Action Worktrees -Project rosy-platform`으로 최신 등록/물리 목록을 얻는다. 조사 보고서의 250개는 재사용하지 않는다.
2. 각 후보의 소유 세션·프로세스·lock·ignored 로컬 데이터·dirty 상태를 조사하고 branch/HEAD/복구 ref를 기록한다. 이름·나이·main 포함만으로 후보를 승인하지 않는다.
3. `.worktrees`의 직접 하위이고 reparse가 아니며, 소유 작업 종료·내용 보존·main ancestry·무활성·무lock을 모두 확인한 명시적 목록만 기존 fail-closed 도구로 제거한다.
4. 정식 `git worktree remove` 후 path/등록 부재와 branch/HEAD 보존을 readback한다. `.worktrees/.omc`와 locked 작업은 별도 owner 확인 전 HOLD다.

## 검증 명령과 증거

pytest는 노트북에서 실행하지 않는다. 커밋된 HEAD를 시험 PC에서 실행하고 로그는 X: 세션에 둔다. `<집중-시험-경로>`는 위 단계의 실제 이동 후 경로와 affected 선택으로 확정한다.

```powershell
git status --short --branch
git diff --cached --name-only
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/projects/rosy-platform/<session>/logs/step-N -- <집중-시험-경로>
python test/known_failures.py X:/DevTemp/projects/rosy-platform/<session>/logs/step-N/run-1.txt
python tools/land.py --tests auto
```

시험 PC에 닿지 않으면 runner의 대기 후 실패를 기록하고 착지하지 않는다. 반복 NEW, 비자동 충돌, unknown owner, invalid frame/calibration, 설치 source 누락은 해당 단계의 중단 사유다. 기존 데이터·동료 WIP를 치워 통과시키지 않는다.

**완료 구분:** plan 작성 → 구현 commit → remote 검사/외부 설치 → local main → 별도 요청된 push/terminal CI → 필요한 artifact/deploy/runtime → 장치/현장 인수. 이 계획과 host 시험은 뒤 단계의 증거가 아니다. 소스 이동으로 장치 calibration·map lineage를 바꾸거나 E-stop을 해제하지 않는다.

**되돌림:** 각 구조 단계의 역방향 새 commit으로 source mapping·소비자·안내를 같이 되돌린다. generated 결과는 재생성한다. 산출물 이관은 기록한 원래 경로와 hash로 되돌린다. 진행 작업을 잃는 reset/stash/광범위 clean은 사용하지 않는다.
