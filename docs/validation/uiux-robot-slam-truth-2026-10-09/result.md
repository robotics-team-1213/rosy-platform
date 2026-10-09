# Robot 맵핑 세션 표시와 설정 카드 높이 — 2026-10-09

- 기준: `uiux/robot-slam-session-truth`, 분기 기준 `57b37622433b2af8252394df45a5bb6bd18c4219`.
- 계약: [ROSY API & Protocol Reference](../../reference/ROSY%20API%20%26%20Protocol%20Reference.md)의 `GET /api/v1/navigation/state`에서 `mapping_active`는 CORE가 수락한 맵핑 세션 상태다. SLAM Toolbox의 실제 실행이나 지도 갱신 성공을 증명하지 않는다. `POST /api/v1/slam/start` 성공도 같은 수준으로 표시한다.
- 변경: Console의 활성/비활성 SLAM 문구를 각각 `세션 수락 · 지도 갱신 미확인`/`세션 없음`으로 고쳤다. 기존 Dashboard의 맵핑 시작/중지 응답도 세션 수락으로 표시하고 설명을 바로잡았다. 데스크톱 현장 설정 그리드는 카드가 같은 행의 긴 카드 높이로 늘어나지 않게 내용 높이에 맞췄다.
- 화면 확인: 실제 FastAPI 정적 자산과 합성 CORE 응답을 사용했다. Console 320×568·390×844·1366×768에서 상태줄이 보이고, 활성·대기·조회 실패가 구분된다. 기존 Dashboard 390×844·1366×768에서는 맵핑 요청 뒤 결과가 보이고 카드 높이가 500px 미만이다. 가로 넘침 및 실제 장치 readback은 이 시험의 증거가 아니다.
- 검증: Console 내비게이션 상태 매트릭스 브라우저 1 passed, 기존 Dashboard 맵핑 브라우저 2 passed, 문서 배치·Dashboard API 33 passed. 각 실행에서 `known_failures.py` 0 NEW. 변경 JS `node --check` 및 `git diff --check` 통과. 하네스 lint 0 error, 기존 갱신 경고 23건.
- 원시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-09--robot-slam-truth/`의 `navigation-stage/`, `legacy/`; 실행 로그 `X:/DevTemp/projects/rosy-platform/2026-10-09--robot-slam-final.txt`, `2026-10-09--legacy-slam-layout.txt`, `2026-10-09--slam-structure.txt`.
  - `operator-console-navigation-320x568.png` SHA-256 `1E090EF737B5BF5D2ACAC9256921757F39C41DD50AF9661F67F11D5E1F045D56`
  - `operator-console-navigation-390x844.png` SHA-256 `18EC3852E7B18D372804DF3A1551E752EB5D9D57F01CE4092F136AEC54F16E5D`
  - `operator-console-navigation-1366x768.png` SHA-256 `D257FD52931449FBE6D60E17517591403CDB380EDA03BE4964C05CFD20112710`
  - `operator-console-mapping-idle-390x844.png` SHA-256 `887C6F12D258F0FE889ADF40DA8BCB7A0978C036A5EA1F91656D27CBB9DD000C`
  - `operator-console-mapping-unknown-390x844.png` SHA-256 `5BF681126F39809243582792D74EB97CBAC955BF42D227CEB5772D6958785B53`
  - `compatibility_slam_card_390x844_local.png` SHA-256 `34746C3BFA5B944D041F2573B625E7642919262438CA0EC04EA0CBE22E922506`
  - `compatibility_slam_card_1366x768_local.png` SHA-256 `753993A834CCFA778403A7354668AE27ED1B8FDA508DCD6900A5C19D9EBE3026`
- 판정: 위 합성 LOCAL 화면은 통과. 설치 이미지, 실제 SLAM Toolbox 실행·지도 갱신, DEVICE/FIELD, 전체 G2/G3 사용자 수용은 HOLD.
