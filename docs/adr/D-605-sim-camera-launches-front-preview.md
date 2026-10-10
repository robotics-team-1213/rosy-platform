## D-605 카메라 SIM 런치는 앞 미리보기를 내고, 그 SIM의 Fleet은 차선 카메라 검사를 켠다

**Status:** Proposed (2026-10-10, 사용자 결정 "SIM도 앞 카메라 미리보기를 줘서 D-601 차선 카메라 검사가 SIM에서도 돌게"). SOURCE 변경, 호스트 테스트, 모델 PC Gazebo 확인만 한다.

잇는 결정: [D-601](D-601-fleet-trip-start-turns-camera-line-on.md) 3항(B, SIM 사이트 설정 `lane_camera_check: false`를 이 기록이 카메라 없는 SIM으로 좁힌다).

### Context

- D-601 B는 Fleet이 lane 계획 전에 CORE `GET /api/v1/vision/front/status`를 읽는다. SIM 런치는 road observer를 띄우지 않아 미리보기가 없었고, 그래서 모든 SIM Fleet이 `fleet_sim_site.yaml`(`lane_camera_check: false`)을 썼다(main `8985ec588`).
- `map_v2_fleet_lane`·`map_v2_fleet_real`과 d495_real 계열 하네스 사본은 Gazebo 카메라를 `camera/front`로 이미 브리지한다. `gz_multi`는 카메라가 없다(`start_camera:=false`).
- road observer는 `road/observation`을 CORE `traffic_policy`에 넣는다. SIM에서 띄우면 정책 입력이 바뀐다.

### Decision

1. 카메라 SIM 런치는 `tools/sim_jpeg_relay.py`(gz_sim이 설치)로 `camera/front`를 `camera/preview/compressed` JPEG로 낸다. 이 노드는 표시용 JPEG만 내고 `road/observation`은 내지 않는다. 그래서 `traffic_policy`는 바뀌지 않는다(map_v2_fleet SIM은 `DISABLED` 그대로).
2. 릴레이는 `use_sim_time`을 쓰지 않는다. 프레임은 Gazebo 헤더 시각을 그대로 갖는다. `/clock` 구독이 코어 한 개의 약 24%를 썼다(없으면 1% 미만).
3. SIM 사이트 설정은 둘이다. 카메라 없는 SIM(`gz_multi`)은 `config/fleet_sim_site.yaml`(`lane_camera_check: false`), 카메라 SIM은 `config/fleet_sim_camera_site.yaml`(`true`). 어느 Fleet이 어느 파일을 쓰는지는 `operations/fleet/test/test_fleet_sim_site_d601.py`의 `SIM_FLEETS`가 고정한다.
4. `pinky_integrated_acceptance`는 이미 road observer로 미리보기를 내고 `traffic_policy: DISABLED`라 바꾸지 않는다. Fleet을 띄우지 않는다.

### Consequences

- 카메라 SIM에서 D-601 B 거절(`TRIP_LANE_CAMERA_UNAVAILABLE`)이 장치와 같이 동작한다. 릴레이가 죽으면 SIM lane 계획도 거절된다.
- D-604(CORE capabilities `line_follow.camera`)가 카메라 토픽에서 직접 가용성을 내게 되면 이 릴레이 없이도 검사할 수 있다. 그때 다시 본다.
- 호스트 pytest와 SIM 확인은 장치나 현장 수용을 대신하지 않는다.
