# VLM 닫힌 질문 벤치 (T3–T4) — 2026-10-23

**계획:** [실험 계획](../../plans/2026-10-23-vlm-fast-judge-experiment.md) T3·T4, A2 배선. **도구:** [`tools/vlm_question_bench.py`](../../../tools/vlm_question_bench.py).
**도구 리비전:** 이 기록과 같은 커밋(`feat/vlm-question-bench`). **위치:** 모델 PC(RTX 5080 Laptop 16 GB), 오프라인 재생. 운영 경로·AI PC·로봇은 쓰지 않았다.
**범위:** 지연과 답 분포만. 사람 정답(T1)이 없으므로 **정확도 수치가 아니다**. 아래 「육안 확인」은 에이전트가 사진 6장을 본 것이며 정답셋이 아니다.

## 입력

| 사진 | 원본 | 표본 | 처리 크기 |
| --- | --- | --- | --- |
| front(Pinky 전면) | `~/rosy-ml/scratch/drivable-branch-replay/src/8kcn-bag-20261009/*.jpg` (431장, 320×240) | 고정 시드 40장 | 원본 → 패치 격자(320×256 또는 308×252) |
| top(천장) | `~/rosy-ml/scratch/v13-map-labels-d209f530/ceiling/frames/*.jpg` (7,128장, 1280×720) | 40장 | 긴 변 448, 672 |
| wrist(OMX 손목) | 현장 PC `~/rosy-test/omx-manual-20261021/frames/*-front.jpg` 사본 (모터 튜닝, 물체 없음) | 40장 | 긴 변 448 |

질문 묶음 `v1`은 도구의 `QUESTIONS`다. 천장 사진에 대상 로봇 crop이 없어 `top.*`은 장면 단위 질문(`robots_close`, `person_present`)으로 바꿨다.

## 지연 (초, 사진 1장 = 전처리 + 사진 prefix 1회 + 질문 전부)

| 모델 | 실행 | 사진 | 이미지 토큰 | p50 | p95 | prefix p50 | 질문 1개 p50 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Qwen3-VL-8B | transformers nf4 | front ×4문 | 117 | 0.366 | 1.013 | 0.127 | 0.051 |
| Qwen3-VL-8B | transformers nf4 | top 448 ×2문 | 149 | 0.318 | 0.604 | 0.166 | 0.051 |
| Qwen3-VL-8B | transformers nf4 | top 672 ×2문 | 289 | 0.387 | 0.926 | 0.247 | 0.054 |
| Qwen3-VL-8B | transformers nf4 | wrist 448 ×2문 | 177 | 0.328 | 0.651 | 0.170 | 0.056 |
| Qwen3-VL-4B | transformers bf16 | front | 117 | 0.201 | 0.508 | 0.061 | 0.030 |
| Qwen3-VL-4B | transformers bf16 | top 448 / 672 | 149 / 289 | 0.166 / 0.213 | 0.327 / 0.476 | 0.070 / 0.121 | 0.030 |
| Qwen3-VL-4B | transformers bf16 | wrist 448 | 177 | 0.166 | 0.334 | 0.085 | 0.031 |
| Qwen3.5-4B | transformers bf16, prefix 복사 | front | 118 | 0.271 | 0.675 | 0.077 | 0.040 |
| Qwen3.5-4B | transformers bf16, prefix 복사 | top 448 / 672 | 150 / 290 | 0.215 / 0.277 | 0.405 / 0.597 | 0.091 / 0.145 | 0.045 |
| Qwen3.5-4B | transformers bf16, prefix 복사 | wrist 448 | 178 | 0.197 | 0.391 | 0.105 | 0.040 |

**운영과 같은 Ollama 0.35.1 `qwen3-vl:8b-instruct`(Q4, digest `0533d743…`), 같은 사진:**

| 사진 | 현행 관찰 호출 1회(설명 생성, `num_predict 96`) p50 / p95 | 질문 전부를 1토큰 + `top_logprobs`로 p50 / p95 | transformers 8B와 답 일치 |
| --- | --- | --- | --- |
| front ×4문 | 1.696 / 1.813 | **0.183 / 0.206** | 0.875 |
| top 448 ×2문 | 1.804 / 1.897 | **0.105 / 0.205** | 0.975 |
| top 672 ×2문 | 1.872 / 1.936 | **0.106 / 0.120** | 0.963 |
| wrist 448 ×2문 | 1.659 / 1.836 | **0.099 / 0.163** | 0.475 |

현행 `Vlm.judge`는 관찰 호출을 사진마다 하고 판단 호출을 한 번 더 하므로, 위 관찰 1회 값은 현행 방식의 하한이다.

## 검증

- 캐시 prefix와 전체 forward 비교(사진 종류마다 5장): 확률 최대 차이 0.025–0.117. 답이 바뀐 경우는 8B wrist 1건, 3.5-4B front 2건이며, 모두 두 선택지가 비슷한 경계 사례다. 위치(M-RoPE) 오류라면 차이가 훨씬 크다. 원인 후보는 bf16·nf4 커널의 수치 차이로, 따로 분리하지 않았다.
- 도구 자가 점검(`_selftest`): 격자 크기, 화질 지표, 백분위.

## 관찰

1. **Ollama만으로 확률 읽기가 된다.** 0.35.1은 이미지 입력에서 `logprobs`·`top_logprobs`를 준다. 질문 4개가 p50 0.18 s로, 같은 모델의 설명 호출 1회보다 약 9배 빠르다. 운영 실행기를 바꾸지 않아도 된다.
2. **CPU 전처리는 병목이 아니다**(processor p50 0.003–0.026 s). 8B nf4는 prefix·질문 계산이 4B bf16의 약 2배다. p95가 p50의 2–3배인 원인은 분리하지 않았다.
3. **천장 해상도 448→672**는 이미지 토큰이 약 2배, prefix가 1.5–1.7배다. 정확도 차이는 정답이 있어야 판단한다.
4. **질문 품질 문제가 바로 보인다.**
   - `front.thing`: 세 모델 모두 대부분 `wall`(8B·VL-4B 40/40). 육안 확인 2장 모두 틀림(트인 바닥, 차단기 받침). 질문 문구·선택지를 다시 짠다.
   - `top.robots_close`: 8B 40/40 yes, 3.5-4B는 해상도에 따라 30/40 ↔ 0/40. 대상 로봇 crop 없는 장면 질문은 불안정하다.
   - `wrist.*`: 8B가 노란 고무 패드를 단 닫힌 빈 손가락을 "물체를 쥠"으로 답한 사례가 있다(00:58–01:01 묶음). 같은 사진에서 `gripper_empty`도 yes여서 **서로 반대인 질문 쌍의 모순 검사**로 걸러진다. Ollama와 일치도 0.475로 손목 질문은 이 모델로 불안정하다.
5. **모델 간 차이:** 육안 확인한 전면 2장에서 `front.lane_obstruction`은 8B가 둘 다 맞고 3.5-4B가 둘 다 틀렸다. 표본 2장이라 결론이 아니다.

## 육안 확인 (에이전트, 정답셋 아님)

| 사진 | 본 것 | 8B | 3.5-4B |
| --- | --- | --- | --- |
| front `1791531693812` | 트인 바닥, 원형 표시, 막는 물체 없음 | obstruction no ✓, thing wall ✗ | yes ✗, wall ✗ |
| front `1791531542188` | 차단기 받침(노랑·검정 줄무늬)이 바로 앞 바닥 | yes ✓, wall ✗ | no ✗, wall ✗ |
| wrist `tune-005918-id15-hold` | 닫힌 손가락, 노란 패드, 물체 없음 | in_gripper yes ✗, empty yes ✓ (모순) | — |
| wrist `tune-232541-id15-before` | 벌어진 손가락, 물체 없음 | in_gripper no ✓, empty yes/unclear 반반 | — |

## 다음

- T1 사람 정답: 위 표본을 Pinky 검수 앱 계열 화면에서 질문별로 단다. `front.thing` 문구는 정답을 달기 전에 고친다.
- 결정 단계에 반대 질문 쌍 모순 → 기권 규칙을 넣는다(설계 「결정 표」).
- 런타임은 Ollama 확률 읽기를 1순위로 두고, 정확도 비교 후 모델을 정한다.

## 원본

모델 PC `~/rosy-test/vlm-bench/out/<모델>-<사진>/{rows.jsonl,summary.json,*.log}`, 실행 스크립트 `run.sh`·`rerun.sh`. 실행 환경: torch 2.11.0+cu128, torchvision 0.26.0, transformers 5.20.2.

| 파일 | sha256 |
| --- | --- |
| Qwen3-VL-8B-Instruct-front/rows.jsonl | `c5603c8eb89530a9523271599ed7027bab4ca4d66af580addb815ae65ce8ec93` |
| Qwen3-VL-8B-Instruct-top/rows.jsonl | `9127e1ea3028a1a34ef176423f1efde12307c351ea8cd7816530cd79ddbbb20a` |
| Qwen3-VL-8B-Instruct-wrist/rows.jsonl | `180a61b0d247b43bdba7c18b1221e7b3f37c9c9bdb21050e295dc77123d98688` |
| Qwen3-VL-4B-Instruct-front/rows.jsonl | `491f12a643b624d7f62a64400b90337ead0ab69eccbca88684c40c3d660b2e4d` |
| Qwen3-VL-4B-Instruct-top/rows.jsonl | `f58ac11bc1c63deee6164a519930247b256758c1bba70872079fa27f260df34a` |
| Qwen3-VL-4B-Instruct-wrist/rows.jsonl | `c3913706df4c81dabb63a7d33d0a5b2d7051ec44a6e23728be7a8b84c02e40d5` |
| Qwen3.5-4B-front/rows.jsonl | `097c1f0313b7f48012a505c69aae1cf5ee9b1e0c8c6107eb25b0a2121cb1d2f3` |
| Qwen3.5-4B-top/rows.jsonl | `1ff50f15a8da1701d547afb01988ef644da0a9368906e37aed7a347c6c263a30` |
| Qwen3.5-4B-wrist/rows.jsonl | `6a110928e6005feed12dd30f82dc6a780a08bfb10f8dcae7d3543fccf142cd94` |
