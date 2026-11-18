---
symptom: "착지 대기열 분석이 엉뚱한 시험을 흔들림 원인으로 지목했고, 선택기가 일부 fleet 파일 변경에 시험 폴더 전체(555개)를 골랐다"
discovered: 2026-11-18
category: workflow-issues
tags: [landing, affected-tests, selector, composition-root, platform_parts, stop-line, flaky-test]
---

# 착지 멈춤은 실패한 id 로 읽고, 선택기는 합성 지점·평면 설치 이름을 따로 다룬다

## 증상

- 11-18 대기열 분석이 `operations/fleet/test/test_app_connected_integration.py` 를 흔들림 후보로 올렸다. 72시간 동안 그 파일이 STOP 문구에 나온 10건 모두 실패한 id 는 다른 시험이었다.
- E′(D-1037 보강 1) 뒤에도 fleet 허브 파일(teach_routes, relocalize_routes, console_builders, assistant/context)을 바꾸면 각각 564개를 골랐다. 이 넷은 선택 집합이 거의 같았다(Jaccard 0.993~1.0).
- `fleet/server/tracking` 은 `tools/harness/platform_parts.yaml` 의 `source_packages` 에 없어 역의존 규칙이 그 파일들을 놓쳤다.

## 원인

- STOP 줄은 `NEW failure in <argv 전체> (log …); <why>` 였다. argv 가 30개 파일까지 되면 뒤에 붙는 `failed again when run alone: <id>` 가 대기열 줄·보고서에서 잘려, argv 의 첫 파일(알파벳 순 첫 파일)이 범인처럼 보였다.
- `tools/harness/affected_closure.py` 의 `narrow` 는 합성 지점(`server/app.py`·`bootstrap/`·`cli.py`)을 지나 걷지 않는다. 그래서 app.py 만 import 하는 라우터는 "아무 시험도 닿지 않음"이 되어 "모르면 폴더 전체" 로 떨어졌다.
- fleet 서버 holder 는 `fleet.server` 로 평면 설치된다(`operations/fleet/fleet/_source_layout.py` 의 `SERVER_HOLDERS`). `source_packages` 에 없는 holder 는 설치 이름으로 import 하는 시험을 찾지 못한다.

## 해결

- STOP 줄은 argv 앞 4개만 보이고 `...` 를 붙인다. 접두 `NEW failure in` 은 rollup bisect 가 읽으므로 유지한다(`fix/land-stop-line-ids` `125e883dcc`, 원격 245 passed, 착지 대기).
- `narrow` 는 바뀐 파일에 직접 닿는 시험이 없으면, 그 파일을 import 하는 합성 지점까지 걸어 그 지점에 닿는 시험(fleet 244개)과 동적 로더만 고른다(`fix/selector-composition-root` `d2e3c6d761`, 원격 69 passed, 착지 대기). 표본 36건 7,895→6,971, 허브 넷 564→333, 나머지 표본은 그대로다. 게시 FULL 은 바뀌지 않는다.
- `platform_parts.yaml` 에 `fleet/server/tracking` 을 더하고, `operations/fleet/test/test_server_holder_imports.py` 가 `SERVER_HOLDERS` 와 `source_packages` 가 같은지 고정한다(`f22cfd55aa`, main 착지).

## 다음에 적용할 조건

- 착지 멈춤의 범인은 STOP 줄이 아니라 `rosy-land-events.jsonl` 의 failure 이벤트나 실행 로그의 실패 id 로 센다.
- 선택기를 좁히는 규칙에 "아무도 안 씀 → 폴더 전체" 같은 대체가 있으면, 그 대체가 실제로 얼마나 자주 걸리는지 표본으로 잰다(`selection_bench.py`, 또는 `affected_tests.select` 의 reasons 에서 `[import closure]` 가 빠진 줄).
- fleet 서버에 holder 를 새로 만들면 `SERVER_HOLDERS` 와 `source_packages` 를 같이 고친다. 시험이 어긋남을 잡는다.
