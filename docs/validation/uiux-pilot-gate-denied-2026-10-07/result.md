# Pilot 접속 거부 문구 G2 부분 확인

2026-10-07 · `uiux/pilot-gate-copy` · LOCAL 합성 CORE

선언 폭 2000×1200, 1200×2000, 390×844, 추가 320×568에서 두 거부 상태를 렌더했다.

| 상태 | 폭별 원본 | 화면 판정 |
|---|---|---|
| 조회 전용 역할 | `X:/DevTemp/projects/rosy-platform/2026-10-07--pilot-gate-copy/after/pilot-viewer-denied-{2000x1200,1200x2000,390x844,320x568}.png` | 조종 `차단됨`, 사용 권한 `조회 전용`, 운전 권한이 없는 이유를 표시. 주행 시작 없음. |
| 구동 꺼짐(무동작) | 같은 폴더의 `pilot-drive-withheld-{2000x1200,1200x2000,390x844,320x568}.png` | 조종 `차단됨`, 사용 권한 `운영자`, 구동이 꺼진 이유를 표시. 주행 시작 없음. |

수정 전 4폭 조회 전용 원본은 X:의 `before/`에 있다. 화면에는 원시 `BLOCK`·`viewer`·`drive_disabled:no_motion`이 보이지 않는다. 각 셀에서 비상 정지 가시성, 가로 넘침 0, 페이지 오류 0을 확인했다. 거부 사유의 알려진 CORE 코드도 운용자 말로 번역하고 모르는 코드는 원시 문자열 대신 상태 확인 안내로 둔다. 서버 판정·권한·요청 경로는 바꾸지 않았다.

`logs/gate-final.txt`의 브라우저 **11 passed**(위 8셀과 기본 접속·비상 정지·잘못된 토큰), `logs/drivers.txt`의 순수 드라이버 **8 passed**, `logs/g1.txt`의 D-153 G1 관련 계약 **90 passed**. 각 `known_failures.py` **0 NEW**.

다른 선언 상태의 G2, 실제 로봇·태블릿 readback과 운전자 G3는 **HOLD**다.
