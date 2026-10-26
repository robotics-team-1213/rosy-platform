---
module: docs
tags: [landing, squash, concurrent-landing, worktree]
problem_type: workflow
---

# 병합 해결 중 main이 움직이면 스쿼시 커밋이 동료 착지를 되돌릴 수 있다

2026-10-25, D-865 P2b 착지 준비 중 발견. 착지 전에 잡혀서 사고는 없었다.

## 증상

오래 걸리는 병합 충돌을 해결한 뒤 브랜드를 `reset --soft main` + 재커밋으로
한 커밋으로 정리했더니, diff가 내 변경이 아닌 **동료 세션이 방금 착지한 파일
839줄 삭제**를 포함했다.

## 원인

충돌 해결 사이에 다른 세션이 main에 착지했다(활발한 착지 큐 환경). 내 병합
트리는 옛 main 기준이고, `reset --soft main`은 **지금의** main을 부모로 삼지만
인덱스(트리)는 옛 병합 결과 그대로다. 두 main의 차이가 내 커밋의 "삭제"로
기록된다. 이 커밋이 그대로 착지되면 ff-only라도 동료 작업이 사라진 트리가
main이 된다.

## 해결

- 스쿼시/재커밋 직전에 `git diff main --stat`(또는 `--numstat`)로 **내가 건드린
  경로만 diff에 있는지** 확인한다. 내가 고친 적 없는 경로의 삭제가 보이면
  main이 내 병합 이후에 움직인 것이다.
- 그 경우: 최신 main에서 다시 병합하거나, 내 파일들만 새 main 위에 다시
  적용한다(워크트리 복사 → `reset --hard main` → 재적용).
- `git stash`는 워크트리 전체가 공유한다 — 세션 로컬로 착각하면 동료 stash를
  pop할 수 있다. 충돌로 중단되면 stash는 보존되지만, 워크트리는 정리해야 한다.

## 검증

- `git diff --name-only main HEAD`가 내 스테이징 목록과 정확히 일치.
- 스쿼시 후 `python tools/harness/size_range.py main HEAD`와 lint가 통과.

## 다음에 적용할 조건

여러 세션이 같은 저장소의 착지 큐를 쓰는 동안에는, 병합 충돌 해결에 오래
걸린 브랜치는 재커밋 전에 반드시 main-대비 diff 경로 검사를 한다. 사고 대응
중이 아니면 스쿼시를 피하고 병합 커밋 그대로 착지하는 것이 안전하다.
