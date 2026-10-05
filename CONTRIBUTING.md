# Contributing

새 팀원은 [팀 가이드](docs/reference/team-guide.md)부터 읽는다. 첫날 설정, 공유 범위, 작업 영역이 거기 있다.

- 착수 순서: [README 「같이 하는 깃」](README.md#같이-하는-깃)
- 바꾸면 안 되는 계약: [README 「핵심 계약」](README.md#핵심-계약)
- 작업 규칙 전문: [AGENTS.md](AGENTS.md)

요약: `main`에서 `<type>/<topic>` 브랜치 → 관련 테스트 + `test/known_failures.py` 비교 → PR → CI → squash 머지.
클론 직후 `bash tools/hooks/install.sh`로 pre-push 훅을 설치하고, git 작성자를 자신의 GitHub 이메일로 설정한다.
비밀값·실제 로봇 주소는 커밋하지 않는다 — 이 저장소는 공개다.
