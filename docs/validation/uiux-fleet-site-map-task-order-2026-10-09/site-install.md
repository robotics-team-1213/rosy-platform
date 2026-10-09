# Fleet 현장 지도 설치 및 읽기 전용 화면 확인 · 2026-10-09

## 설치 식별

- 원격 `main`과 현장 설치 후보: `247561153ca1032bb4fb65123c1b247adb1240a6`.
- GitHub CI `37859420794` 성공, ARM64 site build `37859420877` 성공. `site-247561153ca1` 릴리스 서명 기록은 정확한 source commit과 tag에 `signed`를 남겼다.
- 현장 자동 갱신 기록: `staging` → `switched` → `installed` (2026-10-08 23:46–23:50 UTC). `/opt/rosy/candidate`가 위 SHA 후보를 가리켰다. site stack과 자동 갱신 타이머는 active였고 proxy·Fleet·Vision 컨테이너는 위 SHA 이미지로 `healthy`였다. SSH 터널을 통한 `/healthz`는 HTTP 200이었다.

## 현장 화면

- 설치된 Fleet `/console/site-map`을 SSH 터널과 인증서 검증 예외를 둔 테스트 브라우저에서 읽기 전용으로 열었다. 1440×1000, 390×844, 320×568 전체 화면을 캡처했다. 활성 지도, 경로 미리보기, 운행, 초안 편집, 지도 가르치기 순서가 보였다. 실제 운행 시작·초안 활성화·비상 정지는 누르지 않았다.
- 320px 지도는 의도된 가로 이동 영역이다. 현장 DOM에서 지도 영역 `clientWidth=272`, `scrollWidth=802`, 오른쪽 끝 `scrollLeft=530`, 문서 `scrollWidth=320`을 확인하고 좌우 끝을 각각 캡처했다. 전체 지도를 한 장에 축소하지 않으며, 안내 문구와 이동 영역 이름을 제공한다.
- 320px 현장 캡처에서 긴 세션 표지가 비상 정지 영역 아래로 넘치는 결함을 발견했다. `uiux/site-header-session-1009`의 후속 수정과 3개 폭 Chromium 회귀 검증은 별도 후보이며 이 설치 SHA에는 포함되지 않는다.

## 비공개 원본과 판정

스크린샷 원본은 공개 저장소 밖 `X:/DevTemp/projects/rosy-platform/2026-10-09--site-map-task-order/site/`에만 둔다. SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| `site-map-1440x1000.png` | `6d1cbd1cbc9c9d897a10b3b4f1b2f9e65a3e4cd9742831519b4dc5996520bfbc` |
| `site-map-390x844.png` | `fa5125378463ad4f726aaad68373c6ed1755b61f6a6a1c18072ff630bfc4fcbf` |
| `site-map-320x568.png` | `8d3396cfbae6f440c11f6896c1d7b45273d73d4b4d52de922c4b4e53a7913ada` |
| `site-map-320x568-right.png` | `feb0f95b9c8bda3bdeb6caa8994b2bd2c0bebc41203a8088f865b6504a33b253` |

**판정:** 이 SHA의 CI·빌드·서명·현장 설치·서비스 상태·터널 경유 화면 렌더는 확인했다. 현장 기기에서 신뢰된 인증서로 접속한 운영자 브라우저, 이름 있는 운영자 인증, 로봇 위치 갱신·경로 추종·SLAM·물리 정지와 사람의 G3 수용은 확인하지 못했다. 해당 DEVICE/FIELD 항목은 HOLD다.
