# Pilot 320px 카메라 면적 — LOCAL

**판정: Pilot G2 부분 근거, 제품 전체 HOLD.** `dfc3c3b4e`의 전체 Pilot 브라우저 회귀는 **115 passed, 1 failed**였다. 320×568 주행 화면의 카메라 표시 면적이 뷰포트의 **16.3%**여서 기존 20% 바닥을 통과하지 못했다. 영상은 원본 4:3 비율이고 조작부와 겹치지 않았으나, 작은 화면에서 읽기에 너무 작았다. 원본 실패는 `X:/DevTemp/uiux-pilot-current/run.txt`, 320px 캡처는 같은 폴더의 `shots/pilot-drive-current-320x568.png`다. 이 실패 실행을 전체 통과로 세지 않는다.

320×568 아래 배치에서만 HUD의 세로 간격과 바깥 여백을 줄여 영상에 높이를 돌려주었다. 버튼 표적·영상 `contain`·비상 정지·조작부 분리 규칙은 그대로 확인했다. 수정 뒤 2000×1200, 1333×760, 1200×2000, 390×844, 320×568 카메라 비율·면적·비겹침·조작 접근 브라우저 **5 passed**, `known_failures.py` **0 NEW** (`X:/DevTemp/pilot-camera-320/green.txt`). 320px 원본 `X:/DevTemp/pilot-camera-320/shots/pilot-drive-current-320x568.png`의 SHA256은 `32d7d952726e298acdf4b04175a47b507d68cac9058149979da816a603ffa2d5`다. D-153 G1 다섯 시험 파일 **90 passed**, **0 NEW** (`g1.txt`).

전체 Pilot 브라우저 회귀 재실행과 실제 태블릿·로봇 readback, 나머지 G2, 요청자 G3 여덟 항목은 아직 **HOLD**다.
