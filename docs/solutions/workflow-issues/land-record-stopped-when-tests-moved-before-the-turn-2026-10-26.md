---
module: tools/land.py
date: 2026-10-26
last_updated: 2026-10-27
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

## 기록 생성과 게시 자격은 함께 검증한다 (2026-10-27)

후속 실제 착지 준비에서 `LOAD-FLAKY` 결과가 준비 기록의 `tier="full"`로 남는 것을 관측했다. 격리 보고서가 없는 현재 실행을 과거 캐시의 완료 보고서가 대신하는 경로도 있었다. 기록이 존재한다는 사실만으로 현재 후보가 게시 검증을 마쳤다고 판단하면 안 된다. 앞선 기록 복원은 필요한 수정이었지만, 기록을 쓸 자격까지 보장하지는 않았다.

이번 수정은 기존 자동 착지의 재시도·변화분 재사용 정책을 유지하면서 두 저장 경로 모두 현재 guard와 본시험의 자격을 확인한다. 자동 착지가 허용하는 `LOAD-FLAKY`·다른 tree의 좁은 cache 재사용 결과는 변화분 연결에 필요한 준비 정보만 보존하고 tier를 비워 게시 자격에서 제외한다. 명시적 `--tests full`은 그런 결과를 저장·fast-forward 전에 중단한다.

명시적 FULL은 현재 후보의 새 자식 프로세스에서 정본 FULL 호출과 등록된 전체 브라우저 호출·ALONE 구성을 읽는다. 이전 실행의 full tier만으로 현재 준비를 생략하지 않는다. 같은 프로세스의 준비 증거와 기존 후보/main provenance bridge를 확인한다. 그 연결이 성립하지 않거나 현재 필수 호출·시험 환경이 맞지 않으면 다시 준비한다. 본시험의 정확한 clean 캐시 재사용과 현재 guard·격리 실행의 증거는 따로 확인한다. `--no-cache`만으로 격리 보고서의 과거 캐시 fallback까지 없어지지는 않으므로, FULL의 최초·재시도 모두 현재 보고서만 인정하도록 했다.

이 변경은 격리 시간 상한 안에 모든 nonSafety 파일이 완료됐다는 보장이 아니다. 기존 nonSafety 미도달 기록과 Safety 미도달 중단 정책은 유지한다. 공개 CI, 실제 로봇, 배포 수용도 별도다. 과거 착지 기록을 이 새 검증의 통과로 소급하지 않는다.

확인 근거는 로컬 source `259605fb2c`의 selector·소유권 검사 299 PASS와, 동일한 승인 source 7개를 유지한 로컬 `b36e441576`의 관련 도구 8파일 234 PASS/0 SKIP다. 두 원격 실행은 각각 NEW0/known0/flaky0이며 서로 다른 커밋의 범위별 증거다. 첫 도구 실행의 10실패와 다음 2실패는 실제 검사가 잘못된 시험 구성을 거절한 결과로 보존했고, 형식·저장소 입력·실제 변화분을 고친 뒤 다시 검증했다.

실제 과거 캐시 항목에 다른 커밋·환경의 완료 보고서를 넣은 반례는 수정 전에 1 assertion FAIL/3 PASS/NEW1이었다. 수정 뒤 회귀 시험은 현재 보고서 부재의 재시도 후 중단, 저장·receipt 차단, 현재 완료 보고서의 허용, auto의 과거 fallback 보존을 확인한다. 다음 변경에서도 저장소에 receipt가 생기는지와 그 후보가 실제 자격을 갖췄는지를 함께 검사한다.
