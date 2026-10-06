# Contributing

새 팀원은 [팀 가이드](../docs/reference/team-guide.md)를 위에서 아래로 따라 한다. 첫날 설정, 공유 범위, 이슈에서 머지까지의 명령, 맡을 일이 거기 있다.

요약:

1. `main`에서 `<type>/<topic>` 브랜치 (`feat` `fix` `refactor` `docs` `uiux`)
2. 고칠 경로의 `AGENTS.md`와 관련 ADR을 먼저 읽는다 — 계약: [README 「핵심 계약」](../README.md#핵심-계약)
3. `python tools/harness/rosy_harness.py affected --base origin/main --run`
4. 내가 바꾼 파일만 `git add`, push (pre-push 훅이 lint + 빠른 시험)
5. PR → CI → **Squash and merge**

클론 직후 `bash tools/hooks/install.sh`로 훅을 설치하고, git 작성자를 자신의 GitHub 이메일로 설정한다.
비밀값·실제 로봇 주소는 커밋하지 않는다 — 이 저장소는 공개다.
구조·빌드·시뮬·테스트는 [개발 가이드](../docs/reference/developer-guide.md).
