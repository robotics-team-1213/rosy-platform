## D-149 control 단독 모드의 최종 발행 토픽은 계약된 예외다

**Status:** Accepted (2026-09-21 — 구조적 구성 증거로 승격, 아래 Validation 참조).

**Context:** `control`의 `safety_node`는 `cmd_out` 파라미터 기본값이 `cmd_vel`이고 `sensor_only`가 아니면 이 토픽에 발행자를 만든다(`control/safety/node.py`). control 단독(standalone) 구동에서는 의도적이지만, 파라미터 기본값만으로 CORE 단일 발행자 원칙(D-2, D-38)과 충돌할 수 있는 구조다. `robot.launch.py` 상단 문서는 이미 "core 옆에서 launch하지 마라"고 경고한다. device validation이 HOLD인 지금 운영 구성 실증이 없다.

**Decision:**

1. **`cmd_out=cmd_vel`은 control 단독 모드에서만 유효한 계약된 예외로 명문화한다.** 단독 모드에서 control은 여전히 자체 게이트에서 최종 명령을 발행한다.
2. **CORE와 control 레거시 최종 발행의 동시 구성을 금지하고, launch 계약 테스트로 고정한다.** control에서 `safety_node`를 시작하는 모든 launch 파일은 "core 옆에서 실행 금지" 마커를 문서로 가져야 한다.
3. **기본값 자체는 유지한다.** 단독 모드가 이 패키지의 남은 사용례(패리티 검증, 캘리브레이션)이므로 기본값 분리는 그 사용례의 문서·런북을 파손한다. 운영 프로파일의 명시적 remap 요구는 승격 판정에서 기각한다 — 운영 구성이 구조적으로 control 최종 발행과 격리돼 있으므로(이미지 분리 + 배포 launch 폐쇄) remap을 요구할 대상이 없다.

**Alternatives:** 기본값을 `cmd_vel_legacy`로 분리 — 충돌을 원천 제거하지만 단독 사용례의 기존 문서·스크립트가 전부 파손된다. `sensor_only` 강제 — 레거시 단독 구동 자체가 불가능해진다. 문서만 보강 — 계약 테스트 없이는 드리프트가 재발한다(`web_node`/`wander`의 `cmd_vel` 구독 개명 전례).

**Consequences:** 예외가 눈에 보이는 계약이 된다. 승격 전에는 운영 구성이 이 예외를 우연히 발견하는 일이 없어야 한다.

**Validation / Transition:** 승격 근거(2026-09-21, 기기 부재 상태에서 대체한 구성 증거): (1) **이미지 분리** — core 이미지는 `control`을 복사하지 않는다(Dockerfile "optional slices" 단계 주석). (2) **배포 launch 폐쇄** — compose가 도달하는 launch 폐쇄(`bringup_robot.launch.py` / `hardware.launch.py` → `line_follow.launch.py`)에서 control 실행파일은 `ir_adc_node`·`camera_detect_node`·`line_observer_node`뿐이며 전부 D-143 증거 생산자다. 최종 발행자 `safety_node`는 deploy가 참조하지 않는 레거시 launch 3개(`robot`·`wander`·`dashboard_control`)에만 존재한다. (3) **계약 테스트** — launch 마커(`test_launch_contracts.py`), 코어 launch 배제·compose·deploy 스캔(`test_control_launch_boundary.py`)이 변이 증명돼 있다. 잔여 위험은 io 컨테이너에서의 수동 레거시 실행뿐이며 launch 마커가 첫 방어선이다. 최초 기기 가동 시 `device_readback.py`의 ROS 그래프가 이 격리의 실물 확인을 DEVICE 게이트 증거로 기록한다(승격 조건이 아니라 상시 게이트의 확인 항목).

**정정 (2026-09-22, D-168):** 위 (2)의 실행 파일 목록은 셋이 아니라 넷이다. `line_follow.launch.py`는 `road_observer_node`를 조건 없이 띄운다. 이 노드도 `road/observation`과 `camera/preview/compressed`만 발행하는 D-143 증거 생산자라서 결정과 승격 판단은 바뀌지 않는다. 목록은 이제 기억이 아니라 `test/test_control_deploy_closure.py`가 systemd 유닛과 compose에서 include 사슬을 따라가 도출하고, 이 네 개와의 집합 동일성과 `safety_node` 부재를 검사한다.

**References:** D-2 (자체 cmd_vel 멀렉서), D-38 (CORE의 최종 cmd_vel 소유), D-126 (센서 전용 주입), D-143.

---
