# 활성 UI/UX 정보 배치와 작업 흐름 개선 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fleet와 모든 활성 사용자 표면에서 현재 대상·상태·근거·다음 행동·복구 경로를 구분하고 실제 회귀 및 설치본 증거로 확인한다.

**Architecture:** 기존 표면 등록부 `shared/web/surfaces.yaml`, 공용 토큰·부품, 역할별 HTML/CSS/ES modules와 native 구현을 유지한다. Fleet의 D-658 헤더는 제품·현장, 연결·권한, 알림·접속, 안전 조작을 나눈다. 다른 표면은 같은 정보 구분을 각 역할과 화면 문법에 맞게 적용한다. 본문은 현재 상태와 근거, 주 작업, 예외·복구, 상세 진단 순으로 검토한다.

**Tech Stack:** 기존 Web Components, Chromium/Playwright, 원격 pytest, Android Kotlin 및 LCD PIL. 신규 의존성은 추가하지 않는다.

## 범위와 소유

| 표면 | 헤더와 본문의 역할 | 수정·검증 경로 |
|---|---|---|
| Fleet 관제·설치·지도·Cell·작업 | 현장·권한·연결·안전 구분, 관측과 작업 원장, 설치·지도·Cell의 단계별 다음 행동 | `operations/ui/console/`, `operations/fleet/test/test_fleet_header*.py`, `test_cell_app_browser.py` |
| Robot 접속·운용·작업 준비·설치 정비 | 대상 로봇·역할·접속·안전 구분, 현재 상태에서 권한별 작업으로 이동 | `middleware/ui/robot/`, `test_dashboard_entry_browser.py`, `test_surface_entry_browser.py` |
| Pilot 웹 | 선택 대상·연결 근거·운전석 권한·안전 구분, 접속 실패와 조종 준비를 분리 | `middleware/ui/pilot/`, `test_pilot_browser.py` |
| Learning 작업·객체·픽셀·자료 | 작업과 자료 출처, 검수 상태, 수정·저장·승인 구분, 좁은 화면의 작업 영역 확보 | `learning/curation/perception/review_app_web/`, `test/learning/perception/test_review_flow_browser.py`, `test_pixel_review_browser.py` |
| 경기 보드 | 경기 단계와 수신 근거, 점수·관측·정지 흐름 | `operations/apps/games/games/web/`, `test/test_games_board_browser.py` |
| Pilot Android | 신뢰된 대상 발견·선택·접속, 함께 조종의 장치별 근거와 안전 | `middleware/ui/pilot/android/` 및 기존 Gradle/JVM 검사 |
| Cam Android | 카메라 대상·송출 상태·설치·복구, 승인·송출 상태 구분 | `operations/ui/cam/` 및 기존 Gradle/JVM 검사 |
| 로봇 LCD | 로봇 정체성·부팅·로그인 코드와 판독성 | `middleware/ui/face/`, `test_info_screen.py` |
| 공용 부품·template·styleguide | 접근성 이름·focus 설명·상태·누름면·토큰 일관성 | `shared/web/test/` |

PARKED 제어 진단과 개발용 simulation lane viewer도 등록부에서 확인하되 활성 제품 표면으로 되살리지 않는다. Cam과 LCD에는 로봇 명령 권한이 없으므로 운용 화면의 비상정지나 접속 조작을 복사하지 않는다.

## 실행 순서

1. 등록부와 각 모듈 계약, 현재 main 및 설치본을 확인한다. 공유 main의 다른 세션 변경은 보존하며 각 영역은 자신의 worktree에서 수정한다.
2. 기존 브라우저 시험과 실제 설치 화면을 읽고 정보 위계·상태 거짓 정상·넘침·불명확한 다음 행동을 재현한다. 재현된 실패와 실제 사용자 흐름에 필요한 변경만 한다.
3. 공용 부품의 호출자 속성·접근성·CSP를 보존한다. 아이콘 전용 버튼은 명시된 기존 속성을 유지하는 회귀로 검사한다.
4. Robot/Pilot 웹, Learning, native/LCD/경기 영역을 각 소유 브랜치에서 구현·커밋하고 원격 회귀의 종료 결과와 known_failures 비교를 받는다. 자원 부족 fallback 결과는 적정 자원 수용 증거로 승격하지 않는다.
5. 변경을 검토하고 이 작업 브랜치에 통합한다. 공용 규격, 표면별 브라우저 및 변경된 설치 목록 검사를 완료한다. 계획·수정·원격 회귀·CI·배포·실제 장치 수용을 별도로 기록한다.
6. 기존 Fleet 설치본은 읽기 전용으로 직접 확인한다. 새 변경의 main 착지·push는 저장소 규칙대로 사용자의 명시 지시 뒤 수행한다. 적용 가능한 배포 절차와 정확한 SHA의 CI·서명 설치 증거를 확보한 뒤 설치본에서 재확인한다.

## 확인 기준

- 해당 역할의 상태·출처·다음 행동이 선언 뷰포트에서 읽히고 가로 넘침이 없다.
- 실패·거부·연결 끊김·미확인 상태를 정상 또는 완료로 표시하지 않는다.
- 비상정지 접근성, 명령 권한, CORE 최종 실행 권한, 학습 검수 승인과 초안의 구분을 유지한다.
- 브라우저 캡처는 실제 배포 화면 및 native 실기기 수용과 구분한다. 접속할 수 없는 로봇이나 연결되지 않은 Android 기기의 설치본은 확인 못 함으로 남긴다.
