# 파일 크기 예산과 리팩토링 대기열

**날짜:** 2026-09-30
**상태:** 승인 — **ADR D-362**로 채택 (`ROSY ADR Log.md`). P0–P2 실행 완료.
**부모 정책:** [2026-09-06-module-split-criteria.md](2026-09-06-module-split-criteria.md) X1·D-168 P6 각주(D-362로 재갱신), [`test/architecture/test_module_structure.py`](../../test/architecture/test_module_structure.py) P6 게이트
**측정 기준:** 물리 줄(공백·주석 포함) — P6 게이트와 동일한 측정. 측정일 2026-09-30, Windows 호스트.

## 1. 배경

"코드 유형별로 줄 수 기준을 두고, 넘어가면 리팩토링 대상으로 쪼갠다"는 요구. 조사 결과
저장소에는 이미 그 기제가 있었다 — **D-168 P6**: 생산 파일 600줄 초과 시 `SIZE_VERDICTS`에
`split:`/`accept:` 판정 기록 의무, set-equality 시험으로 누락·부실화 감지, 성장 허용량(+150줄)
초과 시 재판정.

문제는 기준이 아니라 **커버리지 구멍** 두 개였다:

1. **웹 자산(`.js`/`.html`/`.css`)은 스캔 대상이 아니었다.** 저장소 최대 파일인
   `runtime/sensing/web/diagnostic.html`(1857줄)이 게이트 밖에서 자유롭게 자랐다.
2. **`src/` 밖 생산 코드(`deploy/`·`tools/`·`firmware/`)는 전혀 스캔되지 않았다.**
   운영 스크립트들이 무판정 상태였다.

또한 dashboard 패키지 안에 D-262의 로컬 웹 예산 스캔(600줄)이 별도로 존재했는데,
`map-view.js` 612줄이 무판정으로 커밋된 시점부터 이미 부실해 있었다.

따라서 이 계획은 기준을 새로 만들거나 1000줄로 완화하는 것이 아니라, **기존 600줄 예산을
유형별로 명문화하고 커버리지를 전 생산 코드로 확장**하며, 이미 `split` 판정이 내려진
파일들의 실행 대기열을 정리한다.

## 2. 코드 유형별 예산

| 유형 | 범위 | 예산(물리 줄) | 초과 시 | 근거 |
|---|---|---|---|---|
| Python / C++ (`.py` `.cpp` `.hpp`) | `src/` 패키지 생산 코드 | **600** (기존, 변경 없음) | `SIZE_VERDICTS` 판정 의무 | D-168 P6 원문 |
| 셸 (`.sh`) | `src/`, `deploy/`, `tools/`, `firmware/` | **600** | 판정 의무 | 현재 최대 500줄 미만, 사실상 예방 |
| Python (`.py`) | `deploy/`, `tools/`, `firmware/` | **600** | 판정 의무 | 유형 동일, 루트별 완화 불필요 |
| 웹 자산 (`.js` `.html` `.css`) | `src/` 패키지 내 | **800** | 판정 의무 | 마크업/보일러플레이트 오버헤드; 대부분 파일 ≤500 |
| 모든 유형 | 예산과 무관 | **>1000** | 성장 허용량 **0** — 한 줄이라도 자라면 재판정 | 1000줄 넘는 파일은 더 자랄 이유가 없다 |
| 시험 코드 | `test/`, 각 패키지 `test/` | 면제 | — | X4: 커버리지는 부채가 아니다 |
| 데이터 (`.yaml` `.sql` 맵·그래프 등) | 전체 | 면제 | — | 코드가 아니다 (`lane_graph.yaml` 930줄은 맵 데이터) |

핵심 원칙은 module-split-criteria X1을 그대로 계승한다: **줄 수는 분할 근거가 아니라
판정 의무의 트리거다.** 초과 파일은 반드시 `split:`(계획 링크 포함) 또는 `accept:`(소유자·이유)
중 하나로 기록되고, 게이트가 그 판정이 부실해지지 않음을 기계적으로 검증한다.

D-262의 로컬 웹 예산 스캔(`hmi/dashboard/test/test_web_budgets.py`, 600줄)은 D-362 게이트가
상위 집합이므로 통합한다 — 파일은 아키텍처 게이트가 `.js`/`.html`/`.css`를 실제로 커버하는지
확인하는 인수 시험으로 남는다.

## 3. 현재 위반 스냅숏 (2026-09-30, 확장 직후)

확장 시점의 예산 초과 17개(신규 11 + 기존 6 재판정)는 전부 판정 기록과 함께 게이트에
등록됐다. 아래는 실행 완료 후 상태다.

## 4. 정책 메커니즘 — `test_module_structure.py`

1. **웹 자산 편입:** `WEB_SUFFIXES = {".js", ".html", ".css"}`, `FILE_BUDGET_WEB = 800`.
   패키지 총계(PACKAGE_BUDGET 10k)에도 합산.
2. **운영 루트 편입:** `OPS_ROOTS = {deploy, tools, firmware}`의 생산 `.py`/`.sh`를 같은
   `_over_budget`에 합류.
3. **>1000 엄격 등급:** 파일 줄수 > 1000이면 성장 허용량 0 — 판정 시점이나 현재 중 하나라도
   넘으면 한 줄이라도 자라면 재판정强제. 패키지(10k)는 종전대로 +150.
4. **변이 증명 의무:** 게이트 확장은 red→복구→green 변이로 증명했다(deploy 601줄 신규 파일,
   map-view.js 812줄, task_store.py 1062줄 — 전부 "needs a verdict"/"grew past+0" 적발).

## 5. 리팩토링 대기열 — 전량 실행 완료 (2026-09-30)

### P0 — split 판정 존재했던 것들 — **완료**

1. **`app.py` 1556 → 476.** 라우트 그룹이 자기 store를 소유하던 조건이 성숙 —
   `mission_routes`(390)·`task_dispatch_routes`(288)·`intent_routes`(141)·`console_routes`(114)·
   `ingest_routes`(131)·`static_routes`(93)·`site_auth`(154)·`http_errors`(36)로 분리.
   `create_app`·lifespan·감사 미들웨어·비전 임대·배경 루프는 app.py에 잔류.
2. **캘리브레이션 클러스터 → ROS-free 상태기계.** 신규 `calibration_sequence.py`(510) —
   `CalibrationSequence` 믹스인(운동 허가 `safe_motion`·정밀 홈드 `pause_precision`·
   `tick_motion`/`tick_collecting` 단계 분기·`report`/`finish`·인증서 영속)과 `calib_node`
   순수 함수 8개. 노드는 배선만: `startup_calibration_node.py` 584, `calib_node.py` 583.
3. **패키지급: `fleet`·`control` 재편** — 둘 다 split 판정 유지(unscheduled), D-362 P0 실행으로
   fleet 총계는 재판정 기록됨. 2026-10-07 재판정(38952)의 첫 web/server 경계는
   `docs/plans/2026-10-07-fleet-site-map-web-server-seam.md`다.

### P1 — 웹 자산 — **완료**

4. **`diagnostic.html` 1857 → 재판정: accept.** 단일 HTML·단일 IIFE가 `web/AGENTS.md`에
   기록된 **의도된 설계**다(무의존·무빌드·share 직접 서빙). D-150 디버그 전용면(운용
   launch·deploy 배제)이며 소유자도 하나다 — 분할은 그 계약을 깨는 대가로 줄 수만 줄인다.
   성장 허용량 0 유지.
5. **`app.js` 1338 → 745 + `telemetry.js`(419)·`teleop.js`(128)·`state-socket.js`(111).**
   ES 모듈 이동, 무빌드 유지(D-23; D-7 React+Vite는 기각된 방향 그대로).
   임포트 방향 `dom←client←settings←셸` 한 방향 유지.
6. **`styles.css` 1119 → 492 + `console-detail.css`(637).** 캐스케이드 순서가 곧 규칙이므로
   487줄("상태 레일") 경계의 꼬리 분할로 유효 규칙 순서를 그대로 유지. 순서 계약을 두 파일
   헤더와 `dashboard_css()` 시험 헬퍼로 고정.

### P2 — 운영 스크립트 판정 — **완료 (전부 accept)**

7. first-boot 799, verify-media-readback 788, rosy_harness 693, boot-display 688,
   updater 686, secret_scan 670, hw-probe 641 — 단일 진입·원자성·단독 실행(X5).

## 6. 비목표

- 시험 파일 분할 (X4). 시험이 길다는 것은 커버리지다.
- 줄 수만으로 하는 분할 (X1). 예산은 "판정하라"이지 "쪼개라"가 아니다.
- 데이터 파일(.yaml 맵/그래프, .sql) 예산화.
- 번들러·프레임워크 도입 (D-23 무빌드, D-7 기각 유지).
- `reference/`, `private/`, `build/`, `install/`, `log/`, `.worktrees/` — 비생산 트리.

## 7. 실행 태스크 — 전부 완료

| ID | 내용 | 상태 |
|---|---|---|
| T1 | ADR D-362 채택 + `module-split-criteria.md` X1 각주 갱신 | **완료** |
| T2 | 게이트 확장(웹·운영 루트·>1000 허용량 0) + 판정 17건 + 변이 증명 3종 | **완료** — 33 passed |
| T3 | P0-1 `app.py` 라우터 분리 | **완료** — app.py 476, 모듈 8개 예산 내, fleet 전체 920 passed |
| T4 | P0-2 캘리브레이션 상태기계 추출 | **완료** — 노드 584/583, 계열 234 passed + 신귨 실제값 8 passed |
| T5 | P1 웹 자산 + D-262 게이트 통합 | **완료** — 위 §5 참조, 게이트 33 passed |
| T6 | logs·harness 갱신 | **완료** — 회차별 logs.md 기록 |

## 8. 검증 명령

```bash
python -m pytest test/architecture/test_module_structure.py -q          # 게이트
python -m pytest src/site/fleet/test/ -v                                 # P0-1
python -m pytest src/runtime/sensing/test/ -q                            # P0-2 (sensing 별도 라인)
python -m pytest src/runtime/gateway/test/test_dashboard.py src/hmi/web_common/test -q  # P1
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py # P1 브라우저 회귀
python tools/harness/rosy_harness.py lint                                # 문서 일관성
```
