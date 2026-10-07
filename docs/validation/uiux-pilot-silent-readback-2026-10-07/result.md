# Pilot 주행 상태 수신 중단 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** 이 검사는 320×568 브라우저에서 상태 소켓이 열린 채 프레임을 멈추고 REST 조회가 503을 반환하거나 응답 없이 멈추는 전이를 재생한다. 실제 로봇·태블릿·현장 연결 검사는 아니다.

수정 전에는 마지막 `0.12 m/s`와 배터리 `81%`가 계속 현재값처럼 보였다. 수정 후에는 두 전송 경로의 상태 readback이 끊긴 경우 마지막 숫자를 숨기고 「상태 수신 없음」을 표시한다. REST 조회가 다시 성공하면 수치와 수신 표시가 회복한다. 서버가 보낸 `fresh/delayed/disconnected/unavailable` 판정은 그대로 사용한다. 소켓이 실제로 닫힐 때의 세션 안전 동작과 비상 정지 조작은 바꾸지 않았다.

수정 전 집중 브라우저 **1 failed**(숫자가 남음), 수정 후 503·응답 정지의 수신 중단·회복 **2 passed**다. 인접한 증거 4상태×선언 폭 4개, 수신 전 상태, 소켓 닫힘 4폭을 합친 브라우저는 **11 passed**다. D-153 명명 G1은 **90 passed, 1 warning**이며 각 성공 실행의 `known_failures.py`는 **0 NEW**다. 320px 중단 화면은 `X:\DevTemp\pilot-silent-readback\shots\pilot-readback-{status,hang}-320x568.png`, 실행 기록은 같은 X: 폴더의 `red.txt`, `transport-two.txt`, `browser-final.txt`, `g1.txt`다.

이 캡처는 첫 화면의 비상 정지, 숫자 숨김, 경고 문구, 가로 넘침 없음을 보여 준다. 나머지 Pilot 선언 상태·폭, 실제 장치 readback, 운전자 G3 여덟 항목은 여전히 **HOLD**다.
