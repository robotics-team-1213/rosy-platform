# D-707 판정 후보 snapshot과 범위가 고정된 승인 receipt

**Status:** Accepted (2026-10-12, source contract)

기존 `learning/registry/policy` 소유자에서 reasoning 후보의 영속 보관과 외부 보정 승인·폐기를 구현한다. 기존 Registry의 출력 드라이브·신뢰 key/kind 검사와 FULL/BEGIN IMMEDIATE 트랜잭션을 재사용한다. 행동 정책 tables와는 별도의 reasoning tables/hash chain을 같은 SQLite에 둔다. 새 서비스나 학습/운영 writer는 없다(D-427·D-449·D-706).

후보 생성·전체 프로파일/domain·독립 자료 재계산은 기존 Decision 순수 evaluation의 명시적 validator 포트가 맡는다. registry는 운영 Decision을 import하지 않는다. 후보 JSON은 immutable snapshot으로 복사하고 매 읽기에서 bounded JSON·seal·revision과 validator 결과를 다시 확인한다. 동일 후보 등록은 history를 늘리지 않는다. HOLD·FAIL 후보는 보관할 수 있지만 승인하지 않는다.

외부 검증자의 HMAC-SHA256 receipt는 candidate revision·전체 profile SHA·domain·실제 CalibrationArtifact digest·검증 종류·기대 원장 head·판정을 함께 서명한다. 설치된 최소 32-byte key와 kind scope만 신뢰한다. 승인/폐기는 원장 head CAS와 정확한 상태 전이로 처리하고, 모든 읽기에서 snapshot·상태 table·event chain과 receipt를 다시 검증한다. 위조·재제출·다른 자료·동시 전환·변조는 승인 자료를 제공하지 않는다.

approved_artifacts는 승인된 보정 revision→digest만 공급한다. 같은 revision의 다른 digest를 동시에 승인하지 않는다. 폐기 후에는 해당 artifact가 승인 map에서 빠진다. offline 보정 승인은 action admission·현장 수용·운영 current/previous pointer가 아니다. 사건별 revision 보존·새 사건 적용·승격/복귀와 실제 Model PC 검수·AI PC runtime·현장 증거는 [lifecycle 계획](../plans/2026-10-12-reasoning-profile-lifecycle.md)의 후속 작업이다.
