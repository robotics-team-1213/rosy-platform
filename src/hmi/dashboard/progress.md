---
module: dashboard
logical_modules: []
owner: 화면
last_verified: { commit: "uncommitted", date: "2026-09-28" }
gates:
  SOURCE:
    state: HOLD
    evidence: "관리자 /device readback 및 /console 모드·수동 운전·차선 추종·도킹·지도 상태 경로 수정 후 회귀를 다시 실행하지 않음"
    blocker: "2026-09-28 /device host-system and /console mode/teleop/line-follow/docking/map updates need dashboard browser regression before SOURCE can return to GO"
    cmd: "ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test test/test_role_menu_panels_browser.py test/test_role_surface_states_browser.py -q -p no:cacheprovider"
  LOCAL:
    state: HOLD
    blocker: "2026-09-28 host-system and /console action-state updates need fresh administrator /device and operator /console captures at 1366×768 and 390×844; current screenshots predate the map changes"
    cmd: "ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py::test_role_procedure_g2_local_matrix -q -p no:cacheprovider"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: HOLD
    blocker: "share/dashboard 설치를 이미지에서 본 기록이 없다"
  DEVICE:
    state: N/A
  FIELD:
    state: N/A
adrs: [D-23, D-77, D-243, D-283, D-292, D-294, D-300, D-306, D-312, D-314]
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
- 2026-09-28 후속: 보드 장치 점검 결과와 측정 상태를 분리했다. 현재 FastAPI/Chromium 상호작용 확인에서 refresh 후 여러 주기 GET이 와도 접수 상태가 유지됨을 desktop/mobile에서 확인했다. 실제 Host Agent readback은 미확인.
- 2026-09-28 후속: 시스템 화면의 로봇 표시 이름 폼을 한 번만 만들고 편집 초안을 폴링 동안 보존한다. FastAPI/Chromium 확인에서 두 번 이상 신원 폴링 후 폼 1개와 입력 초안을 확인하고, 저장 응답과 다음 조회 상태를 분리했다. 실제 기기 신원 readback은 미확인.
- 2026-09-28 후속: registry에서 보드 장치 패널이 관리자 전용(`min_role: administrator`)임을 확인했다. 비관리자용 버튼 안내는 접근할 수 없는 경로라 제거했다. 권한 거부는 `/device` 표면 진입에서 처리하며, 역할 G2 매트릭스는 비관리자 진입 차단을 포함한다.
- 공용 토큰은 `src/hmi/web`이다. 얼굴 LCD는 `src/hmi/face`다.

## 다음 gate

1. ARTIFACT: 이미지에 `dashboard` 패키지가 설치된다.

## 현재 유효한 금지사항

- 이 폴더에 빌드 단계나 인라인 스크립트를 넣지 않는다.
- Fleet·게임 화면을 여기로 가져오지 않는다.
