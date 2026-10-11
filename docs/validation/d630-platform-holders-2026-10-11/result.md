# D-630 폴더 이동·검증·local main 착지

2026-10-11. 브랜치 `feat/platform-structure-migration`. 사용자가 요청한 순서대로 실제 폴더 이동과 경로 수정은 먼저 커밋·머지했고, 설명 수정은 그다음 커밋으로 분리했다.

## 반영 결과

첫 착지는 `b169c24e70571e13b8032e15b5de086b507c385b`, 나머지 소스 착지는 `7f391fa2d223b5e60fdc896ee0588ca93a0d2a78`이다. 둘 다 `tools/land.py`의 local main fast-forward이며 push하지 않았다. 두 번째 착지 직후 main은 origin/main보다 52 commit 앞이었다. 기존 main의 추적되지 않은 세 파일은 그대로 유지했다.

| 실제 책임 | 현재 물리 경로 |
|---|---|
| CORE 외부 API / 조립 / feature / events | `middleware/core/{api,gateway,services,events}` |
| CORE Drive 조립 / 공통 power 조립 | `gateway/core/drive`, `gateway/core/system` |
| Drive backend와 검증 근거 | `middleware/control/drive/{planning,tracking,recovery,calibration,safety}` |
| Nav2 / grid / wander / sensor-only adapter | `drive/planning/{nav2,grid}`, `drive/tracking/wander`, `drive/safety/adapter` |
| sensor evidence / vision / ROS node 조립 | `middleware/perception/{sensors/sensing,vision/perception,control}` |
| 장치별 binding | `middleware/devices/{pinky,omx}` |
| 관측 상태 projection | `operations/world/src/rosy/world/state/projections/map_pose.py` |
| 현재 상황 분석 / incident context·vision | `operations/situation/rosy_situation/{analyzers,incidents}` |

M8은 canonical source 172파일을 이동했고, 그중 평탄한 Drive 알고리즘 50개는 safety 15, tracking 6, recovery 11, calibration 18개다. 기존 `control.*` 설치·import identity는 정적 package mapping과 좁은 source facade로 보존했다. World와 Situation의 기존 module alias도 동일 객체·monkeypatch identity를 보존하며 구현을 복제하지 않는다. Docker/context, workflow, release/model-code closure, G2 source origin/digest와 시험 소비자를 실제 위치에 맞췄다.

현재 manifest 85개 root의 유지·이전·분리·보류 판정과 최대 5단계 의미 구조는 [전체 폴더 안내](../../reference/platform-folder-responsibilities.md)에 있다. 실제 빈 제품·지원 폴더는 0개였다. `data/drive/.gitkeep`는 계약용 placeholder라 유지했다. namespace/resource 내부 깊이를 맞추려고 공개 import나 설치 위치를 바꾸지 않았다.

공유 main readback에서 이전 `middleware/core/api_web`, `middleware/apps/device` 디렉터리는 ignored `__pycache__`·`.omc` 세션 상태 때문에 남아 있었다. 두 경로의 `git ls-files` 결과는 0개이며 제품 구현은 새 경로에 있다. worktree의 제품 폴더 점검과 공유 checkout의 도구 상태를 구분한다. 동료 세션 상태는 AGENTS의 보존 규칙에 따라 그대로 두었다.

`fleet.ai` 10파일과 `fleet.server.web` 66파일은 기존 패키지·transaction·설치 resource 소비자에 묶여 있어 별도 패키지 carve를 보류했다. 행동 조건부 `operations/prediction/world_model`은 구현하지 않았다. 현재 World는 관측·odom 기반 상태 projection이다. 이 두 후속 작업을 이번에 이동 완료한 holder로 집계하지 않는다.

## 시험과 실패 수정

로그 루트는 X 관리 세션 `2026-10-11--001305--core-responsibility-plan--66d72e`다. pytest는 committed SHA를 시험 PC로 보내 실행했고 노트북에서는 실행하지 않았다. 아래 각 성공 로그는 `test/known_failures.py` 비교에서 0 NEW였다.

| SHA / 범위 | terminal 결과 / 세션 내 증거 |
|---|---|
| 첫 소스 착지 `b169c24e` | 4그룹 5,086 / 5,798 / 4,916 / 1,427 passed; `logs/land-m3-m7-retry.txt`의 landed 기록 |
| `d54c75385` 전체 CORE gateway·features | exit 0; `logs/core-full-reentrant-green/run-1.txt` |
| `e26b309bc` 전체 perception | exit 0; `logs/perception-full-green/run-1.txt` |
| `f9fc67c53` 구조·deployment/model-code closure | 258 passed; `logs/platform-closure-retry/run-1.txt` |
| `40af01b63` checkout 밖 CORE wheel·조립 | 7 passed; `logs/installed-composition-retry/run-1.txt` |
| `08d979511` World / Situation | 각각 118 / 69 passed |
| `398728d3c` 착지 도구 회귀 | 34 passed; `logs/land-interrupted-green/run-1.txt` |
| `398728d3c` 자동 선택 3그룹 | 4,333 / 5,016 / 3,907 passed, **2 / 3 / 2 NEW**; `logs/remaining-auto-red/` |
| `7f391fa2d` 실패 소비자 전체와 구조·설치·closure·harness·착지 재검사 | **362 passed, 0 NEW**; `logs/land-folder-final.txt`, `land-folder-final/feat-platform-structure-migration/run-1-1.txt` |

자동 선택의 7 NEW는 옛 Safety/sensor/vision 경로를 읽는 Gazebo·bench·site-role·URDF fixture와 gateway 통합 시험의 소유권 목록 누락이었다. `7f391fa2d`에서 해당 5파일만 고쳤다. 임계값·기하 비교·Safety assertion은 유지했고 새 실패를 known failure로 등록하지 않았다. 독립 source 리뷰가 이를 승인했다. 구현 source가 같은 자동 선택 결과와 수정된 소비자 재검사를 함께 제시하며, 수정 SHA에서 전 시험을 다시 돌렸다고 주장하지 않는다.

자동 선택기는 packaging/workflow 변경에 대해 CI FULL tier가 남는다고 보고했다. 이전의 중단된 CORE/착지 로그는 통과 증거로 쓰지 않는다. watchdog 재진입 deadlock은 bounded RED 후 `d54c75385`에서 수정했고 전체 CORE를 다시 통과했다. 중단 출력이 새 실패 없음으로 잘못 착지하는 문제도 RED 후 `398728d3c`에서 거절하도록 고쳤다.

[CORE Safety 리뷰](../d628-core-drive-2026-10-11/safety-review.md), [holder Safety 리뷰](safety-review.md)는 production Safety의 source 판정이다. source 착지 직전 diff 검사와 Safety commit-range 검사는 통과했고 harness lint는 0 error였다. 설명 문서의 최종 검사는 별도 후속 commit의 착지 로그로 구분한다.

이동 후 설명 commit `fb50866e4`도 remote 문서·harness·literal·scorecard guard 112 passed, known_failures 0 NEW 이후 local main에 착지했다. 증거는 `logs/land-folder-docs.txt`와 `land-folder-docs/feat-platform-structure-migration/run-1-1.txt`다. 위 공유 checkout 상태 설명은 그 착지 이후 확인한 readback이다.

## 남은 증거와 후속 순서

폴더 단계는 합의한 실제 holder 이동·소비자 정리·local main 착지까지 수행했다. 설명 수정 이후의 주행 알고리즘 확장은 별도 작업이다. 모든 NAV 외부 producer/goal identity 통일, Fleet decision/Console carve와 행동 조건부 World model은 후속 계획이다.

원격 push·CI FULL·Jazzy 실행·ARM64 이미지·현장 overlay 배포/readback·실물 및 현장 수용은 이번에 확인하지 않았다. CORE가 최종 Base `cmd_vel` authority이고 Arm writer는 OMX owner라는 경계를 유지한다. 모델이나 자동 복구를 현장에 활성화하지 않았다. `map_v2_fleet`와 `260919 MAP FILE.STL`의 기존 lineage를 유지했다.
