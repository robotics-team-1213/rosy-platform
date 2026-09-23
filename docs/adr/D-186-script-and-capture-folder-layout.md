## D-186 스크립트와 수집 데이터는 주인 폴더에만 둔다

**Status:** Proposed (2026-09-24). `data/teleop`과 `data/drive`는 이미
만들어져 있다. 어긋난 스크립트를 옮기는 일은
[실행 계획](../plans/2026-09-24-folder-layout.md)이 한다.

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
2. **루트에 남는 셸은 `env.sh`뿐이다.** `source env.sh`가 개발 PC의 ROS와
   워크스페이스를 읽는 진입점이다. 그 외 루트 스크립트는 `tools/`로 간다.
3. **패키지 안 벤치·설치 스크립트는 패키지 소유가 아니다.** 캘리브레이션
   트랙 재현은 `tools/gz/`다. systemd 설치는 `deploy/robot/`다.
4. **측정 증거 스크립트는 그 측정 폴더에 남긴다.** `docs/validation/**/evidence`
   의 셸은 그날 기록의 일부다. 현재 기동법으로 쓰지 않는다.
5. **`deploy/robot/`를 역할별로 나누는 일은 참조를 같은 변경에서 고친다.**
   파일만 옮기고 문서·시험의 경로를 남기지 않는다.

**Alternatives:** 스크립트를 모두 `deploy/`에 두기 — 개발 PC용 일회 실행과
로봇 설치가 한 폴더가 된다. 수집 데이터를 `docs/validation`에 두기 — 확인
메모와 측정 증거가 섞인다.

**Consequences:** 새 `.sh`와 `.ps1`은 위 네 주인 중 하나에만 추가한다.
루트에 스크립트를 더 두지 않는다. 텔레옵 확인과 주행 기록은 `tools/run_data.py`가
`data/teleop`과 `data/drive` 안에만 만든다.

**Validation:** 구현 전. 경로 래칫이 루트 셸을 `env.sh`로 한정하고, 패키지
안의 벤치 셸과 `src/**/deploy/*.sh`가 0건이면 이 결정을 Accepted로 올릴 수 있다.

**구현·처리 계획:** [2026-09-24-folder-layout.md](../plans/2026-09-24-folder-layout.md).
