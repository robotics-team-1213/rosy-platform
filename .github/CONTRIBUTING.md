# Contributing

새 팀원은 [팀 가이드](../docs/reference/team-guide.md)를 위에서 아래로 따라 한다. 첫날 설정, 공유 범위, 이슈에서 머지까지의 명령, 맡을 일이 거기 있다. 훅과 머지에 대한 설명이 이 문서와 다르면 이 문서와 [D-762](../docs/adr/D-762-main-gateway-pull-request-merge-queue.md)가 맞다.

## 지금 main에 들어가는 길 (2026-10-14 기준)

- **팀원.** `main`에서 브랜치를 내고 PR을 연다. `main`에는 직접 push할 수 없다. 머지는 **Squash and merge**다. 저장소 설정이 지금 squash만 허용한다.
- **실험실 PC의 에이전트 세션.** 공유 체크아웃의 로컬 `main`에 `tools/land.py`로 착지하고(lint, 변경 범위 시험, `--ff-only`), 관리자 계정이 그 `main`을 origin에 push한다. 이것은 이행 경로이고 목적지가 아니다. 절차는 [같이 하는 깃](../docs/reference/shared-checkout.md)이다.
- **서버는 아직 CI 통과를 요구하지 않는다.** PR과 `main` push마다 `ci` 워크플로가 돌지만 필수 검사로 걸려 있지 않아서, 적색인 PR도 머지할 수 있다. 녹색을 확인하고 머지하는 것은 지금은 머지하는 사람의 일이다.

## 정해진 방향

모든 변경이 PR로 들어가 merge queue와 auto-merge를 거치고, 공유 로컬 `main`은 없어진다. 여섯 단계(0–5)로 적용한다. 필수 검사, merge queue, 관문 경로의 code owner 승인, 병합 방식 변경은 단계 3이고 아직 적용되지 않았다. 단계와 이유는 [D-762](../docs/adr/D-762-main-gateway-pull-request-merge-queue.md)에 있다. 단계가 적용되면 이 문서를 그때 고친다.

## 실험실 PC 없이 오늘 하는 일

1. `main`에서 `<type>/<topic>` 브랜치 (`feat` `fix` `refactor` `docs` `uiux`)
2. 고칠 경로의 `AGENTS.md`와 관련 ADR을 먼저 읽는다 — 계약: [README 「핵심 계약」](../README.md#핵심-계약)
3. `python tools/harness/rosy_harness.py lint`, 그리고 `python tools/harness/rosy_harness.py affected --base origin/main --run`. 자기 PC에서 pytest를 돌려도 된다(D-584 개정). 실험실 노트북에서는 돌리지 않는다.
4. 내가 바꾼 파일만 `git add`, push. pre-push 훅(`bash tools/hooks/install.sh`)은 시험을 실험실 시험 PC로 보내므로, 그 PC에 닿지 못하는 clone에서는 push를 막는다. 훅을 정적 부분과 시험 부분으로 나누는 일은 D-762 단계 4이고 아직 되지 않았다. 그때까지는 3번을 손으로 돌린 뒤 `git push --no-verify`로 올린다.
5. PR → CI 녹색 확인 → **Squash and merge**. 변경을 들이는 증거는 PR의 CI다.

git 작성자를 자신의 GitHub 이메일로 설정한다.
비밀값·실제 로봇 주소는 커밋하지 않는다 — 이 저장소는 공개다.
구조·빌드·시뮬·테스트는 [개발 가이드](../docs/reference/developer-guide.md).
