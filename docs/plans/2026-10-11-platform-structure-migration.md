# ROSY Platform Structure Migration Implementation Plan

**현재 상태 (2026-10-11):** 채택한 실제 폴더 이동·소비자/패키징 수정은 D-626/D-628/D-630/D-637로 완료하고 local main `d4988bffba`에 반영했다. [현재 89개 holder 책임](../reference/platform-folder-responsibilities.md)과 [D-637 검증 결과](../validation/d637-remaining-folders-2026-10-11/result.md)가 현재 기준이다. 아래 원래 후보·미실행 표는 각 당시 기준의 이력이다. 미래 모델·producer admission 확장·새 API·실기 수용은 폴더 단계 완료에 포함하지 않는다.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-625의 의미 기반 구조를 한 번에 옮기지 않고, 검토 가능한 이전 단위·소비자 목록·실행 도구·복구 절차로 준비한다.

**Architecture:** 기존 D-427 part/import 규칙과 최종 writer를 보존한다. 도구는 선택한 holder의 파일 이동과 참조 보고만 담당한다. 참조 자동 치환은 설치 경로·소유권 ID·과거 기록을 오인할 수 있어 기존 `d427_move.py`의 scanner만 재사용한다. 물리적 이동 완료와 책임 추출 완료는 다른 판정이다.

**Tech Stack:** Python stdlib, 기존 `_legacy_paths.LegacyScan`, Git, JSON 이전표, 원격 pytest, 기존 harness/architecture 계약.

**상태:** M0–M2 준비 완료, M3–M9 미실행, 2026-10-11. 기준 `f14070a59`, 브랜치 `feat/platform-structure-migration`. 사용자는 구조 방향과 ADR·계획·도구 작성을 요청했다. 실제 제품 이전 M3 이후는 실행하지 않았다.

**후속 실행:** 같은 날 사용자의 실행 요청으로 [D-626](../adr/D-626-d625-holder-migration-execution.md)에 따라 M3–M6를 진행한다. 이전 전 후보 `3927f9a33`의 원격 architecture/도구 104 성공 표시·exit 0, known_failures 0 NEW/0 known. 독립 리뷰의 설치 목적지·Safety 코드 보존 조건을 반영한다. 완료 결과는 아래 실행 기록에 추가한다.

## 이전 단위와 선행 조건

| 순서/ID | 현재 → 목표 | 유지할 identity | 실행 전 확인 |
|---|---|---|---|
| M3 / core-api | `middleware/core/api_web` → `middleware/core/api` | `core_api_web`, 기존 ROS package명·HTTP/WebSocket·entry point | Safety API 독립 리뷰 후 수동 이동; 설치/import·gateway consumer·web proxy·test sys.path |
| M4 / pinky-device | `middleware/apps/device/pinky` → `middleware/devices/pinky` | 기존 bringup/profile/description package명 | launch·URDF·image/build·profiles·아래 세 manifest root·장치 closure |
| M5 / omx-device | `middleware/apps/device/omx` → `middleware/devices/omx` | `omx_adapter`, agent/profile identity·ActionPort | Safety 독립 리뷰 후 수동 이동; stop/cancel/HOLD·fresh feedback·entry point·세 manifest root |
| M6 / drive-nav2 | `middleware/core/navigation` → `middleware/control/drive/planning/nav2` | 기존 navigation ROS package명 | launch/config/map/rviz/CMake install·bringup·image·package share 경로 |
| M7 / 책임 추출 | `core/services`, `gateway` 조합 → CORE common + Drive/Arm holder | 기존 import 호환·generation/lock/transaction | CORE 계획 P0–P4/A1–A2의 characterization·port 분리 선행. 이동 도구로 통째 이전 금지 |
| M8 / perception 정리 | `perception/control` 내 sensing/vision → 책임별 인지 | sensor-provider compatibility | 실소비자·dynamic imports·legacy wrappers 확인. operational publisher 부활 금지 |
| M9 / world·prediction | 기존 World/Decision/Situation → 추가 소비자가 필요한 holder | 관측/확정 사건과 예측의 별도 계약 | 실제 두 번째 소비자, revision/frame/stale/conflict, action-conditioned offline replay; 빈 폴더 생성 금지 |

`pinky/description`과 `omx/adapter,agent`는 현재 실재하는 패키지다. 목표 개요의 `binding`으로 이름만 합치지 않는다. 공통 책임을 추출한 뒤에만 binding 배치를 결정한다. `sim` 장치 holder는 새 실제 소비자/장치 계약을 감사한 뒤 후속 단위로 추가한다.

## M0. 계획과 ADR을 먼저 고정한다

1. D-625와 ADR index를 같은 커밋에 기록한다. 3단계 개요/최대 5단계 책임, package 깊이 예외, 세계 상태/행동 예측의 구분을 명시한다.
2. `tools/harness/platform_structure_moves.json`에 위 네 **전체 holder 이동**만 등록한다. 분할·신규 기능 단위는 넣지 않는다. 각 단위는 source/target, 유지할 package, 반드시 볼 consumer, Safety 수동 검토 여부를 가진다.
3. 기존 [전체 구조 설계](2026-10-11-rosy-platform-identity-and-structure-design.md)와 [CORE 계획](2026-10-11-core-responsibility-and-driving.md)을 연결한다. root 제품 문구/현재 구조 설명은 실제 이전 전에 현재 사실을 유지한다.

**완료:** 이름·이전 단위·현재와 목표 차이·실행 권한·비용·검증·복구가 문서에 있다. 계획은 제품 이동 증거가 아니다.

## M1. 먼저 도구 실패 시험을 만든다

**파일:** `test/test_structure_move.py`.

Synthetic Git repository의 등록된 non-main worktree에서 실제 Git 파일 이동을 시험한다. preview 무변경/consumer 검출, 선택 단위 이동·바이너리/문서 보존·참조 미수정, dirty/index/target 충돌, main·stale HEAD·path escape·symlink, source의 untracked/ignored 파일, Safety 단위 거절을 검사한다. pytest는 노트북에서 실행하지 않는다. 시험 커밋을 원격 전송하여 구현 전 RED를 기록한다. 의도된 RED를 기존 known failure에 추가하지 않는다.

## M2. 최소 이전 도구를 구현·검증한다

**파일:** `tools/harness/structure_move.py`, `tools/harness/platform_structure_moves.json`.

- `python tools/harness/structure_move.py core-api`는 HEAD·이전표·파일 수·검출한 consumer와 manual checklist를 JSON으로 출력한다. 출력은 X 관리 세션에 저장한다. 기본 실행은 제품 파일과 index를 바꾸지 않는다.
- `--apply --expected-head <미리보기의 전체 SHA>`만 물리적 이동한다. 실행 위치는 `<repo>/.worktrees/<topic>`의 Git 등록 worktree이며 브랜치는 non-main이어야 한다. 적용 전 HEAD·전체 status·source/target·tracked 파일/실제 파일·link/경계 검사를 다시 한다.
- `git mv`는 선택 holder 하나만 대상으로 하며 Git이 그 이동 경로만 staging한다. 도구는 consumer를 자동 수정하거나 추가 staging/commit/merge/push를 하지 않는다. 출력에 `references_updated: false`와 다음 수정 목록을 남긴다. 이동 후에는 **미완료 이전 후보**다.
- Safety 단위 또는 manifest Safety root/module이 source와 겹치면 적용을 거절한다. API의 `api/v1/safety.py`와 OMX의 owner/stop은 preview만 지원하고 M3/M5의 독립 리뷰 절차로 수동 이동한다. symbol anchor는 기존 package identity를 보존하고 리뷰에서 연결을 검증한다.
- 실제 이동에 새 디렉터리가 필요하면 검증 후 parent만 만든다. 기존 target을 삭제하지 않는다. 실패 시 Git 오류를 그대로 반환하고 현재 상태를 확인한다. 자동 rollback으로 사용자/동료 변경을 덮어쓰지 않는다.

도구 RED→GREEN 후 원격 도구 시험과 `test/test_harness_contracts.py`, `test/test_network_topology_contracts.py`를 실행하고 `known_failures.py`로 비교한다. 실제 네 단위의 preview를 X에 저장하고 제품 tracked 파일과 index가 그대로인지 검사한다. harness generate/lint도 통과해야 한다.

**완료:** 실행 가능한 preview/guarded move 도구, 의미 있는 원격 시험, 현재 트리의 preview 증거. 실제 제품 이동은 0건이다.

## M3–M6. 실제 이전은 한 단위씩 닫는다

1. 실행 요청이 오면 최신 main에서 등록 topic worktree를 만들고 해당 단위 preview를 다시 만든다. `rg`로 source 경로뿐 아니라 package명, 나눠 쓴 경로, 상대 경로, `Path(__file__).parents`, 변수/f-string을 조사한다. scanner의 검출은 완전성 증거가 아니다.
2. preview의 consumer 목록과 아래 **필수 소비자**를 검토한다. target 존재, peer WIP, source의 generated/untracked 파일이 있으면 보존하고 중단한다. 임의 삭제나 stash로 통과시키지 않는다.
3. Safety 없는 단위만 도구 apply로 이동한다. OMX/Safety 단위는 독립 reviewer가 변경 전/후 anchor·stop 동작을 검토한 별도 작업에서 정확한 `git mv`를 한다. 해당 커밋에 `Safety-Review:` trailer를 넣는다.
4. 같은 이전 커밋에서 consumer·packaging·manifest·module 경로를 수정한다. 아래 계약을 만족하기 전 커밋/착지 후보를 완료라고 부르지 않는다.
5. **필수 소비자:** `tools/harness/{platform_parts.yaml,harness.yaml}`, `profiles`, `deploy`의 Docker COPY/compose/native/image/requirements, `.github/workflows`, launch/params/CMake/setup/entry points, tools/remote/release, test fixture/sys.path, 현재 root/module 안내와 API reference의 실제 경로. frozen dependency bytes·Accepted ADR·plans/validation·committed logs는 보존한다. manifest `path` 및 중첩 roots/anchors만 갱신하고 `d427_target`, 기존 `legacy`, import_rules, package/import identity는 유지한다. 새 source 경로 이력은 이 이전표와 새 log 행에 남긴다.
6. `colcon_roots`는 세 part가 유지되므로 무조건 변경하지 않는다. wheel `COLCON_IGNORE`, ament install/package-share, relative links/ancestor 계산은 실제 설치 결과로 확인한다. 문서 생성은 새 module 경로 등록 후 실행한다.
7. 원격 architecture 시험: `test/architecture/test_platform_parts.py`, `test_platform_dependency_boundaries.py`, `test_module_structure.py`, `test_colcon_roots.py`, `test_safety_separation.py`, `test_folder_layout.py`. 관련 module·consumer 시험을 별도 invocation으로 추가하고 duplicate basename을 합치지 않는다. NEW는 별도 main 기준 확인 전 브랜치 실패다.
8. Linux colcon 또는 wheel 설치/import·entry point·launch 로딩을 해당 시험 PC에서 확인한다. ARM64 image closure·장치 API/stop readback·현장 수용은 별도 증거다. 사용자가 착지를 요청했을 때만 `tools/land.py`; push도 별도 요청 이후다.

**각 단위 완료:** paths/refs/packages/manifest/tests/안내가 같은 커밋에서 일치한다. Safety 리뷰가 필요하면 증거가 있다. 설치/ARTIFACT/DEVICE/FIELD의 미확인 항목을 남긴다.

## 복구 절차

preview JSON의 원래 HEAD·source/target·tracked 목록을 X에 보관한다. 적용 뒤 실패하면 먼저 `git status --short`와 `git diff --cached --name-status`로 실제 변경을 확인한다. 공유 main과 peer 파일은 건드리지 않는다.

- **이동만 했고 추가 변경이 없을 때:** 자신의 worktree에서 `git mv -- <target> <source>`로 되돌린다. 부모 경로가 필요하면 원래 source parent만 만든다. target에 다른 파일이 생겼으면 멈추고 분리한다. `git diff --cached --name-status`가 비었는지 확인한다. 빈 parent는 그대로 두어도 된다.
- **참조도 수정했을 때:** 역이동하고 자신의 참조 변경만 역패치한다. 원래 HEAD와 preview 목록에 없는 파일은 복구 대상으로 삼지 않는다. `reset --hard`, `clean`, `stash`, 전체 restore로 되돌리지 않는다.
- **자신의 이전 커밋 이후:** 로컬 topic에서 명시적 역이동/역패치 커밋을 만든다. 착지된 상태라면 최신 main 기반 별도 fix 작업과 동일 검증을 거친다. 장치 rollback은 기존 승인 image로 별도 수행하며 source rollback이 장치 rollback을 증명하지 않는다.

## M7–M9. 경로 이전 이후 책임 추출·world 확장

CORE 계획의 port/admission/취소/guard characterization을 통과한 단위만 추출한다. Drive의 planning/tracking/recovery/곡률 envelope와 Arm의 joints/gripper/limits/workspace를 별도 책임으로 만들면서 기존 writer·generation·budget을 유지한다. process runtime과 action attempt lifecycle은 서로 다른 책임이다.

World State 소비자와 예측 replay 입력 계약을 먼저 연결한다. 이후 한 가지 Drive 또는 Arm 행동 예측을 offline 평가하고 uncertainty/abstention을 검증한다. model provider 선정·학습 job·AI PC 추론·shadow 관찰·실행 활성화는 각각 독립 단계다. world model 출력만으로 복구·goal 완료·Safety 통과를 인정하지 않는다.

## M0–M2 준비 결과

계획/ADR·구현 전 시험은 `e98e0aeed`, 도구는 `360093ecc`, 거절 원인과 tracked link 시험 보강은 `f2f9945c7`에 기록했다. 구현 전 원격 RED에서 도구가 없어 12 NEW였으며 known failure 목록에 넣지 않았다. `f2f9945c7`의 모델 PC 원격 도구/harness/network 계약은 144 성공 표시·exit 0, known_failures 0 NEW/0 known이다. 기존 freshness warning은 별도이며 제품 gate는 올리지 않았다.

실제 Windows 트리 preview는 아래와 같다. 참조 수는 scanner의 검출 건수로, 역사적 `d427_target`·시험 fixture 같은 검토 후 유지할 참조도 포함한다. completeness나 수정 완료 건수가 아니다.

| 단위 | tracked 파일 | 참조 검출 | Safety 자동 이동 차단 |
|---|---:|---:|---|
| core-api | 74 | 73 | Safety module 1개 및 명시적 수동 단위 |
| pinky-device | 97 | 171 | 현재 manifest에는 없음; 장치 설치/stop 검증은 별도 |
| omx-device | 99 | 155 | Safety module 5개 및 명시적 수동 단위 |
| drive-nav2 | 49 | 51 | 현재 manifest에는 없음; 최종 writer 계약은 별도 |

preview 전후 전체 tracked byte hash와 Git status/index가 같음을 확인했다. 제품 이동 0건이다. 결과와 원격 로그는 X 관리 세션 `2026-10-11--001305--core-responsibility-plan--66d72e`의 `evidence/structure-preview`, `logs/structure-move-{red,green,final}`에 보관한다. 자동 참조 치환·Windows 실제 이동·실제 패키지 설치·ARM64 이미지·장치·현장 수용은 검증하지 않았다.

## 2026-10-11 실행 결과 — CORE Drive 우선

위 준비 결과 이후 사용자 실행 요청에 따라 D-626 M3–M6의 네 holder를 실제 작업 브랜치에서 이전했다. 이어 CORE drive 우선 요청에 따라 D-627로 M7의 첫 조립 단위를 먼저 수행했다. API/OMX Safety와 Pinky/Nav2 및 CORE 조립은 각각 독립 source 리뷰를 통과했다. 현재 배치에는 `layout_target`을 쓰고 `d427_target`은 frozen ownership identity로 유지한다.

| 단계 | 현재 결과 |
|---|---|
| M3–M6 | 소스 이전·참조/CI/packaging/harness 갱신·관련 원격 회귀 완료 |
| M7 첫 조립 | CORE `drive/line_follow.py`, `drive/docking.py` 분리, 공개 service/import 호환 및 listener 순서 유지 |
| Python 설치 | CORE/API/Pinky bringup/OMX adapter 실제 Linux wheel build/install 및 package/entrypoint/share 확인 완료 |
| M7 나머지·M8·M9 | 알고리즘 추출·인지 정리·world/prediction 확장은 미실행 |
| Jazzy/ARM64/장치/현장 | 새 후보에 대해 미확인; source 시험으로 대체하지 않음 |
| main/원격/배포 | topic commit만 생성. 착지·push·운용 활성화 미실행 |

CORE 전체 후보 `5faad3583`의 원격 2575 성공·10 skip, feature 1675 성공, architecture/harness/Safety 272 성공, OMX 532 성공·3 skip을 확인했다. 각 성공 실행의 known_failures는 0 NEW/0 known이며 중간 RED/경로 오류도 보존했다. [실제 책임 구조](../reference/core-drive-responsibilities.md), [세부 결과](../validation/d626-holder-migration-2026-10-11/result.md), [Drive 우선 계획](2026-10-11-core-drive-composition-first.md)을 참조한다.

## 2026-10-11 추가 실행 — D-628·D-630 현재 후보

위 상태와 시험 수치는 각 당시 SHA의 역사적 기록이다. 이후 사용자의 전체 나머지 폴더 실행 요청에 따라 아래 실제 소스 책임을 추가로 정리했다. 새 후보의 전체 회귀·착지 판정은 검증 기록 확정 대기이며 이전 후보의 GREEN을 승계하지 않는다.

| 단계 | 현재 소스에서 수행한 범위 | 남는 경계 |
|---|---|---|
| M7 주행 경계 | D-628 mode/input epoch·불변 후보·정책 전후 동일성 검사, line profile→traffic→동적 곡률 제한, fresh 복구 답변, KTURN reverse sweep | 같은 NAV mode의 모든 외부 producer/goal identity admission은 D-442 후속 |
| M7 추가 조립 | `core/drive/traffic.py`, line manager 생성 helper, `core/system/power.py`; 기존 parser export·data path·observer start·service callback 상대 순서 유지 | 새로운 runtime/container/registry 없음; D-628 invalidation listener prefix는 의도적 별도 변경 |
| M8 sensing/vision | `middleware/perception/sensors/sensing`, `vision/perception`에 실제 구현 분리 | 기존 ROS `control`·`control.sensing*` provider/import/share identity 유지 |
| M8 Control Drive | `middleware/control/drive/{safety,tracking,recovery,calibration,planning/grid}`에 기존 알고리즘 분리 | 동일 `control.control.*`, `control.planning/wander/safety` identity. CORE feature 알고리즘과 Arm owner를 통째 이전하지 않음 |
| M9 현재 World | pure Fleet MapPose를 `operations/world/src/rosy/world/state/projections/map_pose.py`로 이전, Fleet identity alias와 실제 service/trip/swarm 소비 유지 | 관측/odom 현재 상태 projection이며 action-conditioned 미래 예측이 아님 |
| M9 Situation | 기존 analyzers와 incident context/vision을 책임별 source holder로 분리 | fact-only shadow·기존 module/patch identity·service 소비자 유지 |
| 전체 root 점검 | [85개 현재 manifest root의 실제 책임·패키지·유지/이전/분리/보류 판정](../reference/platform-folder-responsibilities.md)과 현재 module/root 안내 갱신 | contracts/learning/skills/execution/UI/support 및 Gazebo package ownership 유지 이유 기록 |

source-mode facade와 실제 설치는 구분한다. `control` 배포는 정적 source holder mapping과 self-contained sdist snapshot을 사용하고, World wheel은 checkout 밖 독립 import 대상이다. Docker/context/workflow·source path·G2 origin/digest·영향 시험 소비자를 현재 holder에 맞춰 연결했다. 이 소스 연결이 ARM64 image나 현장 runtime readback을 대신하지 않는다.

[기존 D-628 독립 Safety 리뷰](../validation/d628-core-drive-2026-10-11/safety-review.md)는 source 범위다. 전체 remote/known_failures·구조/harness/Safety·설치 결과와 main 착지 결과는 [확정한 검증 기록](../validation/d630-platform-holders-2026-10-11/result.md)에서 확인한다. 이 추가 기록은 push·배포·live 활성화 결과를 선언하지 않는다.

미래 `operations/prediction/world_model`과 대응 학습·독립 평가는 계획으로 남는다. state/action/horizon/model revision·uncertainty/만료·실제 decision 소비자가 연결되기 전에는 빈 holder를 만들지 않는다. ACT policy 연구를 World rollout으로 이름만 바꾸지 않는다. Fleet decision/Console과 장치 demonstration carve는 현재 transaction/package 소비자 결합을 유지하며 보류 이유를 전체 root 안내에 기록했다.

## 2026-10-11 폴더 단계 착지

위의 초기 후보·미실행 표는 당시 SHA의 이력이다. 이후 채택한 M7 조립·M8·M9 실제 holder 이동과 소비자 수정은 `7f391fa2d`로 local main에 반영했다. 85개 root 판정과 빈 제품 폴더 0개 확인을 마쳤으며, 보류한 패키지 carve와 미래 모델은 완료로 집계하지 않는다. 사용자의 최신 순서에 따라 이동·커밋·머지를 먼저 끝내고 설명 수정을 후속 commit으로 분리했다. [검증 기록](../validation/d630-platform-holders-2026-10-11/result.md)은 RED와 수정 후 362 passed, local main 착지와 남은 CI·ROS·장치 gate를 구분한다.

D-637 후속: 이전에 보류했던 Decision/Console은 기존 Fleet 배포를 유지하며 source holder 분리를 완료했다. Learning 214파일을 curation/registry/training/evaluation 및 shared test/CLI로 나누고 지원 2파일·퇴역 WSL 6파일을 처리했다. 89개 현재 root가 실제 소스 owner와 대응한다. Gazebo launch/scripts의 별도 배포 carve는 기존 gz_sim resource owner를 유지하는 결정이다; 누락된 이동 과제가 아니다.

## 2026-10-13 · Control 진단 추가 시 크기 독립 재판정

34d73ae77에서 기존 구조 검사의 계산식을 그대로 독립 재검산했다. 테스트 실행·pytest import 없이 측정한 잔류 control은 중복 없는 234개 production 파일·35025줄이다. Nav2와 등록 vision unit 66파일·13431줄은 기존대로 제외했다. 기존 34855보다 170줄 증가했으며 observer 법칙 reader/조립 87, node 4, facade/setup 14, map generator 45, 같은 CommandPolicy의 진단 20줄로 설명된다. runtime의 네 노드는 기존 perception 노드에서 그대로 이동한 것으로 중복·증가가 아니다.

drive_review는 기존 SPLIT 의무를 유지한 재판정을 승인했다. 실제 Drive holder는 runtime을 포함한 여섯 곳이며 배포는 기존 단일 control이다. 개별 파일 예산·등록 unit·+150 재검토 기준·control_sensing/provider/control_safety 배포 분리 의무를 유지한다. 다음 +150 초과 또는 새 owner 도입 때 다시 판정하며 이번 기록을 분리 완료·새 설치 실행·지도 완주 증거로 세지 않는다. 파일별 줄수·SHA inventory는 세션 X evidence의 structure-count-da1.json에 보관했다.

## 2026-10-13 · D-747 S2 source 구조 재심사

후보 f380d7b971에서 authority_review가 pytest import/실행 없이 기존 검사 AST의 production filter, 여섯 Drive holder 및 innermost SIZE_UNITS 제외를 독립 재계산했다. 잔류 control은 중복 없는 234파일·35183줄, 제외하는 등록 vision은 66파일·13431줄, 전체는 300파일·48614줄이다. 중복은 0개이고 Nav2는 기존처럼 control holder 범위 밖이다.

기존 35025 대비 증가 158줄은 같은 safety kernel/admission wiring 150(footprint_sweep 69, command_gate 21, safety adapter node 27, lidar_guard 32, policy_handoff 1)과 S2 source mapping/setup/Gazebo provenance 목록 8(3/2/3)로 설명된다. 이동 14파일은 bytes가 같고 프로세스·dependency·writer·owner가 늘지 않는다. 독립 구조 재심사는 기존 SPLIT 의무를 유지한 baseline 35183 갱신을 승인했다. 파일 600/800 예산, 1000 hard tier, +150 재검토 기준, SIZE_UNITS 및 control_sensing/provider/control_safety 배포분리 의무를 바꾸지 않는다.

이 승인은 D-740 동작 안전, source 설치, runtime 또는 현장 수용이 아니다. S2 첫 원격 실행은 새 실패 3건(동적 source 경로 시험 2, 구조 재심사 기준 초과 1)으로 착지하지 않았다. 경로 시험은 기존 source_path 지도를 사용하도록 고치고 새 후보를 원격 재검증한다. 최종 결과는 [S2 기록](../validation/perception-judgment-s2-2026-10-13/result.md)에 남긴다.
