## D-597 차선 유지(keep)가 학습 모델의 drivable 영역으로 길을 찾아 조향한다 — `learned_paint_target: drivable`

**Status:** Accepted (2026-10-10, 사용자 결정 "A로 하면서 B로 바로 처리"; 같은 날 추가 결정: 추론은 로봇 기본, 지연이 안 되면 Fleet(현장 PC), 교차로는 D-384 2항 우측 규칙, "모델은 주행 가능 영역을 찾고 우리는 길을 찾아 진행한다"). 개정 1(2026-10-10, 사용자 "drivable에서 빠지면 횡단보도일 경우 멈췄다가 건너도록 하는 걸로 처리해."): 횡단보도 구간을 같은 추론의 `crosswalk` 클래스에서 낸다(9항). 개정 2(2026-10-10, 사용자 "조향 로직을 수정해서 꼭 돌게 만들어야 해."): keep이 drivable 길의 가운데로 직접 조향하고 막힌 모서리에서 제자리 회전한다(10항).

### Context

- 로봇의 learned paint(D-408)는 모델 출력 중 `lane_marking` 클래스만 쓴다(`learned/runner.py` `infer_mask` → `lane_marking_mask`). v13 계열과 팀 crop128 모델의 `drivable` 클래스는 버려진다. 잘 학습된 drivable 모델이 주행에 아무 영향을 주지 못한다.
- D-592 5항은 로봇 런타임에 drivable 조향 소스를 넣는 일을 따로 정한다고 했다. 사용자가 지금 넣기로 했다.
- 팀 crop128 모델(`lane-seg-20261010-71edcb6d`, 6 클래스, 마지막이 drivable)은 입력이 320x240 프레임의 112..239 행이다. 9dfk에 있는 번들은 그래프 안에서 자르고 0..111 행을 background로 채운 포장본이다. 원본은 매니페스트에 `input.crop`을 둔다. 지금 로더는 이 키를 모르고 조용히 무시한다.
- 모델은 선을 넘지 않고 닿는 바닥을 모두 drivable로 칠한다. 교차로에서는 갈 수 있는 갈래가 모두 칠해진다. 갈래 선택은 조향의 몫이다(전달 문서 §1).

### Decision

1. **새 매개변수.** `line_observer`에 읽기 전용 `learned_paint_target`을 둔다. 값은 `lane_marking`(기본, 지금과 같음)과 `drivable`이다. `paint_source: learned`일 때만 의미가 있다. D-408의 `paint_source` 값과 Host Agent·CORE API(`PUT /line-follow/perception`)는 바꾸지 않는다.
2. **한 번의 추론에서 길을 만든다.** `drivable`이면 paint worker가 `infer_drivable`을 부른다. 순수 함수 `learned/drivable_paint.py`가 다음을 한다(numpy만, ROS 없음).
   - drivable 클래스에서 D-566 4항 `lane_bounded_drivable`(차선 화소 차단, D-576 바깥 차단)로 로봇 앞 도로와 이어진 영역을 구한다. `ignore` 역할(횡단보도, 과속방지턱)은 도로로 본다. 통과만 허용하면 행이 끊긴다.
   - 행 폭 증가 제한(MAX_ROW_GROWTH)은 쓰지 않는다. 그 제한은 아래 행 가운데에 가까운 조각을 남기고 동점이면 왼쪽을 고르므로, 갈래 선택이 D-384와 어긋난다.
   - 영역이 둘러싼 구멍(상자, 잘못 칠한 화소)은 채운다. 갈래가 아니다.
   - 가장 아래 행에서 화면 가운데에 가까운 조각(로봇 아래 도로)에서 시작해 위로 올라가며, 아래 조각에 닿는 조각만 남긴다. 아래 조각 폭의 1/4 이상인 조각이 둘 이상이면 길이 갈라진 것이고 **가장 오른쪽**을 따른다. 그보다 좁은 조각은 가장자리 들쭉날쭉함이다(D-384 2항: 명시 경로·목표 > 목표 없는 교차로는 우회전 > 비등하면 가장 오른쪽). 경로·목표 방향을 갈래 선택에 넣는 일은 뒤 단계다(아래 7).
   - 근거리 띠(아래 40%)에서 그 길이 2% 미만이거나 모델에 drivable 클래스가 없으면 길이 없다. 그때는 같은 추론의 `lane_marking` 마스크를 쓴다(지금의 `learned`와 같다). 마스크가 없거나 늦으면 지금처럼 `denoise_fallback`이다.
3. **keeper에는 경계 페인트로 준다.** 길의 각 행 양쪽 바로 바깥에 선 하나 폭(2 x `lane_paint_half_width_m`, 그 행의 지면 축척)의 띠를 그린다. keeper가 맞추는 페인트 중심은 drivable 경계에서 반 폭 바깥이고, 안쪽 경계(D-408·lane_containment의 drivable 경계)는 drivable 경계 자체다. 화면 가장자리에 닿은 쪽에는 띠를 그리지 않는다. 그 너머는 안 보인 곳이지 경계가 아니다. 짝짓기·측면·모서리·HOLD 판단은 `LaneKeeper` 그대로다.
4. **크롭 입력 매니페스트를 지원한다.** `input.crop = {from_frame: [H, W], rows: [a, b]}`를 읽는다. W가 입력 폭이고 b−a가 입력 높이여야 하고, background 클래스가 있어야 한다. 아니면 거부한다. 프레임을 H x W로 줄이고 a..b−1 행을 넣고, 출력은 전체 프레임 격자에 되돌려 놓으며 나머지 행은 background다. drivable 길은 a행 위로 가지 않는다(`ignore_top = a`). 이 키가 없는 매니페스트는 지금과 같다. 옛 로더는 이 키를 무시하므로 크롭 원본 번들은 이 변경이 들어간 릴리스에만 넣는다. 포장본은 어느 쪽에서나 같다.
5. **출처를 남긴다.** keep_debug의 `paint_source_used`는 길을 썼으면 `learned_drivable`, 차선 마스크로 돌아갔으면 `learned`다. `paint_target_requested`와 `paint_drivable`(`reason` ok/no_drivable_class/low_coverage, `branches`, `near_fraction`)을 함께 싣는다. CORE readback은 `learned_drivable`을 받아 API에는 `learned`로 보고한다. API 열거값과 버전은 그대로다.
6. **기본은 꺼짐이고 로봇별로 켠다.** 운영자 overlay `/etc/rosy/line_observer_overrides.yaml`에 `learned_paint_target`을 허용 키로 넣는다. `lane_marking`, `drivable` 외의 값이면 overlay 전체를 건너뛴다. `paint_source`가 `learned`가 아니면 이 키는 아무 일도 하지 않으므로, Host Agent가 `threshold`로 되돌려도 파일이 유효하다. 켜는 방법은 `line_observer_overrides apply ... --paint-source learned --model-pointer <포인터> --paint-target drivable`이다. 추론 주기(`learned_paint_every_n`), 재사용·움직임 보정(D-570), 오래된 마스크 거절은 지금 paint worker 규칙 그대로다. CORE가 유일한 최종 `/cmd_vel` 발행자다. RobotBody 가드, IR, watchdog, 모드 규칙은 바뀌지 않는다.
7. **추론 위치.** 기본은 로봇(지금의 learned paint worker)이다. Pi 지연이 주행 주기를 못 맞추면 다음 단계는 Fleet(현장 PC) 추론이다. 2의 함수가 순수 함수라 그대로 옮길 수 있다. Fleet 경로는 이번에 만들지 않는다.
8. **뒤로 미룬 것.**
   - Fleet 경로·목표 방향에 따른 갈래 선택(D-384 2항 첫 순위)
   - 옆으로 열리는 T자 갈래의 우회전(지금은 한 조각이 넓어질 뿐 갈래로 보지 않는다)
   - ~~횡단보도: keeper의 D-491 횡단보도 범위는 이 출처에서 비어 있다.~~ 개정 1(9항)이 닫았다. 과속방지턱은 길 안의 도로로 지나간다. 감속 매개변수는 지금 없다.
   - Pi 지연 측정과 D-475 §8 조향 오차 관문, 실물 시험(D-378 순서)

9. **개정 1 (2026-10-10): 횡단보도는 같은 추론의 `crosswalk` 클래스로 알고, 서고, 보고, 건넌다.** 사용자: "drivable에서 빠지면 횡단보도일 경우 멈췄다가 건너도록 하는 걸로 처리해."
   - 길 계산(2항)은 그대로다. 횡단보도·과속방지턱 화소는 길 안의 도로다. 그래서 횡단보도에서 길이 끊기거나 `low_coverage`가 되지 않고, 건너는 동안과 건넌 뒤에도 keeper가 같은 길을 따른다.
   - `infer_drivable`은 모델에 `crosswalk`라는 이름의 클래스가 있으면 그 클래스 마스크를 프레임 크기로 함께 낸다(argmax 한 번 더, 추론은 그대로 한 번). paint worker가 이 마스크를 paint 옆에 두고, paint를 D-570으로 옮길 때 같은 움직임으로 옮긴다. keep_debug(`paint_drivable`)에는 싣지 않는다.
   - keeper는 줄무늬 검출(D-491 4항)이 아무것도 못 찾을 때 이 마스크를 같은 BEV 격자에 놓고, 로봇 차로 corridor(`CORRIDOR_HALF_M`) 칸의 `CLASS_ROW_FRACTION`(0.25) 이상을 덮는 행이 `MIN_ROWS` 이상 이어진 가장 긴 구간을 D-491 구간 `{near_m, far_m}`으로 낸다. 옆 차로의 횡단보도와 몇 행짜리 잘못 칠한 화소는 구간이 아니다. 출력 계약(containment `crosswalk`)과 `uncertainty_m` 상한 규칙은 D-491 그대로다. 이 마스크는 `paint_source_used`가 `learned_drivable`인 프레임에만 쓴다.
   - 서고, 보고, 건너는 일은 CORE D-573 게이트(`crosswalk_gate_enabled`)의 몫이다. 이 개정은 게이트에 카메라 구역을 줄 뿐 CORE 코드와 기본값을 바꾸지 않는다. 게이트가 꺼진 로봇은 구역으로 IR 가드만 쉬고(D-491) 서지 않는다. 켜는 일은 로봇별 설정이고 D-573 켜기 조건(D-577 열린 항목 1)을 따른다.
   - 차로를 가로지르는 흰 선(정지선, `lane_marking` 클래스)은 지금처럼 길을 끊는다. 횡단보도 구간이 되지 않는다.
10. **개정 2 (2026-10-10): keep은 drivable 길의 가운데로 조향하고, 막힌 모서리에서는 제자리에서 돈다.** 사용자: "조향 로직을 수정해서 꼭 돌게 만들어야 해." 같은 날 사용자 의도: keep은 drivable 차로 공간의 가운데를 따라간다. "제자리 도는 것도 생각해서 해야 해. 지금처럼 앞으로 갔다 뒤로 갔다도 좋은 방안이야."
   - 3항의 경계 띠는 테이프 keeper의 짝짓기(차로 폭 0.6–1.6배)에 걸렸다. 길이 차로보다 넓거나(고리, 교차로 입구) 한쪽이 화면 가장자리에 닿으면 한쪽 목표(신뢰 0.6)가 되었고, 벽 앞 L자 모서리에서는 경계가 없어 HOLD `camera_line_not_visible` → 뒤로 물러남 → `camera_reselection_required`가 되었다(9dfk 녹화 20261009T225647Z_rosy_41).
   - 이제 `learned_paint_target: drivable`이면 `line_observer`가 최신 추론의 길(프레임 크기 마스크)에서 직접 조향한다(`learned/drivable_steer.py`, 순수 numpy). 행마다 길의 왼쪽·오른쪽 끝을 지면 좌표로 바꾼다. 양 끝이 보이면 가운데, 한 끝이 화면 가장자리면(안 보임) 보이는 끝에서 `lane_half_width_m`만큼 안쪽, 둘 다 안 보이면 화면 가운데다. 앞보기(0.25 m) ±0.03 m 행들의 중앙값이 목표점이고, 길이 거기까지 닿지 않으면 길의 가장 먼 행들을 쓴다. 출력 계약은 keeper와 같다(error = −y / `lane_half_width_m`, 양쪽 0.9, 한쪽 0.6).
   - 길 마스크는 D-570처럼 다시 그리지 않는다. 목표점 하나를 마스크 프레임 시각과 지금 프레임 시각의 odom 자세 차이로 옮긴다. 마스크는 paint worker의 `stale_s` 안의 것만 쓴다. 없으면 keeper 결과(지금과 같음)를 쓴다.
   - **제자리 회전.** 로봇 앞 통로(|y| ≤ 0.05 m)가 길 위에 있는 거리가 0.24 m 미만이고 길이 화면 옆으로 나가면, 그쪽으로 제자리에서 돈다(error ±0.5, 신뢰 0.37 → CORE 속도 배율이 선속도를 거의 0으로 만든다). 양옆이 다 열려 있으면 더 멀리까지 열린 쪽, 비슷하면(0.05 m 안) 오른쪽이다(D-384 2항). 앞이 0.30 m 이상 열리면 회전을 푼다. 앞이 막히고 옆 출구도 없으면 목표가 없다(HOLD). 그때는 CORE의 뒤로 물러나기(D-407)와 자동 재개(D-407 개정)가 앞뒤 왕복으로 다시 시도한다. 회전 중에는 keeper만 초기화하고 paint worker 마스크는 버리지 않는다.
   - 이 출처의 keep_debug `strategy`는 `drivable_centre`, `drivable_pivot_left|right`이고 `drivable_steer`에 판단(앞 거리, 출구, 목표)을 싣는다. 길이 이미 갈래를 골랐으므로 테이프 keeper의 교차로 HOLD 이유와 `junction_ahead_m`은 싣지 않는다. 횡단보도 구간(9항)과 containment는 keeper 계산 그대로다.

11. **개정 3 (2026-10-10): 선을 넘지 않고, 좌우를 헷갈리지 않는다.** 사용자: "지금 가운데 원에서 시작해서 저렇게 원안으로 들어간 거야. 그것까지 확인해서 문제를 해결해야 해. 선이 넘어가는 문제 그리고 좌우측에 대한 차선을 추종하게 될 경우 이를 헷갈리는 문제에 대해서 고민해서 해야 해. 로직적으로 우리가 해결을 할 수 있게. 녹화된 영상을 보고 판단해서 해결해 볼래." "너가 직접 ROSY CAM을 보면 알잖아."
   - 원인(천장 카메라 기록 Fleet path D-594 + 로봇 녹화): 모델의 drivable은 "로봇에서 선을 넘지 않고 닿는 바닥"이라 로봇 위치에 상대적이다. 몸이 선을 넘으면 선 너머가 새 길이 되고 로봇은 그대로 길 밖을 달린다. 9dfk 20261010T011623Z_rosy_41은 기록 156점 중 49점이 선 위, 89점이 차로 밖이었다. 넘는 순간은 제자리 회전(앞이 선 위로 쓸림)과 출구 쪽 호(안쪽 모서리를 자름)였다.
   - 길 경계 기억: 근거리(0.25 m 이내) 길 가장자리(화면 가장자리가 아닌 쪽)를 odom 좌표로 기억한다. 목표점까지의 직선이 기억한 경계를 지나면 그 목표를 버리고 경계 안쪽(몸 반폭 + 0.01 m)으로 둔다(`*_kept`). 화면을 떠난 선도 넘지 않는다.
   - 한쪽만 보일 때의 목표는 보인 가장자리(테이프 안쪽 끝)에서 차로 반폭 − 테이프 반폭 안쪽이다.
   - 벽(카메라 시야 밖): LiDAR 몸 띠 정면 거리로 길 앞 거리를 줄인다. 옆 0.20 m 안에 0.10 m 넘게 이어진 벽이 있으면 그쪽은 출구가 아니다(신호등 기둥은 벽이 아니다). 두 출구가 비슷하면 오른쪽(0.10 m 차 안).
   - 출구 기억: 길이 막혔는데 옆 출구가 시야에 없으면 0.5 m 안에서 마지막으로 본 출구 쪽으로 돈다.
   - 선 위 제자리 회전은 CORE가 뒤로 조금 물러나며 돈다(D-344 §12 개정 3).

### Consequences

- drivable 모델이 처음으로 로봇 조향에 들어간다. 선이 지워졌거나 반사가 심해도 바닥 영역으로 경계를 잡는다.
- 갈래가 보이면 오른쪽으로 간다. 경로를 모르는 상태의 규칙이며 Fleet 경로가 있으면 뒤 단계에서 그것이 이긴다.
- 성장 제한을 빼서, 차선 틈으로 drivable이 새면 그 행의 길이 넓어진다. 모델이 선 밖 바닥을 drivable로 거의 칠하지 않는 것(crop128 test 0.8%, val 4.2%)과 D-576 바깥 차단에 기댄다.
- 오프라인 재생(2026-10-10, 모델 PC CPU, crop128 포장본, 주행 프레임 36장): 모든 프레임이 `drivable`(근거리 0.04–0.99). 1/4 규칙 전에는 모든 프레임에서 갈래 2–5개가 잡혔고 전부 먼 가장자리 조각이었다. 규칙 뒤에는 1개 14장, 2개 22장(대부분 왼쪽이 열린 교차로 장면)이다. keeper 결과는 drivable 길 기준 오른쪽만 15, 왼쪽만 12, 양쪽 4, 없음 5였다. 같은 프레임의 lane_marking paint는 오른쪽만 20, 왼쪽만 11, 없음 5였다. 모델이 바닥의 상자를 drivable로 칠한 프레임이 있다. 상자는 LiDAR 몸체 가드의 몫이다. 추론과 길 계산은 프레임당 중앙값 20 ms(모델 PC 4 스레드)이고, Pi 값이 아니다.
- 경계 띠는 새 마스크마다 한 번 만들고(캐시), 추론 스레드는 길 계산을 더 한다. Pi 비용은 아직 재지 않았다.

**Related:** [D-384](D-384-road-state-estimator-and-road-behaviour.md), [D-408](D-408-lane-paint-source-learned-floor-mask-with-opencv-fallback.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-566](D-566-v13-1-offroad-false-positive-and-model-pc-job-guard.md), [D-570](D-570-learned-paint-ego-motion-compensated-reuse.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md), [D-592](D-592-drivable-steering-field-test-pc-loop.md).
