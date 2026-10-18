# Contributing

새 팀원은 [인수인계](../docs/reference/handoff.md)로 지금 상황을 보고, [팀 가이드](../docs/reference/team-guide.md)를 위에서 아래로 따라 한다. 브랜치·커밋·PR·push 규칙을 한 장으로 모은 것은 [git으로 일하는 법](../docs/reference/git-workflow.md)이다. 첫날 설정, 공유 범위, 이슈에서 머지까지의 명령, 맡을 일이 거기 있다. 훅과 머지에 대한 설명이 이 문서와 다르면 이 문서와 [D-762](../docs/adr/D-762-main-gateway-pull-request-merge-queue.md)가 맞다.

## 지금 main에 들어가는 길 (2026-10-16 GitHub 설정 확인)

- **팀원.** `main`에서 브랜치를 내고 PR을 연다. `main`에는 직접 push할 수 없다. 머지는 **Squash and merge**다. 저장소 설정이 지금 squash만 허용한다.
- **실험실 PC의 에이전트 세션.** 공유 체크아웃의 로컬 `main`에 `tools/land.py`로 착지하고(lint, 변경 범위 시험, `--ff-only`), 관리자 계정이 그 `main`을 origin에 push한다. 이것은 이행 경로이고 목적지가 아니다. 절차는 [같이 하는 깃](../docs/reference/shared-checkout.md)이다.
- **서버는 아직 CI 통과를 요구하지 않는다.** PR과 `main` push마다 `ci` 워크플로가 돌지만 필수 검사로 걸려 있지 않아서, 적색인 PR도 머지할 수 있다. 녹색을 확인하고 머지하는 것은 지금은 머지하는 사람의 일이다.

현재 필수 승인 수는 0이고 code owner 승인도 필수가 아니다. `.github/CODEOWNERS`의 리뷰 요청과 서버의 승인 강제는 다르다. merge queue와 auto-merge는 아직 적용되지 않았다. 설정 확인 방법과 후속 항목은 [팀 가이드 §8](../docs/reference/team-guide.md#8-협업-설정-확인과-문서-유지)에 있다.

## 정해진 방향

모든 변경이 PR로 들어가 merge queue와 auto-merge를 거치고, 공유 로컬 `main`은 없어진다. 여섯 단계(0–5)로 적용한다. 필수 검사, merge queue, 관문 경로의 code owner 승인, 병합 방식 변경은 단계 3이고 아직 적용되지 않았다. 단계와 이유는 [D-762](../docs/adr/D-762-main-gateway-pull-request-merge-queue.md)에 있다. 단계가 적용되면 이 문서를 그때 고친다.

## 실험실 PC 없이 오늘 하는 일

1. [작업 이슈](https://github.com/robotics-team-1213/rosy-platform/issues/new/choose)에 담당자, 수정 경로, 완료 조건을 적고 겹치는 작업을 확인한다. 개인 클론의 최신 `origin/main`에서 `<type>/<topic>` 브랜치를 만든다 (`feat` `fix` `refactor` `docs` `uiux`).
2. 고칠 경로의 `AGENTS.md`와 관련 ADR을 먼저 읽는다 — 계약: [README 「핵심 계약」](../README.md#핵심-계약)
3. `python tools/harness/rosy_harness.py lint`, 그리고 `python tools/harness/rosy_harness.py affected --base origin/main --run`. 자기 PC에서 pytest를 돌려도 된다(D-584 개정). 실험실 노트북에서는 돌리지 않는다.
4. 내가 바꾼 파일만 `git add`, push. pre-push 훅(`bash tools/hooks/install.sh`)은 시험을 실험실 시험 PC로 보내므로, 그 PC에 닿지 못하는 clone에서는 push를 막는다. 훅을 정적 부분과 시험 부분으로 나누는 일은 D-762 단계 4이고 아직 되지 않았다. 그때까지는 3번을 손으로 돌린 뒤 `git push --no-verify`로 올린다.
5. PR → CI 녹색 확인 → **Squash and merge**. 변경을 들이는 증거는 PR의 CI다.

훅 예외는 **실험실 시험 PC에 닿지 못하는 개인 클론의 주제 브랜치 push**에만 쓴다. lint·관련 시험·생성 기록·공개 범위를 먼저 확인하고, PR에 예외 이유와 실행 결과를 남긴다. lint나 시험 실패를 넘기는 용도로 쓰지 않는다. 실험실 공유 체크아웃은 [기존 절차](../docs/reference/shared-checkout.md)를 그대로 따른다.

동시 작업은 [팀 가이드 §3.6](../docs/reference/team-guide.md#36-동시-작업과-인수인계)에 따라 경로를 나누고, 같은 파일을 고쳐야 하면 이슈에서 통합 담당자와 순서를 정한다. PR에는 연결 이슈, 맡은 경로, 의존 PR, 검증한 커밋과 결과를 남긴다. 인수인계할 때는 미완료 항목과 다음 행동도 적는다.

git 작성자를 자신의 GitHub 이메일로 설정한다.
비밀값·실제 로봇 주소는 커밋하지 않는다 — 이 저장소는 공개다.
구조·빌드·시뮬·테스트는 [개발 가이드](../docs/reference/developer-guide.md).
