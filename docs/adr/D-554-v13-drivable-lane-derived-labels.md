## D-554 `v13-drivable` 학습 라벨은 사람 검수 차선 마스크에서 유도한다

**Status:** Accepted (2026-10-09, 사용자 결정 "새 ADR: 차선 유도 drivable"; SOURCE 구현은 `feat/v13-lane-derived-drivable`, 학습·shadow 주행은 별도 증거).

### Context

D-532는 `v13-drivable` 학습에 사람이 승인한 픽셀 마스크만 쓰게 했고 D-464·D-538·D-542는 기계 승인과 일괄 승인을 막았다. 2026-10-09 모델 PC v13 검수 작업공간은 53장 가운데 승인 0장, 대기 30장(그중 10장은 전부 255), 제외 23장이었다. 사용자는 사람 픽셀 검수를 기다리지 않고 최대한 자동으로 학습해 Pinky에서 주행 시험하기를 원했다.

AI PC에는 팀원의 5클래스 차선 자료 `data-v13`(schema `pinky-lane-dataset-v1`, manifest SHA-256 `846ab931…c04b`, 6,981장, 새 사람 검수 241장 포함)이 있다. 차선 화소는 사람 검수를 거쳤지만 drivable 클래스는 없다. 표본에서 라벨된 선은 대개 한쪽뿐이고, 같은 행에 왼쪽·오른쪽 선이 함께 20행 이상 있는 프레임은 train 1,355, val 266, test 187장이었다.

### Decision

1. **유도 규칙.** 같은 행에 `lane_left`와 `lane_right`가 모두 있고 왼쪽 선의 가장 오른쪽 화소가 오른쪽 선의 가장 왼쪽 화소보다 왼쪽이면, 그 사이의 배경 화소를 drivable로 둔다. D-475 §8의 "흰 경계선 안쪽 도로 바닥"과 같은 화소다. 선 바깥 바닥은 다른 도로일 수 있으므로 drivable도 배경도 아닌 255로 둔다. 음성은 `ignore_top` 경계에 붙은 밝고 매끈한 벽 영역만 배경으로 둔다. 나머지는 255다. 양쪽 선이 함께 있는 행이 기준(기본 20행)보다 적은 프레임은 쓰지 않는다.
2. **자동 판정.** 유도 결과 겹쳐 그리기를 프레임마다 판정하고 `concern`이면 그 프레임을 뺀다. 판정자는 라벨을 만들거나 고치지 않고 빼기만 한다. 판정자는 일부러 망가뜨린 카나리아 프레임(벽 위 drivable, 도로 위 벽, 선 바깥 drivable, drivable 삭제)을 약 10% 섞은 시트로 시험하고, 카나리아의 90% 이상을 `concern`으로 잡을 때만 그 판정을 가져온다. 2026-10-09 모델 PC 로컬 Qwen3-VL 8B는 망가뜨린 겹쳐 그리기 17장을 모두 `ok`로 답해 판정자에서 뺐다. 첫 판정자는 사용자 지시로 검수하는 Claude 에이전트이며 `judge-run.json`의 이름과 지시문 해시로 기록한다. 사람 승인으로 기록하지 않는다.
3. **출처를 따로 표시한다.** 자료 manifest는 `rosy.lane-derived-drivable/1`, `annotation_origin: derived_from_reviewed_lanes`, `adr: D-554`, 원본 manifest 해시, 도구 커밋, 매개변수, 프레임별 이미지·마스크 해시를 적는다. 사람 승인 필드는 쓰지 않는다. 이 자료는 D-464의 `human_reviewed_pinky_indexed`가 아니다.
4. **이 계열에만 적용한다.** D-464·D-538·D-542의 승인 규칙은 다른 학습과 검수 작업공간에서 그대로다. 이 ADR은 `v13-drivable` 학습 입력에 한해 IndexedReview 대신 위 manifest의 해시 재검증을 허용한다. 부모 차선 모델 결속(D-532, `validate_drivable_parent`, 차선 로그잇 동등성)은 그대로 요구한다. 부모는 로봇 shadow의 v11 `lane-seg-20261006-5f5ddcd9`다.
5. **평가 정답이 아니다.** 유도 val/test는 학습 중 검증에만 쓴다. D-475의 사람 고정 평가 세트를 대신하지 않고, 그 세트와 섞지 않는다.
6. **shadow까지만 연다.** 결과는 `candidate`이며 revision은 `v13-drivable-YYYYMMDD-<sha8>`이다. intake와 `deliver.py push`는 이 계보가 있는 `v13-drivable-*`를 lane_seg shadow 슬롯에만 허용한다. active·promote는 계속 막는다. drivable 출력은 조향 권한이 없다. 주행 시험은 기존 차선 경로로 달리면서 shadow 출력을 기록하는 것이며, CORE가 유일한 최종 `/cmd_vel` 발행자다. D-475 §8의 조향 오차 게이트를 통과하기 전에는 shadow 밖으로 승격하지 않는다.

7. **provisional 카메라 출처를 이 후보에만 허용한다** (사용자 결정 2026-10-09). `data-v13`은 8kcn·9dfk·rosy_26·옛 v11 영상을 섞었고, 그 전부를 덮는 승인된 CameraProfile은 없다. 입력이 위 3항의 D-554 자료이고 결과가 shadow 전용 `candidate`일 때만 `accepted: false` 카메라 출처로 학습할 수 있다. 그 사실은 모델 manifest와 run 기록에 `camera_provenance: provisional`로 남긴다. 이 표시가 있는 모델은 shadow 밖으로 나갈 수 없고, 다른 recipe나 사람 검수 자료의 카메라 출처 요구는 그대로다. 부모 v11도 같은 영상으로 학습됐고 조향 권한이 없다는 점이 이 예외의 근거다.

8. **이 계열의 shadow intake 게이트에는 고정 평가를 넣지 않는다** (사용자 결정 2026-10-09). `pinky-heldout-20261001`의 drivable은 D-379 "지나간 폭 0.10 m"이고 차선 클래스도 `lane_line` 하나라서, D-475 §8 정의의 모델을 잴 수 없다(첫 후보 `v13-drivable-20261009-982b09a9`: mIoU 0.065, 차선 클래스 불일치로 거절). 부모 v11과 같이 재생·NaN·가시율·지연 게이트와 부모 차선 동등성으로 shadow intake를 하고, 거절된 평가 보고서도 run 기록에 함께 둔다. D-475 §8 정의의 사람 고정 평가 세트가 생기면 그 평가를 다시 필수로 한다. 첫 후보의 실제 카메라 영상 관찰: 선 안쪽 도로는 칠하지만 선 바깥 카펫, 주차 매트, 앞 로봇의 바닥 부분도 drivable로 칠한다. shadow 주행 기록으로 이 오판을 재고 다음 라벨 규칙에 반영한다.

### Rejected

- 좌·우 선 하나만 있는 행에서 선 반대쪽 전체를 drivable로 칠하기: 표본에서 도로가 아닌 바닥과 벽까지 덮었다.
- 모델 합의(SAM3·v12·Qwen) 자동 승인: 초안이 서로 엇갈리고 대상이 30장뿐이다.
- 선 바깥 바닥을 배경으로 두기: D-475 §8은 다른 도로 바닥도 drivable로 정의한다.

### Consequences and verification

양성 라벨은 사람 검수 차선의 기하에서만 나온다. 이 기하는 갈림길이나 선이 끊긴 곳에서는 비어 있다. 모델은 그런 장면을 거의 보지 못하므로 그 결과를 주행 판단에 쓰지 않는다. 유도 규칙과 해시 재검증은 호스트 시험으로 확인한다. GPU 학습, Pi 지연, shadow 주행 기록은 각각 따로 증거를 남긴다. 호스트 pytest나 shadow 추론은 주행 수용이 아니다.

**Related:** [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-464](D-464-pinky-indexed-review-dataset-build.md), [D-532](D-532-v13-drivable-model-lineage.md), [D-538](D-538-review-studio-workflow.md), [D-373](D-373-learned-perception-on-pinky-and-capture-loop.md).
