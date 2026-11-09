## D-1003 Fleet은 free 구간의 Nav2 목표를 로봇 자기 지도 프레임으로 바꿔 보낸다

**Status:** Accepted (2026-11-09, 사용자 지시: "Fleet R이 관리하는 Pinky가 이미 있는 지도에서 Nav2로 주행, 대형 주행까지"). SOURCE와 Gazebo SIM까지다. 기체·현장 수용은 없다.

잇는 결정: [D-2](D-2-cmd-vel.md)(최종 `cmd_vel`은 CORE 하나), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md)(목표 결과 상관), [D-463](D-463-fleet-lane-route.md)·[D-609](D-609-route-plan-execution-pipeline.md) 4항(free 구간은 짧은 앞 점을 CORE 목표 API로), [D-725](D-725-native-sim-map-pose-binding.md)(SIM 위치 결속), [D-758](D-758-robot-held-site-anchor.md), [D-989](D-989-fleet-auto-locate-observation.md)(현장 지도와 기체 지도 맞춤).

### Context

2026-11-09 코드와 R(`rosy-fleet-r`)의 Fleet DB를 읽은 결과다.

1. **기체 Nav2는 자기 지도 위에서 돈다.** `rosy-navigation.service`의 AMCL·map_server는 기체가 SLAM으로 만든 `/var/lib/rosy/maps/site.yaml`을 쓴다(D-321). 프레임 이름은 `map`이지만 Fleet 현장 지도의 좌표계가 아니다.
2. **Fleet 현장 지도는 차로 그래프다.** `rosy.site_map/1`은 장소·차로 폴리라인·벽 선분이다. R의 7개 버전(`site`, `map_v2_fleet`, `world_261026`)은 모두 차로 간선만 있고 `free` 간선과 벽은 0개다. 점유격자가 아니고, 차선 페인트는 LiDAR에 보이지 않아 이 지도로 AMCL을 돌릴 수 없다.
3. **free 구간 목표가 현장 좌표 그대로 나갔다.** `TripSteps._step_free`가 현장 지도 위 점을 `/api/v1/navigation/goal`에 그대로 보냈다. 두 프레임이 같은 Gazebo 결속(`map_from_world` 0)에서만 맞는다. 천장 sighting(D-587)이나 D-989 auto-locate로 위치를 잡는 기체는 Fleet 자세가 현장 프레임이고 Nav2는 SLAM 프레임이라, 목표가 다른 곳에 떨어진다.

### Decision

1. **위치 추정은 기체가 계속 한다.** 기체는 자기 LiDAR 지도에서 AMCL로 위치를 잡는다. Fleet은 점유격자를 만들거나 기체에 보내지 않는다.
2. **목표를 보내기 직전에 프레임을 바꾼다.** 같은 몸을 두 프레임에서 본 짝 하나로 `T = 기체 자세 ∘ 현장 자세⁻¹`를 만든다. 현장 자세는 그 trip 주기의 Fleet 주행 자세(`driving_pose`)이고, 기체 자세는 같은 주기의 CORE 상태 `pose`(`localization.state=LOCALIZED`, `pose_frame=map`)다. 두 프레임이 같으면 목표는 그대로다. 같은 장소 재전송 판정(`goal_resend_m`)과 진행 표시는 현장 좌표로 한다.
3. **기체 지도 자세가 없으면 예전처럼 현장 좌표를 보낸다.** 짝을 만들 수 없으면 변환하지 않고, 기존 콘솔 신뢰 판정(D-395 UNTRUSTED면 대기·거절)과 CORE 승인이 결정한다. 충전 복귀처럼 CORE 충전소 owner가 D-395 상태 없이 움직이는 경로를 바꾸지 않기 위해서다(호스트 시험 `test_station_camera_pipeline*`이 이 경로를 지킨다). SIM 1~4회차에서는 이 자리를 거절로 두어 LOCALIZED가 없을 때 목표가 하나도 나가지 않는 것을 확인했다.
4. **free 구간 목표는 구간 끝 장소 하나다(D-463의 0.2 m 앞 점을 대체).** CORE는 Nav2가 목표를 수행하는 동안 새 목표를 409 `NAVIGATION_ACTIVE`로 거절한다(`navigation/manager.py`, "cancel first"). SIM 5회차에서 앞 점 방식은 두 번째 전송에서 trip을 실패시켰다(6 cm 이동). 그래서 구간마다 끝 장소를 한 번 보내고, 앞 구간 목표가 아직 끝나지 않아 409가 오면 trip을 끝내지 않고 다음 주기에 다시 보낸다. 구간 사이의 경로는 Nav2가 정하므로 굽은 간선에서는 차로 폴리라인을 벗어날 수 있고, 그때는 기존 이탈 판정(`off_lane_m`)이 trip을 세운다. Fleet의 free 도착·다음 구간 판정 거리는 0.05 m에서 0.15 m로 넓혔다. Nav2는 목표 반경 0.10 m 안 어디서나 서고, Fleet 자세와 AMCL 자세의 차이가 더해진다(SIM 6회차 0.075~0.093 m, 8회차 0.101 m에서 정체). 그래서 0.15 m보다 짧은 free 구간은 한 주기에 지나가고, 끝에서 0.15 m 안에서 시작한 trip은 목표 없이 도착으로 끝난다. 409를 기다리는 동안의 CORE 사유는 trip `detail.goal_wait`에 보이고, 풀리지 않으면 기존 정체 판정(20 s)이 trip을 세운다.
5. **CORE와 API는 바꾸지 않는다.** 경로는 그대로 Fleet trip → CORE `/api/v1/navigation/goal` → Nav2 `NavigateToPose` → `nav_cmd_vel` → CORE 최종 `/cmd_vel`이다(D-2). 결과는 D-316 이벤트와 trip 화면으로 본다.
6. **짝은 trip 위치 포트가 자세를 만든 그 CORE 스냅숏에서 읽는다.** 운영은 `MapPoseService.state`(그 주기의 REST 읽기 재사용), Gazebo SIM은 `NativeGazeboMapPosePort.state`다. 스냅숏을 주지 않는 포트(호스트 시험의 이상 위치 plant)는 예전처럼 현장 좌표를 보낸다. Fleet 앱이 별도 상태 읽기를 하나 더 넣으면 읽기 순번(D-760 8)이 바뀌어 충전 복귀 시험(`test_station_camera_pipeline*`)이 DOCKING에 닿지 못했다.

### 한계

- 두 자세는 한 주기 안의 서로 다른 읽기다. 그 사이 움직임만큼(속도 × 읽기 간격) 목표가 밀린다. 목표는 구간마다 한 번 보내므로 그 구간 동안은 이 오차가 남는다. 더 정확해야 하면 스냅숏의 odom 시각으로 짝을 맞춘다.
- R의 지도에는 `free` 간선이 없어서 이 변경만으로 R에서 Nav2 주행이 일어나지 않는다. 차로를 Nav2로 달리려면 운영자가 해당 간선을 `free`로 바꾼 지도 버전을 활성화해야 한다. 이는 현장 운영 결정이다.
- Fleet 교행 판정(`console._goal`)은 각 기체가 돌려준 계획 경로를 서로 비교한다. 기체마다 Nav2 지도가 다르면 그 비교는 맞지 않는다. 여러 대가 서로 다른 SLAM 지도로 free 구간을 함께 달리기 전에 경로도 현장 프레임으로 바꿔야 한다.
- 모터 모드 기체(Nav2 없음)는 `drive_modes`에 `free`가 없어 free 구간 계획 자체가 나오지 않는다. 변환 거절은 그 밖의 경우(AMCL이 아직 LOCALIZED가 아님)에만 보인다.
- 기체 SLAM 지도와 현장 지도의 관계는 위치 소스(sighting·auto-locate)의 정확도를 그대로 물려받는다. 그 정확도는 실물에서 재지 않았다.

### 검증

- 호스트: `operations/fleet/test/test_trip_robot_frame_goal.py`(90° 돌고 (2, 3) 옮긴 기체 지도, 같은 프레임, 지도 자세 없으면 그대로), `test/test_fleet_trips.py`.
- SIM: `tools/sim/fleet_trips.py --nav`. 두 기체가 Gazebo 월드 지도에서 Nav2+AMCL로 돌고, Fleet 현장 지도와 D-725 결속은 월드를 90° 돌리고 (2, 3) 옮긴 프레임이다. 변환 없이 보낸 목표는 기체 지도에서 3 m 넘게 벗어난다.

### 기각

- **현장 지도를 점유격자로 만들어 기체에 배포:** 벽이 없고 차선 페인트는 LiDAR가 못 본다. 지도 배포·서명·버전 고정 경로도 새로 필요하다.
- **CORE 목표 API에 `frame: odom`을 추가:** Nav2는 TF로 처리할 수 있지만 CORE 계약과 API 버전이 바뀐다. 이번 목적에는 Fleet 안의 변환으로 충분하다.
- **D-989 변환의 역만 적용:** auto-locate를 켠 기체만 다룬다. 이 방법은 위치 소스와 상관없이 같은 짝으로 계산한다.
