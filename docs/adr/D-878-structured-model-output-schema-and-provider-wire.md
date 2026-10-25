## D-878 모델 구조화 출력 — 스키마 정본은 하나, 전송 형식은 어댑터에서, 파싱 실패는 무효 답과 같다 (D-392 §6 보충)

**Status:** Proposed (2026-10-25). [D-392](D-392-provider-neutral-model-tool-contract.md) §6을 모델 출력 JSON까지 넓힌다. 제공자 활성화·데이터 반출·비용 승인·로봇 권한은 바꾸지 않는다(D-358, D-640 유지).

### Context

판단 모델의 답은 모두 JSON으로 받는다. 받는 방식은 경로마다 다르다.

| 경로 | 생성 단계 강제 | 사후 검증 |
|---|---|---|
| 로컬 Ollama(deliberation broker, conversation, operator, situation VLM, OMX judge seat, 큐레이션 일부) | `format: <JSON Schema>` | 정확한 키·enum·결속값, pydantic `strict` |
| Claude CLI | `--json-schema` | `opinion()`/`judgment()` |
| Gemini ER2 | function declaration(`model_tool_catalog`) | `from_function_call` |
| z.ai GLM·opencode free 게이트웨이 | `response_format: json_object`(문법만, 스키마 아님) | `opinion()`/`judgment()` |
| `qwen_review_completion`, `qwen_points`, `lane_failure_loop` | `format: 'json'` 또는 없음 | 손 검사·정규식 |

공통점은 fail-closed다. 재시도·JSON 수리 없이 HOLD·abstain·abort로 끝난다. 예외는 OMX judge seat였다. 범위 밖 선택은 `abort`로 거부했지만 깨진 JSON·시간 초과는 예외로 호출자에게 올라갔다(이 ADR과 함께 고침).

스키마를 `format`으로 넘기면서 프롬프트에도 JSON 모양을 글로 다시 적는 곳이 다섯이다(`incidents/vision.py` PROMPT, `deliberation_conversation.instruction()`, `operator_broker`, `judge_seat.prompt()`, ER2 프롬프트). v2 deliberation은 스키마 객체를 요청 본문 데이터로 넘겨 이 중복이 없다(`versioned_request.prepare_request`).

새 판단 모델 후보로 OpenRouter 같은 라우터가 있다. [OpenRouter 문서](https://openrouter.ai/docs/guides/features/structured-outputs)(2026-10-25 확인)의 사실:

- `response_format: {type: json_schema, json_schema: {name, strict: true, schema}}`로 스키마를 넘긴다. 강제 정도는 제공자마다 다르다. 일부는 보장하고 일부는 강한 힌트로만 쓴다. strict 모드는 JSON Schema 기능 일부만 받을 수 있다.
- [제공자 라우팅](https://openrouter.ai/docs/guides/routing/provider-selection)에서 `response_format`은 기본적으로 선호 조건이다. 그 모델의 제공자가 하나도 지원하지 않으면 요청은 그대로 가고 파라미터는 무시된다. `provider.require_parameters: true`일 때만 지원 제공자로 제한된다.
- [response-healing](https://openrouter.ai/docs/guides/features/plugins/response-healing) 플러그인은 비스트리밍 요청에서 괄호·쉼표·마크다운 감싸기를 고쳐 문법상 유효한 JSON을 돌려준다.

### Decision

1. **스키마 정본은 소비자 코드 한 곳.** 판단마다 출력 JSON Schema는 그 답을 검증하는 쪽이 코드로 만든다(`judgment_schema()`, `SemanticAnswer`/`OperatorAnswer`의 `model_json_schema()`, `model_assessment_schema`, judge seat의 `schema`). OpenAI 호환 `response_format`, Ollama `format`, Claude `--json-schema`, Gemini function declaration은 어댑터가 같은 객체에서 만든다. 손으로 옮겨 적은 스키마 사본을 두지 않는다.
2. **생성 단계 강제는 조언이다.** 어떤 강제 방식을 쓰든 사후 검증(정확한 키 집합·enum·결속값·카탈로그 대조)을 생략하지 않는다. 호출 실패·JSON 파싱 실패·객체가 아닌 답은 범위 밖 답과 같은 실패로 처리한다(HOLD/abstain/abort). 자동 재시도는 없다(D-358 §5와 같음).
3. **라우터 사용 조건.** OpenRouter 같은 라우터로 판단 모델을 부를 때는 `json_schema` + `strict: true` + `provider.require_parameters: true`를 함께 건다. 셋 중 하나라도 빠지면 스키마가 조용히 무시될 수 있다. 대상 엔드포인트가 그 스키마(`const`, `anyOf`, `additionalProperties: false` 포함)를 거절하면 그 모델은 그 판단에 수용하지 않는다. `json_object`만 되는 제공자는 사후 검증만 근거로 하며, 지원 여부는 실제 응답으로 확인한다.
4. **JSON 수리 금지 범위.** response-healing 플러그인과 JSON 수리 라이브러리는 deliberation·incident·conversation·operator·OMX 판단 경로에서 쓰지 않는다. 잘린 답(`finish_reason`/`done_reason`이 `stop`이 아님)을 유효한 JSON으로 덮어 fail-closed 판단을 흐리기 때문이다. 오프라인 큐레이션은 쓸 수 있으나 수리 여부를 결과 행에 남긴다.
5. **프롬프트의 스키마 중복.** 새 경로는 스키마 객체를 본문 데이터로 넘기거나 속성 `description`에 설명을 둔다. 기존 다섯 곳은 실제 모델 응답을 비교한 뒤에만 고친다. Qwen은 스키마 프롬프트에서 빈 결과를 낸 기록이 있다([2026-10-06 설계](../plans/2026-10-06-qwen-point-sam3-lane-drafts-design.md)).
6. **공통 어댑터는 새 제공자와 함께.** 새 제공자를 붙이는 첫 변경에서 OpenAI 호환 응답 검사(choice 하나, model 일치, `finish_reason == 'stop'`, tool call 없음, content 문자열)를 공통 함수로 뽑고 GLM·free 게이트웨이를 옮긴다. 그 전에는 수용된 게이트웨이를 리팩터링하지 않는다. 오류 코드·호출 1회·크기 상한은 각 게이트웨이 시험이 지금처럼 고정한다.

7. **스키마는 검증기의 구조 조건까지 담는다.** 검증기가 요구하는 구조 조건(판정과 단계의 짝, 읽기 전용 제한, 항상 거부하는 도구)은 스키마 변형(`anyOf`)으로도 표현해 생성 단계에서 막는다. 빈 `enum`을 내지 않고, `$ref`는 객체 키 경로만 쓰며, deliberation 작업 본문은 16 KiB 안에 둔다. 스키마를 바꾸면 모델 PC에서 실제 모델 파이프라인 시험(`test/test_structured_output_pipeline.py`, opt-in)을 돌린다.

### Consequences

- 판단 모델을 하나 더 붙일 때 바뀌는 곳은 전송 형식 변환과 응답 봉투 검사뿐이다. 스키마·의미 검증·fail-closed 결과는 그대로다.
- `judgment_schema()`와 `judgment()`는 따로 있다. 확률 합·카탈로그 대조처럼 스키마로 표현할 수 없는 검사가 있어 손 검증을 유지한다. jsonschema 의존성은 더하지 않는다.
- 이 ADR과 함께: `deploy/robot/omx/judge_seat.py`는 호출 실패·깨진 JSON·객체 아닌 답을 `abort` 거부로 받는다. 스키마에 `additionalProperties: false`를 더한다. `test/test_omx_judge_seat.py`가 세 경우를 고정한다.
- 2026-10-25 구현: §6의 공통 어댑터는 새 제공자를 기다리지 않고 `rosy.decision.structured_output`으로 먼저 만들었다. Ollama broker 셋(deliberation, conversation, operator)과 GLM·free 게이트웨이가 쓴다. 전송 바이트는 바뀌지 않는다. 클라우드 두 곳은 json_schema 탐침 전까지 `json_object`로 둔다.
- 2026-10-25 실제 모델 파이프라인(모델 PC, qwen3-vl:8b-instruct, Ollama 0.35.1): `judgment_schema()`의 빈 `enum`이 HTTP 400을 내 기본 로컬 v2 작업이 모두 실패했고, 고친 뒤에도 판정 3건 중 2건이 스키마 틈(`reobserve`에 단계 `null`)으로 거부됐다. 둘 다 고친 뒤 deliberation 3/3, conversation 46/46, operator 26/26, judge seat 4/4, qwen 완성 3/3. 교훈: [solutions](../solutions/runtime-errors/ollama-refused-empty-enum-and-judgment-schema-allowed-steps-the-validator-refuses-2026-10-25.md).
- §5 결과: 다섯 프롬프트의 "중복"은 대부분 분류 규칙과 few-shot 예시다. 현재 프롬프트로 conversation·operator가 전부 맞으므로 지우지 않는다. qwen 완성 좌표 규약(픽셀 대 0-1000)은 합성 프레임으로 판별되지 않아 실제 검수 프레임 비교 전까지 바꾸지 않는다.
- 수용 근거가 아닌 것: 어댑터 시험·문서 확인은 제공자 수용, AI PC 배포, 실물 팔 수용을 대신하지 않는다.

**References:** [D-392](D-392-provider-neutral-model-tool-contract.md), [D-358](D-358-er2-feedback-outbox-and-replan-fencing.md), [D-640](D-640-fleet-deliberation-and-incident-improvement.md), [D-831](D-831-operator-command-preprocessing.md), [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs), [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection), [OpenRouter response healing](https://openrouter.ai/docs/guides/features/plugins/response-healing).
