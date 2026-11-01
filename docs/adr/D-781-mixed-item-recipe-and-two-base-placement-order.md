## D-781 혼합 레시피(`rosy_cell.recipe/3`)와 팔 베이스 둘을 아는 놓는 순서

**Status:** Proposed

**Amended by:** [D-929](D-929-packing-row-gap-band-and-prior-stack-window.md) — §1 `gap`과 §3.1의 간격 조건(측정 이웃 면 기준 놓기에서 2~5 mm 띠).

이 ADR은 D-778 §9의 마지막 G1 선행 조건을 정한다. 크기와 모양이 다른 물체를 쌓는 레시피 스키마, 그리고 컴파일러가 낼 Step의 모양과 순서 규칙이다. 적재 계획 알고리즘의 구현, 온라인 적재, 실물 수용을 뜻하지 않는다. 지금의 `rosy_cell.recipe/1`·`/2`는 바뀌지 않는다. 폴더나 패키지 구조도 바꾸지 않는다.

## Context

[D-778](D-778-bimanual-workcell-foundation.md)은 혼합 팔레타이징을 목표로 정했다. [D-779](D-779-per-arm-cell-job-ledger-and-arm-zone-claims.md)는 Step마다 `depends_on`, `arm`, `alternates`, `zone`을 요구한다. [D-780](D-780-workcell-coordinator-peer-stop-source-and-named-barriers.md)은 협조 Step마다 `barriers`를 요구한다. 이 값들을 내는 것은 컴파일러다. 근거 조사는 [혼합 팔레타이징 적재 계획과 양팔 역할](../assessments/2026-10-17-mixed-palletizing-stacking-plan-research.md)이다.

지금 레시피와 컴파일러는 상자 한 종류를 전제한다. 로컬 main 기준의 소스를 읽은 결과다.

| 영역 | 지금 | 근거 |
|---|---|---|
| 스키마 | `rosy_cell.recipe/1`(로봇이 간지를 놓음)과 `/2`(사람이 간지를 놓음)가 있다 | `operations/processes/palletizing/src/rosy/processes/palletizing/__init__.py` |
| 물체 | `box`가 하나다. 길이·폭·높이·무게와 선택 `grasp_depth`를 가진다 | `recipe.py` |
| 배치 | 층마다 `grid` 또는 `split` 패턴이다. 층을 좌우로 뒤집을 수 있다 | `recipe.py`, `pattern.py` |
| 순서 | 한 층 안에서 로봇 베이스에서 먼 것부터, 같으면 (x, y) 순이다. 핑거 여유는 모델링하지 않고 `gap`에 맡긴다 | `sequence.py` |
| 이동 | 수직 상승 → `carry_z`에서 이동 → 수직 하강이다. `carry_z`는 상자 높이 하나로 정해진다 | `compiler.py`, D-402 §6 |
| 집기 | 고정된 `pick_station` 하나에서 집는다. 치수는 레시피 값이다 | `recipe.py`, `cell.yaml` `stations` |
| 집은 물체 확인 | owner는 레시피 해시와 물체 이름으로 승인된 물체 형상을 찾아, 그리퍼 폭 읽기와 비교한다 | `middleware/devices/omx/adapter/omx_adapter/cell_acceptance.py` `accepted_item_geometry` |
| 예시 | 40×30×30 mm, 20 g 폼 블록. 팔레트 0.10×0.08 m, 2층, `gap` 15 mm | `operations/processes/cell/examples/omx_sim/recipe.yaml` |

## Decision

새 스키마 `rosy_cell.recipe/3`을 더한다. 이 스키마는 패턴과 층 대신 **물체 목록**을 받는다. 컴파일러는 그 목록으로 **놓을 자리와 순서**를 계획하고, D-779·D-780이 요구하는 Step 필드를 낸다. 첫 버전은 오프라인이다. 물체 목록은 미리 알고, 공급 순서는 계획이 정한다.

### 1. 스키마 `rosy_cell.recipe/3`

```yaml
schema: rosy_cell.recipe/3
name: omx-mixed-foam
mode: palletize
items:
  - sku: foam_40x30x30
    length: 0.040
    width: 0.030
    height: 0.030
    mass_kg: 0.020
    grasp_depth: 0.015
    quantity: 4
    orientation: yaw_only        # yaw_only | upright_fixed
    max_load_on_top_kg: 0.10
  - sku: foam_30x20x20
    ...
pallets:
  - {id: A, frame: pallet_a, length: 0.20, width: 0.15, max_stack_height: 0.07, max_load_kg: 0.5}
pick_stations: [infeed_left, infeed_right]
gap: 0.008
stability:
  rule: support_ratio_v1
  max_height_to_base_ratio: 1.5
planner:
  candidates: extreme_points
  yaw_deg: [0, 90]
  allow_push: false
```

- **`items`:** 종류(`sku`)마다 치수, 무게, `grasp_depth`, 수량, 방향 제약, 위에 올릴 수 있는 무게 상한을 적는다.
    - 잡는 폭(그리퍼가 쥐는 면)은 승인된 그리퍼 범위 안이어야 한다. 지금 cell profile은 10~50 mm를 허용한다.
    - 방향은 OMX가 위에서 집기 때문에 `yaw_only`(위 면 고정, 0°/90°만)가 기본이다. 면을 바꾸는 방향은 `handover` Action 종류가 생긴 뒤에 연다(D-778 §9).
- **`pallets`:** 지금과 같다. 양팔 작업대는 0.20×0.15 m 이상이다(D-778 §2).
- **`pick_stations`:** 집는 자리 목록이다. 이름은 `cell.yaml`의 `stations`에 있어야 한다. 어느 팔이 어느 자리에 닿는지는 컴파일러가 `base_in_cell`로 계산한다.
- **`gap`:** 이웃과의 최소 간격이다. OMX의 추정 위치 오차(2~5 mm)보다 커야 한다. 컴파일러는 핑거 개구를 따로 계산하므로(§3), `gap`은 핑거 두께를 담지 않는다.
- **`stability`:** 지지 규칙의 이름과 매개변수다. 첫 규칙 `support_ratio_v1`은 Zhao et al. 2021의 지지 비율·모서리 규칙이다. 바닥의 60%를 넘게 지지되고 모서리 4개가 지지되거나, 80%를 넘게 지지되고 모서리 3개가 지지되거나, 95%를 넘게 지지되면 통과다. 높이가 바닥 짧은 변의 1.5배를 넘는 물체는 첫 버전에서 받지 않는다.
- **`planner`:** 후보 생성 방법, 허용 회전, 밀기 허용 여부다. `allow_push`는 `CELL_PUSH`가 생기기 전까지(D-778 §9, G2.5) `false`만 받는다.
- **받지 않는 것:** `mode: depalletize`, 간지(`slip_sheet`), `layers`는 이 스키마에서 받지 않는다. 섞인 더미를 내리는 일은 관측이 필요하다. 그래서 첫 버전에서 뺀다.
- 레시피 해시는 지금처럼 파싱된 값의 정규 JSON sha256이다.

### 2. 공급 순서는 계획이 정한다

- 오프라인 레시피에서는 컴파일러가 물체마다 놓을 자리와 순서를 정한다. 그 결과로 **집는 자리마다 공급 순서**가 나온다.
- 공급하는 쪽(시뮬레이션의 생성기, 실물의 운영자나 피더)은 그 순서대로 물체를 집는 자리에 둔다. Console은 집는 자리마다 다음에 올 `sku`를 보여 준다.
- Step마다 기대하는 `sku`를 적는다. owner는 지금의 `accepted_item_geometry`로 그 `sku`의 형상을 찾아 그리퍼 폭 읽기와 비교한다. 다른 물체가 왔으면 그 Action은 실패하고, 그 팔이 HOLD된다(D-779 §6).

### 3. 컴파일러가 지킬 계획 규칙

계획 알고리즘의 구현은 정하지 않는다. 첫 구현은 조사 보고서의 추천을 따른다. Extreme Points로 후보를 만들고, 깊고 낮고 구석에 가까운 자리에 점수를 주며, 물체를 하나씩 탐욕적으로 놓는다. 어떤 구현이든 아래 규칙은 지킨다.

1. **기하:** 팔레트 경계 안, 다른 물체와 `gap` 이상 떨어짐, `max_stack_height` 이하, 총무게 `max_load_kg` 이하.
2. **지지:** `stability.rule`을 통과한다. 아래 물체들의 `max_load_on_top_kg`를 넘지 않는다. L1에서는 혼자 안정한 자리(`standalone`)만 허용한다(D-778 §6).
3. **핑거 여유:** 그리퍼가 쥐는 두 면 바깥으로 핑거 두께와 개구만큼의 공간이 비어 있어야 한다. 그 공간은 위에서 내려오는 경로 전체에 걸쳐 확인한다. 손목 회전으로 핑거가 빈 쪽 면을 잡도록 고를 수 있다.
4. **도달성:** 놓을 자세와 집는 자세가 그 팔의 `base_in_cell`로 바꿨을 때 D-402 IK의 해를 가진다. 지금은 장치에서야 확인하는 이 검사를 컴파일 단계로 앞당긴다. 같은 IK 코드를 쓴다.
5. **이동 높이:** `carry_z`는 그 Step 때까지 쌓인 가장 높은 곳과 들고 있는 물체 높이로 Step마다 정한다. 한 값으로 고정하지 않는다.
6. **이동 방식:** L1에서는 D-402 §6의 수직 하강으로만 놓는다. 벽이나 이웃에 붙여 미끄러뜨리는 놓기는 낮은 높이의 수평 이동이므로, `CELL_PUSH`와 함께 연다.

### 4. 팔 배정과 순서 (D-401 §5의 "로봇 베이스에서 먼 것부터" 대체)

- **팔 배정:** 후보 자리마다 닿는 팔 목록을 계산한다. 주 배정 팔은 그 자리가 있는 고정 구역(`left_half`, `right_half`)의 팔이다. 공유 띠의 자리는 닿는 팔 가운데 하나를 주 배정으로 하고, 그 Step의 `zone`은 `shared_band`다. 닿는 다른 팔은 `alternates`가 된다. 대체 팔마다 Action 내용을 따로 컴파일한다(D-779 §4).
- **순서:** 탐욕적 계획이 물체를 놓은 순서가 기준 순서다. 컴파일러는 그중 꼭 지켜야 할 앞뒤 관계만 `depends_on`으로 남긴다.
    - **지지:** 물체 B를 받치는 물체 A는 B보다 먼저다.
    - **핑거 여유:** B의 핑거 여유 공간(규칙 3)에 걸리는 A가 B를 놓을 때 이미 있다고 가정했다면, A는 B보다 먼저다. 반대로 A가 B를 놓는 경로를 막는다면 A는 B보다 나중이다. 계획이 정한 순서는 늘 앞의 경우가 되도록 만든다.
    - **구역:** 같은 팔이 하는 Step끼리는 기준 순서를 따른다.
    - 이 셋에 해당하지 않는 Step끼리는 의존이 없다. 서로 다른 구역의 Step은 두 팔이 동시에 할 수 있다.
- **같은 팔 안의 기본 순서:** 점수가 같은 후보 사이에서는 그 팔의 베이스에서 먼 자리를 먼저 고른다. 지금의 "먼 것부터"는 팔마다의 동점 처리 규칙으로 남는다.
- 팔이 하나인 작업대에서는 `alternates`가 없고, 모든 Step이 같은 팔이다. 그래서 Step은 기준 순서대로 직렬이다.

### 5. 컴파일 결과와 해시

- Step마다 `role`(첫 버전은 `place`), `sku`, `arm`, `alternates`, `zone`, `coupling`(`independent`), `depends_on`, 팔별 Action 내용(`cell` 좌표계에서 그 팔의 베이스 좌표로 바꾼 것)을 낸다. 협조 Step이 생기면 `barriers`도 낸다(D-780 §3).
- 집는 자리마다 공급 순서를 낸다.
- 같은 레시피, 같은 `cell.yaml`, 같은 계획기 버전이면 결과가 같아야 한다(결정적). 계획기 버전은 지금의 `process_artifact_digest`에 들어간다. 무작위 요소를 쓰면 씨앗을 레시피에 적는다.
- Job은 지금처럼 레시피·작업대·처리 산출물 세 해시를 기록하고, 두 사람이 승인한다(D-401 §3, D-403 §3).

### 6. 바꾸지 않는 것

- `rosy_cell.recipe/1`·`/2`, 그 패턴(`grid`, `split`), 간지, 내리기 모드, 그 컴파일 결과. 기존 레시피는 지금과 같은 Job과 해시를 낸다.
- D-402 §6의 이동 규칙. 이 ADR은 `carry_z`를 Step마다 정할 뿐, 수직 상승·이동·하강의 모양은 바꾸지 않는다.
- D-450의 상자 한 종류 팔레타이징 목표와 그 증거.

## Alternatives

- **`recipe/1`에 `items`를 선택 필드로 더하기:** 스키마가 하나로 남는다. 그러나 `box`·`layers`와 `items`가 함께 있을 때의 뜻이 모호하고, 기존 레시피의 해시가 바뀔 위험이 있다. 기각한다.
- **온라인(도착 순서대로)부터 하기:** 공급 순서를 맞출 필요가 없다. 그러나 Step을 미리 만들 수 없어 해시와 두 사람 승인 모델을 바꿔야 한다. 기각한다. 별도 ADR로 연다.
- **계획 알고리즘을 ADR로 고정하기:** 구현이 하나로 정해진다. 그러나 점수 단계는 나중에 PCT 같은 학습 방법으로 바꿀 수 있어야 한다. 규칙(§3)만 고정하고 알고리즘은 열어 둔다.
- **순서를 직렬로 두기(`depends_on = [i-1]`):** 단순하다. 그러나 두 팔이 동시에 일할 수 없다. 기각한다.
- **공급 순서 대신 집는 자리에서 물체를 식별하기:** 운영자 부담이 줄지만, 카메라 식별과 온라인 계획이 필요하다. 온라인 ADR에서 다룬다.

## Consequences

- `palletizing` 패키지에 `recipe/3` 로더, 계획기, 의존 관계 생성, 팔별 Action 컴파일이 생긴다. Fleet Cell 컴파일 경로(`cell_compiler.py`)가 `recipe/3`을 받는다.
- 컴파일러가 D-402 IK를 부른다. IK 코드는 장치와 컴파일러가 같은 구현을 쓰도록 공유 위치에 둔다. 위치는 구현 때 `platform_parts.yaml`과 D-429의 import 경계에 맞춘다.
- owner의 승인된 물체 형상 목록은 레시피 하나에 여러 `sku`를 갖는다.
- Console에 집는 자리별 공급 순서와 다음 `sku` 표시가 필요하다.
- 시뮬레이션 생성기는 공급 순서대로 물체를 만든다.

## Transition / Validation

1. **SOURCE 시험:**
    - `recipe/3` 로더가 잘못된 치수, 그리퍼 범위 밖의 잡는 폭, 받지 않는 키(`layers`, `slip_sheet`, `depalletize`)를 거부하는지 확인한다.
    - 같은 입력이면 같은 Job 해시를 내는지 확인한다.
    - 모든 Step이 §3의 규칙을 지키는지 독립 검사기로 확인한다.
    - `depends_on`에 순환이 없고, 지지·핑거 여유 관계를 모두 담는지 확인한다.
    - 기존 `recipe/1`·`/2`의 Job과 해시가 바뀌지 않는지 확인한다.
2. **G1 SIM(한 팔):** 물체 3~4종, 0.20×0.15 m 팔레트로 혼합 적재를 끝까지 실행한다. 무너짐 0과 적재율 기준선을 기록한다.
3. **G1 SIM(두 팔):** 같은 레시피를 두 팔로 실행해, 서로 다른 구역의 Step이 동시에 실행되고 공유 띠가 한 팔씩만 쓰이는지 확인한다. 한 팔 기준선과 걸린 시간을 비교한다.
4. 적재율 비교 기준으로 py3dbp 포크의 오프라인 결과를 함께 기록한다(보고서 로드맵 1단계).

열린 질문:

- 공급 순서를 운영자가 지키기 어려울 때, 집는 자리에 작은 버퍼(여러 칸)를 두어 순서를 느슨하게 할지
- `max_height_to_base_ratio` 1.5와 `support_ratio_v1` 비율이 폼 블록에 맞는지(G1에서 확인)

**References:** [D-778](D-778-bimanual-workcell-foundation.md), [D-779](D-779-per-arm-cell-job-ledger-and-arm-zone-claims.md), [D-780](D-780-workcell-coordinator-peer-stop-source-and-named-barriers.md), [D-401](D-401-rosy-cell-application.md), [D-402](D-402-omx-motion-planner-v1-analytic-top-down-ik.md), [D-403](D-403-fleet-cell-job-route-cell-transfer.md), [D-450](D-450-palletizing-app-completion-goals.md), [적재 계획·양팔 역할 조사](../assessments/2026-10-17-mixed-palletizing-stacking-plan-research.md).
