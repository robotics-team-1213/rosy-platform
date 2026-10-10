# 두 로봇 한 바퀴 현장 재확인, 2026-10-10 16:47 KST

**판정: 현장 주행 HOLD.** AI PC의 기존 `ai_observer` 권한으로 Fleet 상태·trip·활성 지도·AI 상태·로봇별 지도 자세를 읽고, 현장 PC의 실행 중 컨테이너 이미지 태그를 읽었다. 주행·모드·E-Stop 명령은 보내지 않았다. 주소와 토큰은 기록하지 않는다.

| 항목 | 읽은 값 | 출발 판정 |
|---|---|---|
| Fleet 설치 | `rosy-site-fleet:d81cfad3555cddb8b0b24eeccc69e7ade5eb5371`, 컨테이너 healthy | Git의 이번 후보 `c785edc7f`는 설치 SHA의 조상이 아니다. 유한 한 바퀴 변경 미설치 |
| 지도·trip | `map_v2_fleet` v5, 열린 trip 0 | 기존 지도는 사용 가능, 실주행 없음 |
| AI PC | `rosy-situation` v0.2.0, `owner_mode:shared`, heartbeat present, facts 0 | 후보 v0.3.0의 `trip_route_check` 미설치 |
| `rosy_40` | 온라인, IDLE, line-follow OFF, 지도 자세 `LOCALIZED` (-1.3300, 0.0025), `W_mid`까지 0.0352 m, 차로 WARN/몸체 여유 0.0016 m | 출발 장소 0.05 m 거리만 충족. `junction_turn:false`, 자세 yaw 약 -1.539 rad, sighting anchor age 2.13 s는 현재 시작 제한 2 s보다 큼. 방향·능력 근거 재확인 필요 |
| `rosy_41` | 온라인, IDLE, line-follow OFF, 지도 자세 `LOCALIZED` (0.1031, -0.5222), `E_mid`까지 0.7529 m, 차로 OK/몸체 여유 0.0209 m | `junction_turn:true`이나 선택 출발점 0.05 m 거리 미충족 |

자세와 여유 값은 시간에 따라 변한다. 위 두 좌표·방향은 출발 명령 직전의 증거가 아니며, Fleet은 계획 시와 시작 시 새 자세를 다시 검사해야 한다. 설치 후보·AI PC 버전, `rosy_40` 교차로 회전 근거, 두 로봇의 출발 자세와 방향, Gazebo 차체 간격, 독립 영상 계측을 확인하기 전에는 동시 한 바퀴를 시작하지 않는다. 차체 경계에 관한 별도 분석은 [대조 기록](../two-robot-one-lap-2026-10-10d/result.md)에 있다.

읽은 자세를 활성 지도 v5의 호에 투영한 오프라인 계산에서 `rosy_40`은 `west_out:fwd`·`west:fwd` 중심선에서 각각 약 0.034·0.035 m, 진행 방향 차이는 약 -0.4°였다. 이 한 시점의 방향은 20° 시작 한도 안이지만, `junction_turn:false`와 신선한 sighting 조건을 해소하지는 않는다. `rosy_41`의 `east_out:fwd` 진행 방향 차이는 약 -5°였으나 선택 출발점에서 0.7529 m 떨어져 있었다.

## 17:12 KST 후보 재검증

브랜치 `feat/one-lap-current`의 `2c43968d5`에서 유한 한 바퀴 시작 직전 첫 경로의 차체 여유가 음수이면 출발을 거절한다. 원격 AI PC에서 차체 이탈 출발 거부와 두 로봇의 각자 원위치 도착을 포함한 Fleet 시험 27개, Fleet·AI 관련 회귀 시험 175개가 통과했다. 두 로그는 각각 `X:/DevTemp/one-lap-body-start-fixture/run-1.txt`, `X:/DevTemp/one-lap-body-start-regression2/run-1.txt`이고 `known_failures.py` 결과는 두 실행 모두 NEW 0, KNOWN 0이다. `rosy_harness.py lint`는 오류 0, 기존 검증 상태 경고 24개였고 `safety_review.py main HEAD`는 34개 커밋을 검사해 통과했다.

이 증거는 후보 코드와 가짜 CORE의 동작 범위다. Fleet의 **주행 중** trip 이탈 정지는 아직 중심점 기준이고 AI PC의 차체 기반 경로 사실은 그림자 판정이므로 실제 이탈 방지를 입증하지 않는다. 후보 Fleet 이미지·AI PC 버전이 현장에 설치되지 않았고, Gazebo와 장치·현장 주행 검증도 열려 있다. 현장 HOLD와 출발 조건은 위 판정 그대로다.

## AI 경로 편차의 관제 연결

`65c834b0c`에서 관제의 AI 사실 조회 조건을 교착 발생뿐 아니라 열린 trip에도 적용했다. 같은 로봇·trip·지도 버전의 최신 유효 `OFF_ROUTE` 사실은 차체 허용 경계 초과 거리와 위치 확인 경고로 표시한다. 오래된 사실, 다른 운행·지도, 비정상 수치, 새 `ON_ROUTE`·`UNKNOWN`, trip 종료는 경고를 내지 않는다. 관련 Node 26개 시험을 확인했고, 원격 AI PC에서 전체 관제 Node 시험을 실행하는 `test_console_web_node_unit_tests_pass`를 포함한 `test_site_map_api.py`, `test_console_disabled_features.py`, `test_console_palette.py` 45개 시험이 통과했다(`X:/DevTemp/one-lap-ai-route-queue/run-1.txt`, NEW 0·KNOWN 0). lint 오류 0·경고 24개, Safety-Review 36개 커밋 검사가 통과했다.

이 표시는 AI 관찰을 운영자에게 전달하며 로봇을 움직이거나 정지시키지 않는다. 실제 브라우저 렌더와 현장 설치·주행 수용은 이 시험에 포함되지 않는다.
