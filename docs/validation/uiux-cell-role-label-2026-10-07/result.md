# Cell 접속 역할 표시 — 2026-10-07

**LOCAL 부분 근거; Cell과 제품 UI/UX는 HOLD.** `/console/cell`의 320px 머리는 접속한 운영자에게 원시 `operator`를 표시했다. 같은 Fleet의 `/console`과 설치 화면이 쓰는 역할 어휘에 맞춰 `운영자`·`조회 전용`·`정책 관리자`·`권한 없음`으로 바꿨다. 권한 판정과 API 요청은 그대로다.

현재 main의 수정 전 화면은 `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-current/evidence/fleet-cell-saved-list-320x568.png`, 수정 뒤 화면은 `X:/DevTemp/projects/rosy-platform/2026-10-07--cell-role-label/evidence/fleet-cell-saved-list-320x568.png`다. 수정 전 집중 Chromium 검사는 **1 failed**, 수정 후 **1 passed**, Cell 브라우저 전체 **49 passed**, D-153 G1 **90 passed**, 각 `known_failures.py` **0 NEW**였다. 실행 기록은 같은 X: 회차 `logs/{role-red,role-green,browser-full,g1}.txt`다. 320px에서는 이름과 역할이 좁은 태그 안에서 두 줄로 읽히고, 390px에서는 한 줄이며 비상 정지와 겹치지 않는다.

이 검사는 합성 Fleet 세션에 대한 LOCAL 화면 근거다. 실제 사이트 계정, 전체 Cell G2 상태·폭, 장치 readback, 운영자 G3는 별도 HOLD다.
