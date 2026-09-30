## D-362 파일 크기 예산은 코드 유형별 단일 게이트가 지킨다 — 생산 `.py`/`.cpp`/`.hpp`/`.sh` 600줄, 웹 자산 `.js`/`.html`/`.css` 800줄, 1000줄 초과 파일은 성장 허용량 0; 게이트는 `src/` 패키지와 `deploy/`·`tools/`·`firmware/`까지 본다. 줄 수는 분할 근거가 아니라 `split`/`accept` 판정 의무의 트리거다 (X1 계승, D-168 P6 확장)

**Status:** Accepted (2026-09-30, 정책·게이트 범위만; 시험 코드·데이터 파일 면제, 분할 실행은 별도 변경). D-168 P6의 예산 체계를 유형별로 확정하고 게이트 커버리지를 전 생산 코드로 넓힌다. P0–P2 대기열은 같은 날 전량 실행 완료(아래 도입 판정).

잇는 결정: D-168(모듈 구조 표준과 P6 크기 판정) · [2026-09-06-module-split-criteria.md](../plans/2026-09-06-module-split-criteria.md)의 X1 반기준과 D-168 P6 각주 · D-262(대시보드 로컬 웹 예산 스캔 — 이 결정으로 통합됨) · D-23(정적 대시보드·무빌드) · D-359(토큰 구조) · D-7(React+Vite 기각 유지).
게이트: [`test/architecture/test_module_structure.py`](../../test/architecture/test_module_structure.py). 계획·대기열: [2026-09-30-file-size-budget-and-refactor-queue.md](../plans/2026-09-30-file-size-budget-and-refactor-queue.md).

### Context

1. 사용자 요구(2026-09-30): "코드 유형별로 줄 수 기준을 두고, 넘어가면 리팩토링 대상으로 쪼갠다."
2. 저장소에는 이미 그 기제가 있었다 — D-168 P6: 생산 파일 600줄 초과 시 `SIZE_VERDICTS`에 `split:`/`accept:` 판정 기록 의무, set-equality 시험으로 누락·부실화 감지, 성장 허용량 +150줄.
3. 그 게이트의 커버리지 구멍(같은 날 측정):
   - **웹 자산(`.js`/`.html`/`.css`) 무스캔.** 저장소 최대 파일 `runtime/sensing/web/diagnostic.html` 1857줄이 게이트 밖에서 자유롭게 자랐다.
   - **`src/` 밖 생산 코드 무스캔.** `deploy/`·`tools/`·`firmware/`의 운영 스크립트들이 무판정이었다.
   - **D-262의 로컬 웹 스캔 부실.** dashboard 패키지 소속 600줄 스캔이 `map-view.js` 612줄 무판정 커밋(e89e09e1)을 못 잡고 있었다.
4. X1("줄 수는 분할 근거가 아니다")과의 긴장. 줄 수 상한을 새로 만들어 그것만으로 쪼개면 반기준 위반이다. 대신 "예산 초과 = 판정 의무"라는 기존 구조를 그대로 계승하고 커버리지만 확장한다.

### Decision

1. **예산표** — 물리 줄(공백·주석 포함, 게이트 측정과 동일):

   | 유형 | 범위 | 예산 |
   |---|---|---|
   | `.py`/`.cpp`/`.hpp`/`.sh` | `src/` 패키지 생산 코드 | 600 |
   | `.py`/`.sh` | `deploy/`·`tools/`·`firmware/` | 600 |
   | `.js`/`.html`/`.css` | `src/` 패키지 웹 자산 | 800 |
   | 모든 유형 | 파일 > 1000줄 | 성장 허용량 **0** |

2. **면제.** 시험 코드(X4 — 커버리지는 부채가 아니다), 데이터 파일(`.yaml` 맵·그래프, `.sql`), 비생산 트리(`reference/`, `private/`, `build/`, `install/`, `log/`, `.worktrees/`).
3. **판정 의무, 분할 명령 아님.** 예산 초과 파일은 `SIZE_VERDICTS`에 `split:` 또는 `accept:` 중 하나로 기록된다. set-equality 시험이 누락·부실 판정을, 재판정 규칙이 무단 성장을 각각 잡는다.
4. **1000줄 초과 등급.** 판정 시점과 현재 중 하나라도 1000줄을 넘는 파일은 성장 허용량이 0이다. 패키지 예산(10,000줄)의 허용량은 종전대로 +150.
5. **웹 자산은 패키지 총계에 합산한다.**
6. **분할은 별도 변경이고 무빌드를 유지한다.** 웹 자산 분할은 네이티브 ES 모듈 또는 다중 `<script>`/`<link>` 태그로만 한다(D-23; D-7 방향 유지 기각). CSS 분할은 캐스케이드 순서를 보존해야 한다.
7. **D-262 로컬 웹 스캔은 통합된다.** 상위 집합인 아키텍처 게이트가 웹 예산을 소유하고, 로컬 파일은 인수 시험(게이트가 실제로 커버하는지)으로 남는다.

### 도입 판정 (2026-09-30, 전량 실행 완료)

- **P0 실행:** fleet `app.py` 1556 → 476 + 라우트/인증/정적 모듈 8개(전부 예산 내); 캘리브레이션 클러스터 → ROS-free `calibration_sequence.py`(510) + 노드 584/583. `SIZE_VERDICTS`에서 해당 항목 제거.
- **P1 실행:** `app.js` 1338 → 745 + `telemetry.js`(419)·`teleop.js`(128)·`state-socket.js`(111);
  `styles.css` 1119 → 492 + `console-detail.css`(637, 캐스케이드 순서 보존 꼬리 분할).
  `runtime/sensing/web/diagnostic.html`(1857)은 **accept로 재판정** — 단일 HTML·단일 IIFE가 `web/AGENTS.md`에 기록된 의도된 설계이고 D-150 디버그 전용면이라, 분할은 그 계약을 깨는 대가로 줄 수만 줄인다.
- **P2:** 운영 스크립트 7개 전부 accept(단일 진입·원자성·단독 실행, X5).
- 덤으로 D-262 로컬 웹 예산 게이트가 map-view.js 612 커밋으로 이미 부실해 있었음을 발견 — D-362 아키텍처 게이트(상위 집합)로 통합하고 인수 시험으로 남긴다.

### Alternatives

- **1000줄 단일 상한(원 요구 그대로).** 기존 600줄 게이트를 약화시키고 웹 자산·운영 스크립트의 특성을 무시한다. 기각.
- **줄 수 자체를 분할 근거로 삼는다.** X1 위반. 85줄 `waypoints/manager.py`가 패키지이고 511줄 `docking/manager.py`가 올바르게 한 파일인 저장소에서 근거가 없다. 기각.
- **루트별 차등(deploy는 800 등).** 같은 언어에 다른 규칙은 설명 비용만 늘린다. 유형별로만 나눈다. 기각.
- **게이트 확장 없이 문서만 둔다.** diagnostic.html은 게이트 밖에서 계속 자란다 — 이번 조사의 출발점이 된 결함. 기각.

### Consequences

- 게이트가 웹 접미사와 운영 루트를 스캔한다. 변이 증명 3종으로 실제 적발을 확인했다: deploy 601줄 신규 파일과 map-view.js 812줄은 "needs a verdict"로, task_store.py 1062줄은 "grew past 1060+0"으로 각각 red 적발 후 복구 green.
- 예산 초과 파일 22개가 0개가 됐다 — 기록된 split 판정은 전량 실행, 나머지는 근거 있는 accept(성장 허용량 0 포함).
- 분할 실행 검증: fleet 전체 920 passed, 캘리브레이션 계열 234 passed + 갱신/신규 시험, dashboard 브라우저 회귀(Chromium) 70 passed.
- 동시 세션 교훈: 이 결정의 게이트 확장과 대기열 실행이 같은 날 공유 체크아웃의 다른 세션 작업과 교차하며 한 번 작업 트리를 잃었다 — 복구 후 소규모 커밋으로 보호했다. 공유 체크아웃 규칙(커밋 전 `git status` 전수 확인)의 근거가 됐다.

**References:** D-168, D-23, D-7, D-150, D-262, D-359, X1/X4/X5(2026-09-06-module-split-criteria.md), `test/architecture/test_module_structure.py`, `docs/plans/2026-09-30-file-size-budget-and-refactor-queue.md`.
