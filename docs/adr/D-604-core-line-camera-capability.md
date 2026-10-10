## D-604 CORE가 차선 카메라 상태를 capabilities에 싣고, Fleet 차선 계획 검사는 그 값을 읽는다

**Status:** Proposed (2026-10-10, 사용자 결정 "CORE reports the line camera health in capabilities; Fleet lane admission reads it"). SOURCE 변경과 호스트 테스트만 한다. 사이트 배포와 현장 수용은 이 기록이 하지 않는다.

잇는 결정: [D-601](D-601-fleet-trip-start-turns-camera-line-on.md) B항(계획 때 차선 카메라 검사, 이 기록이 읽는 곳을 바꾼다) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 1항(trip caps) · D-32(지킬 수 있는 것만 광고). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

- CORE `GET /api/v1/system/capabilities`는 line-follow 서비스가 있으면 `drive_modes`에 `lane`을 넣는다(`core_api_web/api/v1/system.py`). 카메라는 보지 않는다. rosy_40(8kcn)은 앞 카메라가 죽어 있다.
- D-601 B는 그래서 Fleet이 계획 때 로봇의 `GET /api/v1/vision/front/status`를 따로 부른다. 계획마다 로봇 호출이 하나 더 늘고, 그 판단이 능력 표면 밖에 있다.
- Gazebo SIM은 앞 미리보기를 내지 않아 `fleet.trip.lane_camera_check: false`로 그 검사를 꺼야 했다.

### Decision

1. **CORE 능력 필드.** capabilities 최상위에 선택 필드 `line_follow: {camera: {available, age_ms, source}}`를 더한다. line-follow 서비스가 없으면 필드가 없다. 값은 `GET /vision/front/status`가 읽는 미리보기 저장소(`svc.vision.status()`) 하나에서 계산한다. 판단 원천은 하나다.
   - `available`, `age_ms`: front/status와 같은 값(저장소의 stale 기준 그대로).
   - `source`: 프레임이 없으면 `NONE`, 미리보기 라벨이 `GAZEBO`면 `GAZEBO`, 다른 라벨(실기 `ROSY`)이면 `DEVICE`.
   - `drive_modes`는 그대로 서비스 존재만 뜻한다. 카메라가 잠깐 끊겨도 계획 능력 집합이 흔들리지 않게 하려는 것이다.
2. **Fleet 계획 검사.** D-601 B 검사는 trip caps에 `line_camera`가 있으면 로봇을 부르지 않고 그 값을 쓴다. `available`이 참이 아니면 422 `TRIP_LANE_CAMERA_UNAVAILABLE`, `detail {stale, age_ms, source}`(`stale`은 프레임은 있으나 오래된 때 참). 필드가 없는 이전 CORE는 지금처럼 front/status를 부른다.
3. **오래된 능력 값.** Fleet은 능력을 5 s마다 백그라운드로 다시 읽고 응답 없는 동안 마지막 값을 쥔다. 쥔 값이 두 갱신 주기(10 s)보다 오래됐으면 `line_camera`를 버리고 front/status를 부른다. 그 안에서는 카메라가 죽은 지 몇 초 안 된 로봇이 계획을 통과할 수 있다. 출발 뒤 CORE line-follow가 차선을 잃고 서는 것이 그 다음 방어선이다.
4. **사이트 스위치** `fleet.trip.lane_camera_check`는 그대로 둔다.

### Safety-Review

- 바뀌는 것은 계획 거절의 근거 출처뿐이다. 움직임 명령, 최종 `/cmd_vel` 소유(CORE), E-Stop은 바뀌지 않는다.
- 거짓 통과 창은 능력 값의 나이(최대 약 10 s)다. D-601에서도 계획과 출발 사이에 카메라가 죽을 수 있었으므로 새 종류의 위험은 아니다.

### Alternatives

- `drive_modes`에서 카메라가 죽으면 `lane`을 뺀다: 계획기가 `TRIP_NO_ROUTE`로 답해 이유가 사라지고, 한 번 끊김에 능력 집합이 흔들린다. 버림.
- CORE 상태 스냅샷에 싣는다: Fleet trip caps는 capabilities에서 읽으므로 한 표면이 더 는다. 지금은 하지 않는다.

### SIM

- CORE는 원시 카메라 토픽을 직접 받지 않는다. 미리보기 노드(`road_observer_node`, SIM 라벨 `GAZEBO`)가 낸 압축 프레임만 받는다. 그러므로 미리보기 노드 없는 SIM은 `source: NONE`, `available: false`를 보고하고, `lane_camera_check: false`는 계속 필요하다.
- 병행 브랜치 `feat/sim-front-camera-preview`가 SIM 미리보기를 내면 이 필드가 `GAZEBO`·`available: true`가 되고, 그때 SIM 사이트 설정의 `lane_camera_check`를 다시 켤 수 있다. 그 전환은 그 브랜치 또는 후속이 한다.

### Validation

- `middleware/core/gateway/test/test_capabilities_controls.py`: 프레임 없음(`NONE`), 신선한 실기 프레임(`DEVICE`, front/status와 같은 `available`), 오래된 `GAZEBO` 프레임, `drive_modes` 그대로, 서비스 없으면 필드 없음.
- `operations/fleet/test/test_trip_start_d601.py`: 능력 값으로 통과·거절(호출 없음), 이전 CORE는 front/status, 계획 경로가 능력 값을 읽음(front/status가 살아 있어도 능력이 죽었다고 하면 거절).
- 호스트 테스트는 장치·현장 수용을 대신하지 않는다. 현장에서 볼 것: rosy_40의 capabilities `line_follow.camera.available: false`와 계획 거절.

### Consequences

- API Reference v1.194: capabilities 행, `/trip` 행, 변경 이력 한 줄. Additive라 이전 Fleet·로봇은 그대로 동작한다.
- 로봇 이미지에 이 CORE가 들어가기 전까지 실기 로봇은 front/status 경로를 그대로 탄다.
