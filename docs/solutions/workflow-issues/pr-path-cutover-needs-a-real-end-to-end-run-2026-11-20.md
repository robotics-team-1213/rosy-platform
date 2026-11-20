---
symptom: "D-1055로 PR+Merge Queue 경로를 연 직후(11-20 16:07) 모든 세션의 첫 pr_land가 차례로 다른 이유로 멈췄다: 실험실 증거 없음, pre-push 훅 거부, 훅 파일 불일치, 가짜 backlog 거부"
discovered: 2026-11-20
category: workflow-issues
tags: [d-1055, pr-land, merge-queue, cutover, lab-evidence, pre-push, publishOnly, freeze, flaky-test]
---

# 병합 경로 전환은 실제 브랜치 하나로 끝까지 돌려 본 뒤에 연다

## 증상

- 전환 전 점검(`queue_cutover_check.py`, `pr_land --dry-run`의 단위 시험)은 모두 통과했다. 그러나 개방 뒤 첫 실제 제출에서 다음이 하나씩 드러났다.
  1. `pr_land`가 "lab-only change requires remote_pytest lab evidence"로 거부했다. 시험 파일 하나만 바꾼 브랜치도 같았다.
  2. 증거를 만든 뒤에는 공용 클론의 pre-push 훅이 "rosy.publishOnly: … is not publish/main-*"로 브랜치 push를 거부했다.
  3. 훅 주석을 고친 브랜치는 "installed pre-push is not the pushed commit's tools/hooks/pre-push"로 다시 거부됐다.
  4. 로컬 main이 origin/main보다 뒤에만 있어도 "branch descends from un-published local main"으로 거부됐다.
- 동결(drain) 중에 공용 GitHub 계정으로 다른 세션이 origin PR을 merge queue에 넣었다(#250, #258). 노트북 동결 파일은 이를 막지 못했다.
- 마지막 거대 게시 PR #257(155커밋)은 merge_group에서 `test_post_age_guard` 한 건(`assert 2 == 1`)으로 큐에서 빠져 약 25분을 잃었다.

## 원인

- `pr_land.verify_lab_evidence`는 `land_cache` 행을 요구하는데, 그 행을 쓰는 곳은 `land.py`·`land_nightly.py`·`publish_evidence.py`뿐이었다. 개방하면서 공용 클론의 `land.py`를 거부했으므로 증거 생산자가 사라졌다.
- `pr_land.ci_entry`는 한 호출의 모든 경로가 한 CI 매트릭스 항목 아래에 있을 때만 항목을 돌려준다. 선택기가 여러 항목의 시험을 한 호출로 묶으면, 전부 GitHub CI에서 도는 시험이어도 "CI에서 못 돎"이 되어 실험실 증거를 요구했다.
- D-868의 `rosy.publishOnly` 훅은 그대로였다. 설정을 지우면 `land_freeze`의 공용 클론 `land.py` 거부도 함께 풀린다(`land_freeze.py`가 같은 설정을 읽음).
- pre-push 훅은 설치본과 push하는 커밋의 `tools/hooks/pre-push`가 같아야 통과한다. 브랜치에서 훅 파일을 바꾸면 그 브랜치는 push할 수 없다.
- backlog 검사는 "로컬 main이 HEAD의 조상"만 보았다. 로컬 main이 origin/main의 조상(뒤처짐)이어도 조건이 참이 된다.
- 동결은 로컬 파일에만 있었고, 모든 세션이 같은 GitHub 계정을 쓴다. GitHub 권한으로는 "큐 등록만" 막을 수 없다.
- `test_post_age_guard`는 실제 시계 0.05초 타임아웃과 0.01초 sleep을 경주시켰다. 느린 러너에서 첫 전송이 먼저 타임아웃되어 전송이 두 번 나갔다.

## 해결

- `tools/pr_evidence.py`(PR #260, 병합): `pr_land.required_lab_invocations`를 같은 원격 실행기(`remote_pytest.run`)로 돌려 깨끗한 통과만 `land_cache.record`로 남긴다. 가드는 바꾸지 않았다. `passed_ids`가 `PASSED <id>` 줄을 요구해 실행 때만 `-rA`를 붙이고 기록 argv는 원래대로 둔다.
- `pr_land --evidence`(PR #266): 증거 생성을 같은 명령에 넣고, 활성화된 publishOnly 클론에서는 자기 push에만 `ROSY_PUSH_REASON="pr_land D-1055 <세션>"`을 넣는다. backlog 거부는 로컬 main에 origin/main이 모르는 커밋이 있을 때만 한다.
- `fix/pr-land-ci-entry-split`: 혼합 호출을 CI 항목별로 나눠, 실제로 CI에서 못 도는 부분(OMX 어댑터, 브라우저, 환경 토큰, lab_only 등)만 증거를 요구한다. 시험 파일 하나 바꾼 브랜치 2개가 1 → 0 호출이 됐다.
- 동결 중 큐 투입: GraphQL `dequeuePullRequest`로 뺐다(`gh pr merge --disable-auto`는 이미 큐에 든 PR을 빼지 못한다). `pr_land`의 drain 거부(`fix/pr-land-cutover-permission`), 서버 쪽 동결 게이트(`feat/server-cutover-gate`, 저장소 변수 + merge_group 검사), PR 본문 세션 기록과 `tools/merge_queue.py`(`feat/pr-land-attribution-queue`)를 준비했다.
- flake: 시험에서 타임아웃을 이벤트로 열도록 바꿨다(`fix/post-age-guard-flake`). 단언은 그대로다. merge queue는 HEADGREEN으로 바꿨다(바꾸기 전 설정은 작업 기록에 보관).

## 검증 근거

- `fix/post-age-guard-flake`에서 증거 생성 전 `pr_land --dry-run` 거부, 생성 후 통과(원격 271 passed).
- 첫 PR #260: 생성 → 병합 13분(CI 통과 즉시 자동 큐 등록 6분, merge_group 7분). 이전 경로는 첫 큐 → 로컬 착지 p50 1.9시간·p90 12.8시간(11-19) + 게시 PR(#257 82분).
- `merge_queue.py list`는 가짜 실행기 시험을 통과했지만 실제 큐에서 `gh -q` 출력 끝 줄바꿈 때문에 실패했다. 고친 뒤 시험 가짜도 줄바꿈을 내도록 바꿨다.

## 다음에 적용할 조건

- 병합·게시 경로를 바꿀 때는 개방 전에 실제 브랜치 하나를 새 경로 끝까지(증거 → push 훅 → PR → 큐 → 병합) 돌린다. dry-run과 가짜 실행기 시험은 증거 생산자 부재, 설치된 훅, 실제 CLI 출력 형식을 보지 못한다.
- 옛 경로를 끄기 전에 옛 경로만 만들던 산출물(여기서는 `land_cache` 증거)이 무엇인지 목록을 만들고, 새 경로의 생산자를 먼저 둔다.
- 공유 설정 하나를 두 가드가 읽으면(`rosy.publishOnly`) 한쪽을 풀려고 설정을 지우지 않는다. 필요한 쪽에 좁은 예외를 둔다.
- 브랜치에서 `tools/hooks/pre-push`를 바꾸지 않는다. 바꿔야 하면 설치·push 순서를 따로 정한다.
- 동결은 서버 쪽에서도 강제한다. 지시문과 로컬 파일만으로는 공용 계정의 큐 등록을 막지 못한다.
- 시험의 타임아웃은 실제 시계로 경주시키지 않는다. merge_group의 flake 한 건은 PR 하나에 약 25분을 더한다.
