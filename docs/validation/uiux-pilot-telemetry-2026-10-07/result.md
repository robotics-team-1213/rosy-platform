# Pilot 주행 HUD 속도·배터리 증거 상태 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** 이 검사는 D-153의 상태 정직성과 화면 폭을 Pilot 주행 HUD에서 확인한다. 실제 로봇·사이트 설치본의 readback이나 운전자 G3를 대신하지 않는다.

기존 HUD는 속도 수신 전에도 `0.00 m/s`와 `0°/s`를 보였고, 상태 조회 실패 후에도 마지막 숫자를 유지할 수 있었다. 이제 서버의 `evidence.velocity`와 `evidence.battery` 판정을 웹소켓과 REST 상태 조회에 공통으로 적용한다. `fresh`는 수치를, `delayed`는 마지막 수치와 `received_at` 기준 나이를, `disconnected`와 `unavailable`은 수치 대신 사유를 표시한다. 수신 전에는 `—`를 표시한다. 비상 정지의 위치와 동작은 바꾸지 않았다.

| 상태 | 2000×1200 | 1200×2000 | 390×844 | 320×568 |
|---|---|---|---|---|
| fresh | 확인 | 확인 | 확인 | 확인 |
| delayed | 확인 | 확인 | 확인 | 확인 |
| disconnected | 확인 | 확인 | 확인 | 확인 |
| unavailable | 확인 | 확인 | 확인 | 확인 |

이 16칸은 로컬 개발 서버와 합성 상태 응답의 Chromium 캡처다. 각 칸에서 증거 문구, 비상 정지의 가시성, 가로 넘침 없음, 카메라 영역 높이 > 화면 높이의 20%를 검사했다. 320px 지연·연결 끊김 화면은 HUD 문구가 단어 중간에서 쪼개지지 않도록 수정 후 육안으로 다시 확인했다. 원본 캡처는 `X:\DevTemp\pilot-telemetry-evidence\shots\pilot-telemetry-{state}-{width}x{height}.png`에 있다.

브라우저 집중 실행은 **5 passed** (`test_drive_hud_does_not_invent_zero_before_velocity_readback`와 상태 4개×폭 4개)다. 그 밖의 첫 기동·거부·SAFE_STOP·확인 대화상자 등 Pilot의 선언 G2 셀, 실제 설치본/로봇 readback, 사용자 G3 8항은 남아 있다.
