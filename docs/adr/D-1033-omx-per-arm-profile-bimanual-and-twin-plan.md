## D-1033 OMX 1팔·2팔 공통 프로필 정본, 양팔 실행·Fine 탑재 경계 및 카메라 투영 디지털 트윈 운영 규격

**Status:** Proposed (2026-11-15, 사용자 지시 + Gemini 4 Hydrogen · GLM-5.3 2라운드 패널 합의안; 실물 측정·카메라 3대 복구 및 증분 B·Fine 구현은 별도)

잇는 결정: [D-427](D-427-platform-three-parts-middleware-operations-learning.md)·[D-429](D-429-five-concerns-control-port-and-site-devices.md)·[D-430](D-430-safety-as-a-separate-concern.md)(모듈 소유와 safety 경계) · [D-496](D-496-omx-hardware-arm-control-acceptance.md)(하드웨어 측정 프로필) · [D-766](D-766-size-limits-split-on-exceed.md)(어댑터 10,000줄 상한) · [D-778](D-778-bimanual-workcell-foundation.md)·[D-780](D-780-workcell-coordinator-peer-stop-source-and-named-barriers.md)(양팔 권한·barrier) · [D-782](D-782-omx-action-conditioned-world-model.md)(예측 REJECT/HOLD 전용) · [D-856](D-856-application-action-boundary.md)(앱-실행 경계) · [D-911](D-911-omx-native-reviewed-operating-envelope.md)(checked 운영 envelope) · [D-933](D-933-arm-s-cell-coordinate-frame-markers.md)(셀 좌표계 마커) · [D-947](D-947-omx-palletizing-sim-models-and-claim-scope.md)(팔레타이징 sim 모델·주장 범위) · [D-983](D-983-two-arm-timing-on-fixed-paths.md)(양팔 고정 경로 타이밍) · [D-1014](D-1014-unified-area-xyz-coordinate-directive-from-middleware-to-cell.md)(통합 구역·AreaXYZ) · [D-1021](D-1021-one-owner-per-value-identity-in-account-placement-in-site-map.md)(값마다 소유자 하나)

### D-427 · D-429 · D-430 관계

| 기준 결정 | 이 ADR과의 관계 | 변경 여부 |
|---|---|---|
| D-427 (모듈 분할 소유) | 순수 스케줄·기하 수학만 `middleware/devices/omx/adapter`에 두고 셀 실행·프로필 조합·벨트 원장은 `deploy/robot/omx`에 남긴다(D-766 10,000줄 상한 준수) | 유지 (새 최상위 폴더 없음) |
| D-429 (CORE·드라이버 분리) | `omx_adapter/contracts`의 ROS/하드웨어 계약에 셀 토폴로지 필드를 섞지 않는다 | 유지 |
| D-430 (Safety 경계) | D-911 `Gate`·`Guarded`·`checked`·`load_predict`·`runner_strain` 경계를 그대로 둔다. 예측·트윈은 D-782 §1대로 `REJECT`/`HOLD`만 가능하며 `PERMIT` 권한을 갖지 않는다 | 유지 |

### Context

2026-11-15 두 차례 패널(Gemini 4 Hydrogen · `zai-coding-plan/glm-5.3`, 각 1라운드 독립 + 2라운드 상호 반박)에서 다음 두 문제를 검토했다.

1. **카메라 투영 디지털 트윈의 한계와 역할**: `omx_twin.py`와 `omx_real2sim.py`는 좌표 기준 이탈(2026-11-14 `arm_a` 44 mm·`arm_b` 26 mm)과 카메라 이동(2026-11-10 USB 재연결 56 px)을 실행 전에 거르는 데는 유효하다. 그러나 top D435(`640×480@650 mm`)는 `1 px ≈ 1.05 mm`(맵 상한 `1σ ≈ 2 mm`)인 반면 배 칸 여유는 `2.7 mm`이고, `fit-camera`에서 카메라와 관절 영점을 동시에 풀면 파라미터 상쇄로 어긋남이 `4.5 → 6.3 px`로 악화되며(`findings.md`), MuJoCo는 parent-child 접촉(손목 홀더 간섭)과 전류 한계(`250 mA`)를 보지 못한다. `omx_twin.py live` 역시 기본 2초 주기(`--period 2`, ssh 타임아웃 20 s)라 실시간 하중·접촉 방어를 대신할 수 없다.
2. **1팔(S)·2팔(A/B) 프로필 경계와 양팔 실행 공백**: `cell_auto_setup.load_config`·`cell_robot_profile`·`cell_arm_cal`이 이미 팔 1대 공통층을 형성하고 `cell_two_arm.py`도 이를 읽지만, `grasp_planner.py:60`의 `ROSY_OMX_TCP_X_M or tcp_x_m` 우선순위 역전과 `cell_two_arm.py:363`의 단일 `kin` 공유 때문에 양팔에 서로 다른 `tcp_x_m`을 실을 수 없었다. 또한 D-983 계산 결과 `home(0.8, 0.8)` 대기는 배 위 작업에서 순서 자체가 나오지 않아("순서 없음"), 직렬 3단에서도 `wait(side)` 실측 없이는 안전 그물이 되지 못한다.

### Decision

#### 1. 1팔·2팔 공통 프로필과 토폴로지 경계 (새 프로필 포맷 금지)

- **팔 1대 공통 프로필 정본**: `cell_auto_setup.load_config`(`cameras`, `params`, `plan`, `calibration_path`) + `cell_robot_profile.v1`(`operating_profile_path`) + `arm-cal-<arm_id>.json`(`cell_arm_cal`, `z_profile_mm`, `sim_real_twin`, 집게 EMA). 1팔(S)과 2팔(A/B) 모두 이 묶음을 그대로 쓴다.
- **계약 격리**: `OmxAdapterProfile`(`adapter_profile.py`)과 D-496 `hardware_profile.py`에는 2팔 토폴로지 필드를 넣지 않는다. `two_arm_config.py`(`rosy.omx-two-arm-pipeline/1`)는 Leader-Follower 티칭·캡·게인 커미셔닝 전용으로 격리한다.
- **토폴로지 고유층**: `omx_adapter/coordination.py`(순수 스윕·스케줄 수학), `workcell_coordinator.py`(2-owner barrier/coupled stop), `deploy/robot/omx/`의 `cell_two_arm.py`·`cell_zones.py`·`cell_cycle.py`·`cell_belt_handover.py`가 소유한다.

#### 2. TCP 소유 분리 및 `cell_two_arm.py` 팔별 분리

- **정본 분리**: IK/경로 계획 시점의 정본은 `plan["tcp_x_m"]`이고, 셀 실행 스윕·FK 검증 시점의 정본은 `arm-cal-<arm_id>.json`의 `z_profile_mm.tcp_v21_x_mm`다.
- **최소 수정**: `grasp_planner.py`의 `load_kinematics`는 `tcp_x_m or os.environ.get("ROSY_OMX_TCP_X_M")`로 우선순위를 뒤집고, `cell_two_arm.py`는 팔별 `kin = load_kinematics(None, tcp_x_m)` 인스턴스로 분리한다. `plan["tcp_x_m"]`과 `arm-cal`의 `tcp_v21_x_mm`이 허용치 이상 어긋나는 라이브러리는 실행 전에 거부한다.
- `arm_a`의 미측정 `fingertip_m` 실측을 양팔 스윕 증명의 필수 전제로 둔다.

#### 3. 카메라 투영 디지털 트윈 2층 구조와 Harbor 경계

- **실행 전 Coarse + Gate**: `cell_depth_pose`로 top 카메라 높이·기울기를 독립 고정(±0.6 mm / ±0.6°)한 뒤에만 `omx_twin.py fit-camera --params joints`를 돌린다. 카메라 자세와 관절 영점을 동시에 푸는 `--params both`는 식별 근거가 생길 때까지 금지한다. `omx_real2sim.py` + `omx_map_gate`는 기준 단일성(`W`, `docks-photo` 189.8 mm)과 2σ 초과 여부만 검사해 실행을 막는다.
- **실행 중 역할 분리**: 접촉·하중 방어는 `load_predict`·`runner_strain`·가드 4검사가 맡고, `omx_twin.py live`는 정지·청크 경계에서 카메라 이동(56 px 점프)·역할 이상만 감시해 `HOLD` 근거를 낸다.
- **Harbor 경계**: Harbor는 논리 상태(본선/야드/임시 칸)·반출 제안·완료 근거만 소유하고, 트윈 결과는 UI 가시화와 D-856 P1 사전 검증 조회(`REJECT`/`HOLD`)로만 소비한다. 기하·보정 입력은 `real2sim`·`cell_requests` 경계 밖으로 내지 않는다.

#### 4. 양팔 대응 확정 규격 (단기 직렬 3단 vs 데모 뒤 확장)

- **단기 확정 (11/21 데모 — 증분 A, 직렬 3단)**:
  - 한 번에 1팔만 이동(`cell_cycle` / 직렬 3단), 팔별 D-911 `Gate` + `checked` + `zone_side` 밖 목표 거부, 벨트 용량-1 토큰(`unknown` 시 `HOLD`).
  - D-983의 깨진 전제(`home(0.8, 0.8)`에서 배 위 작업 `순서 없음`)에 따라 데모 시나리오 `--plan-only` 통과와 **`wait(side)` 자세 실측 1회**를 모두 필수 게이트로 승격한다.
  - 한 팔 실패 시 상대는 현재 세그먼트만 마치고 정지, 측정 위치 마진 확인 후 접기, 집은 채 멈춘 리프트는 후퇴 금지·사람 호출. A/B 집기는 사전 계획 라이브러리(`--carry`)만 쓴다.
- **데모 뒤 확장 — 증분 B (A/B 동시 동작)**:
  - 벨트 적층(동시 이득 0 s)이 아닌 **재취급·반출 이동**에서만 채택하며, 직렬 대비 실측 시간 이득이 있을 때만 쓴다.
  - 필수 전제: `arm_a` `fingertip_m` 실측, `wait(side)` 스윕 검증, `cell_two_arm.execute`의 `on_segment_done` 재계산(`plan(start=...)`) 및 실행 중 `Gate.open` 연결.
- **데모 뒤 확장 — Fine 스택(`cell_look`, `cell_pinch`, `cell_feel`) 양팔 탑재**:
  - 상대 팔이 `wait` 또는 세그먼트 경계에 정착(`joint_jitter.settled_state`)한 직렬 창에서만 실행한다.
  - 각 훅이 최악 보정 폭 `B`(`look.max_total_mm` 등)를 선언하고 `clearance(계획 스윕 ⊕ B, 상대 정지 자세) ≥ margin_m` 정적 마진 게이트를 통과해야 허용한다. 거부율 완화가 필요하면 정지 창 내 실측 보정 경로 재검사를 후속으로 연다. `grasp_servo`(조그 서보잉)는 데모 뒤 별도 수용으로 보류한다.
- **데모 뒤 확장 — 증분 C (벨트 인계 자동화)**:
  - 5사건 사슬(`slot_reserved → S_placed → end_observed → AB_grasped → belt_empty_verified`)과 `arm_s` top 벨트 끝 관측·`transit_s` 실측으로 연결한다.

### Consequences

- 새 어댑터·프로필 스키마를 늘리지 않고 1팔(S)과 2팔(A/B)의 공통 설정·보정 사슬을 하나로 고정한다.
- `cell_two_arm.py`의 팔별 TCP·`kin` 분리는 약 3줄 변경과 정합 검사로 바로 착수 가능하며, 기존 Arm S 경로에 회귀를 주지 않는다.
- 단기 데모와 데모 뒤 확장(동시 동작·Fine 탑재·벨트 인계) 사이의 하드웨어·측정 게이트(`arm_a` `fingertip_m`, `wait(side)`, 카메라 3대 USB 복구)가 명시되어 무리한 실물 시도를 막는다.
- 실제 실행 계획은 [2026-11-15 OMX 1·2팔 프로필·양팔 확장·트윈 구현 계획](../plans/2026-11-15-omx-bimanual-and-twin-plan.md)에서 관리한다.
