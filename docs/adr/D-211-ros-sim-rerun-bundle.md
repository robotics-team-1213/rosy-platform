## D-211 ROS-SIM 재실행 묶음 — 현재 트리에서 2대 관제+군집을 증명한다

**Status:** Proposed (2026-09-25).

**Context:**

1. D-79는 과거 트리·다른 artifact의 증거로 현재 gate를 GO로 만들지 못하게 한다. D-83은 ROS-SIM 최소 재실행 묶음을 요구한다. fleet ROS-SIM은 현재 HOLD다(설계 입력 로그는 GO가 아니다, D-89).
2. D-210 1차 범위는 시뮬에서 먼저 닫혀야 실물 단계로 갈 수 있다.

**Decision:**

1. 다음을 **같은 현재 트리의 colcon install** 위에서 재실행하고 묶음으로 판정한다: `core` 기동 + `bringup` + `navigation` + `description` 2대 namespace 격리 + `gz_sim gz_multi 2대` + `fleet console` gather/scatter(goal/cancel/전체 e-stop) + `relay` leader→follower + FOR-004 HOLD/ABORT/resume.
2. 과거 `install/setup.bash` 재사용 금지. `gz_multi`는 단일 DDS 도메인·namespace·`ros_gz_bridge` 분리(D-114), 스폰 좌표는 map initialpose로(D-115).
3. 릴레이는 byte-for-byte fan-out이며 유실 프레임을 반복하지 않는다. HOLD는 릴레이 일시정지로 만든다(신규 endpoint 금지).
4. 성공 기준: 2대 goal/cancel/e-stop 왕복, 스트림 단절 시 follower HOLD, arming 거절 시 실행 중 세션 불변, 로봇 1대 실패가 다른 로봇 결과를 거짓 완료로 만들지 않음.
5. 증거는 수용 기준 §4 레코드(run_id, source revision+dirty, env, command, observation, fault_recovery, result, 판정자, UTC)로 남긴다.

**Consequences:** 이 묶음이 GO가 되기 전에는 ARTIFACT/DEVICE를 1차 범위 근거로 승격하지 않는다. 실패 항목은 HOLD로 남기고 다음 단계로 진행하지 않는다.

**Validation:**

```bash
cd src && colcon build --symlink-install --event-handlers console_direct+
python3 -m pytest core/core/test/ site/fleet/test/ sim/gz_sim/test/ -q
bash tools/run_fleet_sim.sh
```

**References:** D-79(현재 트리 재실행), D-83(ROS-SIM 묶음), D-87(colcon install 전제), D-89(D-35 후보 조건), D-114/D-115(gz_multi), D-31(릴레이), 수용 기준 §4/§9.
