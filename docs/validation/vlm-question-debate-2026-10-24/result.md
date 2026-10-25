# VLM 질문 v2·v3와 토론 1라운드 — 2026-10-24

**앞 회차:** [vlm-question-bench-2026-10-23b](../vlm-question-bench-2026-10-23b/result.md). **설계:** [D-857](../../adr/D-857-rosy-learning-product-definition.md) §4–5, [실험 계획](../../plans/2026-10-23-vlm-fast-judge-experiment.md).
**도구:** 질문 세트 v3는 이 기록과 같이 게시되는 `tools/vlm_question_bench.py`. 의견 갈림을 고르고 토론 답을 합의에 반영한 쪽(Learning VLM 판단 화면·가져오기)은 아직 미게시 로컬 코드다(v2 토론 `commit c2da4574ff`, v3 `commit 3adfeaa32a`).
**위치:** 모델 PC, 오프라인. 운영 경로·AI PC·로봇은 쓰지 않았다.
**범위:** 모델끼리의 합의 수만 센다. 사람 정답이 0건이므로 **답이 맞는지는 판정하지 않았다.** 합의는 임시 정답이며 승인이 아니다(D-514 §5, D-853 §3).

## 방법

- 합의 규칙: 서로 다른 모델 2개 이상이 같은 답, 각 p ≥ 0.8. 같은 모델의 런타임·해상도 변형은 하나로 센다.
- 의견 갈림: 평가셋(보기당 30장) 밖에서 어느 질문이든 합의가 없는 (사진, 질문).
- 토론 1라운드: 의견 갈림마다 각 모델에 같은 사진·질문과 다른 모델들의 답·확률(익명)을 보여 주고 다시 묻는다. 답은 선택지 토큰 확률로 읽는다. 토론 답은 같은 모델의 기존 답을 대신한다(모델 수가 늘지 않는다).
- 모델: Qwen3-VL-8B-Instruct(nf4), Qwen3-VL-4B-Instruct, Qwen3.5-4B. 사진: front 60, top 40, wrist 35장(앞 회차와 같은 표본).

## 결과

| 질문 세트 | 토론 전 의견 갈림 | 토론 후 | 합의 |
| --- | --- | --- | --- |
| v2 | 62 | 55 | 7 |
| v3 | 82 | 64 | 18 |

| 질문 | v2 합의/의견 갈림 | v3 질문 | v3 합의/의견 갈림 |
| --- | --- | --- | --- |
| `front.lane_tape`(both/left/right/none) | 0/27 | `front.tape_left`·`front.tape_right`(사진 기준 yes/no) | 의견 갈림 0·1, 합의 0/1 |
| `front.lane_obstruction`(차로 안 물체) | 0/17 | `front.object_between_tapes`(아래쪽 절반, 두 테이프 사이) | 1/26 |
| `top.robots_close`(로봇끼리 가까움) | 0/10 | `top.robot_count`(zero/one/two/many) | 0/10 |
| `front.wall_ahead` | 1/1 | 같음 | 12/25 |
| `front.shape` | 2/2 | 같음 | 1/15 |
| `wrist.gripper_empty` | 4/5 | 같음 | 4/5 |

v3에서 `wall_ahead`·`shape`의 의견 갈림이 늘어난 것은 Qwen3.5-4B가 v3에서 처음 front에 답했기 때문이다(v2에서는 top·wrist만).

## 관찰

- 좌우 기준이 없던 차선 테이프 질문은 사진 기준 두 질문으로 나누자 처음부터 세 모델이 합의해 의견 갈림이 거의 없어졌다.
- 「두 테이프 사이 물체」와 「로봇 수」는 문구를 좁혀도 합의가 0–1건이다. 문구 문제인지 이 사진 크기(front 320×240, 천장 전체 화면)에서의 모델 한계인지는 사람 정답 없이 가를 수 없다.
- 천장 프레임에는 로봇별 위치가 없다(사진당 ArUco 자세 하나). 로봇 주변을 잘라 묻는 질문은 위치 자료가 생긴 뒤에 가능하다.
- 토론 1라운드 소요(적재 포함): v2 기준 8B 74 s, 4B 48 s, Qwen3.5-4B 32 s.

## 원본

모델 PC `~/rosy-test/vlm-bench/debate-20261024/`(v2), `~/rosy-test/vlm-bench/v3-20261024/`(v3 벤치 `out/`, 토론 `dout/`). 수치는 각 폴더의 `debate.jsonl`(토론 전 의견 갈림)과 `debate-after.jsonl`(토론 후)을 질문별로 센 것이다.

| 파일 | 해시 |
| --- | --- |
| debate-20261024/debate.jsonl | sha256 `9e72166fb4141b01273ce7ad7a83b3506bdc9f9cc457cd60839b89fcfc68019f` |
| debate-20261024/debate-after.jsonl | sha256 `52927e0b988396f91ebfefb01b6eecee0fb53d0219a2cc42b9fac31434ab7cd5` |
| v3-20261024/debate.jsonl | sha256 `b9d5d609e5b0ee6e2fd5701b5caf60180fbb7dee06348d3e94b7c5af2b4f4c13` |
| v3-20261024/debate-after.jsonl | sha256 `f66b5f0d3900f0ce517282c72980121e0726ecc4b98422a4bb276ea9c604c079` |
