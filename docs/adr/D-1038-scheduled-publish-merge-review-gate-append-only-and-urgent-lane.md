## D-1038 게시 PR 예약 병합, review-gate 추가 전용 면제, 긴급 차선

**Status:** Proposed (2026-11-17, 사용자가 세 게이트 변경을 승인함; 첫 실제 운영 관측 전)

잇는 결정: [D-889](D-889-cicd-integration-train-scheduled-publish.md)(게시는 명시적 FULL 착지 기록) · [D-868](D-868-local-main-first-merge-commit-publish.md)(로컬 main 먼저, merge commit 게시) · [D-441](D-441-site-stack-automatic-update.md)(서명자는 origin main의 녹색 CI만) · [D-1036](D-1036-publish-evidence-from-nightly-full.md)(야간 FULL 기록).

### 승인

2026-11-17 사용자가 아래 세 변경을 승인했다. 서명자 규칙은 바뀌지 않는다. 서명자는 origin main 위의 정확한 커밋에서 최신 `push`·`workflow_dispatch`·`schedule` 실행이 녹색일 때만 서명하며, **`merge_group` 실행은 받지 않는다**(D-441, `deploy/site/auto_sign_candidates.py`).

### 결정

1. **게시 PR 예약 병합.** `publish_main.py --merge-when-green auto --apply`가 열린 `publish/main-*` PR이 정확히 하나일 때 그 PR을 병합한다(없으면 종료 0, 여럿이면 종료 7). 검사는 그대로다: mergeable, `ci-result` SUCCESS, head의 녹색 FULL 기록, `--match-head-commit`. 닫기·다시 열기·force push는 없다. Windows 예약 작업은 `tools/register_publish_merge_task.ps1`이 등록하며(이 저장소는 등록하지 않는다, 운영자가 실행) 병합 뒤 로컬 main 역동기화는 기존 안내대로 사람이 한다.
2. **review-gate 추가 전용 면제.** `.github/review-gate.sh`는 `docs/logs.md`, `docs/index.md`, `docs/reference/ROSY ADR Log.md`, `tools/harness/adr_gaps.txt`를 PR이 **삭제한 줄이 0개**일 때만 겹침 계산에서 뺀다(GitHub 파일 목록의 `deletions`). 한 줄이라도 고치거나 지우면 이전처럼 센다. 게시 PR 전체를 면제하지 않는다.
3. **긴급 차선.** `tools/urgent_lane.py`: 시작은 `worktrees.py new --from origin/main --urgent`(그 기반만 "main에 아직 없음" 거절을 건너뜀, 낡은 이력 검사는 유지). 커밋 뒤 `evidence`가 origin/main..HEAD의 영향 시험과 `test/browser_scope.py`가 매핑한 브라우저 파일(`ROSY_RUN_BROWSER_TESTS=1`)을 시험 PC에서 돌려 해시가 묶인 증거 파일을 남긴다. `land`는 `tools/land.py --urgent`로 로컬 main에 착지한다. `publish`는 착지로 main이 섞이기 전 증거 커밋을 `urgent/<topic>-<날짜>`로 push하고 merge commit PR을 연다(기본 dry run, `--apply`로 실행, 커밋 30개 초과 거절). `urgent/` PR 병합은 같은 검사를 쓰되 FULL 기록 자리에 그 증거 파일을 둔다.

### 바꾸지 않는 것

`publish_evidence.py`의 검사, known_failures 의미, 브라우저 범위 축소 금지, 서명 이미지·origin main·녹색 CI 규칙, squash·rebase 금지, 검토 에이전트 규칙.

### 검증

`test/test_publish_main.py`(auto), `test/test_review_gate_script.py`(추가만 면제, 한 줄 수정은 겹침), `test/test_urgent_lane.py`(가짜 git·gh)를 시험 PC에서 돌렸다. 실제 GitHub·예약 작업·`worktrees.py --urgent`의 실저장소 동작은 아직 관측하지 않았다.
