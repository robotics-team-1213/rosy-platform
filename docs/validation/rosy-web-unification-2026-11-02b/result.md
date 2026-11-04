# 웹 통합 증거의 Git 무결성 필드 명확화

[원래 동결 결과](../rosy-web-unification-2026-11-02/result.md)의 실행 관측과 SHA 값은 유지한다. 이 후속은 증거 JSON의 필드 이름만 다룬다.

131087f3b1의 문서 영향 검사에서 320 passed, 1 failed였다. `test_no_secrets_in_tracked_files`가 `original`, `source`, `head`, `unchanged_test_blob`처럼 무결성 의미가 없는 필드의 공개 40자리 Git OID를 high-entropy-token으로 분류했다. 실제 자격 증명·개인 키·비밀 토큰이 아니며, 독립 검토가 보존한 73개 원본 로그 해시와 시험 blob을 이미 대조했다.

- `revisions`의 각 phase 값은 명시적 `commit` 필드로 묶었다.
- 전체 Git 커밋을 담는 `source`/`head`는 `source_revision`/`head_revision`으로 명명했다.
- `unchanged_test_blob`은 `unchanged_test_blob_oid`로 명명했다.

커밋·blob·SHA-256·카운트·관측 결과·실패 이력은 바꾸지 않았다. 실행·UI·인증·안전 코드와 secret scanner·검사 제외 목록·public provenance도 바꾸지 않았다. 이 표현은 기존 scanner의 공개 무결성 문맥 규칙을 따른다. 두 문서의 실제 scanner 함수를 이용한 정적 검사에서 발견0이며, committed HEAD의 문서 영향 원격 재검증 결과는 별도 실행 영수증으로 남긴다. 이 정적 관측만으로 원격 검증 성공을 주장하지 않는다.

CE: 해당 없음 — 필드 의미와 허용 문맥은 기존 scanner 코드·시험으로 설명된다. 운영 배포·실물 수용은 미실행이다.
