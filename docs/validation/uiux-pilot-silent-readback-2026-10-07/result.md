# Pilot 주행 상태 수신 중단 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** 이 검사는 320×568 브라우저에서 상태 소켓이 열린 채 프레임을 멈추고 REST 조회가 503을 반환하거나 응답 없이 멈추는 전이를 재생한다. 실제 로봇·태블릿·현장 연결 검사는 아니다.

수정 전에는 마지막 `0.12 m/s`와 배터리 `81%`가 계속 현재값처럼 보였다. 수정 후에는 두 전송 경로의 상태 readback이 끊긴 경우 마지막 숫자를 숨기고 「상태 수신 없음」을 표시한다. REST 조회가 다시 성공하면 수치와 수신 표시가 회복한다. 서버가 보낸 `fresh/delayed/disconnected/unavailable` 판정은 그대로 사용한다. 소켓이 실제로 닫힐 때의 세션 안전 동작과 비상 정지 조작은 바꾸지 않았다.

수정 전 집중 브라우저 **1 failed**(숫자가 남음), 수정 후 503·응답 정지의 수신 중단·회복 **2 passed**다. 인접한 증거 4상태×선언 폭 4개, 수신 전 상태, 소켓 닫힘 4폭을 합친 브라우저는 **11 passed**다. D-153 명명 G1은 **90 passed, 1 warning**이며 각 성공 실행의 `known_failures.py`는 **0 NEW**다. 320px 중단 화면은 `X:\DevTemp\pilot-silent-readback\shots\pilot-readback-{status,hang}-320x568.png`, 실행 기록은 같은 X: 폴더의 `red.txt`, `transport-two.txt`, `browser-final.txt`, `g1.txt`다.

이 캡처는 첫 화면의 비상 정지, 숫자 숨김, 경고 문구, 가로 넘침 없음을 보여 준다. 나머지 Pilot 선언 상태·폭, 실제 장치 readback, 운전자 G3 여덟 항목은 여전히 **HOLD**다.

2026-10-07 추가 LOCAL 확인: 동일한 소켓 무응답·REST 503/무응답 전이를 Pilot 선언 폭 2000×1200, 1200×2000, 390×844, 320×568에서 다시 재생했다. 마지막 속도·배터리 숫자 숨김, 「상태 수신 없음」, 비상 정지 표시, 가로 넘침 없음, REST 회복을 모두 확인했다. 브라우저 **8 passed**, `known_failures.py` **0 NEW**. 원본은 `X:/DevTemp/pilot-silent-widths/shots/pilot-readback-{status,hang}-{2000x1200,1200x2000,390x844,320x568}.png`, 실행 기록은 같은 X: 폴더의 `browser.txt`다. 다른 Pilot G2 셀, 실물 장치와 G3는 **HOLD**다.

착지 전 재실행 첫 회는 fixture가 Chromium 금지 포트 1723을 골라 페이지 로드 전에 **8 setup failed**였다(`preland-browser.txt`). 다시 실행한 동일 8셀은 **8 passed**, `known_failures.py` **0 NEW**였다(`preland-browser-retry.txt`). 금지 포트 회차는 UI 판정에 포함하지 않는다.

이어진 LOCAL 정직성 보정: 상태 수신이 멈춘 화면에도 조작 요청의 응답 시간은 계속 표시될 수 있다. 출처가 다른 두 값을 혼동하지 않도록 단독 `7ms`를 `조작 응답 7ms`로, 실패 문구를 `조작 응답 시한 초과`로 바꿨다. 수정 전 320px 단언 **1 failed**, 수정 후 네 폭×두 전송 실패 **8 passed**, `known_failures.py` **0 NEW**; G1 관련 계약 **35 passed**, **0 NEW**. 320px 원본 `X:/DevTemp/pilot-latency-label/shots/pilot-readback-status-320x568.png`의 SHA256은 `1348c72071d054d81e4f1a47a77600a7635fc1aaab948aff5d9cbd84913db1ca`이며, 실행 기록은 같은 X: 폴더의 `red.txt`, `green.txt`, `g1.txt`다. 이 값은 조작 요청의 응답 시간이지 로봇 운동 완료 시간이나 상태 수신 지연이 아니다. 제품 전체 판정은 **HOLD**다.
