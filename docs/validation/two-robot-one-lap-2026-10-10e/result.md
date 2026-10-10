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
