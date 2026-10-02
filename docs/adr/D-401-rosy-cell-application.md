## D-401 Rosy Cell은 셀 설정과 레시피를 분리하고 해시로 묶은 Job(Step 목록)을 만드는 Application이다

**Status:** Proposed (2026-10-01, 구조·계약 결정). ROS-free 코어(`rosy_cell`)의 형식만 정한다. Fleet 제출 구현, 화면, 장치 측 Step API, 셋업·티칭용 OMX 장치 API, 도달성·IK 판정, ROS-SIM·DEVICE·FIELD 수용은 포함하지 않는다.

## 배경

- D-399 §5는 첫 Application 후보로 팔에 묶이지 않는 팔레타이징·셋업 앱 Rosy Cell을 지목하고, 범위와 계약을 후속 ADR 4에 넘겼다. 이 ADR이 그 계약 중 셀 설정, 레시피, Job의 형식을 정한다.
- 팔레타이징은 박스와 팔레트 치수에서 층별 배치를 계산하고, 그 배치를 로봇 베이스 좌표의 순서 있는 동작 목록으로 바꾸는 일이다. 이 계산에는 ROS, I/O, 모션, IK가 필요 없다. 그래서 장치와 분리된 순수 코어로 먼저 만들고 테스트한다.
- 셀 설정(작업대에서 한 번 티칭한 좌표계)과 레시피(무엇을 어떻게 쌓을지)는 바뀌는 주기와 소유자가 다르다. 한 파일에 섞으면 레시피를 바꿀 때마다 티칭을 다시 해야 하거나, 티칭이 바뀐 것을 레시피 검증이 모른다.
- 이름은 D-377 규칙("Rosy + 영어 한 단어")을 따른다.

## 결정

1. **Rosy Cell은 D-399 Application이다.** 위치는 `src/site/cell`, 패키지는 `rosy_cell`, 표시 이름은 "Rosy Cell"이다(D-377 규칙 `rosy_<word>`).
2. **입력은 두 파일이다.**
   - `cell.yaml`(schema `rosy_cell.cell/1` (→ `rosy_cell.cell/2`, 아래 보강 참조))은 티칭한 3점 좌표계를 원시 점(원점, x축 위의 점, 평면의 +y쪽 점)으로 보관한다. 검증 임계값(`min_span_m`, `min_angle_deg`, `max_tilt_deg`), 스테이션, `approach_clearance_m`도 여기에 둔다.
   - `recipe.yaml`(schema `rosy_cell.recipe/1`)은 박스, 팔레트(각각 좌표계 id를 가리킴), 모드(`palletize`/`depalletize`), 간격(gap), 층 목록, 슬립 시트를 담는다.
3. **두 파일은 각각 내용 해시(정규화 JSON의 sha256)를 갖는다.** Job은 두 해시를 모두 기록한다. 장치는 자신이 검증받은 셀과 해시가 다른 Job을 거절해야 한다. 티칭이 바뀌면 이전에 검증한 Job은 자동으로 무효가 된다.
4. **Job은 순서 있는 Step 목록이다.** Step은 `pick`, `place`(대상 `box` 또는 `slip_sheet`, 로봇 베이스 좌표 목표 자세, `approach_z`), `pallet_done`이다. 목표 자세 `Pose`는 위치와 yaw만 담는다. `max_tilt_deg`가 허용하는 팔레트 기울기는 Step에 실리지 않는다. 장치의 계획기는 베이스 좌표 자세로 계획하고, 임계값을 넘는 기울기는 셀 설정을 읽을 때 거절된다. Rosy Cell은 Job을 Mission으로 Fleet에 제출하고, Fleet이 승인(D-330)한 뒤 Step을 장치에 하달하는 것이 **유일한 실행 경로**다(Mission/Step 원장은 Fleet, D-328). 이 경로는 아직 열려 있지 않다. D-330 §2는 정지 세대 계약 시험 전 Mission 하달을 열지 않고, D-336 §5는 호스트 간 하달을 보류한다. 그 보류가 풀리기 전에는 Rosy Cell Job이 장치에서 실행되지 않는다. Rosy Cell은 장치를 직접 호출하지 않고, Motion Intent를 보내지 않으며, IK나 도달성을 판정하지 않는다(D-399 §5). 팔 셋업과 티칭을 장치 곁에서 하는 경로는 별도의 OMX 장치·티칭 API ADR이 필요하며(D-399 §5, D-282 §5), 이 ADR의 범위 밖이다.
5. **v1 패턴과 기능.**
   - 패턴은 `grid`(0°와 90° 중 더 많이 들어가는 쪽), `split`(0° 열과 90° 띠), 그리고 어느 층에든 적용하는 `mirrored`(아래 층과 맞물리게 하는 반사)다.
   - 슬립 시트는 어느 층 아래에든 둘 수 있다. 여러 팔레트를 순서대로 채울 수 있다. 디팔레타이즈는 팔레트 순서까지 포함한 정확한 역순이며, 팔레트 하나를 비울 때마다 `pallet_done`을 낸다.
   - 한 층 안의 놓는 순서는 로봇에서 먼 쪽부터다. 적재 순서는 각 팔레트 좌표계에서 로봇 베이스로부터 먼 박스부터이며 레시피가 아니라 티칭한 좌표계에서 나온다. 거리는 팔레트 좌표계 xy 평면에서 박스 중심과 로봇 베이스(베이스 좌표 원점) 사이로 재고, 같으면 (x, y) 순으로 정한다. 보장하는 것은 이 먼 쪽 우선 순서뿐이다. 이미 놓인 박스 옆의 그리퍼·손가락 여유는 여기서 모델링하지 않으며, 레시피 `gap`과 장치 계획기의 몫이다. 로봇 베이스가 팔레트 바닥 영역 안에 놓이도록 티칭된 팔레트는 컴파일에서 거절한다.
6. **임계값은 설정에서 받고, 기하 기본값은 URDF에서 온다**(D-397 규칙). 코드는 물리 기본값을 갖지 않는다. 유일한 리터럴은 정확히 맞는 경우를 바닥 처리에서 잃지 않기 위한 float 여유(`1e-9`)다.

## 검토한 대안

| 대안 | 판단 |
|---|---|
| MoveIt Task Constructor를 앱 안에서 실행 | 앱이 IK와 도달성을 갖게 되어 D-399 §5와 D-376(계획은 장치 로컬)에 어긋난다. 채택하지 않는다. |
| ROBOTIS의 "task constructor 탭" 방식 | 장치 UI와 앱이 한 프로세스에 붙는다. Fleet 승인과 장치 로컬 owner 경계를 건너뛴다. 채택하지 않는다. |
| 벤더 팔레타이징 UI | 특정 로봇·컨트롤러에 묶이고 레시피, 해시, Fleet 원장과 연결되지 않는다. 팔에 묶이지 않는 Application이라는 목표와 맞지 않는다. 채택하지 않는다. |
| 셀 설정과 레시피를 한 파일에 둔다 | 위 배경의 이유로 채택하지 않는다. |

## 결과

- Rosy Cell 코어는 `rosy_cell` 하나로 ROS 없이 테스트된다. Fleet 제출, 화면, 장치 Step 실행은 각각 후속 작업이다.
- 레시피는 해시로 고정되고, 티칭 변경은 셀 해시 불일치로 장치에서 거절된다.

## 수용 기준과 증거 경계

- **SOURCE:** `rosy_cell` 코어가 위 형식으로 패턴, 스택, 순서, 로더, 컴파일러를 구현하고 ROS-free pytest가 통과한다.
- **ROS-SIM / DEVICE / FIELD:** 이 결정으로 승격하지 않는다. 도달성과 실행은 장치 측 Step API와 MoveIt 채택(D-399 후속 3)이 있어야 한다.
  - **보강 (2026-10-01, D-402):** 시뮬레이션 실행은 [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md)의 해석 IK로 먼저 하고, MoveIt은 같은 인터페이스의 후속 구현으로 붙인다. 셀 schema는 `rosy_cell.cell/2`(`home`, `kinematics_revision`)로 올린다([D-404](D-404-omx-setup-teaching-api-simulation-first.md) §5).
  - **보강 (2026-10-02, C3b):** 레시피 `box`에 선택 필드 `grasp_depth`(m)를 둔다. TCP가 상자 윗면에서 이만큼 아래에서 쥔다. 0 ≤ `grasp_depth` < `height`이고 없으면 0(윗면, 기존 계약)이다.
    - 자리는 셀 공구 정의가 아니라 물건(레시피)이다. 안전하게 쥘 높이는 물건마다 다르고, 같은 공구로 슬립시트(2 mm)는 윗면에서 쥐어야 하기 때문이다. 공구 쪽 한계(TCP 바닥, 패드 길이)는 장치 플래너가 거절로 지킨다.
    - 상자 Step의 `target.z`는 이제 TCP 파지 높이 = 윗면 − `grasp_depth`다. `approach_z`는 그대로 윗면 + `approach_clearance_m`이다. 슬립시트는 깊이 0이다.
    - `carry_z` = 가장 높은 면 + 매달린 높이 + clearance. 매달린 높이 = max(`height` − `grasp_depth`, 슬립시트 두께)다. 쥔 상자의 바닥이 TCP 아래 `height − grasp_depth`에 있기 때문이다.
    - 공구 손가락 끝은 TCP보다 `fingertip_overhang_m` 아래까지 내려간다. 이 값은 `cell.yaml`의 필수 필드다. 장치 프로필(OMX: `cell_profile.yaml` `gripper.fingertip_overhang_m`, 고정 URDF와 손가락 mesh에서 0.00257 m)에서 받는다. 두 값은 저장소 루트의 교차 계약 시험이 같게 묶는다. 셀은 공구가 실제로 놓인 자리이고, `rosy_cell`은 장치 패키지를 import하지 않기 때문이다.
      - 매달린 높이 = max(`height − grasp_depth`, 슬립시트 두께, `fingertip_overhang_m`).
      - `grasp_depth > height − fingertip_overhang_m`이면 컴파일이 거절한다. 손가락 끝이 상자 바닥 아래로 내려가면 놓는 면을 찌르기 때문이다.
      - (리뷰 보강 2026-10-02.) 아직 영속된 `cell/2` 파일이 없어 schema 번호는 올리지 않았다.
    - C3 Gazebo에서 Step z가 윗면이라 손가락이 2–3 mm만 걸쳤다(C3 문제 6). 근거와 실측은 [C3 증거](../validation/rosy-cell-gazebo-c3-2026-10-02/README.md)에 있다.

**관련 결정:** [D-328](D-328-model-proposed-missions-and-independent-goal-evidence.md), [D-376](D-376-omx-pick-place-planning-and-execution-boundary.md), [D-377](D-377-app-names-rosy-plus-one-english-word.md), [D-386](D-386-omx-async-goal-acceptance-and-phase-state.md), [D-397](D-397-pinky-geometry-urdf-nominal-calibration-refines.md), [D-399](D-399-rosy-layered-architecture-site-plane-device-pipeline.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md), [D-336](D-336-fleet-omx-local-ipc-boundary.md)
