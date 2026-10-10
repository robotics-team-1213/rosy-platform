# 두 로봇 지도 경로 한 바퀴 현장 검증 Implementation Plan

**Goal:** 관제에서 각 로봇의 출발·복귀 장소와 경유 장소를 정한다. Fleet은 활성 지도에서 두 개의 1회 경로를 계산하고 교통 허가를 나누어 주행시키며, 각 로봇은 한 바퀴 뒤 출발 장소에서 정지한다. Fleet은 주행 중 지도 자세와 계획 경로의 이탈을 감시한다. AI PC는 독립된 관찰 결과를 Fleet에 기록하되 정지 권한은 Fleet·CORE에 둔다.

**Architecture:** 기존 `POST /api/fleet/robots/{id}/trip`의 `to`·`via` 계획, `POST /api/fleet/trips/{id}/start`의 실행, D-517 교통 블록, D-494 경로 이탈 정지를 재사용한다. `repeat: false`인 유한 경로로 한 바퀴를 표현한다. 관제의 출발 장소 선택은 두 로봇 각각에 대해 별도 계획·시작·취소를 만든다. AI PC 판단은 동일한 Fleet 결과를 되풀이하는 대신 지도, 계획 구간, 시각이 붙은 자세에서 경로 이탈을 따로 계산하여 그림자 사실로 제출한다.

**Tech Stack:** ROS 2 Jazzy CORE, Fleet FastAPI/Pydantic·표준 라이브러리 경로 계획기, 관제 JavaScript, AI PC `rosy-situation`, 원격 pytest/Gazebo.

---

## 확정된 운행 목표와 현재 상태

- 최초 목표는 **두 로봇 각각 한 바퀴 후 원위치 정지**다. 이후 경로는 관제 운영자가 지도에서 정한다. 현장 로봇은 `rosy_40`, `rosy_41`; 활성 지도는 `map_v2_fleet` v5다. 현재 지도에서 복귀 정지 후보는 `W_mid`와 `E_mid`(파란 B)다. 실제 출발점은 시작 직전 Fleet의 지도 자세와 관제 선택으로 확정한다.
- 지도는 일방통행이다. 예시 경로는 `W_mid → SW_line → SW → SE → SE_line → E_mid → NE_line → NE → NW → NW_line → W_mid`와 그 반대 출발 순환이다. 경유 `E_mid`/`W_mid`를 사용해 짧은 동일 장소 도착 경로를 피한다. 계획의 실제 `segments`와 `actions`를 승인 전에 화면에 그린다.
- 2026-10-10 현장 읽기: 두 로봇 온라인, 열린 trip 0, AI 상황 서비스 heartbeat 있음. `rosy_40`은 `junction_turn:false`, `rosy_41`은 `junction_turn:true`; 두 로봇 모두 `goal_navigation:false`, `lane_arc:false`. Fleet 실행 검사는 차로 경로에 `junction_turn`을 요구하므로 `rosy_40`의 현재 능력으로는 동시 한 바퀴를 시작할 수 없다. 능력 값을 강제로 참으로 바꾸지 않는다.
- AI PC의 현재 분석기는 정체·후방 막힘·로봇 앞 장애 및 교통 교착을 판단한다. 경로 이탈 사실은 아직 만들지 않는다. Fleet의 기존 trip 경로 이탈 판정과 차로 적합성 알림은 AI PC의 독립 판정이나 물리적 무이탈 증거가 아니다.
- 현장 Fleet 설치 SHA `e6ffe9c2eb9359f22d081a154be9f41c5d2866de`에는 `fix/trip-offroute-stop`의 자유 주행 이탈 취소 수정이 없다. 최종 전달에는 그 수정을 포함하고 설치 SHA를 다시 읽는다.

## Task 1. 관제의 유한 한 바퀴 계획

**Files:** `operations/fleet/fleet/server/web/card-trip.js`, `operations/fleet/fleet/server/web/shared/site-map-model.js`, 관련 `operations/fleet/test/web/*`, 필요 시 `operations/fleet/test/test_console_card_trips_browser.py`.

1. 두 개 이상의 정지 가능한 장소가 있는 지도에서 각 로봇의 출발·복귀 장소와 반대편 경유 장소를 관제에서 고른다. 현재 지도는 `kind:start`가 없으므로 기존 무한 반복 선택기에 의존하지 않는다.
2. `to=<출발 장소>, via=[<경유 장소>], repeat=false` 계획을 먼저 요청한다. 계획 응답의 지도 버전, 구간, 거리, 시작 자세 검사를 보여 주고, 별도 시작 버튼으로만 실행한다. 시작 장소에서 멀리 있는 로봇을 한 바퀴로 오인하지 않도록 계획과 시작 양쪽에서 출발 장소 근접성을 검사한다. 그 검사에는 현행 API 계약의 개정과 회귀 시험이 필요하다.
3. 두 로봇은 별개 계획과 별개 취소를 갖는다. 두 번째 시작이 교통 블록·교차로·능력 검사에서 거절되면 첫 번째 운행을 몰래 재시작하거나 취소하지 않는다.

## Task 2. Fleet 경로 준수와 AI PC 그림자 판정

**Files:** `operations/fleet/fleet/server/trip_runner.py`, `operations/fleet/test/test_trip_runner.py`, `operations/situation/rosy_situation/{service,analyzers}.py`, Fleet AI 사실 계약·시험, API reference·ADR.

1. `fix/trip-offroute-stop`의 0.5 s 이탈 시 실제 정지/자유 목표 취소 수정과 시험을 합친다. 지도 자세가 `LOCALIZED`가 아니거나 오래되면 주행을 중단한다. 판단은 계획에 들어 있던 구간에 한정하고 거리·자세 시각·지도 버전·중단 사유를 기록한다.
2. AI PC는 열린 trip, 그 계획 구간, 활성 지도, 시각이 있는 로봇 자세를 읽는다. 자체 점 대 선분 거리 계산으로 계획에서 벗어났는지 검사하고, 입력이 오래되었거나 지도 버전이 다르면 `UNKNOWN`으로 남긴다. 차로 적합성 점수만 복사해서 독립 판정이라고 부르지 않는다.
3. AI 판단은 새 그림자 사실과 관제 경고로 기록한다. AI PC가 `/cmd_vel` 또는 로봇 REST를 직접 호출하지 않는다. Fleet의 주행 차단 규칙은 AI 결과가 없어도 동작해야 한다. AI 통신 장애·지연·오탐 주입 시험을 추가한다.

## Task 3. 기기와 현장 허가

1. 두 로봇의 설치 이미지 SHA, CORE 능력, 카메라 `keep` 근거, 교차로·굽이 능력, E-Stop, 신선한 IR·LiDAR·지도 자세, trip lease, 현장 지도 ID를 읽는다. `rosy_40`의 `junction_turn:false` 원인을 설치/센서/안전 근거에서 찾고 실제 근거가 회복될 때까지 운행을 보류한다.
2. 모델 PC의 격리된 Gazebo에서 현장 지도와 동일한 버전·차로폭·차체 크기로 두 로봇 동시 한 바퀴, 교차로 정지, 경로 이탈, 자세 상실, 로봇 간 정지 거리, 두 번째 시작 거절, 통신 단절을 재생한다. 독립 참값으로 몸체 경계 침범 0과 정지 거리를 판정한다. 기존 단일 로봇 SIM 도착 결과는 수용 근거가 아니다.
3. 서명된 후보를 현장 Fleet·두 CORE·AI PC에 적용한 뒤 SHA/설정/권한을 다시 읽는다. 한 로봇 저속·빈 구역으로 차로 준수와 정지를 검증한 후 두 로봇을 각기 다른 정지 장소에서 동시에 시작한다. 관제 화면에 두 계획을 그려 구간·방향·교통 점유·실시간 자세·편차·AI 사실을 기록한다.
4. 성공 판정은 **두 trip `arrived`**, 각 로봇의 실제 정지 및 시작 장소 복귀, 계획 구간 이탈 없음, 최소 차체 간격·정지 거리 충족, Fleet/AI/CORE 로그와 독립 영상 시각 일치다. 한 로봇만 도착하거나 안전 근거가 빠지면 미완료로 둔다. E-Stop 해제나 강제 능력 광고를 검증 수단으로 쓰지 않는다.

## 검증 명령과 증거 경계

- 소스 변경은 전용 worktree에서 경로별로 스테이징·커밋한다. 노트북 pytest 금지: `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/one-lap -- operations/fleet/test/test_trip_runner.py operations/fleet/test/test_site_map_trip.py -q` 후 `python test/known_failures.py X:/DevTemp/one-lap/run-1.txt`. AI PC 시험도 원격 시험 PC를 사용한다.
- Gazebo는 `python tools/remote/remote_pytest.py --pick sim`이 고른 PC에서 실행한다. 호스트 pytest 통과를 장치·현장 증거로 바꾸지 않는다.
- 결과를 `docs/validation/two-robot-one-lap-2026-10-10/`에 코드/지도/이미지 SHA, 명령과 응답, 두 trip의 시각별 상태, 안전 수치, AI PC 사실, 현장 영상 근거로 남긴다. 사람의 현장 감독과 복귀 확인을 마지막 수용 조건으로 둔다.
