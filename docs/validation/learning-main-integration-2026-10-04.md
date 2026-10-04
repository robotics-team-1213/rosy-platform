# 학습 루프와 D-427 main 통합 후보

학습 HEAD `2a5109db7`에 main `dd159ab33`을 별도 worktree에서 병합했다.
공유 main과 기존 학습 worktree는 변경하지 않았다. 이 기록은 소스 통합 검증이며
전체 학습 목표 완료, 상시 서비스 설치, 장치 배포나 현장 수용을 뜻하지 않는다.

충돌한 파일 9개는 양쪽 의도를 보존했다. main의 이동된 safety 지정과
OwnerPolicySession 지정을 함께 유지했고, learning CI suite와 D-449 Proposed
상태를 유지했다. D-446/447이 도착한 뒤 임시 gap을 제거했다. 학습 코드와 시험의
경로 참조 10개 파일을 D-427 위치에 맞췄다. 기존 main 로그의 bytes를 그대로
접두부로 보존하고 학습 로그를 추가했으며, 양쪽 부모의 append-only 검사도 통과했다.

실행 결과:

- 공통 Episode/registry/OMX/Pinky/owner 검사: 211 passed, 14 skipped.
- perception 전달·watch·journal·recording·human review 검사: 235 passed, 14 skipped.
- architecture/safety/selector/harness 첫 실행: 117 passed, 1 failed.
  이동 경로 치환이 main의 의도적인 legacy 검사 예외 목록을 변경한 오류였다.
  해당 목록을 main bytes로 복원한 뒤 실패한 시험 1개가 통과했다.
- 독립 리뷰: architecture/selector/owner 131 passed,
  OMX curation/registry 90 passed, 1 skipped; 중요 결함 없음, APPROVE.
- harness lint: 0 errors, 8 warnings. 경고는 기존 모듈 검증 시점 관련이다.

Windows의 skip은 Linux·영상/학습 도구가 필요한 시험을 대체하지 않는다.
fast/affected gate와 원격 CI는 별도로 실행·기록한다. 실제 관리자 설치,
현재 로봇 HOLD 소유자와의 조율, shadow/rollback, 사람 정답 라벨과
인증된 owner/Fleet 결과 수용은 여전히 남아 있다.

비공개 실행 로그는 `X:/DevTemp/rosy-learning-audit-20261004/merge-learning-*.txt`에 있다.
