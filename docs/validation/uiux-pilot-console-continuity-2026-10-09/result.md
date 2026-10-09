# Pilot 운전석에서 Robot 운용 지도로 이어지는 LOCAL 검증 — 2026-10-09

- 기준: `uiux/pilot-console-map-flow`, 분기 기준 commit `fda0abffffbe71d7397782424996d172a23a3238`.
- 시나리오: 2000×1200·390×844의 Pilot 주행 화면에서 `운용 지도`를 누른다. 개발 CORE가 0 속도와 IDLE 요청을 받은 뒤 같은 탭에서 실제 CORE FastAPI의 `/console` 문서·정적 자산으로 이동한다. Pilot 세션 토큰을 Console 세션으로 넘기고 인증된 `/api/v1/ui/surfaces/console` 조회, 지도 화면, 비상 정지 접근을 확인한다. Console API·화면은 실제 소스를 썼으며 로봇 상태와 지도 미수신은 LOCAL 합성 데이터다.
- 발견·수정: 통합 시험 라우터가 `/api/v1/map/costmap?scope=global`의 쿼리를 버리자 지도 없음이 연결 실패로 보였다. URL 쿼리를 보존해 CORE의 지도 미수신 상태를 그대로 검사한다. 또한 실제 지도 데이터가 없는 화면에서 “현재 지도를 볼 수는 있습니다”라고 단정하던 Robot Console 문구를 “지도가 들어오면 읽기 전용으로 볼 수 있습니다”로 고쳤다.
- 화면 확인: 전환 후 두 폭 모두 지도 없음 원인과 작업 준비 링크가 보인다. 지도 레이어·링크·상태줄이 순서대로 놓이고 가로 넘침과 브라우저 페이지 오류가 없다. 주행 목표·초기 위치 버튼은 사용 불가 상태이며 비상 정지는 보인다.
- 검증: 이 통합 브라우저 2 passed와 기존 Pilot 지도 이동 순서 시험 2 passed, 셸 자산·Pilot 라우트·문서 배치 12 passed; 각 실행에서 `known_failures.py` 0 NEW. `node --check`, `git diff --check`, Impeccable detector `[]`. 하네스 lint 0 error, 기존 갱신 경고 23건.
- 원시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-09--pilot-console-flow/`의 `captures-final/`, `run-final.txt`, `structure.txt`, 격리 확인 `final-isolation.txt`. 앞선 쿼리 누락 캡처는 `captures/`, 최초 CORE import 실패와 시험 수정 기록은 `run.txt`·`run2.txt`·`run3.txt`에 둔다.
  - `pilot-before-console-2000x1200.png` SHA-256 `791B2731409548FFE5E50A8F6BD145D4FB0981BDCEFF729B2BC8A22900928E75`
  - `pilot-before-console-390x844.png` SHA-256 `55CE710F4E8238464CFABE4A4874D33E66FF598B1CBFE9A4B6CAD424515D7DD5`
  - `console-after-pilot-2000x1200.png` SHA-256 `405B525CBB5248E0FA6B61458A67F4B434D8FDE233C7E27FB61276038669CDB2`
  - `console-after-pilot-390x844.png` SHA-256 `C6FB784F2E1D16A02E5AB1A3BBE02BC702B3B2B7F7D9EA110D7316CD1154DC23`
- 판정: 같은 탭의 LOCAL 전환·인증·지도 미수신 설명은 통과. 요청 수락은 실제 로봇 정지 readback이 아니며, 이 시험은 실제 지도·경로·SLAM 실행이나 설치 앱의 WebView 세션을 증명하지 않는다. 전체 G2/G3와 DEVICE/FIELD는 HOLD.
