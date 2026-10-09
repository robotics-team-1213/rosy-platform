## D-599 drivable 주행 모델은 팀 crop128(`v13-drivable-20261010-ede0ae96`)로 한다 — 로봇 실물 시험 먼저, intake 규칙은 따로 정한다

**Status:** Accepted (2026-10-10, 사용자 결정: 팀 crop128 모델 "drivable-v13-crop128-20261010"로 drivable 주행; "A를 바로 처리해야 한다", "A로 하면서 B로 바로 처리"; "그것도 사실 로봇 자체에서 해야 하는데 만약 시간이 문제라면 fleet에서 하는 걸로 잡아도 돼"; "모델 PC에서 확인하는 건 학습을 위한 부분").

### Context

- **후보.** 2026-10-09~10에 drivable 후보가 여럿 나왔다.
  - `v13-drivable-20261009-982b09a9`: D-554 차선 유도 라벨. 선 바깥을 255로 두어 실물에서 카펫 전체를 drivable로 칠했다. 거절했다(D-554 9항).
  - `v13-drivable-20261009-bc6070f7`, `v13-drivable-20261010-86c86e7f`(v13.3.01): 8kcn shadow 후보. D-592는 처음에 86c86e7f를 시험 모델로 적었다.
  - 12&13팀 crop128 `v13-drivable-20261010-ede0ae96`: 모델 PC `~/Desktop/drivable-v13-crop128-20261010/`에 전달됐다(README 기준). 팀 U-Net v13을 프레임(320x240)의 112..239 행 128x320 크롭으로 미세조정하고, 그 위에 `SlimHead(16)` 문맥 drivable 헤드(18,914 매개변수)를 얹었다. 클래스는 background, lane_left, lane_right, crosswalk(ignore), speed_bump(ignore), drivable 6개다.
- **팀 실험의 핵심.** 차선 특징 위의 작은 헤드는 선 바깥 바닥을 53–71% drivable로 칠했다(README §3.4 #1·#2). bottleneck·d4·d3 문맥을 합친 헤드가 이를 0.7–1.3%로 내렸고, 크롭 128행 + 폭 16(#9)이 전달본이다.
- **런타임 공백.** 로봇의 learned paint는 `lane_marking` 역할 클래스만 쓴다(`middleware/perception/control/sensing/perception/learned/paint_worker.py:154` → `middleware/perception/control/sensing/perception/learned/runner.py:117-123` `infer_mask` → `middleware/perception/control/sensing/perception/learned/lane_mask.py:145`). drivable을 보는 `lane_evidence`(`lane_mask.py:103-106`)는 shadow 증거라 명령을 내지 않는다. D-554 6항·D-576·D-475 §8이 drivable에 조향 권한을 주지 않았고, 그 결정을 닫지 않은 채 후보를 학습·배포했다. 그래서 어느 후보도 조향을 바꾸지 못했다([교훈](../solutions/workflow-issues/check-the-runtime-consumes-a-learned-output-before-training-it-2026-10-10.md)).
- **지금 9dfk 상태(2026-10-10).** 그래프 안 크롭 포장본이 `v13-drivable-20261010-71edcb6d`로 올라갔다가(2026-10-09 16:53Z) 세션 rosy-2a가 `lane-seg-20261010-71edcb6d`로 이름을 바꿨다(19:18Z, "team crop128 lane+drivable model is not the v13-drivable lineage (D-532/D-554/D-558); field test, no intake"). paint 포인터 `/var/lib/rosy/models/paint`가 이 모델을 가리키고 overlay는 `paint_source: learned`, `learned_paint_every_n: 4`다. 8kcn에는 없다.

### Decision

1. **drivable 주행 모델은 팀 crop128로 한다.** 정체는 다음이다.
   - 원본: revision `v13-drivable-20261010-ede0ae96`, 전달 폴더의 `model/model.onnx` sha256 `ede0ae96327c22f5da61dca40a75ceb2f011f163bd2fa2f3e27c1558a988d39b`, 입력 `[1,3,128,320]`, 매니페스트에 `input.crop = {from_frame:[240,320], rows:[112,240]}`.
   - 로봇용 포장본: revision `lane-seg-20261010-71edcb6d`, `model.onnx` sha256 `71edcb6d00006c7351c107e12875b847b6ce2d446acc48c080a18865197871fc`. 입력 `[1,3,240,320]`이고 그래프 안에서 112..239 행을 자르고 0..111 행을 background로 채운다. 원본과의 차이 max|d| 0. 지금 로더가 `input.crop`을 모르므로 포장본이 기본이다.
   - 자료: `v13-drivable-human-20261009`, manifest sha256 `da3e9919474e93b476aec96911e1e892de3247e35ac1516b8b6d4cbeecc3ec95`, `annotation_origin: human_reviewed`, 1,428장(train 1,075 / val 190 / test 163, D-554 최신 자료와 같은 이미지·분할).
2. **고른 이유.**
   - 라벨: drivable은 "로봇과 흰 선을 넘지 않고 이어진 바닥"이고, 두 선이 보이는 행에서 선 바깥 카펫은 음성이다. 1,428장 모두 사람이 고쳤다. 982b09a9를 망친 선 바깥 오검을 라벨이 직접 막는다.
   - 지표(README §3.1): drivable test IoU 0.989, precision 0.996, recall 0.994, 선 밖 바닥 오검 0.8%. val은 0.981 / 4.2%이고, 실물은 val 쪽을 예상한다.
   - 차선: 근거리 144–239 행(조향 40%)의 차선 IoU는 240 입력 U-Net보다 0.3점 이내로 같다. 원거리 112–143 행은 떨어진다(lane_left 81.0→78.5, speed_bump 84.0→67.7).
   - 계산: 노트북 CPU에서 240x320 U-Net의 약 52%다. Pi는 재지 않았다. 같은 비율이면 약 170 ms로 카메라 주기 125 ms보다 길다.
3. **D-554 계보·intake 공백은 지금 메우지 않는다.** 이 모델은 D-554의 `v13-drivable` 계열이 아니다.
   - 부모가 D-554 4항의 v11 `lane-seg-20261006-5f5ddcd9`가 아니라 팀 U-Net v13 crop128이다.
   - 자료가 `derived_from_reviewed_lanes`가 아니라 `human_reviewed`라서 D-554 2항 판정자 블록이 없다.
   - 그래서 `lane-seg-*` 이름으로 intake 없이 실물 시험에만 쓴다. 이 이름은 D-558 `v13.x.yy` 버전 대상이 아니다. intake와 shadow 밖 승격을 어떤 규칙으로 받을지(D-554 4항 부모 확장, 사람 검수 자료의 승인 경로, `input.crop` 로더 지원)는 사용자가 정한다. 그 결정 전에는 store intake, `deliver.py` 승격, 운영 기본값 변경을 하지 않는다.
4. **추론은 로봇에서 한다.** 기본은 로봇의 learned paint worker다. Pi 지연이 주행 주기를 못 맞추면 Fleet(현장 PC)에서 추론한다. 모델 PC는 학습·내보내기·평가용이고 주행 런타임 호스트가 아니다.
5. **매 프레임 사용을 주장하기 전에 Pi 지연을 잰다.** 9dfk에서 실제 전처리 포함 추론 지연과 `paint_source_used`/`paint_model_revision` 비율을 기록한다. `learned_paint_every_n`과 프레임 수 게이트가 느린 마스크를 버리므로([교훈](../solutions/logic-errors/learned-paint-frame-count-gate-drops-slow-masks-2026-10-10.md)), 그 비율 없이 "모델로 주행했다"고 하지 않는다.
6. **교차로는 오른쪽이다.** 모델은 선을 넘지 않고 닿는 갈래를 모두 drivable로 칠한다. 갈래 선택은 조향이 D-384 결정 2(Fleet 목표 방향 > 목표 없는 교차로에서는 우회전 > 비등하면 가장 오른쪽)로 한다.
7. **조향 배선은 다른 ADR이 정한다.** 이 ADR은 모델만 고른다.
   - A, 바로 할 실물 시험: D-592(drivable 실물 조향 시험, 로봇/Fleet 루프가 CORE teleop으로 보냄). 같은 날 개정으로 시험 모델이 `lane-seg-20261010-71edcb6d`가 됐다.
   - B, 본 경로: D-597(keep 모드 drivable 조향 소스 `learned_paint_target: drivable`, 크롭 매니페스트 지원 포함).
   - 두 ADR 모두 2026-10-10 현재 별도 브랜치에서 진행 중이다. CORE가 유일한 최종 `/cmd_vel` 발행자이고 RobotBody 가드·IR·watchdog은 그대로다.

### Rejected

- **`v13-drivable-20261010-86c86e7f`(D-554 계열) 유지.** 계보 규칙은 맞지만 선 밖 오검을 줄이는 사람 라벨이 없다. 사용자가 crop128로 바꿨다.
- **intake 규칙을 먼저 정하고 시험.** 사용자가 실물 시험을 먼저 하기로 했다("A를 바로 처리해야 한다"). 계보 공백은 3항처럼 이름과 범위로 가둔다.
- **모델 PC에서 추론하는 시험 루프.** D-592 개정과 같은 이유로 뺐다. 모델 PC는 학습용이다.

### Consequences and verification

- 9dfk 한 대에 이 모델이 있다. 8kcn은 시험 전에 같은 포장본을 올려야 한다.
- 원거리 행이 약해서 과속방지턱·횡단보도를 일찍 보는 데는 불리하다. 필요하면 팀 README의 144행 크롭(96..239)을 다음 후보로 본다.
- 판단 근거: D-592 시험 기록(`docs/validation/`), Pi 지연과 learned 프레임 비율, D-475 §8 조향 오차 게이트.
- 뒤로 미룬 것:
  - 횡단보도·과속방지턱 동작(지금은 ignore 역할이며 D-597 길 안에서는 도로로 칠해진다)
  - Fleet 추론 경로(Pi 지연이 안 될 때)
  - 3항 intake·승격 규칙(사용자 결정)
  - junction·로터리 장면이 적은 자료(README §8)의 보강

**Related:** [D-378](D-378-real-drive-errors-and-autonomy-gates.md), [D-384](D-384-road-state-estimator-and-road-behaviour.md), [D-408](D-408-lane-paint-source-learned-floor-mask-with-opencv-fallback.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-532](D-532-v13-drivable-model-lineage.md), [D-554](D-554-v13-drivable-lane-derived-labels.md), [D-558](D-558-drivable-model-semantic-version.md), [D-576](D-576-drivable-own-road-beyond-boundary-blocked.md), [D-592](D-592-drivable-steering-field-test-pc-loop.md), [D-597](D-597-drivable-keep-steering-source.md).
