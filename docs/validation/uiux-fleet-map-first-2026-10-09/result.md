# Fleet 현장 지도 첫 화면 검증 · 2026-10-09

기준 소스: 로컬 `main` commit `be28e6a5c08767eb188219f8d7918c9fefa10a8d`에서 분기한 `uiux/fleet-map-auth-space`. 브라우저 테스트의 가짜 Fleet 응답으로 지도, 인증, 경로 미리보기를 확인했다. 실제 현장 서버나 로봇에 명령을 보내지 않았다.

## 관찰과 수정

- 연결 성공 뒤에도 토큰 입력 세부 항목이 펼쳐져 있었고, 320 × 568 화면에서 지도의 시작점은 화면 위 755.625px였다. 지도 앞의 선택형 평면 영상 도구가 핵심 지도를 더 아래로 밀었다.
- 공용 로그인 도우미가 연결 성공 시 토큰 세부 항목을 접는다. 요약 행은 남아 다시 펼쳐 재접속할 수 있다. 암호 로그인을 제공하는 사이트에서 처음 접는 기존 동작도 유지한다.
- 현장 지도에서는 지도와 범례를 먼저 보여주고, 표시 전용 평면 영상 도구를 그 뒤에 둔다. 지도와 영상 좌표의 데이터 처리 및 운행 권한은 바꾸지 않았다.
- 변경 후 320 × 568, 390 × 844, 1440 × 1000 브라우저 시나리오에서 `map-viewport` 시작점이 첫 화면 안에 있고 `plane-source`보다 앞임을 DOM 위치로 검사했다. 320px 화면에서 접속 상태, 비상 정지, 지도 일부가 첫 화면에 보이는 스크린샷을 확인했다.

## 재현 자료

원본 PNG와 실행 로그는 `X:/DevTemp/projects/rosy-platform/`에만 둔다. 공개 저장소에 접속 정보나 캡처 원본을 넣지 않는다.

| 자료 | 경로 | SHA-256 |
|---|---|---|
| 변경 전 320px 지도 | `2026-10-09--fleet-site-map-current/site-map-fresh-320x568.png` | SHA-256 `5bc2e75d7ecf39dd9bf0088ef7406a9d3e010bdbfc3e5d85b8a825dcb5ada283` |
| 변경 후 320px 지도 | `2026-10-09--fleet-site-map-mapfirst/site-map-fresh-320x568.png` | SHA-256 `68c174eff9eedcc8a03c9107122e82cf03ecdba37a481936cf990f18c8dedcd5` |
| 변경 후 1440px 지도 | `2026-10-09--fleet-site-map-mapfirst/site-map-fresh-1440x1000.png` | SHA-256 `4cbccc6fca1f3d4b92587026e0e5d069a14ff3914c41e1ff9103dcdfee61ed4b` |

브라우저 테스트는 `ROSY_RUN_BROWSER_TESTS=1`로 현장 지도 폭 3종, 경로 미리보기, 평면 영상 좌표 표시 전용, 비밀번호 로그인 흐름을 실행했다. 결과와 `known_failures.py` 판정은 `2026-10-09--fleet-site-map-mapfirst-full.txt`에 있다. UI 이미지 검토는 LOCAL 브라우저 증거다. 실제 현장 배포, 장치 화면, 운행 및 사용자 G3 수용은 이 기록으로 입증되지 않는다.
