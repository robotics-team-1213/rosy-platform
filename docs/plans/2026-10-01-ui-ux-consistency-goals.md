# UI/UX 공용화·일관성 목표 — 실행 계획 (D-396)

결정: [ADR D-396](../adr/D-396-uiux-consistency-goal-system.md). 이 문서는 여섯 목표의 실행 순서와 완료 기준을 추적한다.

## 현재 자산 (2026-10-01 기준)

- 단일 출처: `web_common/tokens.css`, `ui.js`(13 컴포넌트), `components.css`, `theme.js`, `template.html`
- 등록부: `surfaces.yaml` — 9 서피스(web 7 · lcd 1 · native 1), 문법 4종
- 계약: token_parity · shared_controls · typography_focus · dialog · responsive_tiers · 앱 이름(D-377) · 역할 소유(D-370)
- 안내서: `DESIGN.md`(D-359 §8)
- 장치 계약: D-394(화면 카드=페이로드, 장치=프로파일)

## 실행 순서

| 단계 | 목표 | 일 | 상태 |
|---|---|---|
| 1 | G1 | `test_single_language.py` — ① web_common 밖 커스텀 엘리먼트 정의 금지 ② 서피스 CSS의 `:root` 토큰 재정의 금지(`raw_colours` 의 `:root` 예외는 등록부 선언으로 존중 — 게시판 피치 색 선례). 변이 증명 2종 | ✅ 이번 |
| 2 | G2 | 실측: 강제 시험이 이미 있다(`test_a_dropped_contract_or_baseline_is_explained` — 빈 `contracts`는 `contract_reason` 필수). `lane-live-view`도 이미 선언됨 → **빈 칸 0 확인 완료** | ✅ 확인 |
| 3 | G5 | 브라우저 회귀 한 번의 명령 문서화(아래) + baseline 존재 강제도 이미 시험 중(`test_declared_baselines_are_tracked`) | ✅ 문서화 |
| 4 | G3 | D-394 완료 상태 기록(추가 코드 없음 — 계약 시험이 이미 측정) | ✅ 기록 |
| 5 | G4 | `manual-drive` transitional 소유 추적 표 유지(Pilot 이행은 외부 일정) | 기록(아래) |
| 6 | G6 | 랜딩 절차에 이미 녹아 있음(ADR 동반) — 관행 유지 | 상시 |

## G1 세부 — 승격 압력의 계약화

검사 두 개가 "공용화"를 강제한다:

1. **커스텀 엘리먼트는 web_common 만 정의한다.** 서피스 JS/HTML에서 `customElements.define` 을 찾으면 위반 — 공유 컴포넌트가 필요하면 `web_common/ui.js` 에 넣고 소비만 한다.
2. **토큰 변수를 재정의하지 않는다.** 서피스 CSS가 `:root`(및 `[data-theme]`) 블록에서 `--` 변수를 선언하면 위반 — 지역 변수는 지역 스코프(컴포넌트 셀렉터 안)에서만.

승격 판단(무엇을 web_common 으로 올릴지)은 사람이 한다. 계약은 미루는 순간 붉어지게 만들 뿐.

## G4 추적 표

| 조작 | 소유 | 상태 |
|---|---|---|
| manual-drive | dashboard console.teleop | transitional — Pilot DEVICE 이행 대기(D-370 4의 1) |

## G5 회귀 스윕

```
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py test/test_games_board_browser.py src/hmi/dashboard/test -q
```

- 옵트인 이유: Chromium·Playwright 필요. 돌리지 않는 옵트인 시험은 시험이 아니다 — UI 변경 커밋은 이 명령을 1회 돌린 증거를 동반한다(test/AGENTS 원칙).
- baseline: `surfaces.yaml` 의 `baseline`/`baseline_reason` — 빈 칸 없음(계약 시험이 검사).
