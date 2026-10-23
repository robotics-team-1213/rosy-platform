---
title: Closed VLM questions need one kind per question, a per-photo evaluation set and a cap on every human queue
date: 2026-10-24
category: design-patterns
module: tools/vlm_question_bench.py, learning/curation/perception/vlm_judge.py, D-857
problem_type: design_pattern
component: perception_review
symptoms:
  - "multi-way 'what is ahead' (wall/object/robot/person/none) answered wall on 40 of 40 frames, also on open floor and on a barrier base"
  - "per-question evaluation sets of 30 unioned to 132 of 135 photos"
  - "every front photo outside the evaluation set landed in the disputed queue with no cap"
root_cause: design_flaw
resolution_type: design_change
severity: medium
applies_when:
  - "writing or changing closed questions for a VLM or LLM judge"
  - "sizing a human truth queue or a fixed evaluation set"
tags: [vlm, closed-questions, logprobs, consensus, human-truth, review-queue, d-857, d-853]
---

# Closed VLM questions need one kind per question, a per-photo evaluation set and a cap on every human queue

## Problem

빠른 VLM 판단(선택지 토큰 확률 읽기, D-857)과 사람 정답 대기열을 만들면서 세 번 같은 종류의 실수를 했다. 셋 다 시험은 통과했고 실제 자료에 돌려 보고서야 드러났다.

## What we saw

| 설계 | 실제 자료에서 | 고친 뒤 |
| --- | --- | --- |
| 다지선다 `front.thing`(wall/object/robot/person/none) | 8B·4B 모두 40/40 `wall`. 에이전트 육안 2장(트인 바닥, 차단기 받침) 둘 다 오답 | 종류마다 yes/no(`wall_ahead`·`robot_ahead`·`person_ahead`): `wall_ahead` yes 4/60 |
| 평가셋 「질문당 30장」을 질문마다 뽑아 합집합 | 135장 중 132장이 사람 평가셋 | 「사진 종류당 30장, 그 사진의 모든 질문, 고정」: 보기당 30 |
| 의견 갈림 대기열은 점검만 상한(50) | front 평가셋 밖 30장 전부 의견 갈림. 자료가 늘면 끝없음 | 의견 갈림도 보기당 50장(오래된 것부터), 나머지는 `disputed_waiting` |

증거: [vlm-question-bench-2026-10-23](../../validation/vlm-question-bench-2026-10-23/result.md), [2026-10-23b](../../validation/vlm-question-bench-2026-10-23b/result.md), 모델 PC 8790 대기열 `/api/learning/vlm/queue`(2026-10-24).

## Guidance

- **질문 하나 = 사물 종류 하나 = yes/no/unclear.** 「무엇인가」 다지선다는 모델이 가장 흔한 답 하나로 쏠린다. 확률을 읽어도 쏠림은 그대로다.
- **사람이 보는 단위는 사진이다.** 평가셋·대기열 크기는 「질문 수 × 장수」가 아니라 사진 장수로 정하고, 한 사진의 질문은 한 번에 답하게 한다. 합집합으로 계산하면 거의 전체가 된다.
- **사람에게 가는 모든 대기열에 상한을 둔다.** 하나만 상한을 두면 상한 없는 쪽이 넘친다. 넘는 건은 버리지 말고 대기 수로 센다.
- **답 분포를 실제 자료로 먼저 본다.** 정답 없이도 「한 선택지 40/40」, 「두 모델 3/60 vs 28/60」 같은 분포가 질문 결함을 드러낸다. 사람 정답을 달기 전에 이걸 본다.
- **모델 합의·토론은 임시 정답이다.** 승인·승격 근거가 아니다(D-514 §5, D-853 §3, D-857 §4).

## When to Apply

- VLM·LLM에 닫힌 질문을 새로 만들거나 바꿀 때(인식 검수 초안, 막힘 판단, 파지 확인).
- 사람 확인 대기열·평가셋 크기 규칙을 정할 때.

## Still open

애매한 질문(`front.lane_tape`의 좌우 기준, `front.lane_obstruction`의 「차로 안」 범위, 대상 없는 천장 장면 질문)은 1라운드 토론에서 0/27·0/17·0/10 합의였다. 기준을 명시한 v3로 확인 중이며, 결과가 나오면 이 문서에 덧붙인다.
