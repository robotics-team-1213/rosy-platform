## D-1014 OMX 통합 구역·3차원 좌표(AreaXYZ) 체계 및 ROSY 미들웨어 → rosy-cell 적층 지시 계약

**Status:** Accepted (2026-11-11, 사용자 확인: "우리가 각각 좌표를 지정해서 그곳의 지정된 곳에 이를 두게하는 식의 area xyz 축을 하나로 합친 체계를 만들어서 이를 adr로 결정하에 이를 rosy 미들웨에서 지시하면 rosy-cell 에서 처리하는걸로 해보자"). 미들웨어 좌표·지시 계약, `rosy-cell` 실행기, 호스트·실물 3단 적층 검증까지 포함한다.

잇는 결정: [D-911](D-911-omx-native-reviewed-operating-envelope.md)(실물 작업 범위 및 안전 엔벨로프), [D-971](../reference/ROSY%20ADR%20Log.md)(인시던트 원장 및 안전 홀드), [D-1006](D-1006-calibration-health-before-adaptation.md)(캘리브레이션 건전성), [D-1010](D-1010-site-map-frame-binding.md)(사이트 맵 프레임 바인딩), [D-1012](D-1012-omx-sim-pipeline-mujoco-to-isaac-and-gazebo-ros-contract.md)(OMX 시뮬레이션·실행 파이프라인).

### Context

1. **기존 피킹·적층 좌표 지정이 사이트 이름·격자 슬롯·팔 미터 좌표로 분산되어 있었다.**
   - 기존 `cell_auto_pick.py`와 `grasp_planner.py`는 `--from pallet-l1 --dest pallet-l2`, `--roi`, `sites["pallet-l2"]["place"]`, `stack-calibration.bias.json` 등 여러 설정 파일과 인자에 의존해 목표 위치를 간접 조합했다.
   - 이 때문에 상위 ROSY 미들웨어가 "특정 구역(`area`)의 지정된 `(x, y, z)` 좌표(또는 `col, row, tier` 슬롯이 결합된 3차원 좌표)에서 컨테이너를 집어 지정된 1단·2단·3단 `(area, x, y, z)` 좌표에 정확히 적층하라"고 직접 지시하기 어려웠다.
2. **실물 1단·2단·3단 적층에서 구역·열별 편차(`bias_mm`)와 층별 높이(`z`), 팔별 집게 캘리브레이션(`arm-cal-<arm_id>.json`)이 일관되게 결합되어야 한다.**
   - 선박 홀(`pallet` / `ship_hold`) 내 1열(`x = 0.1280 m`), 2열(`x = 0.1580 m`), 3열(`x = 0.1935 m`)과 1단(`z = 0.0074 m`), 2단(`z = 0.0398 m`), 3단(`z = 0.0674 m`) 높이를 하나의 통합 좌표 체계(`AreaXYZ`)로 묶으면, 미들웨어는 직관적인 단일 좌표 지시만 내리고 `rosy-cell`이 팔별 프로필·손목 카메라 중앙 정렬·파지 심의(`reinsert_pick`)·정밀 안착을 일괄 수행할 수 있다.

### Decision

구역(`area`)과 3축 좌표(`x, y, z, yaw_deg`)·격자 슬롯(`col, row, tier`)을 하나로 합친 **`AreaXYZ` 통합 좌표 체계(`rosy.omx-area-xyz.v1`)**를 정의하고, **ROSY 미들웨어(`omx_adapter.area_xyz`)가 지시(`rosy.omx-cell-area-xyz-directive.v1`)하면 `rosy-cell`(`deploy/robot/omx/cell_area_xyz.py`)이 이를 받아 실행**하도록 결정한다.

1. **통합 `AreaXYZ` 좌표 모델 (`rosy.omx-area-xyz.v1`)**

   | 필드 | 타입 | 설명 |
   |---|---|---|
   | `area` | `str` | 작업 구역 식별자 (`"pallet"`, `"ship_hold"`, `"temp_plate_a"`, `"temp_plate_b"`, `"beltend"`) |
   | `col`, `row`, `tier` | `int \| None` | 구역 내 선택적 슬롯 주소 (`col: 1..3`, `row: 1..2`, `tier: 1..3` = 1단·2단·3단) |
   | `x`, `y`, `z` | `float` | 팔 기준 작업 공간 미터 좌표 (`m`). 명시적 `(x, y, z)` 지정 또는 `(area, col, row, tier)` 테이블로부터 결정론적으로 해석 |
   | `yaw_deg` | `float` | 집게 회전각 (기본 `-90.0°`) |
   | `bias_mm` | `[float, float]` | 구역·열별 보정 오프셋 `[bx_mm, by_mm]` (예: `Col 1: [0.0, 0.0]`, `Col 2: [-3.8, 0.0]`, `Col 3: [+1.5, 0.0]`) |
   | `effective_xyz_m` | `[float, float, float]` | `bias_mm`가 반영된 최종 제어 목표 좌표 `[x + bx/1000, y + by/1000, z]` |
   | `site_id` | `str` | 하위 호환 사이트 키 (`pallet-l0`, `pallet-l1`, `pallet-l2`, `beltend` 등 자동 도출) |

2. **구역(`area`) 기준 기본 슬롯·층(`tier`) 좌표 규격 (`pallet` / `ship_hold`)**
   - **열·행 중심 (`x, y`)**:
     - `Col 1`: `x = 0.1280 m`, `Col 2`: `x = 0.1580 m`, `Col 3`: `x = 0.1935 m`
     - `Row 1` (전방 적층 슬롯): `y = -0.0130 m` (`Col 3`은 `-0.0030 m`), `Row 2` (후방 피킹 슬롯): `y = -0.1060 m`
   - **층별 높이 (`tier -> z`)**:
     - `1단 (tier=1, l0)`: `z = 0.0074 m` (`above_z = 0.0474 m`)
     - `2단 (tier=2, l1)`: `z = 0.0398 m` (`above_z = 0.0798 m`)
     - `3단 (tier=3, l2)`: `z = 0.0674 m` (`above_z = 0.1074 m`)
   - 미들웨어는 슬롯 지정(`area="pallet", col=2, row=1, tier=3`)과 명시적 좌표 오버라이드(`x=0.1580, y=-0.0130, z=0.0674`)를 동시에 또는 선택적으로 사용할 수 있으며, 두 경우 모두 동일한 `AreaXYZ` 정규화 객체를 생성하고 D-911 작업 공간 경계(`workspace_min_m` ~ `workspace_max_m`)를 검증한다.

3. **ROSY 미들웨어 → `rosy-cell` 실행 지시 파이프라인 (`rosy.omx-cell-area-xyz-directive.v1`)**
   - **미들웨어 계층 (`middleware/devices/omx/adapter/omx_adapter/area_xyz.py`)**:
     - `resolve_area_xyz(...)`: 구역·슬롯·명시 좌표를 단일 `AreaXYZ`로 정규화하고 작업 공간 엔벨로프 및 지지 층(`tier`) 유효성을 검증한다.
     - `build_directive(arm_id, pick, place, ...)`: `rosy-cell`에 전달할 `rosy.omx-cell-area-xyz-directive.v1` 명령 페이로드를 생성한다.
   - **셀 실행 계층 (`deploy/robot/omx/cell_area_xyz.py`)**:
     - 미들웨어의 `AreaXYZDirective`를 수신해 팔별 자동 캘리브레이션 프로필(`cell_arm_cal.py`, `arm-cal-<arm_id>.json`)을 적용하고, `grasp_planner.plan_pick`으로 Pick(`pick.effective_xyz_m`) 및 Place(`place.effective_xyz_m`) 청크 라이브러리를 생성한다.
     - 손목 카메라(`arm_b_wrist` / `arm_s_wrist`) 기반 실시간 `(x, y)` 중앙 보정(`wrist_servo`), `schema_version = 2` 파지 안정성 심의(`cell_grasp_debate.py`, 불안정 시 `reinsert_pick` 제자리 재투입 후 재시도), 정밀 적층 하강(`descend_place_guard_frac = 0.28`)을 수행하여 지정된 `(area, x, y, z)`에 1단·2단·3단 컨테이너를 적층한다. 이송(transfer) 중에는 중간 `park`를 거치지 않고 상승 높이(`above_pick -> above_place`)를 유지해 파지된 컨테이너가 흔들리거나 빠지지 않도록 한다.
     - 평행 집게의 180° 대칭성을 이용한 `normalize_pick_yaw_deg(yaw_deg, x, y)`로 가로(`0°`)·대각선(`±45°`, `50°`) 컨테이너 피킹 시 `arm_b`의 케이블 한계(`wrist_roll >= 5.0`)를 침범하지 않는 등가 집게 각도를 자동 선택하고, 안착 지점에서는 목표 각도(`세로 = -90.0°`)로 회전 정렬한다.
     - **결정론적 다중 뷰(Side + Top) 목표 구역·방향 검증 (`verify_stack_outcome`)**:
       - Isaac-Sim 스타일로 사전 정의된 측면(`SIDE_ROI_BY_COL_TIER[(col, tier)]`) 및 상단(`TOP_ROI_BY_COL_ROW[(col, row)]`) 2D 목표 구역 ROI 안에서 컨테이너 색상 채움률(`fill_ratio`), 중심 오차(`du_px, dv_px`), 그리고 상단 `minAreaRect` 장축/단축 비율 기반 방향(`classify_container_orientation`: `vertical_ns` 세로 / `horizontal_ew` 가로 / `diagonal` 대각선)을 코드로 직접 판정한다.
       - 목표 구역 채움률·중심 오차 또는 목표 방향(`expected_orientation`)을 벗어나면 `task_verified = False`로 판정하고 실패 원인에 따라 복구 모드(`"re_pick_and_re_place"`, `"re_align_place_zone"`, `"re_orient_and_re_place"`)를 결정한다.
     - 실행 중 발생한 모든 이상·재투입·보정 사례는 `cell_problem_pipeline.py`(`problem-cases.jsonl`)에 자동 기록되어 시뮬레이션(`tools/sim/omx_tier_stack_recovery_sim.py`) 회귀 검증으로 환류된다.

### 검증

- 호스트·원격 단위 및 시뮬레이션 시험:
  - `test/test_omx_area_xyz.py`: `AreaXYZ` 좌표 해석, 슬롯↔명시적 `xyz` 통합, D-911 경계 검증, `side`+`top` 목표 구역 및 컨테이너 방향(`세로/가로/대각선`) 판정, 180° 집게 회전 정규화 검증.
  - `test/test_omx_tier_stack_problem_recovery.py` & `tools/sim/omx_tier_stack_recovery_sim.py`: 실물 실행에서 포착된 문제 상황(이송 중 `park` 낙하, HSV 오검출, 측면 3점 보정, 가로/대각선 오방향 감지 및 재정렬, hover 집게 완전 개방 게이트) 시뮬레이션 학습·회귀 검증 (`8 passed`).
- 실물 셀(`rosy-arm-cell`, `arm_b`) 검증: 미들웨어 `AreaXYZDirective`로 1단·2단·3단 적층 실행 및 `side`+`top` 카메라 구역·방향 검증·텔레메트리 확인.
