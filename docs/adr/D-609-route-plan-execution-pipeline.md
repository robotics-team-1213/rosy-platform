## D-609 경로 계획부터 실행 완료 증거까지 하나의 Fleet trip 파이프라인으로 잇는다

**Status:** Accepted (2026-10-10, 사용자 요청: path planning·waypoint·path execution을 하나의 파이프라인과 ADR로 명확히 함). 설계 결정이며 이 문서만으로 새 장치 동작이나 현장 수용이 생기지 않는다.

잇는 결정: D-9(로봇 웨이포인트), D-463(짧은 자유 주행 목표), D-488·D-489·D-490(현장 지도와 경로 계획), D-494(실행 상태기), D-517(교통·재계획), D-541(trip lease), D-550(목표 lease), D-594(지난 경로 기록), D-601(차선 출발).

### Context

같은 "경로"라는 말이 세 대상을 가리킨다. 로봇의 `~/.rosy/waypoints.json`은 이름 붙인 **단일 자세**이고, Nav2 `NavigateToPose`는 그 자세까지의 로봇 국소 계획·추종을 맡는다. Fleet `via`는 활성 사이트 지도의 **경유 장소 순서**이며 `fleet.routing.trip.plan_trip`이 방향 있는 차로 구간을 계획한다. Fleet `TripRunner`는 그 구간을 `lane` 또는 `free` 방식으로 실행한다. Nav2 설정에 `waypoint_follower`가 있어도 현재 로봇 API는 `FollowWaypoints` 미션을 제공하지 않는다.

현재 `TripProgress._arrived`는 `free` 마지막 구간에서 지도 자세의 남은 거리, `lane`에서 CORE 정지 지시 수락과 지도 자세를 사용한다. `trip.state=arrived`는 이 **Fleet 소프트웨어 판정**이다. Nav2 마지막 액션의 성공, 최종 구동 출력 0, 바퀴 정지, 물리적 도착을 모두 증명한 필드로 읽으면 안 된다. D-594의 지나온 길도 관측·표시 기록이지 경로 실행 권한이나 완료 증거가 아니다.

### Decision

1. **단일 주인과 식별자.** 여러 지점·차로·반복 운행은 Fleet trip 하나가 계획과 실행을 소유한다. `plan_id`는 저장된 계획의 식별자이고 `/start` 뒤 같은 값이 `trip_id`다. 로봇의 저장 웨이포인트 `name`은 단일 목표 선택에만 쓴다. Fleet 경유지는 활성 사이트 지도 `place_id`로 적는다. 서로 자동 변환하지 않는다. 외부 클라이언트는 ROS 액션을 직접 호출하지 않고 Fleet 또는 CORE API를 쓴다. 최종 `/cmd_vel`은 CORE 하나가 발행한다.
2. **계획 단계.** 이름 있는 운영자의 `POST /api/fleet/robots/{robot_id}/trip`은 활성 지도 버전, 신뢰된 지도 자세, 로봇 종류·`drive_modes`·속도 한도, 목표와 순서 있는 `via`를 입력으로 삼는다. D-489의 차로 상태 A*가 방향·회전·금지·차단 간선을 고려해 `segments`, `places`, `actions`, 거리·예상 시간을 만든다. 계획 응답과 감사 기록에 `plan_id`를 남기고 **로봇을 움직이지 않는다**. `execute: true`는 실행 지름길이 아니다.
3. **실행 승인 단계.** `/api/fleet/trips/{plan_id}/start`는 별도 운영자 동작이다. 저장 계획의 30 s 유효기간과 지도 버전, 로봇 능력·현재 모드·위치 신뢰도, 첫 차로 정렬, 차선 카메라, 다른 이동 주인, 필요한 trip lease를 다시 검사한다. 어느 하나라도 거절되면 계획을 실행했다고 기록하지 않는다. 지도나 자세가 계획 후 바뀌었으면 다시 계획한다.
4. **구간 실행 단계.** `TripRunner`의 0.5 s 루프가 현재 지도 자세를 계획 구간에 투영한다. `lane`은 CORE 차선 추종과 다음 장소의 교차점 지시·통행권을 쓰고, `free`는 D-463의 짧은 전방 점을 CORE 목표 API에 보내 Nav2가 그 점의 국소 경로를 계획·추종하게 한다. Fleet은 Nav2의 내부 경로를 차로 계획으로 간주하지 않는다. CORE의 목표 수락은 이동 완료가 아니다. 모든 구간은 `trip_id`, `segment_index`, 지도 버전과 함께 읽을 수 있어야 한다.
5. **진행·재계획 단계.** Fleet은 지도 자세, 차로 이탈, CORE 교차점 상태, 목표 거절, 정체, 지도 변경과 차단 간선을 본다. 차로 변경 계획은 다음 장소에서 정지·보류하고 운영자 `/confirm-replan` 뒤에만 새 구간을 실행한다. 위치가 `LOCALIZED`가 아니거나 명령·연결·lease가 불명확하면 새 이동을 계속 승인하지 않고 기존 정지 경로를 사용한다. 재시작은 자동 재개하지 않는다.
6. **종료 의미와 증거.** 기존 `started → running → arrived|stopped|failed|canceled`를 유지한다. `arrived`는 D-494의 **경로 진행 판정**으로만 표시한다. 운영·검증 기록은 별도로 (a) 계획: 지도 id·버전·해시와 계획 구간, (b) 전송: 각 구간의 CORE 수락 또는 거절과 상관 식별자, (c) 진행: 시각·출처가 있는 지도 자세와 구간 전환, (d) 종료: Nav2 결과(`free`) 또는 CORE 정지 상태(`lane`), 최종 명령·바퀴 정지 readback을 연결한다. 일부가 없으면 그 증거는 `UNKNOWN`으로 남기며 `arrived`에서 추론해 채우지 않는다. 기존 `GET /api/v1/navigation/path`의 마지막 경로도 현재 목표와 상관이 확인되기 전에는 (b)·(d)를 증명하지 않는다.
7. **수용 관문.** SOURCE는 계획→저장→시작→구간 지시→재계획·취소→종료의 계약 시험, ROS-SIM은 같은 `trip_id`의 지도·목표·CORE 출력·참값 도착, DEVICE는 설치 이미지·ROS 그래프·실제 CORE 목표/정지 readback, FIELD는 운영자가 고른 한 로봇·한 경로의 물리적 완주와 안전 정지 확인이다. 앞 단계의 PASS를 뒤 단계의 PASS로 승격하지 않는다. 실물 경로 주행은 기존 D-494·D-601 장치·현장 관문을 따른다.

### 구현 순서와 판정

- 기존 `fleet.routing`·`TripRunner`·CORE `NavigateToPose` 연결을 재사용한다. 새 계획기, Nav2 `FollowWaypoints` API, 두 번째 `/cmd_vel` 발행기를 만들지 않는다.
- 먼저 현재 `arrived`와 독립적인 종료 증거를 같은 trip에 연결할 수 있는지 계약 시험으로 확인한다. 특히 마지막 `free` 목표의 Nav2 결과와 최종 정지 readback이 없는 경우를 성공 증거로 분류하지 않는다. 필요한 상관 필드가 기존 API에 없으면 D-18 절차에 따라 API Reference와 스키마를 함께 개정한 뒤 구현한다.
- `lane`과 `free`, 단일 목표와 `via`, 정상 도착·목표 거절·위치 상실·취소·재계획·Fleet 재시작을 시험한다. 호스트 fake의 `arrived`와 ROS-SIM·DEVICE·FIELD 증거를 따로 보고한다.

### Consequences

운영자는 계획 미리보기와 실행 시작을 분리한 채 한 trip의 진행을 따라갈 수 있다. `arrived`라는 상태명은 유지되지만 물리적 완료 보증으로 확장되지 않는다. 종료 증거 연결과 현장 수용이 남은 동안 파이프라인은 **SOURCE 계약과 구현 연결 수준**이며 실물 자동 경로 주행 완료로 선언하지 않는다.
