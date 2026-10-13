# Pilot에서 실제 Console 지도까지 같은 탭 인증 인계 (2026-10-08)

## 발견과 수정

Pilot은 인증 토큰을 `sessionStorage`의 `rosy.pilot.token`에, Console은 `rosy.dashboard.token`에 보관한다. 기존 `운용 지도` 이동 시험은 `/console`을 대역 HTML로 바꿔 0 속도·IDLE 요청 순서만 검사했다. 실제 Console의 인증 상태는 확인하지 않았다. 이전 Console 토큰을 넣은 재현 시험에서는 두 화면 크기 모두 이동 후 그 이전 토큰이 남아 있었다 (`logs/before-handoff.txt`, 2 failed).

Pilot이 보유한 토큰이 있으면 조종 종료 요청을 마친 뒤 같은 탭의 Console 세션 키에 복사하고 `/console`로 이동한다. 기존 다른 계정의 Console 세션 키는 이 Pilot 세션으로 교체된다. URL·쿠키·`localStorage`에는 토큰을 넣지 않는다. Pilot 토큰이 없으면 기존 Console 로그인 상태를 임의로 바꾸지 않는다.

## 모바일·데스크톱 화면 증거

| 화면 | PNG | SHA-256 |
|---|---|---|
| Pilot 주행, 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-console-session-9d1e/evidence/before/pilot-map-handoff-390x844.png` | SHA-256 `CD7EA53040CA6B308C5B8E1868309217 AD7B4B85CC18E9A5C7B5EE1AF1343B25` |
| Pilot 주행, 2000×1200 | `X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-console-session-9d1e/evidence/before/pilot-map-handoff-2000x1200.png` | SHA-256 `4B4126565ACC3FD1F767111249DCD595 0E63804561E2D0860104D37892746EEB` |
| 실제 CORE가 서빙한 Console, 390×844 | `X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-console-session-9d1e/evidence/after/pilot-to-real-console-390x844.png` | SHA-256 `8F8BD1650240807BED31AE5B2698E5F9 0429F20738ADC40F4C168D501F89299C` |
| 실제 CORE가 서빙한 Console, 1366×768 | `X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-console-session-9d1e/evidence/after/pilot-to-real-console-1366x768.png` | SHA-256 `1CBD18937290CEFD28E9A70BD30F0C8E 04F8B158635AFF624E42551BC9FD9F5B` |

SHA-256 열의 두 부분을 공백 없이 이어 붙이면 원본 파일의 전체 digest다.

Pilot 주행 캡처는 개발용 CORE 대역 응답이다. 도착 캡처는 소스 트리의 실제 CORE FastAPI 앱·Console 자산을 TestClient로 제공한 별도 LOCAL 시나리오다. 두 시나리오를 결합해 검증했지만 실제 로봇을 조종한 직후의 설치 앱·Console 연속 캡처는 아니다. TestClient에는 사용 가능한 지도 스냅숏이 없어 Console은 지도 수신 실패를 표시한다. 경로·SLAM·물리 주행을 만들어 보여 주지 않았다.

## 검증과 수용 경계

- Pilot 주행 중 이동은 0 속도와 소유한 MANUAL의 IDLE API 요청 뒤에 일어난다. 도착 페이지에서 Pilot 토큰이 Console 세션 키에 있고 URL·영구 저장소에는 없는지 확인했다.
- 실제 CORE Console의 `/api/v1/ui/surfaces/console` 요청이 인계 토큰으로 인증되고 `운용자` 역할 및 지도 패널이 나타나는지 390×844·1366×768에서 확인했다. 수평 넘침과 페이지 오류는 0건이다.
- 관련 브라우저·셸 자산·Pilot 라우트 **10 passed**, `known_failures.py` **0 NEW** (`X:/DevTemp/projects/rosy-platform/2026-10-08--pilot-console-session-9d1e/logs/regression-final.txt`). `node --check`와 `git diff --check` 통과.
- LOCAL 인증 인계만 확인했다. 설치 앱의 WebView 세션 유지, 실제 로봇 정지 readback, 지도·경로·SLAM 데이터, D-153 전체 G2/G3와 DEVICE/FIELD는 **HOLD**다.
