---
module: tools
date: 2026-10-25
problem_type: workflow_issue
component: development_workflow
severity: high
tags: ["git", "merge", "squash", "origin", "harness", "D-868"]
applies_when: "로컬 main과 origin/main처럼 같은 작업이 다른 커밋으로 두 번 들어간 두 이력을 병합할 때"
---

# squash로 갈라진 두 이력을 합치면 충돌 없는 자동 병합이 조용히 깨진다

## 증상

2026-10-16(#54)부터 실험실 세션은 로컬 main에 착지하고, 같은 작업의 일부는 origin 기반 브랜치의 squash PR로 공개 main에 들어갔다. 10-25에 두 이력을 합치자(로컬 2,222 대 origin 120 커밋) 파일 333개가 충돌했다. 충돌을 로컬 판으로 풀고 lint가 통과한 뒤에도 FULL 시험에서 착지가 열여섯 번 멈췄다.

## 원인

충돌한 파일만 한쪽으로 고르면, 충돌하지 않은 반대쪽 변경은 git이 그대로 넣는다. 그 결과 한쪽의 시험·배치가 다른 쪽의 소스와 만난다.

- 이름 바꾸기 충돌: 같은 파일을 로컬은 `sitemap/`·`recognition/`·`assistant/`로, origin은 `maps/`·`site_observation/`·`work/assistant/`로 옮겼다. 로컬 배치를 고른 뒤에도 origin 쪽에서만 추가된 같은 내용의 사본, 패키징 매핑(`fleet_sources.py`), 안전 태그 파일의 이동(`goal_lease.py`)이 남았다.
- 반쪽 리팩터: origin #130은 `shared/web/request.js`를 지우고 소비자 import를 바꿨는데, 충돌한 소비자는 로컬 판이 되고 삭제와 시험 변경만 들어왔다.
- 시험이 다른 판의 코드를 검사: origin의 오래된 정리 시험이 로컬에서 다시 쓴 코드를 검사했고, 반대로 origin이 필수 인자를 더한 함수를 로컬 시험이 옛 방식으로 불렀다.
- append 전용 기록: `logs.md` 항목은 양쪽 판이 모두 남아야 하고 날짜 순이어야 한다. ADR Log는 git 텍스트 병합이 같은 행을 두 번 넣는다. squash 커밋이 이력에 들어오면 `safety_review_exempt.json`의 squash 연결 항목도 필요하다.
- 검사의 빈틈: `size_range.py`는 커밋마다 첫 부모 대비 바뀐 파일만 보므로, 병합의 두 번째 부모 쪽에서 한도를 넘긴 파일을 놓친다(`collection_intake.py` 620줄, 전체 트리 검사 `test_module_structure`만 잡음).

## 해결과 검증

- 원인 차단: [D-868](../../adr/D-868-local-main-first-merge-commit-publish.md). 로컬 main에 먼저 착지하고 공개 main에는 merge commit PR로만 올린다. 저장소와 `main-protection` ruleset을 merge commit 전용으로 바꿨다.
- 병합 순서: ① 충돌은 정본 쪽으로 푼다. ② 정본에 없는 반대쪽 추가 파일 가운데 같은 내용의 사본을 blob 해시로 찾아 지운다. ③ 반대쪽 커밋마다 추가한 줄이 결과 트리에 있는지 대조해 빠진 기능만 다시 들인다. ④ `logs.md`는 양쪽 항목을 모두 두고 날짜로 안정 정렬한 뒤 `rosy_harness.is_append_only`를 두 부모에 대해 확인한다. 같은 제목의 두 판은 `tools/harness/log_repairs.yaml`에 해시 쌍으로 잇는다. ⑤ ADR Log와 `adr_gaps.txt`는 정본 판을 두고 반대쪽에만 있는 행만 더한다. ⑥ lint 뒤 FULL 시험과 전체 트리 크기 검사를 돌린다.
- 독립 읽기 전용 검토가 크기 초과와 병합된 기능의 누락 여부를 따로 확인했다.

## 다음에 적용할 조건

- 같은 작업이 두 이력에 다른 커밋으로 있으면, 충돌 수가 아니라 자동 병합된 반대쪽 변경이 위험이다. lint 통과를 병합 완료로 보지 않는다.
- 병합 결과에서 `git diff main HEAD --name-status -M`의 이동(R)과 추가(A)를 먼저 훑는다. 정본 배치에 없는 디렉터리는 사본인지 확인한다.
- 병합 커밋이 있는 브랜치는 `size_range`만 믿지 말고 `test/architecture/test_module_structure.py`를 함께 돌린다.
