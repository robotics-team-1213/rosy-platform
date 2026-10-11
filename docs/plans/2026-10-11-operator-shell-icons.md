# 운용 shell·아이콘·근거 위계

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Follow the repository shared-worktree and remote-test procedure.

**Goal:** 사용자가 지도·현재 상태·다음 행동을 먼저 인지하고, 필요할 때 사건 근거와 진단을 열어 확인한다. 기존 공용 규격·권한과 이동된 소스 경로를 유지한다.

**Architecture:** 공용 아이콘/설명 → Fleet 공통 shell → 역할별 업무 영역 → 단계별 사건 근거. 기존 HTML/CSS/ES module과 API를 사용한다.

**Tech Stack:** 기존 Web Components, HTML, CSS 토큰, ES modules, node test, 원격 pytest/Playwright. 새로운 런타임 의존성은 없다.

## 확정 와이어프레임

```text
┌─────────────────────────────────────────────────────────────┐
│ 헤더: Rosy Fleet · 사이트       알림  접속  개발표지  비상정지 │
├────────┬──────────────────────────────────┬─────────────────┤
│ 관제   │                                  │ 현재 상태/개입   │
│ 설치   │ 중앙: 현재 문서의 업무           │                 │
│ 지도   │ 관제=지도·영상                   │ 알림/기록/도구   │
│ Cell   │ 설치=단계, 지도=초안, Cell=실행   │ 선택 맥락       │
│        │                                  │ 근거는 펼침     │
├────────┴──────────────────────────────────┴─────────────────┤
│ 푸터: 보조 운영정보 · 출처/진단 경로                          │
└─────────────────────────────────────────────────────────────┘
```

좌측 탐색은 공용 의미 아이콘과 설명을 사용한다. 작은 화면에서는 가로 탐색으로 재배치한다. 헤더와 비상정지는 각 문서에서 같은 자리에 있고, 현재 개입은 작은 화면에서도 먼저 도달할 수 있다. 푸터는 문서 흐름 안에 둔다.

## 변경 소유권과 순서

1. 공용: `shared/web/ui.js`, `components.css` 및 기존 `/styleguide` 견본. 의미 아이콘·접근성 이름·focus 설명·상태를 정의하고 예외 없이 검사한다.
2. Shell: `operations/ui/console`의 네 HTML, `shared/fleet-header.*`, `shared/doc-tabs.css`, 배치 시트. 전역/문서/작업 단계를 구분하고 기존 ID·route·API 소유를 보존한다.
3. 사건: `operations/ui/console/console.js`의 보고서 렌더링과 관련 표시. 요약 → 역할별 결과 → 근거 → 원시 진단으로 접고 검토 저장·API 거절·내보내기를 보존한다.
4. 통합: 원격 브라우저·계약 검사를 실행하고 `known_failures`와 비교한다. 공용 조작 48/14/12, 네 문서·두 테마·네 폭, 원시 진단 기본 숨김, tooltip 키보드, 알림/현재 개입, 검토 완료를 검증한다.
5. 마감: 공식 main 착지·푸시·CI·서명 관제 설치와 실제 화면 readback. 기기/주행 수용은 별도다.

## 기존 검사와 마감 기준

- 공용 API/규격: `shared/web/test/test_action_icon_contract.py`, `test_shared_controls.py`, `test_ui_token_contracts.py`, `test_no_element_style.py` 및 기존 styleguide 브라우저 검사. 아이콘 이름·토큰·선택·focus 설명과 disabled 사유를 확인한다.
- Shell: `operations/fleet/test/test_fleet_header.py`, `test_fleet_header_browser.py`, `test_fleet_role_consumers_browser.py` 및 실제 네 문서. 큰 화면의 좌측 탐색·중앙 작업·우측 맥락과 작은 화면의 재배치·정지 접근을 확인한다.
- 사건: `operations/fleet/test/test_console_queue_inline_browser.py`, `operations/fleet/test/web/line-stuck.test.mjs`, `test/test_fleet_console_browser.py`. 기본 JSON 숨김, 요약에서 누가 무엇을 했는지, 펼침과 폴링 focus, 원문 보존, 검토 저장·내보내기·거절·완료 구분을 확인한다.
- 모든 시험은 커밋된 HEAD의 원격 로그와 `test/known_failures.py` 비교 결과를 기록한다. source-only·SKIP·CI·설치본·실물 증거를 섞지 않는다.

## 검증 상태

ADR와 와이어프레임을 먼저 확정했다. 구현·원격 시험·최종 설치는 아직 미완료다. D-639의 통일 규격 검사 결과를 이 작업의 shell 검증으로 대체하지 않는다.
