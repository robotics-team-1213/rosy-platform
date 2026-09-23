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

시험은 `test/test_folder_layout.py`다. 모듈 벤치와 bringup이 설치하는
스크립트는 그 모듈에 남긴다.

## Task 2: 루트와 패키지 안의 어긋난 스크립트

**Files:** `fix.sh`, `run_fleet_sim.sh`, `src/core/core/deploy/install.sh`,
`src/apps/control/tools/gz/run_track260905.sh`, 그 경로를 적는 문서와 호출부

1. `fix.sh`는 `tools/fix_ament_resource.sh`로 옮겼다. 저장소 루트는 스크립트
   위치에서 계산한다.
2. `run_fleet_sim.sh`는 `tools/run_fleet_sim.sh`로 옮겼다. 실행 시 저장소
   루트로 이동한다.
3. `src/core/core/deploy`는 제거했다. 제품 유닛은 `deploy/robot/native`에
   이미 있으므로 옛 유닛을 옆에 복사하지 않는다.
4. `run_track260905.sh`는 control 모듈의 벤치가 실행하고 시험하므로
   `src/apps/control/tools/gz/`에 남긴다.

## Task 3: bringup 환경 스크립트

**Files:** `src/hardware/bringup/scripts/rosy_env.sh`, 그 파일을 source하는 곳

1. `rosy_env.sh`는 bringup이 설치하고 DDS 계약 시험이 그 경로를 본다.
2. 개발 PC의 `env.sh`와 역할이 다르므로 `src/hardware/bringup/scripts/`에 둔다.

## Task 4: deploy/robot 평탄화는 나중

검증 스크립트와 개발 오버레이 스크립트를 하위 폴더로 나누는 일은 이 계획의
1–3이 끝난 뒤의 별도 변경이다. 그 변경은 `deploy/robot/*.sh`와 `*.ps1`를
읽는 시험·문서 경로를 같은 커밋에서 고친다.

## 착지 후 확인

```text
python -m pytest test/test_folder_layout.py test/test_run_data.py -q
python tools/harness/rosy_harness.py lint
```
