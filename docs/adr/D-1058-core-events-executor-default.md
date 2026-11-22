## D-1058 CORE 실행기 기본값을 events로 바꾼다 (D-953 후속 3 개정)

**Status:** Accepted (2026-11-20, 사용자 지시: "그것도 기본값 전환해". D-953 후속 3의 "기본값은 바꾸지 않는다"를 이 결정이 개정한다. 주행 확인은 아래 남은 확인으로 둔다)

잇는 결정: [D-953](D-953-pi45-cpu-native-path.md)(실행기 선택 도입·확인 1~6) · [D-430](D-430-safety-as-a-separate-concern.md)(safety 경로 독립 검토) · [D-1](D-1-rclpy-uvicorn.md)(단일 프로세스).

### Context

- CORE는 유휴에서 한 코어의 약 77%를 쓴다. py-spy 표본의 약 85%가 rclpy 파이썬 실행기의 wait-set 재구성이었다. 콜백 하나당 약 2.6 ms다.
- 2026-11-20 y8xs에서 바퀴를 움직이지 않고 잰 값이다. 근거는 [검증 기록](../validation/core-events-executor-2026-11-20/result.md)에 있다.
  - CORE CPU: navigation을 켰을 때 threaded 76.8%, events 25.4%. 꺼졌을 때 59.4%, 15.1%.
  - `cmd_vel` p99는 유휴·CPU 부하·디스크 동기 쓰기에서 events 24~28 ms, threaded 28~31 ms였다. 두 모드 모두 100 ms 이상 간격은 0회였다.
  - 종료(exit 0, 포트 해제)와 정지 상태의 estop이 두 모드에서 같았다. events로 45분 운전했을 때 메모리가 평탄했다.
- Gazebo(`tools/sim/nav_events_probe.py`)에서는 `/clock` pause·재개, Nav2 목표·취소, slam save(3 s 안), pilot recorder가 두 모드 모두 통과했다.
- 코드 검토에서 실행기 콜백 안의 블로킹 future 대기는 없었다. `save_map`과 recorder의 `wait=True`는 API 스레드에서만 쓴다. 지금도 CORE 콜백은 기본 상호배타 그룹이라 한 노드 안에서 겹치지 않는다(`test_core_callbacks_never_rely_on_a_reentrant_group`).

### Decision

1. `ROSY_CORE_EXECUTOR`의 기본값을 `events`로 바꾼다(`middleware/core/gateway/core/node.py` `core_executor_kind`). 빈 값도 `events`다. `threaded`는 계속 고를 수 있다.
2. 되돌리기는 코드 변경 없이 한다. 기체에서 `/etc/systemd/system/rosy-core.service.d/`에 `Environment=ROSY_CORE_EXECUTOR=threaded` drop-in을 두고 `daemon-reload`, `restart rosy-core`를 한다. 잘못된 값은 지금처럼 `main()`에서 rclpy보다 먼저 실패한다.
3. D-953 결정 2(제어 노드 `ROSY_EXECUTOR`)는 이 결정의 대상이 아니다.

### Consequences

- **남은 확인.** D-953 확인 가운데 주행 부분은 아직 하지 않았다. 사람이 로봇 옆에 있을 때 다음을 한다. 하나라도 이전보다 나쁘면 2의 drop-in으로 되돌리고 이 ADR을 다시 본다.
  - 주행 중 `cmd_vel` 50 Hz와 safety 20 Hz의 간격, deadman·watchdog 반응. map·costmap·scan 부하를 넣은 경우도 잰다.
  - 주행 중 estop과 고장 주입.
  - navigation을 켠 상태로 수 시간 운전.
  - 실기 slam_toolbox `save_map`.
- 한 스레드가 모든 콜백을 돈다. 느린 콜백(파일 fsync 등)은 `cmd_vel` tick을 미룰 수 있다. threaded에서도 같은 노드의 콜백은 겹치지 않았으므로 새 위험은 safety_node tick과 같은 스레드를 쓰는 것이다.
- Gazebo·개발 실행도 기본으로 events가 된다.

### D-427·D-429·D-430과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 폴더·소유자 변경 없음 |
| D-429 | 해당 없음 |
| D-430 | CORE 실행기는 safety 경로다. 독립 검토와 `Safety-Review:` 꼬리말로 바꾼다 |
