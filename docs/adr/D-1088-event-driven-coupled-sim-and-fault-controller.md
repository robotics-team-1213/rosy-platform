## D-1088 이벤트 기반 결합 시뮬레이션(Gazebo Pinky ↔ MuJoCo OMX) 및 경계 고장 주입 컨트롤러

**Status:** Accepted (2026-11-28, 사용자 결정: 2단계 하이브리드 물리 루프 목표, 호스트별 스택 분리, 초기 현장 장애 토글 포함, World 읽기 전용 순수성 유지, 이벤트 기반 결합). 호스트 계약·시뮬 컨트롤러·단위 시험 범위이며 실물/현장 수용은 별도다.

| 결정 | 관계 |
|---|---|
| [D-427](D-427-platform-three-parts-middleware-operations-learning.md) | 지킨다. 새 최상위 폴더 없이 `tools/sim/coupled_sim_controller.py`에 둔다. |
| [D-429](D-429-five-concerns-control-port-and-site-devices.md) · [D-430](D-430-safety-as-a-separate-concern.md) | 지킨다. CORE(`/cmd_vel`)·Fleet 배차 권한과 실물 안전 경계를 바꾸지 않으며 `operations/world`·`applications/world`는 읽기 전용을 유지한다. |
| [D-182](D-182-policy-does-not-know-sim-names.md) | 지킨다. 운영 Fleet/CORE/정책 코드에 시뮬레이션·고장 주입 분기를 넣지 않고 브리지/어댑터 경계에서만 주입한다. |
| [D-480](D-480-sim2real-three-tiers-and-gap-registry.md) | 지킨다. `M`(물리 모델링)과 `D`(벤치 고장 주입) 경계를 연결하며 `RTF < 0.9` 실행은 `INCONCLUSIVE`로 판정한다. |
| [D-527](D-527-decision-test-host-boundaries.md) · [D-1012](D-1012-omx-sim-pipeline-mujoco-to-isaac-and-gazebo-ros-contract.md) · [D-1075](D-1075-rosy-world-offline-demo-and-isaac-observation.md) | 잇는다. `Gazebo`(Pinky Nav2)와 `MuJoCo`(OMX 셀)를 단일 물리 엔진으로 합치지 않고 경계 이벤트로 결합하며, `World`는 오프라인·실시간 공통 읽기 전용 투영만 소유한다. |

### Context

실물 로봇·OMX 팔이 꺼져 있거나 현장에 접근할 수 없을 때도 실제 AI(`qwen3-vl:8b-instruct`), `Sim-Fleet`, `Decision`, `ROSY World` 전 구간을 폐루프로 검증하고 현장 장애를 회귀 시험해야 한다. 기존 [`world_swarm.py`](../../tools/sim/world_swarm.py)는 고정 키프레임 재생이고 [`world_factory_close.py`](../../tools/sim/world_factory_close.py)는 사후 영수증 봉합이어서 실시간 Pinky↔OMX 화물 인계와 현장 장애 주입이 빠져 있었다.

### Decision

1. **4계층 역할 분리 (World 순수성 보장)**
   - **① Physics Backends (`Gazebo Pinky + CORE/Nav2`, `MuJoCo 3-Arm + ACT`):** 물리 스텝, 센서·관절·화물 상태만 생성한다.
   - **② Sim Scenario & Fault Controller (`tools/sim/coupled_sim_controller.py`):** 단일 화물 원장(SSOT), 3개 경계 이벤트 중계, 현장 장애 토글 주입, 시뮬레이션 영수증을 소유한다.
   - **③ 격리 `Sim-Fleet` + `Sim-Vision` + AI (`Ollama`, `Situation` sim-profile, `rosy-omx-act-http`):** 실운영 호스트(`Fleet-R`)와 분리된 격리 스택에서 운영 코드 그대로 배차·판단·복구를 수행한다.
   - **④ `ROSY World` (`operations/world`, `applications/world`):** **100% Read-Only** 투영·3D 시각화·패리티·RTF·활성 장애 배지 관측만 맡는다. 제어 명령·장애 토글·시나리오 리셋 권한을 두지 않으며, `adapter="real"` 또는 `world_id="real-site"`로의 위장을 거부한다.

2. **이벤트 기반 결합 (단일 화물 원장 + 3개 경계 이벤트)**
   - 화물 소유권은 `ON_PINKY → HANDOFF_AT_S3 → IN_CELL_ARM_S → ON_BELT → IN_CELL_AB → ON_SHIP` 순서로 단일 원장이 전이한다(실패 시 `CARGO_FAULT`).
   - **`S3_ARRIVED_SETTLED`:** Gazebo에서 Pinky가 S3에 정차·안정화되면 실제 정차 오차 `(dx_m, dy_m, dyaw_rad)`와 `bed_velocity_measured`를 MuJoCo `pinky_bed` 초기 위치로 넘긴다.
   - **`CARGO_LIFTED_OR_DROPPED`:** MuJoCo `arm_s`가 양측 파지 인양(`bilateral_lift`)에 성공하면 Gazebo 트레이를 비우고(`IN_CELL_ARM_S`), 실패·낙하 시 `CARGO_FAULT`로 전이해 출발을 막는다.
   - **`CELL_BED_CLEAR`:** MuJoCo `arm_in_bed_zone=False`가 보고될 때만 Pinky 출발을 허가한다.

3. **1.0x 실시간 페이싱 및 RTF 게이트**
   - 두 시뮬레이터는 벽시계 1.0x 페이싱을 기준(`LIVE_FRESH_MS`, `RoadSpeed` TTL과 정합)으로 돌며, 어느 구간이든 `RTF < 0.9`이면 결과를 `INCONCLUSIVE`로 기록한다(D-480 5항).

4. **경계 고장 주입(7종) 및 호스트·격리 배치**
   - **7종 경계 토글:** `pinky.tangled_or_stall`, `pinky.s3_brake_unmeasured`, `arm.usb_unplugged`, `vision.calibration_mismatch`, `vision.camera_drop`, `bridge.seq_conflict_409`, `hub.heartbeat_lag`. Fleet·CORE 내부 코드가 아니라 시뮬레이터·비전·워크셀·허브 브리지 경계에서만 주입해 `TOGGLE ON → 기대 차단/복구 → TOGGLE OFF → 정상 회복`을 회귀 시험한다.
   - **브리지 및 격리 스택:** Gazebo Pinky 브리지·MuJoCo 3-Arm OMX 브리지가 경계 이벤트(`s3-arrived`, `cargo-lifted`, `cell-bed-clear`, `cell-stage`)를 중계하며, `deploy/sim_site/`가 실운영 `deploy/site/`와 분리된 격리 시뮬레이션 Compose 스택을 제공한다.
   - **호스트 배치:** 기본은 `Model PC`(Gazebo 3 Pinky + 격리 Sim-Fleet + Sim-Vision + World + Controller)와 `AI PC`(MuJoCo OMX + ACT + Ollama + Situation sim-profile) 분산이며, 단일 호스트 점검 시 동일 스택의 경량 프로파일로 AI PC 단독 기동을 허용한다.

### Consequences

- [`tools/sim/coupled_sim_controller.py`](../../tools/sim/coupled_sim_controller.py), [`tools/sim/coupled_sim_fault_suite.py`](../../tools/sim/coupled_sim_fault_suite.py), 회귀 시험([`test/test_coupled_sim_controller.py`](../../test/test_coupled_sim_controller.py), [`test/test_coupled_sim_fault_suite.py`](../../test/test_coupled_sim_fault_suite.py))이 화물 원장 SSOT, 3+1 경계 이벤트(`/api/sim/events/cell-stage` 포함), 7종 장애 토글·영수증 검증, World 읽기 전용 패리티 투영과 루프백 HTTP 서버를 제공한다.
- Gazebo/MuJoCo 이벤트 브리지와 격리 [`deploy/sim_site/`](../../deploy/sim_site/) 스택이 운영 Fleet/CORE/World 경로를 수정하지 않고 결합 시뮬레이션 및 고장 주입 검증을 완결한다.
