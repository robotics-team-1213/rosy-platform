# 기존 운용 화면의 인증·지도 확인창 회귀 복구 (2026-10-08)

## 원인과 조치

`/dashboard` 브라우저 시험의 인증 교체·페이지 이탈 시나리오는 지도 목표 확인창이 열리기를 기대했지만, 시험 서버의 `/api/v1/map` 응답은 `{}`였다. 폭·높이·해상도가 없는 지도에서는 좌표를 만들 수 없으므로 현재 `map.js`가 목표 확인창과 전송을 막는 것이 맞다. 변경 전 로컬 `main`에서 같은 시험이 실패했다 (`X:/DevTemp/projects/rosy-platform/2026-10-08--line-follow-gate-7a2c/logs/main-old-auth.txt`).

시험에만 10×10 셀, 1m/셀, 원점 (-5,-5), `fixture-map` ID를 가진 합성 지도를 제공했다. 기존 로봇 자세 (1.25,-0.50)가 지도 안에 들어간다. 제품 코드나 실제 조작 허용 조건은 바꾸지 않았다. 빈 지도에서 전송을 막는 동작은 유지했다.

## LOCAL 증거

실제 `/dashboard` 정적 자산을 Chromium에서 열고, 390×844와 1366×768의 목표 확인창을 캡처했다. 두 폭 모두 합성 API 응답이며 실제 로봇의 지도나 주행 증거가 아니다.

| 화면 | PNG 원본 | SHA-256 |
|---|---|---|
| 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--auth-map-fixture-5e91/evidence/after/auth-map-goal-confirm-390x844.png` | `6BA38671F29F47BD8F85291E20EE70EA5B9044D77C2BCF2E12EB99FC31C3D3AA` |
| 1366×768 | `X:/DevTemp/projects/rosy-platform/2026-10-08--auth-map-fixture-5e91/evidence/after/auth-map-goal-confirm-1366x768.png` | `9E39D9943356305C66F7935B65F45ED6B997A497FCB0EF0B4D962BF4957E8E27` |

브라우저 시험은 인증을 바꾼 뒤 오래된 모드·지도 응답이 화면을 덮지 않는지, 확인창 취소 뒤 목표 POST가 없는지, 페이지가 숨겨진 뒤 응답·소켓 이벤트가 기존 화면을 바꾸지 않는지 확인한다. 수정 후 해당 흐름 **2 passed** (`logs/after.txt`), 지도 요청·좌표 시험을 더한 묶음 **5 passed** (`logs/regression.txt`), 각각 `known_failures.py` **0 NEW**다. 실행 로그는 이번 X 세션의 `logs/`에 있다.

## 수용 경계

이 변경은 시험의 사실성을 복구한 LOCAL 근거다. 실제 설치 앱의 인증 전환, 장치 지도·위치·명령 readback, D-153 전체 G2/G3 및 현장 운영자 평가는 확인하지 않았다. ARTIFACT/DEVICE/FIELD는 **HOLD**다.
