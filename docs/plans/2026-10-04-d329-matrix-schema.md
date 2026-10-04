# D-329 전환 4단계 — `matrix.json` 스키마와 보존 시험

**Status:** PLAN rev 1 (2026-10-04). D-329 Decision 4·Transition 4가 "실행 계획에서 정한다"고 미뤄둔 두 가지 — 파일명 규칙과 `matrix.json` 스키마 — 를 고정하고, 스키마가 생겼으므로 같은 회차에 계약 시험을 연다. 이 계획 자체는 G2 판정을 올리지 않는다.

## 1. 스키마 v1 — `rosy.g2-matrix/1`

회차 폴더(`docs/validation/<topic>-<date>/`)마다 최대 한 개의 `matrix.json`:

```json
{
  "schema": "rosy.g2-matrix/1",
  "round": "2026-10-04",
  "tier": "LOCAL-synthetic",
  "surfaces": [
    {
      "id": "pilot",
      "cells": [
        {"state": "connect", "viewport": "2000x1200", "file": "pilot-connect-2000x1200.png"}
      ]
    }
  ]
}
```

- `schema` — 문자 그대로 `rosy.g2-matrix/1`. 다르면 시험이 빨갛다.
- `round` — 회차 날짜(`YYYY-MM-DD`). 폴더 이름의 날짜와 같아야 한다.
- `tier` — 증거 등급을 사람이 한 줄로 적는다(`LOCAL-synthetic`, `LOCAL-browser`, …). 시험은 값을 요구만 한다(D-153의 등급 판정은 시험이 아니다).
- `surfaces[].id` — `surfaces.yaml`의 표면 `id`. 등록되지 않은 id면 빨갛다.
- `surfaces[].cells[]` — 한 셀 = 표면 × 상태 × 뷰포트. `state`는 소문자·숫자·하이픈. `viewport`는 `"<가로>x<세로>"`. `file`은 회차 폴더 안 상대 경로.
- 같은 (id, state, viewport) 셀이 둘이면 빨갛다. 셀마다 파일이 있어야 하고, 그 파일은 **추적된** 파일이어야 한다(D-329가 고치려 한 "그 자리에 있는지"를 시험이 판정한다).

## 2. 파일명 규칙

새 회차의 보존 셀 파일명은 `<surface-id>-<state>-<가로>x<세로>.png`(예: `pilot-drive-2000x1200.png`, `console-operate-fresh-1366x768.png`). 셀의 `file`이 규약과 어긋나면 시험이 빨갛다. 과거 회차의 64장을 이 규약으로 되돌려 맞추는 일은 **별도 배치**다(D-329 본문이 순서를 이렇게 못 박았다) — 이 계획의 범위가 아니다.

## 3. 시험

`shared/web/test/test_baseline_matrix.py`:

1. 추적된 `docs/validation/*/matrix.json` 전부를 읽는다(파일시스템 `rglob`이 아니라 `git ls-files` — 빌드 산출물 집어오기 방지, D-329 Context 3과 같은 이유).
2. 스키마·round-폴더 날짜 일치·id 등록·셀 유일성·파일 존재·파일 추적·파일명 규칙을 검사한다.
3. **변이 확인**: 검사 함수를 합성 오류 매트릭스(스키마 틀림·미등록 id·없는 파일·규약 밖 파일명·중복 셀)로 돌려 각 오류가 잡히는 것을 같은 파일에서 단언한다. 실제 회차에 대해서는 오류 0건.

## 4. 첫 적용

`docs/validation/pilot-g2-baseline-2026-10-04/` — 2026-10-04 Pilot 크래프트 회차 1의 셀 9장을 규약명으로 옮기고(`gate-tablet-land.png` → `pilot-connect-2000x1200.png` 등) 그 회차에 `matrix.json`을 남긴다. `surfaces.yaml` pilot의 `baseline` 경로를 같은 커밋에서 새 파일명으로 고친다.

## 검증

- `python -m pytest shared/web/test/test_baseline_matrix.py -q`
- `python -m pytest shared/web/test -q` (레지스트리 회귀)
- `python tools/harness/rosy_harness.py lint`

## 완료 정의

스키마가 문서로 고정되고, 시험이 변이 확인과 함께 초록이며, Pilot 회차가 첫 관측 사례가 된다. 과거 회차 backfill과 D-329 승격 판정은 이 계획 밖.
