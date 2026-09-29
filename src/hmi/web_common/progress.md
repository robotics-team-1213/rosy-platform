---
module: web_common
owner: CORE
last_verified: { commit: "9049bd37", date: 2026-09-27 }
gates:
  SOURCE:
    state: GO
    evidence: "HMI web + dashboard 100 passed with browser tests; dashboard API route/manifest 29 passed (2026-09-27 Windows)"
    cmd: "powershell -NoProfile -Command \"$env:ROSY_RUN_BROWSER_TESTS='1'; python -X utf8 -m pytest src/hmi/web_common/test src/hmi/dashboard/test -q\""
  LOCAL:
    state: GO
    evidence: "실 CORE TestClient API + visible Chromium: styleguide, operator /console·/setup, administrator /console·/setup·/device at 1366x768 and 390x844; blue focus ring, disabled opacity 0.45, 0 missing kinds, 0 page errors, no positive horizontal overflow"
    cmd: "X:\\DevTemp\\rosy-design-system-polish\\visible_roles.py"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-61, D-147, D-168, D-72, D-194, D-195, D-277, D-284, D-285, D-286, D-287, D-292, D-294, D-300, D-329]
plans:
  - docs/plans/2026-09-15-module-harness-design.md
  - docs/plans/2026-09-26-rosy-modern-brand-palette.md
  - docs/plans/2026-09-26-rosy-tokenized-design-system.md
  - docs/plans/2026-09-26-shared-typography-interaction-tokens.md
---
## 지금 상태

- 라이브러리·계약 등급(D-168 P2)이다. 프로세스가 없으므로 ROS-SIM~FIELD는 N/A이며, 그 판정은 이 패키지를 싣는 `core` 모듈의 gate가 소유한다.
- 2026-09-22 harness에 처음 등록했다. 이전 이력은 `git log -- src/hmi/web`를 본다.
- 자체 `test/`가 토큰·팔레트·헤드리스·공유 조작 부품을 본다. 브라우저 버튼·글자 크기의 소스는 `components.css`와 `tokens.css`다(D-194). ament_cmake라 colcon test 배선은 없고 CI 4경로·직접 pytest로 실행한다.

## 다음 gate

1. 새 메뉴/페이지는 D-292에 따라 작업 질문·URL·역할·표면 소유를 먼저 정하고, 공통 셸·토큰·컴포넌트 계약에 연결한다. 표면별 레이아웃과 제품 질문은 유지한다.

## 현재 유효한 금지사항

- Do not copy tokens into consumers; link `/common/tokens.css`; `/ui/tokens.css` is a legacy alias (D-129 정정 2026-09-29, D-130.3).
