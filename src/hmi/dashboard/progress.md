---
module: dashboard
logical_modules: []
owner: 화면
last_verified: { commit: "9049bd37", date: 2026-09-27 }
gates:
  SOURCE:
    state: GO
    evidence: "HMI web + dashboard 100 passed with browser tests; dashboard API route/manifest 29 passed after latest-main integration (2026-09-27 Windows)"
    cmd: "ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/web/test src/hmi/dashboard/test -q"
  LOCAL:
    state: GO
    evidence: "actual CORE TestClient API + visible Chromium: styleguide, operator console/setup, administrator console/setup/device at 1366×768 and 390×844; focus ring and disabled treatment visible, no positive horizontal overflow, 0 missing button kinds or page errors"
    cmd: "X:\\DevTemp\\rosy-design-system-polish\\visible_roles.py"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "share/dashboard 설치를 이미지에서 본 기록이 없다"
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-23, D-77, D-243, D-283, D-292, D-294, D-296]
plans:
  - docs/plans/2026-09-26-d283-console-action-groups.md
  - docs/plans/2026-09-26-rosy-tokenized-design-system.md
  - docs/plans/2026-09-26-shared-typography-interaction-tokens.md
---

## 지금 상태

- 운용 콘솔의 HTML·JS·CSS는 여기 있다. FastAPI는 `src/runtime/api_web`이 같은 프로세스에서 이 파일을 읽는다.
- D-283: 조작 탭은 현재 페이지에서만 선택을 유지한다. 그룹을 떠나기 전 텔레옵 terminal zero, 차선 추종 OFF, 도킹 비진행 상태를 확인한다. 확인 실패 시 그룹/화면을 유지한다. G3 8명 평가 전 D-201 desktop 수용은 HOLD다.
- 공용 토큰은 `src/hmi/web`이다. 얼굴 LCD는 `src/hmi/face`다.

## 다음 gate

1. ARTIFACT: 이미지에 `dashboard` 패키지가 설치된다.

## 현재 유효한 금지사항

- 이 폴더에 빌드 단계나 인라인 스크립트를 넣지 않는다.
- Fleet·게임 화면을 여기로 가져오지 않는다.
