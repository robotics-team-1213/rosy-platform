# 정책의 DatasetManifest·Episode 파일 연결

D-449 Proposed 후속이다. 정책 원장의 dataset revision 참조를 실제 보존 파일과
교차검증하고 승격/후속 이력 조회의 전제 조건으로 둔다.

1. DatasetManifest 전체 FileRef 해시/크기를 검증한다. 실제 공통 Episode manifest
   revision 목록을 정확히 비교하고, Episode sources/streams/evidence의 모든 파일이
   dataset의 선언된 files 안에 같은 SHA/bytes로 포함되는지 검사한다.
2. X의 immutable snapshot과 SQLite 등록을 트랜잭션으로 보존한다. 복사 뒤에도
   같은 canonical metadata·실제 bytes를 재검증한다. source 변조는 복사본에 영향을
   주지 않으며 재등록은 idempotent다. 미등록·손상 dataset은 승격을 거절한다.
3. 실제 ACT dataset 6 Episodes/234 files를 등록하고 새 process에서 정책 참조와
   매칭한다. 누락 manifest/stream·미등록/손상 데이터의 거절과 기존 정책 회귀를 확인한다.
4. 독립 코드 리뷰·영향 guards·검증 기록을 남긴다. 원본 sample body의 profile
   validator 이동(Q6), 라벨/독립 과제 진위, owner/rollback/Fleet는 별도 후속이다.
