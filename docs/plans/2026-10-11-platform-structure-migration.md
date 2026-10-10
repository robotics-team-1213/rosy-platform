# ROSY Platform Structure Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** D-625의 의미 기반 구조를 한 번에 옮기지 않고, 검토 가능한 이전 단위·소비자 목록·실행 도구·복구 절차로 준비한다.

**Architecture:** 기존 D-427 part/import 규칙과 최종 writer를 보존한다. 도구는 선택한 holder의 파일 이동과 참조 보고만 담당한다. 참조 자동 치환은 설치 경로·소유권 ID·과거 기록을 오인할 수 있어 기존 `d427_move.py`의 scanner만 재사용한다. 물리적 이동 완료와 책임 추출 완료는 다른 판정이다.

**Tech Stack:** Python stdlib, 기존 `_legacy_paths.LegacyScan`, Git, JSON 이전표, 원격 pytest, 기존 harness/architecture 계약.

**상태:** M0–M2 준비 완료, M3–M9 미실행, 2026-10-11. 기준 `f14070a59`, 브랜치 `feat/platform-structure-migration`. 사용자는 구조 방향과 ADR·계획·도구 작성을 요청했다. 실제 제품 이전 M3 이후는 실행하지 않았다.

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
