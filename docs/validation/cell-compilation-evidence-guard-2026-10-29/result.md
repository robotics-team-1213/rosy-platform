# 공정 컴파일 검증 기록의 공개 식별자 결속

2026-10-29. 공정 컴파일의 [기존 고정 기록](../cell-compilation-boundary-2026-10-29/result.md)을
보존하면서 착지 가드의 공개 식별자 판정을 보완했다. 실행·기하·장치 권한과 보안 검사 구현은 바꾸지 않았다.

## 재현과 수정

최신 main 병합 후보 commit `41bc33561eec0a7e72a8c8da3ebaad9f4a8d301e`의 원격 affected
실행에서 `test_no_secrets_in_tracked_files`가 검증 기록의 Git ID·artifact digest를
high-entropy-token으로 탐지했다. 단독 재실행도 실패했고 base main commit
`f3a56910754637c95194a7435263c1f29af70a58`에서는 통과해 착지 도구가 중단했다.
실패·취소한 묶음을 통과 근거로 사용하지 않는다.

`docs/validation/AGENTS.md`와 기존 공개 SHA 교훈에 따라 고정 기록을 재작성하지 않았다.
수정 commit `b05dc2c218db09dab93d4d6eda719826333f5aa8`은
`deploy/robot/pinky_pro/release/public_provenance.json`에 정확히 7개 record만 추가한다.
기존 259개 record와 순서는 그대로다. 각 항목은 파일 경로·UTF-8 한 줄 SHA-256·해당 값에
정확히 결속한다. Git 값 네 종류가 실제 commit 객체이고 artifact 값이 샘플 fixture의
`process_artifact_digest`와 같음을 직접 확인했고 독립 읽기 전용 reviewer도 확인했다.
범용 허용·matcher·임계값·credential 검사는 변경하지 않았다.

## 집중 원격 검증

```text
python tools/harness/rosy_harness.py affected --base HEAD^ --json | python tools/remote/remote_pytest.py --affected-json - --log-dir <external-log-dir>
python test/known_failures.py <external-log-dir>/run-1.txt
```

위 명령은 수정 commit b05dc2c218의 checkout에서 실행했다. 공식 runner가 배치한 AI-role
시험 PC에서 9개 대상 suite를 실행해 **318 passed, 0 skipped, 0 failed**와 runner exit 0을
확인했다. 대상에는 보안 가드·공개 provenance·harness·문서/모듈 배치·protocol alignment·
robot runtime 검사가 포함된다. 경고 42개는 기록하며 통과 수와 섞지 않는다.

로그 위치는 외부 scratch의 `rosy-cell-public-evidence-20261029/run-1.txt`다.
이 결과는 집중 가드 검증이며, 공정 전체의 재착지·공개 게시·CI·실물 수용을 대신하지 않는다.
기존 공정 생산 코드·양쪽 adapter·시험은 이전 검토와 동일하다.

CE: 해당 없음 — 기존 `git-ids-in-validation-records-need-the-commit-prefix-2026-10-07` 교훈의
고정 기록/exact-line provenance 절차를 적용했으며 새로운 일반 규칙이나 교훈을 추가하지 않았다.
