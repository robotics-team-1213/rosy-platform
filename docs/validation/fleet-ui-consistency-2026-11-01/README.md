# Fleet UI 일관성 정비 회차 검증 기록 (2026-11-01~02)

대상: `applications/fleet/web`(다섯 영역 문서 + 네 가벼운 문서), 로봇 셸·대시보드·Pilot·경기 보드, 학습 검수 12화면. 브랜치 `uiux/fleet-install-subnav`(18+ 커밋, SHA는 착지 기록 참조).

## 무엇을 했나

1. **설치 문서 하위 탐색 좌석 통일(D-741 6)** — 본문 안 사이드바를 공용 `ui-subnav` 좌석으로. 다섯 영역 문서의 좌석 기하 실측 일치(x=72, w=232).
2. **경로 줄 도입(D-926 2)** — 아홉 Fleet 문서 본문 머리 `ui-pathbar`(문서 h1 하나 + 현재 화면 strong), 화면 이름 주인: task-chooser `onSelect`·`bindScreens` `label`·`area-nav`.
3. **비평 이행** — 이중 에이전트 비평(impeccable) 23/40 → 27/40. P0(죽은 탭 `</section>`)·P1(표식 어휘·URL 보존·거짓 표시)·P2/P3(경로 줄 화면 이름·canvas role·알림 글리프·묶음 머리글·skip link·랜드마크) 전부 처리 또는 근거 종결. 스냅숏: `.impeccable/critique/`(2026-10-31T17-27-42Z, 18-09-46Z).
4. **D-945 전 표면 자리 규칙** — ADR + DESIGN.md 규범 표 + `shared/web/test/test_layout_canon.py`(Fleet 9문서·로봇 셸·검수·Pilot·경기 보드·대시보드 준수).
5. **로봇 목적지 메뉴 통일** — `SURFACE_RAIL` 단일 출처, `ui-rail-item` 부품, 셸·브리지 같은 어휘(사용자 지시 2026-11-01).

## 게이트가 잡은 결함(착지 큐에서, main 진입 전)

검수 어휘 계약 충돌(원복+정정) · 캔버스 role 소유권 · 머리 예산 계약(테마 원복, 사용자 재확인) · 크기 래칫 · OMX ROS 시험 exit 5 지뢰(공통 인프라 수리) · 브리지 actionIcon 참조 오류(변이 증명으로 적발·수습).

## 증거와 경계

- 샘플 서버 Chromium 실측: 좌석 기하·경로 줄 추적·탭 전환·딥링크 보존·390px 넘침 0·페이지 오류 0. node 403/403.
- 원격 pytest(모델/AI PC): 계약 시험·브라우저 범위 통과 기록은 착지 로그(`rosy-land-wt/land-uiux-fleet-install-subnav-*.log`)와 land 이벤트가 소유.
- 이 기록은 LOCAL 설계 증거다. 실물 장치·현장 수용(D-153 G3)·운영 배포를 대신하지 않는다.

## 2026-11-02 표면 전체 감사(5차)와 남은 일

두 갈래 읽기 전용 감사(CSS 토큰·중복, JS 중복·책임 혼재·문구)를 돌렸다. 기존 계약 시험이 원시 색·글자 크기·간격·장식·`ui-*` 덧칠·`element.style`을 이미 막고 있어, 이번 회차는 시험이 못 보던 틈만 다뤘다.

이번에 고친 것: Fleet 좁은 좌석 22rem 경계 허가 · 조작 표면 넷(Fleet·대시보드·Pilot·경기 보드) noscript · 검수 이미지 style 속성(CSP가 무시) · skip-link 세 사본과 sr-only 사본 제거(덧칠 검사에 skip-link 추가) · 검수 403 문구 통일과 '같은 뜻 한 말' 계약 · 검수 행간 토큰.

남은 일(우선순위 순, 각각 별도 변경):

1. **결정 필요 — 신호 녹색 등.** D-525는 가상 신호 녹색 등을 `--status-good`으로 정했고 로봇 패널·Fleet 지도(`traffic-view.js`)가 그렇게 그린다. Fleet 신호기 카드(`.lamp.green.on`)는 `--nominal`(무색)이고 `test_console_palette`가 Fleet의 `--status-good` 참조를 금한다. 같은 등이 두 색이다.
2. **공용 키트 채택.** `shared/web/control-dom.js node`·`workflow-controls.js`(상태 패널·결과·진행)·`request.js`가 거의 쓰이지 않아, 로봇 13·Fleet 7·Pilot 6·검수 8곳에 `el/node` 사본, 검수 12곳에 요청 래퍼 사본이 있다. 검수 `window.confirm` 7곳은 `confirmIrreversible`로.
3. **토큰 없는 범주.** z-index(표면마다 1–30, 공용 1000–2002), 강조 줄 3·4px, 점·견본 크기 4종, Pilot의 임의 `color-mix` 비율 12곳 — 층·줄·점·scrim 단계 토큰을 먼저 정한 뒤 옮긴다(층 순서가 표면 안에서 의미가 있어 기계 치환 금지).
4. **중복 부품.** 카드 컨테이너(약 50블록, 반경 3·채움 6종), 왼쪽 강조 줄 카드, 오버레이 빈 상태(`.map-empty` 두 모양), 범례 배치, 로그 보기, 표(`.ui-data-table` 미사용), 단계 스트립 재구현(`stage-strip.css`를 견본만 씀), 모니터링 toolbar·pager.
5. **문구.** 다시 시도/다시 확인/재시도/새로고침, 불러오는 중/확인 중/조회 중, 읽지 못했습니다/불러오지 못했습니다, 오프라인/연결 끊김/응답 없음 — 정본을 정해 `SAME_MEANING_RETIRED`에 하나씩 더한다.
6. **책임 혼재.** 로봇 대시보드의 두 셸(`index.html`+`app.js` 898줄 vs `surface.html`+`panels/`)이 원격 조작·하드웨어·도킹을 각자 갖는다. 경기 보드 정지 표시는 `ui-status`가 아닌 span(`data-state="sent"`).
