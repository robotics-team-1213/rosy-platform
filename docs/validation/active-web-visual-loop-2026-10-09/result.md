# 활성 웹 16화면 브라우저 대조 · 2026-10-09

## 범위와 방법

[활성 웹 레이아웃 와이어프레임](../../plans/2026-10-09-active-web-layout-and-navigation-design.md)의 16개 화면을 소스에서 제공하는 서버·API fixture와 로컬 Chromium 148로 열었다. 원본 캡처와 실행 출력은 `X:/DevTemp/rosy-web-visual-loop/` 및 `X:/DevTemp/rosy-{learning,games,pilot,robot,fleet}-loop-output.txt`에 보관한다. 파일 해시는 `captures.sha256`에 기록한다. Fleet은 정적 자산 서버와 읽기 API fixture, Robot은 CORE TestClient의 읽기 응답, Pilot은 가짜 CORE 개발 서버, Games는 PreviewServer, Learning은 빈 로컬 ReviewStore를 사용했다. 쓰기·로봇 이동은 하지 않았다.

| 제품 / 활성 화면 | 전화 폭 캡처 | 넓은 폭 캡처 | 확인한 역할·탐색 |
|---|---|---|---|
| Fleet 관제 | `fleet-console-320.png` | `fleet-console-1366.png` | 네 문서 탭, `/console` 브랜드, 정지 |
| Fleet 설치·보정 | `fleet-install-320.png` | `fleet-install-1366.png` | 상단 탭, 설치 선택기, 정지 |
| Fleet 현장 지도 | `fleet-map-320.png` | `fleet-map-1366.png` | 상단 탭, 지도 내부 단계 탐색, 정지 |
| Fleet Cell | `fleet-cell-320.png` | `fleet-cell-1366.png` | 상단 탭, 1–5단계·저장 문서 탐색, 정지 |
| Robot 연결 | `robot-dashboard-320.png` | `robot-dashboard-1366.png` | `/dashboard` 브랜드, 역할 화면 진입, 정지 |
| Robot 운용 | `robot-console-320.png` | `robot-console-1366.png` | 3화면 전환, `/dashboard` 브랜드, 정지 |
| Robot 작업 준비 | `robot-setup-320.png` | `robot-setup-1366.png` | 왼쪽 작업 선택, 3화면 전환, 정지 |
| Robot 설치·정비 | `robot-device-320.png` | `robot-device-1366.png` | 작업 선택, 3화면 전환, 정지 |
| Pilot 접속 | `pilot-connect-320.png` | `pilot-connect-1200.png` | 대상·접속·정지와 브랜드 홈 |
| Pilot 주행 | `pilot-drive-320.png` | `pilot-drive-1200.png` | 조종·정지·지도 인계; 390/1200px 브랜드 복귀의 정지·IDLE 기록 |
| Pilot Gazebo 팔 연습 | `pilot-arm-320.png` | `pilot-arm-1200.png` | SIM 전용·페어링 대기; 안전한 취소 전 브랜드 이동 차단 |
| Games 경기 보드 | `games-320.png` | `games-1366.png` | 피치·관측·정지, `/` 브랜드 홈 |
| Learning 작업 목록 | `learning-jobs-320.png` | `learning-jobs-1366.png` | 네 탭, `/learning` 브랜드 홈 |
| Learning 객체 검수 | `learning-object-320.png` | `learning-object-1366.png` | 작업 목록·객체·픽셀·자료 등록 이동 |
| Learning 픽셀 검수 | `learning-pixel-320.png` | `learning-pixel-1366.png` | 독립 픽셀 검수와 작업 목록 복귀 |
| Learning 자료 등록 | `learning-catalog-320.png` | `learning-catalog-1366.png` | 등록·검수 이동, 브랜드 홈 |

## 발견 → 수정 → 재확인

1. Learning 320px에서 네 번째 `자료 등록` 탭이 오른쪽으로 잘렸다. 2×2 탭으로 바꾼 뒤 네 항목의 viewport 안 표시, 가로 넘침 0, 현재 탭 표시, 브랜드 클릭 `/learning`, 브라우저 오류 0을 네 화면에서 다시 확인했다.
2. Games 이름표는 이동할 수 없고 본문 건너뛰기가 없었다. 실제 PreviewServer 홈 `/`에 링크하고 필드의 초점 대상을 추가했다. 320/1366px에서 홈 클릭·정지 표시·가로 넘침 0·브라우저 오류 0을 확인했다. 설계 그림의 `/board` 표기는 이 서버의 실제 경로와 다르며 `/`가 현재 계약이다.
3. Pilot 이름표는 이동할 수 없었다. 주행 중 브랜드 클릭은 기존 종료 절차를 사용하게 바꿨다. 가짜 CORE에서 페이지 복귀 전 `IDLE`과 선속도·각속도 0이 기록됐다. Gazebo 팔 연습은 진행 중 목표의 취소 확인 없이 이탈하지 않도록 브랜드에 `aria-disabled`를 표시하고 클릭을 차단했다. 320/390/1200px 주행·접속, 320/1200px 팔 연습에서 가로 넘침 0과 브라우저 오류 0을 확인했다.
4. Fleet과 Robot은 검사한 기본·빈 상태에서 홈·화면 이동·정지가 이미 작동했다. Fleet 관제의 3:2 지도·개입 계약과 상단 네 탭, Robot의 왼쪽 작업 선택을 유지했다.

## 판정의 한계

이 기록은 **로컬 G2 일부 셀**이다. Fleet API fixture는 실제 인증·현장 장비가 아니고, Robot의 상태는 읽기 전용 TestClient, Pilot은 가짜 CORE, Games는 PreviewServer, Learning은 빈 자료다. `fresh / delayed / disconnected / unavailable`, 권한 거부, SAFE_STOP, 입력 중 이탈, 실제 데이터가 많은 상태를 16화면 전부에서 교차 검증한 기록은 아니다. G1 전체 게이트, G2 전체 선언 셀, G3 사용자 평가, 설치 이미지와 장치·현장 readback은 별도이며 전체 상용 UI 판정은 HOLD다.
