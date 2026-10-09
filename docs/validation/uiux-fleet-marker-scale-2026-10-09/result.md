# Fleet 지도 로봇 마커 비율 검증 · 2026-10-09

기준 소스: 로컬 `main` commit `25bacfcad3034b3affb212b464780ecf2d5892c0`에서 분기한 `uiux/fleet-marker-scale`. FastAPI 정적 자산과 합성 Fleet 응답을 Chromium에서 표시한 **LOCAL** 결과다.

1920 × 1080 첫 캡처에서 40 × 40 격자 지도 로봇 방향 마커의 화면상 판정 상자는 약 **161.94px**였다. 작은 격자에서 최소 3셀을 차지하게 한 크기 계산이 큰 캔버스에서 확대된 결과다. 로봇과 목표 주변의 경로·거리 라벨을 과하게 가렸다.

마커 크기를 현재 캔버스의 화면 픽셀 밀도에 맞춰 제한했다. 1920 × 1080과 320 × 568에서 각 마커 판정 상자가 42px 이하인지 확인한다. 마커의 지도 좌표, 방향, 온라인 표시, 호출 링, 목적지, 명령 경로는 바꾸지 않았다. 기존 라벨 겹침과 320px 지도 래스터 선명도 검증도 함께 통과했다.

| 캡처 | X: 아래 위치의 파일 | SHA-256 |
|---|---|---|
| 변경 후 데스크톱 지도 부분 | `fleet_marker_map_1920x1080.png` | `ecd340ec577d7acef6ff6bc1dcac280c6e23fb75674246673cf830ececd82921` |
| 변경 후 모바일 지도 부분 | `fleet_marker_map_320x568.png` | `aac04c2bc86404d7245da3d516d5fcf32b3764ad12911fee4cfecf41c637064f` |

원본은 `X:/DevTemp/projects/rosy-platform/2026-10-09--fleet-marker-scale/`에 있다. 변경 전 전체 화면은 `X:/DevTemp/projects/rosy-platform/2026-10-09--fleet-console-current/fleet_console_exception_first.png` (SHA-256 `db91838529f2693cc13e84e6c63692ad36cc66c4dc7f3f5d32a46a247755cd22`)이며, 현재 소스 확인에서 브라우저 5건이 통과했다. 변경 후 관련 브라우저 6건 통과, `known_failures.py` NEW 0 (`2026-10-09--fleet-marker-regression.txt`).

이 캡처는 합성 데이터의 지도 표현만 검증한다. 실제 로봇 위치, 경로 추종, SLAM 실행, 현장 배포, 장치 화면 및 사용자 G3 수용 증거가 아니다.
