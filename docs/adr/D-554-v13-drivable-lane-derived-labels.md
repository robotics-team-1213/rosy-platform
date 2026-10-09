## D-554 `v13-drivable` 학습 라벨은 사람 검수 차선 마스크에서 유도한다

**Status:** Accepted (2026-10-09, 사용자 결정 "새 ADR: 차선 유도 drivable"; SOURCE 구현은 `feat/v13-lane-derived-drivable`, 학습·shadow 주행은 별도 증거).

### Context

D-532는 `v13-drivable` 학습에 사람이 승인한 픽셀 마스크만 쓰게 했고 D-464·D-538·D-542는 기계 승인과 일괄 승인을 막았다. 2026-10-09 모델 PC v13 검수 작업공간은 53장 가운데 승인 0장, 대기 30장(그중 10장은 전부 255), 제외 23장이었다. 사용자는 사람 픽셀 검수를 기다리지 않고 최대한 자동으로 학습해 Pinky에서 주행 시험하기를 원했다.

AI PC에는 팀원의 5클래스 차선 자료 `data-v13`(schema `pinky-lane-dataset-v1`, manifest SHA-256 `846ab931…c04b`, 6,981장, 새 사람 검수 241장 포함)이 있다. 차선 화소는 사람 검수를 거쳤지만 drivable 클래스는 없다. 표본에서 라벨된 선은 대개 한쪽뿐이고, 같은 행에 왼쪽·오른쪽 선이 함께 20행 이상 있는 프레임은 train 1,355, val 266, test 187장이었다.

### Decision

1. **유도 규칙.** 같은 행에 `lane_left`와 `lane_right`가 모두 있고 왼쪽 선의 가장 오른쪽 화소가 오른쪽 선의 가장 왼쪽 화소보다 왼쪽이면, 그 사이의 배경 화소를 drivable로 둔다. D-475 §8의 "흰 경계선 안쪽 도로 바닥"과 같은 화소다. 선 바깥 바닥은 다른 도로일 수 있으므로 drivable도 배경도 아닌 255로 둔다. 음성은 `ignore_top` 경계에 붙은 밝고 매끈한 벽 영역만 배경으로 둔다. 나머지는 255다. 양쪽 선이 함께 있는 행이 기준(기본 20행)보다 적은 프레임은 쓰지 않는다.
2. **자동 판정.** 모델 PC 로컬 VLM(Qwen3-VL)이 유도 결과 겹쳐 그리기를 프레임마다 보고 `concern`이면 그 프레임을 뺀다. VLM은 라벨을 만들거나 고치지 않고 빼기만 한다. 사람(또는 사용자 지시를 받은 에이전트)이 표본 시트를 보고 기록을 남긴다.
3. **출처를 따로 표시한다.** 자료 manifest는 `rosy.lane-derived-drivable/1`, `annotation_origin: derived_from_reviewed_lanes`, `adr: D-554`, 원본 manifest 해시, 도구 커밋, 매개변수, 프레임별 이미지·마스크 해시를 적는다. 사람 승인 필드는 쓰지 않는다. 이 자료는 D-464의 `human_reviewed_pinky_indexed`가 아니다.
4. **이 계열에만 적용한다.** D-464·D-538·D-542의 승인 규칙은 다른 학습과 검수 작업공간에서 그대로다. 이 ADR은 `v13-drivable` 학습 입력에 한해 IndexedReview 대신 위 manifest의 해시 재검증을 허용한다. 부모 차선 모델 결속(D-532, `validate_drivable_parent`, 차선 로그잇 동등성)은 그대로 요구한다. 부모는 로봇 shadow의 v11 `lane-seg-20261006-5f5ddcd9`다.
5. **평가 정답이 아니다.** 유도 val/test는 학습 중 검증에만 쓴다. D-475의 사람 고정 평가 세트를 대신하지 않고, 그 세트와 섞지 않는다.
6. **shadow까지만 연다.** 결과는 `candidate`이며 revision은 `v13-drivable-YYYYMMDD-<sha8>`이다. intake와 `deliver.py push`는 이 계보가 있는 `v13-drivable-*`를 lane_seg shadow 슬롯에만 허용한다. active·promote는 계속 막는다. drivable 출력은 조향 권한이 없다. 주행 시험은 기존 차선 경로로 달리면서 shadow 출력을 기록하는 것이며, CORE가 유일한 최종 `/cmd_vel` 발행자다. D-475 §8의 조향 오차 게이트를 통과하기 전에는 shadow 밖으로 승격하지 않는다.

### Rejected

- 좌·우 선 하나만 있는 행에서 선 반대쪽 전체를 drivable로 칠하기: 표본에서 도로가 아닌 바닥과 벽까지 덮었다.
- 모델 합의(SAM3·v12·Qwen) 자동 승인: 초안이 서로 엇갈리고 대상이 30장뿐이다.
- 선 바깥 바닥을 배경으로 두기: D-475 §8은 다른 도로 바닥도 drivable로 정의한다.

### Consequences and verification

양성 라벨은 사람 검수 차선의 기하에서만 나온다. 이 기하는 갈림길이나 선이 끊긴 곳에서는 비어 있다. 모델은 그런 장면을 거의 보지 못하므로 그 결과를 주행 판단에 쓰지 않는다. 유도 규칙과 해시 재검증은 호스트 시험으로 확인한다. GPU 학습, Pi 지연, shadow 주행 기록은 각각 따로 증거를 남긴다. 호스트 pytest나 shadow 추론은 주행 수용이 아니다.

**Related:** [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-464](D-464-pinky-indexed-review-dataset-build.md), [D-532](D-532-v13-drivable-model-lineage.md), [D-538](D-538-review-studio-workflow.md), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md).
