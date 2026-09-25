---
module: docs
---

# D-231 이동 묶음 실행 계획

**Status:** 2026-09-25 작성. 아직 실행하지 않았다. 기준은 [D-231](../adr/D-231-layered-source-roots-keep-package-names.md)이다.
[2026-09-24-multi-robot-structure.md](2026-09-24-multi-robot-structure.md)의 Task 6–8(옛 `src/hardware`·`src/apps` 경로)은 이 계획이 대체한다. 그 계획의 P4–P7은 그대로 뒤따른다.

**목표:** `src/`를 `contracts / runtime / devices/<계열> / products / hmi / site / sim`으로, `dock/`·`signal/`을 `firmware/`로 옮긴다. 패키지 이름·import·launch·설치된 유닛은 바꾸지 않는다. 동작 변경은 0이다.

## 지켜야 할 것

- 패키지 이름을 바꾸지 않는다. colcon은 `package.xml`로 찾는다.
- 한 단계 = 한 영역 = 한 커밋. 각 커밋은 `git mv`와 그 경로를 부르는 **살아 있는 파일**을 함께 고친다(D-186 §6).
- 기록 문서의 옛 경로는 고치지 않는다: `**/logs.md`, `**/index.md`(생성물은 `generate`로 다시 만든다), `STATUS.md`, `docs/adr/`, `docs/plans/`, `docs/validation/`, `docs/solutions/`(D-226).
- 동작을 고치고 싶은 것이 보여도 이 묶음에서 고치지 않는다. 적어 두고 따로 한다.
- 깊이가 바뀌는 것은 계열 폴더로 들어가는 장치 패키지뿐이다(`src/devices/<pkg>` → `src/devices/<계열>/<pkg>`). 나머지는 영역 이름만 바뀌므로 `parents[N]`을 고치지 않는다.

## 시작 조건

- [ ] `ListAgents`에서 `src/`를 만지는 다른 세션이 없다. 있으면 그 세션이 커밋하고 멈출 때까지 기다린다.
- [ ] 이미지 릴리스 사이다(D-191). 진행 중인 SD·payload 작업이 없다.
- [ ] `git status --short -- src test tools deploy .github`가 비어 있다.

## 모든 단계에 공통인 절차

```bash
# 살아 있는 참조만 찾는다
refs() { git grep -l -F "$1" -- . ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!docs/solutions' \
         ':!**/logs.md' ':!**/index.md' ':!STATUS.md'; }
move() {  # move <old> <new>
  mkdir -p "$(dirname "$2")"; git mv "$1" "$2"
  for f in $(refs "$1"); do sed -i "s#$1#$2#g" "$f"; done
}
check() { git grep -n -F "$1" -- . ':!docs/adr' ':!docs/plans' ':!docs/validation' ':!docs/solutions' \
          ':!**/logs.md' ':!**/index.md' ':!STATUS.md'; }   # 비어 있어야 한다
```

각 단계 끝에서:
1. `check <옛 경로>`가 비어 있다.
2. 옮긴 영역의 `src/<영역>/AGENTS.md`를 만들거나 고치고, 떠난 영역의 AGENTS.md에서 행을 지운다. `src/AGENTS.md` 표를 맞춘다.
3. `tools/harness/harness.yaml`의 모듈 `path`를 고친다. `tools/fix_ament_resource.sh`의 glob에 새 영역을 넣는다.
4. 옮긴 모듈의 `logs.md`에 `- 변경: <새 경로>로 이동, 동작 변경 없음 (D-231)`을 추가한다.
5. `python tools/harness/rosy_harness.py generate`, `python tools/harness/rosy_harness.py lint`(오류 0).
6. 그 단계의 시험 명령이 통과한다.
7. 커밋 `refactor(<영역>): move <패키지들> under src/<영역> (D-231)`.

## 단계 0: 작업 브랜치와 D-196 통합

```bash
cd "f:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git worktree add --relative-paths .worktrees/d231-move -b refactor/d231-layered-move main
cd .worktrees/d231-move
git merge refactor/multi-robot-structure
```

2026-09-25 기준 충돌 15개. 푸는 법:

| 파일 | 푸는 법 |
|---|---|
| `**/index.md`, `**/logs.md`, `docs/index.md`, `docs/logs.md`, `deploy/{index,logs}.md` | logs는 양쪽 항목을 날짜순으로 모두 남긴다. index는 `generate`로 다시 만든다 |
| `test/test_module_structure.py` | 두 쪽을 합친다. 브랜치의 `robots` 영역·계열 규칙 + main의 이후 변경 |
| `tools/harness/harness.yaml` | 두 쪽의 모듈과 `adr_gaps`를 합친다(D-196은 작성됨, 예약 줄 삭제) |
| `.dockerignore` | main의 현재 경로(c8c5c6ac) + 브랜치의 `src/robots` 허용 |
| `AGENTS.md`, `src/AGENTS.md`, `docs/reference/AGENTS.md`, `D-178` | 두 쪽 문장을 모두 반영 |

그다음 D-207에 따라 제품 설정을 제품 영역으로 옮긴다:

```bash
move src/robots/pinky_pro src/products/pinky_pro
git rm -q src/robots/AGENTS.md
```

- `core_common/profile.py`가 찾는 것은 패키지 이름(`pinky_pro`)의 share라서 코드 변경이 없다. 경로 문자열 `src/robots`가 남은 시험·문서는 `move`가 고친다.
- `test/test_target_layout.py`의 `TARGET`에 `"products/pinky_pro": "products/pinky_pro"`를 넣는다.
- `test/test_module_structure.py`의 `DOMAINS`는 이 묶음 동안 **옛 영역 ∪ 새 영역**이다. 패키지 깊이 규칙은 `devices/<계열>/<패키지>`를 허용한다.

시험: `python -m pytest test/ src/core/core_common/test src/products/pinky_pro/test -q`

## 단계 1: `firmware/` (colcon 밖)

```bash
move dock firmware/dock
move signal firmware/signal
```

`dock/`·`signal/`은 흔한 문자열이다. `refs`가 `docking/` 같은 이름을 잡지 않았는지 `git diff --stat`로 본다. 살아 있는 참조는 약 20곳이다(펌웨어 안 문서, `test/`의 도크·신호 계약 시험, 루트 README·AGENTS).
시험: `python -m pytest test/test_dock_contract.py firmware/signal/observer/test -q`, 그리고 신호 계약 시험.

## 단계 2: `contracts/`

```bash
move src/core/interfaces src/contracts/interfaces
move src/core/core_common src/contracts/core_common
```

살아 있는 참조: `interfaces` 5곳, `core_common` 14곳(ci.yml, Dockerfile, `.dockerignore`, `tools/`, fleet 시험).
시험: `python -m pytest src/contracts/core_common/test test/test_robot_runtime.py test/test_module_structure.py -q`

## 단계 3: `runtime/` (가장 크다)

```bash
move src/core/core_features src/runtime/core_features
move src/core/core_events src/runtime/core_events
move src/core/core_api_web src/runtime/core_api_web
move src/core/control src/runtime/control
move src/navigation/navigation src/runtime/navigation
move src/core/core src/runtime/core          # 마지막: "src/core/core" 는 다른 경로의 접두가 아니다
```

살아 있는 참조: `core/core` 약 35곳, `control` 34곳, `core_features` 19곳, `core_api_web` 9곳, `core_events` 8곳, `navigation` 8곳.
순서가 중요하다. `src/core/core`는 `src/core/core_*`의 접두이므로 맨 마지막에 옮긴다. 그때는 `core_*` 경로 문자열이 이미 모두 바뀐 뒤라 치환이 다른 패키지를 건드리지 않는다. 끝나면 `check src/core/core`와 `check src/navigation/`가 비어 있다(`src/core/web_common`은 단계 4).
시험: `python -m pytest src/runtime/core/test src/runtime/core_features/test src/runtime/control/test test/ -q` (CI의 core 스위트 경로도 이 커밋에서 바꾼다).

## 단계 4: `hmi/`

```bash
move src/face/emotion src/hmi/emotion
move src/core/web_common src/hmi/web_common
```

단계 3 뒤라 `src/core/`가 비어야 한다. 살아 있는 참조는 각 7곳이다. systemd 유닛은 설치 경로를 부르므로 바뀌지 않는다. `deploy/`에서 `src/face`를 부르는 곳이 있는지 `check`로 본다.
시험: `python -m pytest src/hmi/emotion/test src/hmi/web_common/test test/test_boot_display.py -q`

## 단계 5: `devices/<계열>/` (깊이 +1)

```bash
for p in bringup sensor_adc lamp_control led; do move src/devices/$p src/devices/pinky_pro/$p; done
move src/devices/imu_bno055 src/devices/common/imu_bno055
move src/products/omx_adapter src/devices/omx/omx_adapter
git grep -nE "parents\[[0-9]\]" -- src/devices
```

- 한 층 깊어졌다. 저장소 루트나 `src`를 `parents[N]`으로 찾는 시험은 N을 1 올린다. 패키지 루트를 뜻하는 `parents[1]`은 그대로 둔다. 하나씩 읽고 고친다.
- 계열 AGENTS: `src/devices/AGENTS.md`(계열 표와 규칙: Pinky 보드 전용은 `pinky_pro`, 여러 차체가 쓰는 칩은 `common`, 팔은 `omx`), `src/devices/{pinky_pro,common,omx}/AGENTS.md`. 옮긴 패키지의 `<!-- Parent: ../AGENTS.md -->`는 그대로 맞다.
- `test_module_structure.py`의 `KNOWN_DIRECTION` 사유 문자열에 적힌 경로를 맞춘다.
시험: `python -m pytest src/devices test/test_bringup_motor_contracts.py test/test_robot_runtime.py test/test_nav2_hardware_slice.py -q`

## 단계 6: `test/architecture/`, `docs/architecture/`

```bash
mkdir -p test/architecture
for t in test_module_structure test_layer_boundaries test_folder_layout test_document_placement test_target_layout; do
  git mv test/$t.py test/architecture/$t.py
done
move docs/concept docs/architecture
```

- 옮긴 시험의 `ROOT = Path(__file__).resolve().parents[1]`은 `parents[2]`가 된다.
- `test/conftest.py`의 `sys.path` 설정이 하위 폴더에도 적용되는지 확인한다. 안 되면 `test/architecture/conftest.py`를 둔다.
- `test_document_placement.py`의 루트 허용 목록은 이 단계에서 바뀌지 않는다.
- `docs/concept`를 부르는 ADR 본문은 기록이라 두고, README와 docs AGENTS만 고친다.
시험: `python -m pytest test/ -q`

## 단계 7: 시험 전환과 확인

- `test/architecture/test_target_layout.py`의 `MOVED = True`.
- `test_module_structure.py`의 `DOMAINS = {"contracts", "runtime", "devices", "products", "hmi", "site", "sim"}`. 옛 영역을 지운다.
- 빈 영역 폴더(`src/core`, `src/face`, `src/navigation`, `src/robots`, `src/apps`)와 그 AGENTS.md를 지운다.

확인(모두 통과해야 main에 넣는다):

```bash
python -m pytest test/ src -q                              # host 전체
python tools/harness/rosy_harness.py lint                  # 오류 0
wsl -d Ubuntu -e bash -c 'rsync -a --delete "/mnt/f/Dev/Control/Robot/ROS/Rosy/Rosy OS/.worktrees/d231-move/src/" ~/rosy_ws_d231/src/ \
  && cd ~/rosy_ws_d231 && rm -rf build install log && source /opt/ros/jazzy/setup.bash && colcon build 2>&1 | tail -5'
```

- colcon: 패키지 수가 이동 전과 같고(현재 20 + `pinky_pro`) 실패 0.
- 2대 sim 벤치를 이동 전과 같은 명령으로 1회 돌려 같은 결과가 나온다.
- payload/이미지 빌드 1회(기존 ARTIFACT 절차). 장치 인수는 기존 게이트로 따로 본다.

## main 반영

```bash
cd "f:/Dev/Control/Robot/ROS/Rosy/Rosy OS"
git status --short                        # 겹치는 미커밋 편집이 있으면 멈추고 주인 세션에 커밋 요청
git merge --no-ff refactor/d231-layered-move -m "Merge branch 'refactor/d231-layered-move' (D-231 layered source roots)"
git worktree remove .worktrees/d231-move
git branch -d refactor/d231-layered-move refactor/multi-robot-structure
```

main이 그 사이 움직였으면 먼저 작업 브랜치에 main을 머지하고 단계 7 확인을 다시 돈다. 머지한 뒤 활성 세션에 새 경로를 알린다.

## 되돌리기

각 단계가 한 커밋이므로 `git revert <커밋>`으로 단계 단위로 되돌린다. main 머지 뒤 문제가 보이면 머지 커밋을 `git revert -m 1`로 되돌리고, 작업 브랜치에서 고친다.
