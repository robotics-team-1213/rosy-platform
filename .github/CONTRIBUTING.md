# 기여하기

새 팀원은 [인수인계](../docs/reference/handoff.md)로 지금 상황을 본다. 브랜치·커밋·PR·push 규칙을 한 장으로 모은 것은 [git으로 일하는 법](../docs/reference/git-workflow.md)이다. 작업 위치를 고른 뒤 해당 절차를 따른다.

| 작업 | 시작 문서 |
|---|---|
| 개인 클론 설정, 시험 PC 접속 불가 시 훅 예외 | [팀 가이드](../docs/reference/team-guide.md) |
| 실험실 공유 체크아웃에서 사람·에이전트가 작업 | [같이 하는 깃](../docs/reference/shared-checkout.md) |
| 최종 커밋 검토, 게시·CI·병합 | [PR 파이프라인](../docs/reference/pr-pipeline.md) |
| 작업 경로 분담, 동시 수정, 교대 | [팀 가이드 §3.6](../docs/reference/team-guide.md#36-동시-작업과-인수인계) |

작업 이슈에 담당 경로와 완료 조건을 적고, 바꿀 경로의 `AGENTS.md`와 [핵심 계약](../README.md#핵심-계약)을 읽는다. PR에는 검토·시험한 커밋 SHA와 실제 결과를 남긴다. 형식은 PR 템플릿을 따른다.

이 저장소는 공개다. 작성자는 자신의 GitHub 이메일을 사용하고, 비밀값·실제 장치 주소·계정은 커밋하지 않는다. 문서 작성 기준은 [D-777](../docs/adr/D-777-concise-human-agent-documentation.md), 구조·빌드·배포는 [개발 가이드](../docs/reference/developer-guide.md)를 본다.
