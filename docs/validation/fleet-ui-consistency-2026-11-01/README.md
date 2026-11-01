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
