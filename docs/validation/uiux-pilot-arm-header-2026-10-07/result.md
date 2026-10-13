# Pilot Gazebo 팔 화면 320px 머리·동등 창 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** 시작 커밋 `04372b3cc`의 `uiux/pilot-arm-320` 브랜치에서 로컬 가짜 OMX SIM 드라이버와 Chromium으로 확인했다. 시험 fixture를 실제 `app.js`와 같이 Gazebo 팔 화면에서 Home·비상 정지 버튼을 숨기도록 맞췄다. 이 시뮬레이션 전용 화면은 실물 주행·정지 근거가 아니다.

320×568 원본에서는 팔·그리퍼 창이 같은 너비로 쌓이고 가로 넘침이 없지만, 상단에는 Pinky 연결 게이트의 오래된 「대기」와 「직접 조종」 부제가 남아 팔 본문의 「조작 가능」·「시뮬레이션 전용」과 충돌했다. 팔 화면에서만 그 두 문구를 숨기고 본문의 상태·범위 설명을 유지했다. 수정 전 320px 상태 시험 **1 failed** (`X:/DevTemp/pilot-arm-320/red-status.txt`); 수정 후 390×844·320×568 팔 폭 검사와 2000×1200·1200×2000·390×844·320×568 팔·그리퍼 배치 검사 **6 passed**, `known_failures.py` **0 NEW** (`green.txt`). D-153 G1 **90 passed**, **0 NEW** (`g1.txt`).

원본 네 장은 `X:/DevTemp/pilot-arm-320/shots/pilot-arm-gripper-{2000x1200,1200x2000,390x844,320x568}.png`. 320px PNG SHA256 `175b6a11502edc9a748f46271b0adfc12cffbb99bd34dd05641bad82038328d6`; 수정 후 브라우저 로그 SHA256 `5ca28148d552d0c37bf705d29996b86997270d1b976b71d459a4c0fe388b4b06`.

이는 합성 SIM 화면의 LOCAL 배치·문구 근거다. 실제 태블릿에서의 판독·팔 장치 readback, Pilot의 나머지 G2 상태×폭과 요청자의 G3 여덟 항목은 남아 있다.
