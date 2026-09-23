## D-186 스크립트와 수집 데이터는 주인 폴더에만 둔다

**Status:** Accepted (2026-09-24). 루트 셸은 `env.sh`만 남았다.
모듈이 시험하는 벤치 스크립트와 패키지가 설치하는 스크립트는 그 모듈에 둔다.

**Context:** D-168은 `src/<domain>/<package>/` 안의 ROS 패키지 모양을 정한다.
패키지 밖 실행 파일은 그 규칙에 없다. 지금은 저장소 루트, `src/core/core/deploy`,
`src/apps/control/tools/gz`, `deploy/robot` 한 줄, `docs/validation` 증거가
같은 종류의 일을 한다. 텔레옵으로 확인한 기록과 주행 기록도 소스 트리에
들어가면 커밋과 설치물이 섞인다.

**Decision:**

1. **네 주인만 둔다.**
   - `deploy/` — 로봇, 이미지, SD에 들어가는 설치·검증·릴리스 절차.
   - `tools/` — 개발자가 워크스페이스에서 반복하는 절차.
   - 패키지의 `scripts/` — 그 패키지가 설치해서 실행하는 파일만.
   - `data/teleop`과 `data/drive` — 텔레옵으로 확인하고 적은 기록, 그리고
     주행 궤적과 bag. 세션 파일은 git에 넣지 않는다.
     학습용으로 남기는 영상만 `data/teleop/learning/`에 커밋한다.
2. **루트에 남는 셸은 `env.sh`뿐이다.** `source env.sh`가 개발 PC의 ROS와
   워크스페이스를 읽는 진입점이다. 그 외 루트 스크립트는 `tools/`로 간다.
3. **모듈이 시험하고 설치하는 파일은 그 모듈에 둔다.**
   `control/tools/gz/run_track260905.sh`는 control 벤치가 실행하고 시험한다.
   `bringup/scripts/rosy_env.sh`는 bringup이 설치하는 로봇 환경이다.
   개발 PC용 `env.sh`와 겹치지 않는다.
4. **모듈 게이트 문서는 모듈 루트에만 둔다.** `progress.md`, `logs.md`,
   `index.md`는 `tools/harness/harness.yaml`에 등록된 모듈 경로에만 있다.
   모듈 안의 설명 문서는 그 모듈의 `docs/`에 두고, 저장소 결정과 실행 계획은
   `docs/adr`와 `docs/plans`에만 둔다. `data/`의 문서는 `README.md`뿐이다.
5. **측정 증거 스크립트는 그 측정 폴더에 남긴다.** `docs/validation/**/evidence`
   의 셸은 그날 기록의 일부다. 현재 기동법으로 쓰지 않는다.
6. **`deploy/robot/`를 역할별로 나누는 일은 참조를 같은 변경에서 고친다.**
   파일만 옮기고 문서·시험의 경로를 남기지 않는다.
7. **옛 `src/core/core/deploy` 설치기는 제품 유닛과 겹치므로 두지 않는다.**
   제품 `rosy-core.service`는 `deploy/robot/native`다.

**Alternatives:** 스크립트를 모두 `deploy/`에 두기 — 개발 PC용 일회 실행과
로봇 설치가 한 폴더가 된다. 수집 데이터를 `docs/validation`에 두기 — 확인
메모와 측정 증거가 섞인다.

**Consequences:** 새 `.sh`와 `.ps1`은 위 네 주인 중 하나에만 추가한다.
루트에 스크립트를 더 두지 않는다. 텔레옵 확인과 주행 기록은 `tools/run_data.py`가
`data/teleop`과 `data/drive` 안에만 만든다.

**Validation:** `test/test_folder_layout.py`와 `test/test_run_data.py`.

**구현·처리 계획:** [2026-09-24-folder-layout.md](../plans/2026-09-24-folder-layout.md).
