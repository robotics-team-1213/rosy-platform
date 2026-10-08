# Console 지도 미수신 상태 검증 — 2026-10-08

- 기준: `uiux/console-map-truth-71a2`, 분기 기준 `18355ef2b`.
- 범위: Pilot에서 실제 CORE `/console`로 이동한 Operator 화면, 390×844 및 1366×768 Chromium. 로컬 TestClient/가상 CORE이며 설치본이나 장치 화면은 아니다.
- 발견: 이전 캡처 라우터가 `/api/v1/map/costmap?scope=global`의 쿼리를 버려 CORE가 400을 반환했다. 그 결과 화면이 지도 미수신을 연결 실패처럼 표시했다. 실제 CORE는 지도와 비용 지도 미수신에 각각 `404/NOT_FOUND`, `runtime.maps`의 두 값에 `false`를 반환한다.
- 수정: 브라우저 라우터가 쿼리를 보존한다. Console 지도는 기존 Dashboard와 같이 `runtime.maps`를 `createFieldMap`에 전달한다. 빈 지도 문구는 지도 설정 의무를 단정하지 않고 상태 확인을 안내한다.
- 확인: 실제 CORE 응답으로 Pilot→Console 진입 후 지도 `empty` 상태, 빈 지도 안내, 연결 오류 안내 부재를 확인했다. 요청 실패 오버레이 회귀도 통과했다. 관련 브라우저 테스트 3 passed, 문서 배치 검사 15 passed/1 skipped, `known_failures.py`: 0 NEW/0 known. 하네스 lint 0 errors/23 기존 갱신 경고, `git diff --check` 통과.
- 원시 증거: `X:/DevTemp/projects/rosy-platform/2026-10-08--console-map-truth-71a2/run.txt` 및 `evidence/after/`.
  - `pilot-to-real-console-390x844.png` SHA-256 `0BFDA855A9B84FA4F5213F68E7E3A8B74AA3349367C7088CF60F28A4121E94E3`
  - `pilot-to-real-console-1366x768.png` SHA-256 `C80E2E739BC8070A6A51FE00C17C21814ED0FC5EB1A95D71A01F8148FAA8E351`
- 판정: 이 지도 미수신 시나리오의 LOCAL 브라우저 근거 통과. 전체 G2 상태·해상도 행렬, G3 사용자 검토, 설치 이미지, DEVICE/FIELD는 별도 HOLD.
