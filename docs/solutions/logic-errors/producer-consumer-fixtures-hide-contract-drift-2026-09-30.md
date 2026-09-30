---
title: 두 도구가 주고받는 모양은 한 곳에 정의하고, 실제 생산자 출력을 실제 소비자에 넣는 시험을 하나 둔다
date: 2026-09-30
category: logic-errors
module: tools/perception/dataset (extract → prelabel, build → publish) — D-356 학습 루프
problem_type: integration_issue
component: development_workflow
symptoms:
  - "extract.py와 prelabel.py의 단위 시험이 모두 녹색인데, prelabel 순위 점수에 규칙 기반과의 차이(|error_delta|)가 한 번도 더해지지 않음"
  - "publish.py 시험은 녹색인데 build.py 산출물을 올리면 이미지·마스크 없이 manifest.json만 올라감"
  - "학습자용 README의 데이터셋 구조가 실제 build.py 산출물과 다름"
root_cause: missing_validation
resolution_type: code_fix
severity: high
related_components:
  - testing_framework
tags: [contract, fixtures, round-trip-test, perception, dataset, d-356, parallel-agents]
---

# 두 도구가 주고받는 모양은 한 곳에 정의하고, 실제 생산자 출력을 실제 소비자에 넣는 시험을 하나 둔다

## Problem

D-356 학습 루프에서 도구 여러 개가 파일·딕셔너리 모양을 주고받는다. 각 도구의 단위 시험은 모두 통과했지만, 도구 사이의 모양이 달라 루프의 한 단계가 조용히 죽어 있었다. 오류는 나지 않았다.

## Symptoms

- `extract.py`는 섀도 곁 데이터를 키 `"shadow"`에 `{"data": "<json 문자열>"}`로 저장했다. `prelabel.py`는 `side["perception/learned/shadow"]["error_delta"]`를 읽었다. 키도 다르고 JSON도 풀지 않았다.
- `publish.py`의 staging은 데이터셋의 images 폴더 바로 아래 파일만 읽었다. `build.py`는 세션별 하위 폴더에 썼다.
- 학습자용 README는 `build.py`가 생기기 전에 쓰여 구조가 달랐다.

## What Didn't Work

- **모듈별 단위 시험:** 소비자 시험의 fixture가 소비자가 기대하는 모양으로 손수 만들어졌다. 생산자 시험은 생산자 자신의 모양만 확인했다. 양쪽 모두 녹색이었다.
- **작업별 리뷰:** 한 작업의 diff만 보는 리뷰는 세 건 중 두 건을 놓쳤다. 브랜치 전체를 가로지르는 리뷰에서야 섀도 키 불일치가 드러났다.

## Solution

- **키를 한 곳에 둔다:** 공유 키를 `control.recording`에 정의했다(`CAMERA_TOPIC`, `SIDE_TOPICS`, `SHADOW_TOPIC`). `extract.py`와 `prelabel.py`가 모두 이것을 import한다.
- **String 페이로드는 생산자가 푼다:** `extract.py`가 JSON String을 `json.loads`로 풀어 토픽 이름을 키로 저장한다.
- **실제 경로로 시험한다:** `extract` 모양의 행을 실제 `prelabel.score_frame`에 넣는 시험을 추가했다. `test_string_side_data_round_trips_into_prelabel_score` in `tools/perception/test/test_dataset_extract.py`.
- **publish는 manifest를 따른다:** `publish._stage`는 디렉터리 구조를 가정하지 않고 `manifest.json`의 `frames[]` 경로를 따라간다.

수정은 `feat/perception-learning-loop` 브랜치에 있으며 아직 main에 머지되지 않았다(브랜치 커밋 5f2eb7e4 외; 머지 방식에 따라 SHA가 바뀔 수 있다).

## Why This Works

키가 한 곳에만 있으면 한쪽만 바뀌는 일이 없다. 왕복 시험은 fixture가 아니라 실제 생산자 출력을 소비자에 넣는다. 그래서 두 모듈의 기대가 어긋나는 순간 실패한다.

## Prevention

- 두 도구가 파일·딕셔너리 모양을 주고받으면, 키와 스키마 이름을 공유 모듈 하나에 둔다.
- 생산자의 실제 출력을 실제 소비자에 넣는 시험을 최소 하나 둔다. 소비자 기대를 흉내 낸 fixture는 계약의 증거가 아니다.
- 문서(README 등)는 그것이 설명하는 코드가 생긴 뒤에 쓰거나, 코드가 생기면 다시 대조한다.
- 같은 브랜치에서 여러 구현 에이전트가 병렬로 커밋할 때는 amend와 rebase를 금지한다. 이번에 한 에이전트가 자기 커밋을 amend했는데, 다른 에이전트의 커밋이 끼지 않아 운 좋게 무해했다.

## Related Issues

- [D-356](../../adr/D-356-perception-learning-loop-and-model-delivery.md), 설계 `docs/plans/2026-09-30-perception-learning-loop-design.md`
