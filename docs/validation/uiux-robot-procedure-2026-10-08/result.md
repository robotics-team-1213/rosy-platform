# Robot 작업 준비·설치/정비 모바일 절차 확인

- 날짜: 2026-10-08
- 기준: `uiux/robot-procedure-flow`, 분기 HEAD `2fa5d896f0f6abc7645eac9394171ee91bb18c7b`
- 원본: `X:/DevTemp/projects/rosy-platform/2026-10-08--155452--robot-procedure-flow--00bbd5/`
- 판정: **LOCAL 부분 근거**. 실물 Host Agent, 저장 readback, 설치자 G3는 HOLD.

## 관찰과 수정

Chromium에서 역할별 `/setup`·`/device`를 1366×768과 390×844로 캡처했다. `/setup`은 위치 끊김과 목록 오류를 같은 작업 안에서 안내하고, `/device`는 작업 선택기를 통해 시스템 상태와 네트워크 작업을 나눈다. 다만 Host Agent 원본이 `delayed`·`unavailable`인 네트워크 작업에서 모든 실행 버튼은 잠겼지만 SSID·암호·프로파일 ID 입력은 활성 상태였다. 사용자가 수행할 수 없는 작업에 암호를 먼저 입력하게 되는 모순이다.

`host/operations.js`의 기존 네트워크 잠금 판단을 세 입력에도 적용하고, 입력의 `aria-describedby`를 버튼과 같은 차단 안내에 연결했다. 상태가 `fresh`로 돌아오면 입력이 다시 활성화된다. 기존 초안 값은 보존한다. API·권한·전송 경로와 비상 정지는 변경하지 않았다.

## 확인

| 근거 | 결과 |
|---|---|
| `test_host_operations_browser.py` | 3 passed. `fresh`에서는 세 입력 활성, `delayed`·`disconnected`·`unavailable`에서는 비활성 및 차단 안내 연결. `known_failures.py`: 0 NEW. |
| 역할 G2 `test_role_procedure_g2_local_matrix` | 변경 전 1 passed, 변경 후 1 passed. 변경 후 역할·상태·폭 60기록, 가로 넘침 0, pageerror 0, 비상 정지 60/60 표시. `known_failures.py`: 0 NEW. |
| 원본 이미지 | 변경 전 `evidence/administrator-device-unavailable-host-operations-390x844.png`, 변경 후 `evidence-after/administrator-device-unavailable-host-operations-390x844.png`와 지연 장면을 원본 크기로 비교. 차단 안내는 유지되고 세 입력의 비활성 표시가 적용됐다. |

로그는 같은 X: 경로의 `logs/host-operations.txt`, `logs/procedure-matrix-after.txt`에 있다. G2는 CORE·Host Agent 응답을 브라우저 fixture로 재현한 것이며 실제 네트워크 변경이나 로봇 이동을 수행하지 않았다. 실제 장치의 연결 회복·입력 재사용, 화면 독회와 현장 사용성은 별도 확인이 필요하다.
