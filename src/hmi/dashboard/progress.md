---
module: dashboard
logical_modules: []
owner: 화면
last_verified: { commit: "uncommitted", date: 2026-09-27 }
gates:
  SOURCE:
    state: GO
    evidence: "D-306 /device 결과 표시 및 현재 teleop 자격 fixture 정렬 후 dashboard + 역할 브라우저 회귀 46 passed (2026-09-27 Windows)"
    cmd: "ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test test/test_role_menu_panels_browser.py test/test_role_surface_states_browser.py -q -p no:cacheprovider"
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
adrs: [D-23, D-77, D-243, D-283, D-292, D-294, D-300, D-306]
plans:
  - docs/plans/2026-09-27-uiux-surface-closure.md
  - docs/plans/2026-09-26-d283-console-action-groups.md
  - docs/plans/2026-09-26-rosy-tokenized-design-system.md
  - docs/plans/2026-09-26-shared-typography-interaction-tokens.md
---

## 지금 상태

- 운용 콘솔의 HTML·JS·CSS는 여기 있다. FastAPI는 `src/runtime/api_web`이 같은 프로세스에서 이 파일을 읽는다.
- D-283: 조작 탭은 현재 페이지에서만 선택을 유지한다. 그룹을 떠나기 전 텔레옵 terminal zero, 차선 추종 OFF, 도킹 비진행 상태를 확인한다. 확인 실패 시 그룹/화면을 유지한다. G3 8명 평가 전 D-201 desktop 수용은 HOLD다.
- D-306: `/device`의 Host Agent 네트워크·릴리스 조작은 요청 중·거부·오류·접수 결과를 해당 절차 안에서 볼 수 있다. 결과 문구는 적용 완료 readback을 뜻하지 않는다. 현재 회차는 브라우저 fixture의 해당 상호작용만 검증했고 `/setup`·`/device`의 전체 G2/G3는 아직 닫히지 않았다.
- 공용 토큰은 `src/hmi/web`이다. 얼굴 LCD는 `src/hmi/face`다.

## 다음 gate

1. ARTIFACT: 이미지에 `dashboard` 패키지가 설치된다.

## 현재 유효한 금지사항

- 이 폴더에 빌드 단계나 인라인 스크립트를 넣지 않는다.
- Fleet·게임 화면을 여기로 가져오지 않는다.
