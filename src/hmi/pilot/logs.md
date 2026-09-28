# pilot logs

## 2026-09-29 · 8f4ecfe2 · feat(hmi): pilot 골격과 /pilot 라우트 (실행 계획 T1)
- 변경: 패키지 `pilot`(ament_cmake)·`index.html`(ui-shell spatial)·`styles.css`·`core_api_web` `/pilot`·`/pilot/assets` 라우트와 MIME allowlist·`core_api_web` package.xml `pilot` 의존성. 실패 테스트 선행.
- 증거: `test_pilot_route.py` 2 passed(404→200 확인). api_web 전체 72 passed·web_common 3 failed 는 `known_failures.py` 판정 0 new(기존 fleet 카메라 코너 스타일·system.js 결함, 2026-09-29 Windows).
- gate 변화: SOURCE GO.
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · 434ceb0b · feat(pilot): stick.js 순수 입력 매핑 (실행 계획 T3)
- 변경: `stick.js` — `shapeAxis`(데드존·감도 곡선·클램프·원점 대칭), `mapInput`(pad·pedals·keys), `PRESETS`(low/mid/high 클라이언트 상한). 모듈을 `pilot_assets`·CMakeLists 에 등록.
- 증거: `test_stick.py` 8 passed(Node 서브프로세스, `_run_js` 패턴). 라우트 시험 포함 10 passed.
- gate 변화: 없음(SOURCE GO 유지).
- 결정: D-323.
- 교훈: 없음

## 2026-09-29 · uncommitted · docs(pilot): harness 등록과 문서 지도 (실행 계획 T2)
- 변경: `harness.yaml` 에 `pilot` 등록·`adr_gaps` 에 D-322 선점 기록(Isaac 세션 미착지 행). 모듈 `AGENTS.md`·`progress.md`·`logs.md` 신설. `src/AGENTS.md`·`src/hmi/AGENTS.md` 지도에 등재. D-323 ADR 본문·목차 행·설계·실행 계획 문서를 브랜치에 이식.
- 증거: 이 기록 아래 generate·lint·계약 시험으로 확인.
- gate 변화: 없음.
- 결정: D-323.
- 교훈: 없음
