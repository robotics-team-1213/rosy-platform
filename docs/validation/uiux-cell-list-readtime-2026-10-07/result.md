# Cell 문서 목록 마지막 수신 시각 — 2026-10-07

**LOCAL 부분 근거; Cell과 제품 UI/UX는 HOLD.** `/console/cell`은 문서 목록을 한 번 읽은 뒤 행만 남겨, 화면을 오래 열어 두면 목록이 언제 확인된 것인지 알 수 없었다. 이제 목록이 있거나 비어 있거나 마지막 성공 응답을 브라우저가 받은 시각을 별도로 표시한다. 문서 행의 「수정」 시각과 뜻이 다르다. 조회 중·실패·자격 변경에서는 이전 목록과 마지막 수신 시각을 현재 근거로 남기지 않는다.

Cell의 선언 폭 **1440×1000, 390×844, 320×568**에서 실제 Fleet 테스트 서버와 Chromium으로 목록 성공·조회 실패·복구를 재생했다. 수정 전 320px 집중 검사는 **1 failed**(목록 존재 시 시각 칸이 숨겨짐), 수정 뒤 세 폭 성공·실패/복구 **6 passed**, 조회 잠금·완료 **1 passed**, Cell 브라우저 전체 **49 passed**, G1 **90 passed**, 각 `known_failures.py` **0 NEW**다. Harness lint는 오류 0·기존 경고 22건이다. 실행 기록과 원본 화면은 `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-list-readtime/logs/`와 `evidence/fleet-cell-{saved-list,list-error,list-recovered}-{1440x1000,390x844,320x568}.png`에 있다. 320px에서 목록·수신 시각은 같은 내용 칸 안에 있고 가로 넘침이 없다.

표시 시각은 **브라우저가 HTTP 목록 응답을 받은 로컬 시각**이다. 서버가 문서 값의 `fresh`/`delayed`를 판정한 증거가 아니며, 이후 변경을 자동으로 감지하지도 않는다. 실제 사이트 계정·나머지 Cell G2·장치 readback·운영자 G3가 남아 판정은 HOLD다.
