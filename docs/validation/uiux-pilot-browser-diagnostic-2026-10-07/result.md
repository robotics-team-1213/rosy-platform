# Pilot 현재 후보 브라우저 회귀 진단 — 2026-10-07

로컬 격리 checkout `058d3e977`에서 2026-10-07에 실행했다. 이 회차는 [Pilot 후보 APK](../uiux-pilot-candidate-apk-2026-10-07/result.md)의 웹 소스와 같은 checkout을 사용했다. 실행 중 공유 `main`은 `cc094d0ac`까지 전진했지만 격리 checkout은 바뀌지 않았다.

| 검사 | 결과 |
|---|---|
| 공용 반응형·디자인 범위 계약 | `test_responsive_tiers.py`와 `test_design_scope_gates.py`: **15 passed**, `known_failures.py` **0 NEW**. `X:/DevTemp/rosy-pilot-full-current/responsive.txt` SHA-256 `355adf09a192011eeea1c591f7b1747e87ea4e742cd816bb8018980df7fcbe0f`. |
| Pilot 전체 브라우저 | opt-in 121개 수집. 약 30분 후 진단 실행을 수동 중단했다. 출력은 `........F..............................`까지만 남아 **완료 결과·실패 traceback이 없다**. `X:/DevTemp/rosy-pilot-full-current/browser.txt` SHA-256 `769afe8826d923fb5229c16177a1e16c92371afd6b5249c19fe5c2151077af90`. 이 불완전한 파일에 대한 `known_failures.py`의 0 NEW는 합격 근거가 아니다. |
| 첫 실패 위치 재생 | 수집 순서의 첫 아홉 개를 같은 순서로 `-vv -x` 재실행해 **9 passed**, `known_failures.py` **0 NEW**. 아홉째는 2000×1200 비상 중 카메라 보기였고 별도 단독 실행도 **1 passed**, **0 NEW**였다. 원본 `first-nine.txt` SHA-256 `bed54876e7fcd606b8b1d81b2a75f8ee4e2ef57e0421f62b2e64552e6b58aea7`, `emergency-2000.txt` SHA-256 `b46d3fe0bffb6bde5665970ec20635cc14a3f049b6d07a6533dc4f5c2422e54c`. |

첫 실행의 `F`는 재생에서 반복되지 않았다. 원래 traceback이 없으므로 원인을 코드 결함이나 단순 시간 문제로 단정하지 않는다. **전체 Pilot 브라우저 무오류 판정은 이번 실행에서 미확인**이다. 위의 통과는 선언 G2 상태×폭 전부, 실제 Lenovo/로봇 readback, 요청자 G3 독회를 대신하지 않는다. Pilot과 제품 전체 UI/UX는 **HOLD**다.
