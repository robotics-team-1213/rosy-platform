---
title: 학습한 출력이 런타임에 실제로 쓰이는지부터 확인한다 — drivable 모델은 배포됐지만 조향에 닿지 않았다
date: 2026-10-10
category: workflow-issues
module: learned paint (middleware/perception/control/sensing/perception/learned), v13-drivable / crop128 drivable models
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "a model is trained or retrained for a new output class (drivable, crosswalk, speed_bump, ...)"
  - "a model is pushed to a robot paint or shadow slot and someone expects driving to change"
  - "an ADR gives an output 'no authority for now' and defers the decision"
  - "someone asks whether a model or an object class already exists"
symptoms:
  - "the user believed the deployed drivable model was already finding the path"
  - "9dfk ran lane-seg-20261010-71edcb6d with paint_source learned, but steering used only the lane_marking classes"
  - "several v13-drivable candidates (982b09a9, bc6070f7, 86c86e7f) were trained and pushed while no runtime path read the drivable class"
  - "the assistant first said no such model existed without searching the model PC"
root_cause: missing_validation
resolution_type: workflow_improvement
tags: [drivable, learned-paint, lane_marking_mask, consumer-path, authority-gap, model-pc, d-554, d-592, d-597, d-599]
---

# 학습한 출력이 런타임에 실제로 쓰이는지부터 확인한다

## Context

2026-10-09~10에 drivable 모델을 여러 번 학습하고 로봇에 올렸다. 플랫폼 후보 `v13-drivable-20261009-982b09a9`(차선 유도 라벨, 카펫 전체를 칠해 거절), `v13-drivable-20261009-bc6070f7`, `v13-drivable-20261010-86c86e7f`(8kcn shadow), 그리고 12&13팀의 crop128 모델 `v13-drivable-20261010-ede0ae96`(사람 검수 1,428장, drivable test IoU 0.989, 선 밖 바닥 오검 0.8%)이다. crop128은 그래프 안 크롭 포장본 `lane-seg-20261010-71edcb6d`로 9dfk에 올라갔고, paint 포인터가 그 모델을 가리키며 overlay는 `paint_source: learned`였다.

그런데 로봇의 learned paint는 모델 출력에서 `lane_marking` 역할 클래스만 쓴다.

- `middleware/perception/control/sensing/perception/learned/paint_worker.py:154`가 `model.infer_mask(frame)`을 부른다.
- `middleware/perception/control/sensing/perception/learned/runner.py:117-123`의 `infer_mask`는 `lane_marking_mask`만 돌려준다. `infer_with_mask`(`runner.py:125-133`)도 같다.
- `middleware/perception/control/sensing/perception/learned/lane_mask.py:145`가 `c.role == "lane_marking"`인 클래스만 마스크에 넣는다. drivable, crosswalk, speed_bump는 버려진다.
- drivable을 보는 곳은 `lane_evidence`(`lane_mask.py:103-106`) 하나인데, 이것은 shadow 증거이고 명령을 내지 않는다(`lane_mask.py:17`, D-209).

즉 잘 학습된 drivable 모델이 배포됐지만 조향은 한 번도 바뀌지 않았다. 일부러 그렇게 정한 것이기는 했다. D-554 6항, D-576, D-475 §8은 drivable에 조향 권한을 주지 않고 "조향 오차 게이트를 통과한 뒤" 정하기로 했다. 그 "나중에 정한다"를 닫는 작업이 없는 채로 모델 학습과 push만 계속됐다. 사용자는 모델이 이미 길을 찾고 있다고 믿었다. 팀의 전달 README §6도 "consumer `learned/lane_mask.py` uses the drivable centroid"라고 적어, shadow 증거 경로를 주행 경로로 읽었다.

같은 날 어시스턴트는 "그런 모델이나 물체 클래스는 없다"고 먼저 답했다. 모델 PC(OMEN) `~/Desktop/drivable-v13-crop128-20261010/`을 찾아보지 않은 답이었다.

## Guidance

1. **학습·push 전에 소비 경로를 코드에서 끝까지 따라간다.** 새 클래스나 새 출력을 학습하기 전에, 런타임에서 그 클래스 인덱스나 역할을 읽어 명령까지 가는 호출을 파일:줄로 적는다. 적을 수 없으면 그 출력은 "기록만 됨"이다. 학습 계획과 사용자 보고에 그렇게 쓴다.
2. **"권한은 나중에" 결정은 닫는 날짜나 담당을 같이 둔다.** ADR이 출력에 권한을 주지 않으면, 그 출력으로 모델을 더 학습하거나 push하는 커밋·보고마다 "이 출력은 아직 주행에 쓰이지 않는다"를 적는다. 사용자가 그 공백을 모른 채 결과를 기대하게 두지 않는다.
3. **모델이 없다고 답하기 전에 모델 PC를 찾는다.** 모델 PC `~/Desktop`, `~/rosy-ml/scratch`, 로봇 `/var/lib/rosy/models`를 본 뒤에 답한다. 팀 전달물은 저장소 밖 데스크톱에 온다.
4. **모델 PC는 학습용이다.** 주행 확인은 로봇(늦으면 Fleet 현장 PC)에서 한다. 사용자: "모델 PC에서 확인하는 건 학습을 위한 부분".
5. **실물 시험을 먼저, 통합은 그 결과로.** 소비 경로가 없으면 로봇 코드를 바꾸지 않는 실물 시험(D-592, CORE teleop 경유)으로 먼저 효과를 보고, 런타임 조향 소스(D-597)는 그와 나란히 넣는다.

## Why This Matters

모델 지표(IoU, 오검률)가 좋아도 런타임이 그 출력을 버리면 주행 결과는 0이다. 이번에는 하루 넘게 후보 4개를 학습·검토·배포하고 9dfk에 실제로 올렸지만, 차선 클래스 출력이 부모 모델과 같아서 paint 포인터를 바꿔도 조향은 그대로였다(D-592 Context). shadow 증거 경로와 주행 경로가 같은 파일(`lane_mask.py`)에 있어 읽는 사람이 둘을 섞기 쉽다.

## When to Apply

- 새 클래스·새 헤드·새 출력 채널을 학습하거나 그 모델을 로봇에 올릴 때
- "모델이 ~을 이미 한다"는 말을 사용자에게 하거나 들을 때
- ADR이 어떤 출력을 "shadow만", "권한 없음", "나중에 정함"으로 둘 때
- 모델·자료·클래스가 있는지 묻는 질문에 답할 때

## Examples

나쁜 예: drivable test IoU 0.989 모델을 9dfk paint 포인터에 걸고 "drivable 모델로 주행 중"이라고 보고한다. 실제 조향은 `lane_marking_mask`(`lane_mask.py:145`)만 본다.

좋은 예: 올리기 전에 `paint_worker.py:154` → `runner.py:117` → `lane_mask.py:145`를 읽고 "drivable 출력은 지금 조향에 쓰이지 않는다. 쓰려면 D-597의 `learned_paint_target: drivable` 같은 소비 경로가 필요하다"고 먼저 말한다.

## Related

- 모델 선택 ADR(이 브랜치): [D-599](../../adr/D-599-drivable-model-team-crop128.md)
- [D-592](../../adr/D-592-drivable-steering-field-test-pc-loop.md) drivable 실물 조향 시험(로봇/Fleet 루프, CORE teleop), [D-597](../../adr/D-597-drivable-keep-steering-source.md) drivable keep 조향 소스(`learned_paint_target`)
- [D-554](../../adr/D-554-v13-drivable-lane-derived-labels.md) 6항, [D-475](../../adr/D-475-human-reviewed-fixed-eval-truth.md) §8, [D-408](../../adr/D-408-lane-paint-source-learned-floor-mask-with-opencv-fallback.md), [D-209](../../adr/D-209-perception-folder-and-learned-backend.md)
- [learned paint 프레임 수 게이트가 느린 마스크를 버린다](../logic-errors/learned-paint-frame-count-gate-drops-slow-masks-2026-10-10.md) — 소비 경로가 있어도 느리면 닿지 않는다
- [모든 후보 모델을 장치 전에 SIM 폐루프로 시험한다](test-every-candidate-model-in-the-closed-loop-harness-before-device-2026-10-10.md)
