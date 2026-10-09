## D-597 차선 유지(keep)가 학습 모델의 drivable 영역으로 길을 찾아 조향한다 — `learned_paint_target: drivable`

**Status:** Accepted (2026-10-10, 사용자 결정 "A로 하면서 B로 바로 처리"; 같은 날 추가 결정: 추론은 로봇 기본, 지연이 안 되면 Fleet(현장 PC), 교차로는 D-384 2항 우측 규칙, "모델은 주행 가능 영역을 찾고 우리는 길을 찾아 진행한다").

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
   - 가장 아래 행에서 화면 가운데에 가까운 조각(로봇 아래 도로)에서 시작해 위로 올라가며, 아래 조각에 닿는 조각만 남긴다. 둘 이상이면 길이 갈라진 것이고 **가장 오른쪽**을 따른다(D-384 2항: 명시 경로·목표 > 목표 없는 교차로는 우회전 > 비등하면 가장 오른쪽). 경로·목표 방향을 갈래 선택에 넣는 일은 뒤 단계다(아래 7).
   - 근거리 띠(아래 40%)에서 그 길이 2% 미만이거나 모델에 drivable 클래스가 없으면 길이 없다. 그때는 같은 추론의 `lane_marking` 마스크를 쓴다(지금의 `learned`와 같다). 마스크가 없거나 늦으면 지금처럼 `denoise_fallback`이다.
3. **keeper에는 경계 페인트로 준다.** 길의 각 행 양쪽 바로 바깥에 선 하나 폭(2 x `lane_paint_half_width_m`, 그 행의 지면 축척)의 띠를 그린다. keeper가 맞추는 페인트 중심은 drivable 경계에서 반 폭 바깥이고, 안쪽 경계(D-408·lane_containment의 drivable 경계)는 drivable 경계 자체다. 화면 가장자리에 닿은 쪽에는 띠를 그리지 않는다. 그 너머는 안 보인 곳이지 경계가 아니다. 짝짓기·측면·모서리·HOLD 판단은 `LaneKeeper` 그대로다.
4. **크롭 입력 매니페스트를 지원한다.** `input.crop = {from_frame: [H, W], rows: [a, b]}`를 읽는다. W가 입력 폭이고 b−a가 입력 높이여야 하고, background 클래스가 있어야 한다. 아니면 거부한다. 프레임을 H x W로 줄이고 a..b−1 행을 넣고, 출력은 전체 프레임 격자에 되돌려 놓으며 나머지 행은 background다. drivable 길은 a행 위로 가지 않는다(`ignore_top = a`). 이 키가 없는 매니페스트는 지금과 같다. 옛 로더는 이 키를 무시하므로 크롭 원본 번들은 이 변경이 들어간 릴리스에만 넣는다. 포장본은 어느 쪽에서나 같다.
5. **출처를 남긴다.** keep_debug의 `paint_source_used`는 길을 썼으면 `learned_drivable`, 차선 마스크로 돌아갔으면 `learned`다. `paint_target_requested`와 `paint_drivable`(`reason` ok/no_drivable_class/low_coverage, `branches`, `near_fraction`)을 함께 싣는다. CORE readback은 `learned_drivable`을 받아 API에는 `learned`로 보고한다. API 열거값과 버전은 그대로다.
6. **기본은 꺼짐이고 로봇별로 켠다.** 운영자 overlay `/etc/rosy/line_observer_overrides.yaml`에 `learned_paint_target`을 허용 키로 넣는다. `lane_marking`, `drivable` 외의 값이면 overlay 전체를 건너뛴다. `paint_source`가 `learned`가 아니면 이 키는 아무 일도 하지 않으므로, Host Agent가 `threshold`로 되돌려도 파일이 유효하다. 켜는 방법은 `line_observer_overrides apply ... --paint-source learned --model-pointer <포인터> --paint-target drivable`이다. 추론 주기(`learned_paint_every_n`), 재사용·움직임 보정(D-570), 오래된 마스크 거절은 지금 paint worker 규칙 그대로다. CORE가 유일한 최종 `/cmd_vel` 발행자다. RobotBody 가드, IR, watchdog, 모드 규칙은 바뀌지 않는다.
7. **추론 위치.** 기본은 로봇(지금의 learned paint worker)이다. Pi 지연이 주행 주기를 못 맞추면 다음 단계는 Fleet(현장 PC) 추론이다. 2의 함수가 순수 함수라 그대로 옮길 수 있다. Fleet 경로는 이번에 만들지 않는다.
8. **뒤로 미룬 것.**
   - Fleet 경로·목표 방향에 따른 갈래 선택(D-384 2항 첫 순위)
   - 옆으로 열리는 T자 갈래의 우회전(지금은 한 조각이 넓어질 뿐 갈래로 보지 않는다)
   - 횡단보도·과속방지턱: 길 안에서는 도로로 칠해지므로 keeper의 D-491 횡단보도 범위는 이 출처에서 비어 있다. 지금은 손대지 않는다.
   - Pi 지연 측정과 D-475 §8 조향 오차 관문, 실물 시험(D-378 순서)

### Consequences

- drivable 모델이 처음으로 로봇 조향에 들어간다. 선이 지워졌거나 반사가 심해도 바닥 영역으로 경계를 잡는다.
- 갈래가 보이면 오른쪽으로 간다. 경로를 모르는 상태의 규칙이며 Fleet 경로가 있으면 뒤 단계에서 그것이 이긴다.
- 성장 제한을 빼서, 차선 틈으로 drivable이 새면 그 행의 길이 넓어진다. 모델이 선 밖 바닥을 drivable로 거의 칠하지 않는 것(crop128 test 0.8%, val 4.2%)과 D-576 바깥 차단에 기댄다.
- 경계 띠는 새 마스크마다 한 번 만들고(캐시), 추론 스레드는 길 계산을 더 한다. Pi 비용은 아직 재지 않았다.

**Related:** [D-384](D-384-road-state-estimator-and-road-behaviour.md), [D-408](D-408-lane-paint-source-learned-floor-mask-with-opencv-fallback.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-566](D-566-v13-1-offroad-false-positive-and-model-pc-job-guard.md), [D-570](D-570-learned-paint-ego-motion-compensated-reuse.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md), [D-592](D-592-drivable-steering-field-test-pc-loop.md).
