---
title: 이름을 바꾼 설정의 새 키를 기본 yaml에 두면 옛 overlay와 deep-merge되어 CORE가 못 뜬다
date: 2026-10-02
category: logic-errors
module: core_common config (rosy_default.yaml) + core bridge control_sensor_adapter (D-400)
problem_type: logic_error
component: service_layer
symptoms:
  - "기본 yaml에 `mode: \"off\"`, 로봇 overlay에 옛 `enabled: true` — 병합 결과에 두 키가 함께 있어 \"takes mode or enabled, not both\"로 CORE 시작 거부"
  - "YAML 1.1에서 따옴표 없는 `mode: off`는 문자열이 아니라 False로 읽힌다"
root_cause: config_error
resolution_type: config_change
severity: high
tags: [config, deep-merge, overlay, yaml, rename, d-400]
---

# 이름을 바꾼 설정의 새 키를 기본 yaml에 두면 옛 overlay와 deep-merge되어 CORE가 못 뜬다

## Problem
D-400에서 `control.sensor_adapter.enabled: bool`을 `mode: off|shadow|enforce`로 바꾸며, 두 키를 함께 쓰면 거부하도록 했다(`_parse_mode`, `src/runtime/gateway/core/bridge/control_sensor_adapter.py`). 계획은 기본 yaml에 `mode: "off"`를 적으라고 했다. 그러면 옛 형식(`enabled: true`)을 쓰는 로봇 overlay가 `load_config`의 deep-merge(`src/contracts/foundation/core_common/config.py` `_deep_merge`: 기본 → 로봇 `core.yaml` → `~/.rosy/rosy.yaml`) 뒤 두 키를 모두 갖게 되어, 하위 호환을 약속한 바로 그 로봇에서 CORE가 시작하지 못한다. 구현 서브에이전트가 Task 1 보고에서 짚었고, 머지 전에 고쳤다.

## Symptoms
- 기본값에 새 키, overlay에 옛 키 → 병합 결과에 둘 다 → "not both" 설정 오류로 시작 거부.
- 단위 시험은 매핑 하나씩만 파싱해서 통과했다. 병합된 결과를 파싱하는 시험이 없었다.

## What Didn't Work
- "기본값을 명시해 두면 읽기 쉽다"는 이유로 새 키를 기본 yaml에 적는 것. 층이 합쳐지는 설정에서는 기본값도 한 층이다.

## Solution
- 기본 yaml에는 새 키를 **적지 않는다**. 없으면 off로 읽는다(파서의 기본값). 문서화는 주석으로:
  ```yaml
  sensor_adapter:
    # mode: "off"   # D-400: unset = off ... Set it (quoted) in the robot overlay.
    # Use exactly one of mode / enabled across all layers (default, robot core.yaml, local overlay).
    stale_hold_s: 2.0
  ```
- 병합 경로를 그대로 시험한다: 패키지 기본 문서에 `_deep_merge`로 `{"control": {"sensor_adapter": {"enabled": True}}}`를 합친 뒤 파싱해 `enforce`가 나오는지(`test_packaged_default_merged_with_legacy_enabled_overlay_is_enforce`).
- 문자열 모드 값은 따옴표로 쓰고, 파서는 문자열이 아니면 "quote it in YAML"이라고 거부한다 — YAML 1.1의 `off`/`on`/`no`/`yes`는 불리언이 된다.

## Why This Works
옛 키와 새 키의 배타성은 **한 층 안의 실수**를 잡으려는 규칙인데, deep-merge는 층을 하나의 매핑으로 합친 뒤에 검사한다. 기본 층이 새 키를 갖고 있으면 아래 층이 옛 키를 쓰는 순간 "두 키를 함께 썼다"로 보인다. 기본 층이 키를 비워 두면 배타성 검사는 실제로 운영자가 쓴 층들 사이에서만 걸린다.

## Prevention
- 설정 키 이름을 바꾸거나 형식을 바꾸는 변경은, **패키지 기본값 + 옛 형식 overlay를 실제 병합 함수로 합친 결과**를 파싱하는 시험을 하나 둔다.
- 배타적인 키 쌍(옛 키/새 키)이 있으면 기본 yaml에는 둘 다 두지 않는다.
- 모드처럼 `off`/`on` 값을 갖는 키는 따옴표를 요구하고, 파서가 불리언을 받으면 따옴표 안내와 함께 거부한다.

## Related Issues
- ADR D-400 (`docs/adr/D-400-core-safety-policy-off-shadow-enforce.md`), 계획의 "실행 중 변경 기록" 표 Task 1 행.
- `docs/solutions/logic-errors/producer-consumer-fixtures-hide-contract-drift-2026-09-30.md` — 각 쪽을 따로 시험하면 합쳐진 계약의 어긋남을 못 본다는 같은 계열.
