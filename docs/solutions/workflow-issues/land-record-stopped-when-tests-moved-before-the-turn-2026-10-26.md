---
module: tools/land.py
date: 2026-10-26
problem_type: workflow_issue
component: landing_pipeline
severity: high
tags: ["land", "land-record", "pre-push", "publish", "A-prime", "regression", "side-output"]
applies_when: "land.py의 시험 단계 위치·순서를 바꿀 때(잠금 밖 준비, 재준비, 조각내기), land_record·land_full·land_cache를 쓰는 조건을 건드릴 때, 또는 pre-push가 갑자기 길어지거나 publish_main이 오래된 SHA나 '게시할 것 없음'을 낼 때"
---

# 시험을 차례 앞으로 옮기자 착지 기록이 조용히 끊겼다

## 증상

10-26 16:12 병렬 착지(A', 모든 착지가 잠금 밖에서 미리 시험)가 main에 들어간 뒤 `.git/rosy-land/<sha>.json` 착지 기록이 하나도 새로 쓰이지 않았다. 마지막 기록은 16:21의 5e162cca21로, A' 이전 코드로 준비한 착지였다. 그 뒤 FULL 11532 passed로 착지한 `feat/uiux-shell-tokens`도 기록이 없었다. 착지는 모두 성공했고 시험도 오류도 없었으므로, 기록 폴더를 직접 보기 전까지 아무도 알아채지 못했다.

## 원인

`tools/land.py`는 차례 라운드에서 `full_main`(이전 실행이 시험한 main)이 있으면 그 사이 main 변화분만 고르고 `reusable = False`로 둔다. "FULL은 이전 후보에서 돌았다"는 뜻이었다. A' 이전에는 FULL을 잠금 밖으로 미룬 드문 착지만 이 분기를 탔다. A' 이후에는 모든 auto 착지가 `land_prepare.prepare`에서 `land_full.save`를 하므로 **모든** 착지가 이 분기를 타고, 기록 쓰기 조건 `if reusable and landed == candidate`가 항상 거짓이 되었다. FULL은 이제 잠금 안에서 돌지 않으므로(`note`면 다시 준비) `tier="full"` 기록도 사라졌다.

기록은 착지의 부산물이지만 두 소비자가 있다.
- pre-push(`land_record.owed`)는 기록 사슬이 origin/main까지 이어질 때만 시험을 재사용한다. 기록이 끊기면 게시 push가 affected 계층을 다시 돌려 30~40분이 걸린다.
- `publish_main.py`는 tier가 `full`인 기록이 있는 SHA만 게시 후보로 삼는다. 기록이 끊기면 오래된 SHA를 고르거나 게시할 것이 없다고 한다.

착지 자체를 시험하는 `test_land.py`에는 "착지가 끝나면 기록이 있다"를 끝에서 끝까지 확인하는 시험이 없었다. 그래서 A'의 시험 407~627건이 모두 초록이었다.

## 해결

`fix/land-record-after-prepare`:
- `land_full.save`가 준비한 tier와 invocations도 저장한다.
- `land_full.prepared(wt, branch, full_main)`가 그 main 위의 준비 결과를 돌려준다.
- 차례 라운드는 `reusable = False` 대신 준비 결과가 있을 때만 재사용 가능으로 둔다.
- `land_record.write(prepared=...)`는 invocations를 "준비 + 변화분"으로 남기고, tier는 준비한 tier로, `prepared_on`·`prepared_candidate`도 함께 남긴다.

이 기록이 근거로 삼는 논리는 착지가 이미 쓰는 D-762 stage 0과 같다. 준비 시험이 `prepared_on` 위에서 초록이었고, 차례에서는 `prepared_on..main` 변화분 선택이 후보 위에서 초록이었다는 것이다.

## 확인 근거

- 새 시험 `test_a_landing_prepared_before_its_turn_leaves_a_record_with_the_prepared_tier[full|affected]`: 원격 `test_land*`·`test_land_record`·`test_publish_main` 153 passed.
- 변이: 분기를 옛 `reusable = False`로 되돌린 커밋에서 두 경우 모두 빨강.

## 다음에 적용할 조건

- 착지 파이프라인의 단계를 옮기거나 나눌 때는 시험 결과뿐 아니라 **부산물(land_record, land_full, land_cache, land_events)과 그 소비자(pre-push, publish_main, land_stats)** 를 목록으로 적고, 각 부산물이 끝에서 끝까지 생기는지 시험으로 확인한다.
- "착지 성공"만 보는 시험은 부산물이 끊긴 것을 잡지 못한다. 착지 뒤 `land_record.read(main, HEAD)`처럼 소비자가 읽는 형태로 확인한다.
- pre-push가 갑자기 길어지거나 publish_main이 예상보다 오래된 SHA를 고르면, 먼저 `ls -t .git/rosy-land | head`로 마지막 기록 시각을 본다.
