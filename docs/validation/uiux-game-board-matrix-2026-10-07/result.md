# 게임 보드 G2 선언 폭 LOCAL 행렬 — 2026-10-07

**판정: LOCAL 부분 근거, 제품 UI/UX HOLD.** D-153의 게임 보드 질문은 경기장·공·로봇·골을 볼 수 있는가다. 현재 후보 `uiux/game-board-matrix`의 실제 PreviewServer와 Chromium에 합성 경기 응답을 넣었다. 원본은 `X:/DevTemp/projects/rosy-platform/2026-10-07--game-board-matrix/evidence/games_matrix_<state>_<width>x<height>.png`, 실행 기록은 같은 X: 폴더의 `logs/matrix-after-assert.txt`다.

| 상태 | 1280×800 | 390×800 | 320×568 | 관찰 |
|---|---|---|---|---|
| 최초 기동 | first_boot | first_boot | first_boot | 점수 `—`, 필드 대기, 정지 가시 |
| 첫 조회 오류 503 | first_error | first_error | first_error | 마지막 경기 정보를 꾸며내지 않음 |
| fresh | fresh | fresh | fresh | 점수·공·로봇·필드 표시 |
| delayed | delayed | delayed | delayed | 마지막 생성 3.0초 전과 마지막 수신 표시 |
| disconnected | disconnected | disconnected | disconnected | 현재 위치가 아닌 마지막 수신 위치라고 표시 |
| unavailable | unavailable | unavailable | unavailable | 시각 정보 없는 이전 형식 응답을 현재로 주장하지 않음 |
| 정지 요청 접수 | stop_requested | stop_requested | stop_requested | `실제 정지 확인 중`을 명시 |

각 셀에서 가로 넘침이 없고 정지가 첫 화면 안에 있다. 390/320px에서는 점수·필드·관측 패널의 시작점과 폭 차이가 1px 이하다. 새 행렬 브라우저 **3 passed**, 보드 전체 브라우저 **37 passed**, 각 `known_failures.py` **0 NEW**다. D-153 G1은 **90 passed**, harness lint는 오류 0·기존 경고 22건이다. 원본 크기로 320px fresh와 390px 정지 접수, 1280px 연결 오류를 육안 확인했다.

게임 호스트에는 로봇 등록 목록이나 권한별 입력이 없어 빈 목록·권한 거부·확인 대화상자 셀은 해당하지 않는다. 공/로봇 유실 HOLD와 정지 실패·타임아웃은 기존 보드 브라우저가 별도로 캡처한다. 정지 접수 캡처는 합성 HTTP 200 응답일 뿐 **SAFE_STOP 물리 readback이 아니다**. 실물 카메라·경기·정지, 운영자 G3 여덟 항목은 미검증이므로 게임 표면과 제품 전체 판정은 HOLD다.
