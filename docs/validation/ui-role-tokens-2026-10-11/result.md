# D-639 UI 역할·토큰 검증

## 구현

등록된 11개 표면과 관제 하위 화면을 감사했다. 공용 CSS가 색상·서체·조작·disclosure 규격을 소유하고, canvas는 공용 역할 서체를 읽으며 Android는 같은 토큰의 생성 결과를 소비한다. 일반 조작과 비상정지는 48px 높이·14px 글자·12px 수평 여백을 공유한다. 각 화면은 기존 기능·권한을 유지하면서 현재 정보, 조작, 알림, 기록·근거를 구분한다.

관제 UI 소스는 `operations/ui/console`, 검수 소스는 `learning/curation/perception/review_app_web`이다. Fleet 서버의 자산 매핑을 그대로 사용한다. 폴더 이동 후 계약 검사도 다시 수행한다.

## 실행 증거

| 검사 | 소스 | 결과 | 로그 |
| --- | --- | --- | --- |
| 공용 규격·토큰·참조·mutation | 32860ffe13 | 104 PASS, NEW 0 | X:/DevTemp/ui-role-static-final/run-1.txt |
| 실제 역할·소유권 | acccbc4dd | 52 PASS, NEW 0 | X:/DevTemp/ui-role-ownership-final/run-1.txt |
| 관제·지도·Cell·실제 영상 기록 | 438ea67a0 | 116 PASS, NEW 0 | X:/DevTemp/ui-role-integrated-fleet-browser-correct/run-1.txt |
| Robot·Pilot 브라우저 | 354b55cfb0 | 179 PASS, NEW 0 | X:/DevTemp/ui-role-devices/pilot-robot-3.txt |
| 기존 실패 목록 독립 재검증 | 7775c5eca7 | 45 PASS, NEW 0 | X:/DevTemp/ui-role-final-baseline/run-2.txt |
| Learning 전체 브라우저 3개 suite | 1d9595374a | 168 PASS, NEW 0 | X:/DevTemp/ui-role-devices/learning-final-6.txt |
| 인라인 스타일 금지·canvas 토큰·정지 완료 | b44a8a7525 | 7 PASS, NEW 0 | X:/DevTemp/ui-role-canvas-csp-final/run-1.txt |
| Android Cam 최신 shapes·입력 서체 | ab17c6cac 포함 | 413 PASS, debug APK 빌드 성공 | X:/DevTemp/ui-role-devices/cam-gradle-5.txt |
| Android Pilot | 354b55cfb0 포함 | 105 PASS, debug APK 빌드 성공 | X:/DevTemp/ui-role-devices/pilot-gradle-1.txt |

기존 실패 43개 선택 항목 중 변경된 parametrization 한 항목은 함수 전체로 재검증하여 45개가 실행됐다. 오래된 fixture는 현재 API·준비 상태·유효 지도 목표에 맞췄으며 권한 취소, CORE 거절, no-POST 검사를 유지했다. 결과 수는 서로 겹치므로 합산하지 않는다. Python과 Chromium은 원격 시험 PC에서 실행했다.

첫 착지 검사에서 6,245 PASS·968 SKIP와 함께 canvas 서체 탐침의 인라인 스타일 쓰기 1건이 NEW로 검출됐다. 같은 파일을 기존 CSSOM 방식으로 고쳤으며 관련 7개 시험이 통과했다. 검사 규칙을 완화하거나 실패 목록에 추가하지 않았다. 폴더 이동 후 독립 검토에서 새 P1/P2는 확인되지 않았다. 공식 착지 검사는 수정된 소스에서 다시 수행한다.

## 수용 경계

공식 `tools/land.py --tests auto`는 3회 main 변경을 반영한 후 `654e88851a`를 main에 fast-forward했다. 마지막 원격 검사는 첫 호출 6,246 PASS·968 SKIP, 두 번째 호출 989 PASS·36 SKIP였으며 두 로그 모두 NEW 0이다. 로그는 `X:/DevTemp/land/uiux-ui-role-tokens/run-3-1.txt`와 `run-3-2.txt`이다. SKIP는 실행 증거로 계산하지 않는다.

푸시·CI·새 서명 설치본 검증은 실행 결과를 추가하기 전까지 미완료다. 후속 D-641 shell 통합과 함께 검증한다. 선행 `8a140aeb2` 설치본에서 1366×768·320×568 및 비상정지/알림 48/14/12를 확인한 증거는 이번 변경의 설치 증거를 대신하지 않는다. Android 실제 기기·LCD 현장 수용 및 실물 주행은 이 UI 회귀 시험에 포함하지 않았다.
