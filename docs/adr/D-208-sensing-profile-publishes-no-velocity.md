## D-208 감지 프로파일은 속도를 발행하지 않는다

**Status:** Accepted (2026-09-25). [D-149](D-149-control.md)를 대체하지 않는다. `profile:=full` 의 `safety_node` 는 그 결정의 단독 모드 예외로 남는다.

**Context:**

1. **`sensing` 이 최종 발행자를 켜고 있었다.** `startup_profile('sensing')` 은 `safety` 를 항상 참이로 두고, `robot.launch` 는 그 값을 보지 않고 `safety_node` 를 붙였다. `safety_node` 의 `cmd_out` 기본값은 `cmd_vel` 이다(D-149).
2. **함대 시뮬이 그 프로파일을 감지 스택으로 쓴다.** `tools/run_fleet_sim.sh` 는 `profile:=sensing` 으로 `robot.launch` 를 연다. 이름과 달리 레거시 최종 발행자가 같이 올라왔다.
3. **정지 보정도 `cmd_vel_raw` 발행자를 만들었다.** `calibration_sensing_only` 는 움직이지 않는다고 하면서 발행자만 그래프에 남겼다. 발행하지 않아도 토픽 주인이 하나 더 생긴다.
4. **제품 런치는 이미 이 노드를 켜지 않는다.** D-149의 배포 폐쇄는 `ir_adc_node`, `camera_detect_node`, `line_observer_node`, `road_observer_node` 만 증거로 둔다. 어긋난 쪽은 그 폐쇄가 아니라 `sensing` 이라는 이름의 레거시 런치다.

**Decision:**

1. **`profile:=sensing` 은 Twist 발행자를 만들지 않는다.** `safety` 는 거짓이다. 켜지는 프로세스는 카메라, 웹, 정지 보정뿐이다. 정지 보정은 `cmd_vel_raw` 발행자를 만들지 않는다.
2. **`profile:=full` 만 D-149의 예외다.** `safety_node` 를 끄지 못한다. 이 프로파일을 core 옆에서 켜지 않는다. launch 파일은 그 마커를 유지한다.
3. **프로파일 스위치로 `safety` 를 켜고 끄지 않는다.** `full` 은 항상 켜고 `sensing` 은 항상 끈다. 인자로 뒤집지 못한다.

**Consequences:** `tools/run_fleet_sim.sh` 의 `profile:=sensing` 은 더 이상 최종 `cmd_vel` 을 올리지 않는다. 단독 비교 그래프는 `profile:=full` 로만 남는다. 패키지를 나누는 일은 아니다. 그 분리는 D-205 P1–P3 이다.

**Validation:** `src/core/control/test/test_startup_profile.py` 가 감지 프로파일의 프로세스 집합에 `safety_node` 가 없음을 본다. `src/core/control/test/test_launch_contracts.py` 가 `safety_node` 를 시작하는 launch 의 D-149 마커를 유지한다. 두 파일 9건이 2026-09-25에 통과했다.
