---
title: Ollama가 빈 enum 스키마를 400으로 거절했고, judgment 스키마는 검증기가 거부할 답을 허용했다
date: 2026-10-25
category: runtime-errors
module: operations/decision deliberation (judgment_schema, D-878), deploy/ai_pc/deliberation_ollama.py
problem_type: integration_issue
component: service_layer
symptoms:
  - "로컬 v2 deliberation이 HOLD / LOCAL_PROVIDER_FAILED, failure_kind TRANSPORT로 끝나고 모델 답이 없다"
  - "2026-10-12 qwen v2 synthetic attempt가 QWEN_V2_PROVIDER_FAILED로 끝났고 원인을 구분하지 못했다"
  - "400을 고친 뒤 실제 판정 3건 중 2건이 스키마 제약 생성인데도 INVALID_JUDGMENT_STEP으로 거부됐다"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [ollama, json-schema, structured-output, deliberation, qwen, constrained-decoding]
---

# Ollama가 빈 enum 스키마를 400으로 거절했고, judgment 스키마는 검증기가 거부할 답을 허용했다

## Problem

`judgment_schema()`가 만든 v2 판정 스키마를 Ollama `format`으로 넘기는 로컬 deliberation 경로가 실제 모델에서 두 번 막혔다. 단위 시험은 모두 가짜 `exchange`를 써서 통과했고, 모델 PC의 실제 qwen3-vl:8b-instruct로 `test/test_structured_output_pipeline.py`를 돌렸을 때 처음 드러났다.

## Symptoms

- 요청이 0.0초 만에 `HTTP 400`. 응답 본문: `JSON schema conversion failed: JSON schema error at #/properties/missing_evidence/items: enum must be a non-empty array`. Ollama 0.35.1이 llama-server의 스키마→문법 변환을 쓰기 때문이다(모델 PC·AI PC 모두 0.35.1).
- `deliberation_ollama.main()`은 HTTPError를 `OSError`로 보고 `TRANSPORT`로만 분류하며 본문을 버린다(원문 비노출 정책). 그래서 2026-10-12 시도의 원인이 남지 않았다.
- 400을 고친 뒤: 모델이 `verdict: reobserve`, `next_step: null`을 냈고 `judgment()`가 `INVALID_JUDGMENT_STEP`으로 거부했다.

## What Didn't Work

- 가짜 Ollama 응답으로 만든 단위 시험: 요청 스키마를 실제 문법 변환기에 넣지 않으므로 400을 재현할 수 없다.
- 변형마다 속성을 통째로 복사한 첫 스키마: 작업 본문이 `canonical()`의 16 KiB 상한을 넘어 `deliberation payload exceeds budget`.

## Solution

1. 허용 목록이 빈 배열은 `{'type': 'array', 'maxItems': 0}`으로 낸다(뜻은 같다). 받은 스키마에서 목록을 읽는 곳(Ollama broker, GLM judgment)은 `schema_missing_allowlist()` 하나를 쓴 뒤 다시 만들어 비교한다.
2. 스키마가 검증기의 구조 조건을 같이 표현한다. 루트 `properties`는 읽는 코드를 위해 그대로 두고 루트 `anyOf` 변형을 더했다: 쉬는 판정(`abstain`, 필요성이 맞을 때 `do_not_intervene`)은 단계 `null`, `reobserve`는 읽기 전용 단계, `candidate`는 허용 단계. `step()`이 항상 거부하는 `device_action_api` 도구는 처음부터 빼었다.
3. 변형은 `{'$ref': '#/properties/<필드>'}`와 이름 키 `#/$defs/<field>.<tool>`만 가리킨다. llama.cpp의 `$ref` 해석은 객체 키 경로만 따라가고 배열 인덱스(`#/properties/next_step/anyOf/1`)는 해석하지 못한다. 참조로 바꿔 16 KiB 안에 들어왔다.

결과(모델 PC, 같은 시험): deliberation 0/3(400) → 1/3(스키마 틈) → 3/3. conversation 46/46, operator 26/26, judge seat 4/4는 변화 없이 통과.

## Why This Works

제약 생성은 스키마가 허용하는 것만 막는다. 검증기(`judgment()`)가 따로 요구하는 구조 조건(판정과 단계의 짝, 읽기 전용 제한)이 스키마에 없으면 모델은 문법상 유효하지만 결국 거부될 답을 낸다. 조건을 스키마로 옮기면 생성 단계에서 그 답이 나올 수 없다. 확률 합·우승 선택 같은 의미 조건은 여전히 검증기만 본다.

## Prevention

- 스키마를 바꾸면 `ROSY_RUN_STRUCTURED_MODEL_TESTS=1`로 모델 PC에서 `test/test_structured_output_pipeline.py`를 돌린다(`ROSY_TEST_HOSTS`로 모델 PC 고정, `-s`로 `STRUCTURED_PIPELINE_RESULT` 행 확인). 시험 행에는 HTTP 오류 본문이 남는다.
- 새 스키마 규칙: 빈 `enum` 금지, `$ref`는 객체 키 경로만, 작업 본문 16 KiB 이내. `test_model_judgment.py`가 빈 enum·변형 짝·참조 경로를 고정한다.
- 검증기에 구조 조건을 더하면 같은 변경에서 스키마 변형에도 더한다.

## Related Issues

- [D-878](../../adr/D-878-structured-model-output-schema-and-provider-wire.md) 모델 구조화 출력 원칙
- `docs/validation/deliberation-host-admission-2026-10-12/qwen-v2-synthetic-attempt.md` — 원인 미확인으로 남은 시도. 이번 400이 같은 원인일 가능성이 높으나, 그 실행의 요청을 다시 보지 않았으므로 확정하지 않는다.
