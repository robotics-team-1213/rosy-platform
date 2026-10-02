# D-413 고정 셀 이전 기준선

**기준 커밋:** `b4a3d518` (2026-10-02, Task 0 시작 시 `main`)

**실행 브랜치:** `refactor/platform-cell-slice`
**범위:** source/local 기준선만. 새 패키지·설치·실행 경로는 아직 적용하지 않았다.

## 작업 현황

| 항목 | main 기준 | 별도 worktree/브랜치 | 다음 동작 |
|---|---|---|---|
| Cell C2 / D-402 | 해석 IK `pose_plan.py`, FK/IK, CELL_TRANSFER 네 phase와 owner 분기 있음. main의 OMX suite 기준선에서 확인 | `feat/rosy-cell-c2-planner`는 현재 main을 포함하고 추가 미착지 변경 없음 | 새 플랫폼 API가 이를 대체하거나 직접 구동하지 않고 adapter 경계를 보존 |
| Cell C3 / Gazebo | 셀 공정 컴파일러와 C2 경로는 있음. 목표 물체를 포함한 완전한 종단 수용은 main에서 확인되지 않음 | `feat/rosy-cell-c3-gazebo` HEAD `f63bb564`; C3/C3b 코드·증거 커밋들이 이 브랜치에만 있음. worktree의 OMX `progress.md`는 미커밋 변경 | 착지 상태·시뮬 증거·미커밋 progress를 소유자와 확인하고 기존 작업 재사용 |
| Fleet C4 / D-403 | 일반 Mission admission/dispatcher/UDS 경로는 있음. Cell Job의 ordered CELL_TRANSFER 접수·재컴파일/스텝 전환은 아직 플랫폼 계획의 검증 대상 | 조사 시점에 독립 C4 구현 worktree 없음 | C3/D-403 잔여 작업을 Task 4에서 구분해 구현 |
| 기존 계약 | `core_common.protocol.schemas`가 공유 protocol 정본. D-18 적용 | 타입별 이관 후보만 계획에 기재 | wire type은 소비자·생산자 변환/호환 증거 없이 이동하지 않음 |
| main 상태 | Task 시작 시 `test/test_module_separation.py`와 D-155 ADR 수정이 타 세션 변경으로 미커밋 | 본 브랜치 worktree는 깨끗함 | 타 세션 파일을 수정·스테이징하지 않음 |

세션 간 브랜치는 main과 다른 시점일 수 있으므로 위 브랜치 상태를 기능 완료로 간주하지 않는다. `ownership.csv`는 첫 이전 경로의 현 소유자·호출자·설치와 롤백 지점을 기록한다.

## 기준선 실행

Windows host, Python 3.14, `-B -X utf8`, 저장소 밖 `X:\DevTemp\rosy-platform-v02`의 pytest temp를 사용했다. 각 suite는 중복 test basename 충돌을 막도록 따로 실행했다.

| Suite | 결과 | 로그 |
|---|---:|---|
| Cell `src/site/cell/test` | 143 passed | X: `rosy-platform-v02-cell.txt` |
| Fleet `src/site/fleet/test` | 1,336 passed, 7 skipped | X: `rosy-platform-v02-fleet.txt` |
| OMX `src/products/omx/adapter/test` | 268 passed, 5 skipped | X: `rosy-platform-v02-omx.txt` |
| 구조 `test/architecture` | 76 passed, 1 skipped | X: `rosy-platform-v02-arch.txt` |

`test/known_failures.py` 각 로그 판정: 0 new, 0 known, 7 listed but not failing. 이 실행 범위에서는 실패가 없었다.

기준선은 source regression만 다룬다. Gazebo ROS-SIM의 완성, ARTIFACT, DEVICE/FIELD는 증명하지 않는다.

## 실패 판정

Fleet 로그와 위 세 완료 로그를 `test/known_failures.py`에 대조한다. 저장소 소유 코드 변경은 없으며, Task 1부터 완료한 경계만 다음 task가 사용한다. 구현 중 실패는 숨기지 말고 main의 사전 등록 실패와 구분한다.
