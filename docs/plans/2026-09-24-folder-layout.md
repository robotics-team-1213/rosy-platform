---
module: docs
---

# 스크립트와 수집 폴더 실행 계획 (D-186)

결정: [D-186](../adr/D-186-script-and-capture-folder-layout.md).

시험이 먼저다. 파일을 옮긴 변경은 그 경로를 읽는 문서와 시험을 같이 고친다.
`deploy/image`, `deploy/sd`, `deploy/robot/native`, `docs/validation/**/evidence`는
이 계획에서 옮기지 않는다.

이미 있는 것: `data/teleop`, `data/drive`, `data/README.md`, `tools/run_data.py`,
`test/test_run_data.py`. 세션 파일은 gitignore된다.

## Task 1: 경로 래칫

**Files:** `test/test_folder_layout.py`

1. 실패하는 시험: 저장소 루트의 `*.sh`는 `env.sh`만이다.
2. `src/**/deploy/*.sh`와 `src/apps/control/tools/gz/*.sh`는 0건이다.
3. `data/teleop`과 `data/drive`가 있고, `tools/run_data.py`가 그 두 종류만 만든다.
4. `docs/validation` 안의 `*.sh`는 `evidence/` 아래에만 있다.

이 시험은 Task 2 전에는 적색이다. 적색을 목록 예외로 바꾸지 않는다.

## Task 2: 루트와 패키지 안의 어긋난 스크립트

**Files:** `fix.sh`, `run_fleet_sim.sh`, `src/core/core/deploy/install.sh`,
`src/apps/control/tools/gz/run_track260905.sh`, 그 경로를 적는 문서와 호출부

1. `fix.sh`는 `tools/fix_ament_resource.sh`로 옮긴다. 절대 경로 `/mnt/f/Dev/...`를
   빼고, 스크립트 위치에서 저장소 루트를 계산한다.
2. `run_fleet_sim.sh`는 `tools/run_fleet_sim.sh`로 옮긴다. 맵 인자는
   `src/sim/gz_sim`이 고르는 경로를 받게 하고, 스크립트 안에 control 맵을
   직접 적지 않는다.
3. `src/core/core/deploy/install.sh`와 옆의 유닛 파일은 `deploy/robot/`로
   옮긴다. 주석의 `src/core/deploy/install.sh` 경로는 새 경로로 고친다.
   네이티브 설치가 이미 같은 유닛을 깔면 이 파일은 옮기지 않고 제거하고,
   그 사실을 시험과 문서에 적는다.
4. `run_track260905.sh`는 `tools/gz/run_track260905.sh`로 옮긴다.
   호출부와 주석의 패키지 경로를 새 위치로 고친다.

## Task 3: bringup 환경 스크립트

**Files:** `src/hardware/bringup/scripts/rosy_env.sh`, 그 파일을 source하는 곳

1. 저장소 안에서 `rosy_env.sh`를 source하는 곳을 찾는다.
2. 호출이 없으면 파일은 패키지 설치물이 아니다. `deploy/robot/`의 신원
   설명으로 안내를 옮기고, 스크립트는 제거한다.
3. 호출이 있으면 그 호출이 로봇 설치 절차인지 확인한다. 설치 절차이면
   `deploy/robot/`로 옮기고 bringup의 설치 목록을 같이 고친다.

## Task 4: deploy/robot 평탄화는 나중

검증 스크립트와 개발 오버레이 스크립트를 하위 폴더로 나누는 일은 이 계획의
1–3이 끝난 뒤의 별도 변경이다. 그 변경은 `deploy/robot/*.sh`와 `*.ps1`를
읽는 시험·문서 경로를 같은 커밋에서 고친다.

## 착지 후 확인

```text
python -m pytest test/test_folder_layout.py test/test_run_data.py -q
python tools/harness/rosy_harness.py lint
```
