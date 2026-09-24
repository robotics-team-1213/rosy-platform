## D-216 CAP-001 예시의 `protocol_version` 오타를 고친다 — `"1"`이 아니라 `"1.0"`이다

**Status:** Accepted (2026-09-25). SRS:230을 `"1.0"`으로 수정함.

**Context:**

1. `docs/spec/ROSY CORE SRS.md:230`의 CAP-001 예시는 `"protocol_version": "1"`이다.
2. API Ref §9.1(`ROSY API & Protocol Reference.md:647`)과 `schemas.py:25`
   (`PROTOCOL_VERSION = "1.0"`)는 `"1.0"`이다. envelope `protocol_version` 1.0은 전 문서에서 일관된다.
3. SRS:234는 "정확한 스키마 정의는 API Ref를 따른다"고 스스로 위임하므로, 이 불일치에서는 API Ref가 우선한다.

**Decision:** SRS:230을 `"protocol_version": "1.0"`으로 고친다. API-002 Corrective(문서가 틀리게 적혀 있던 것을
구현과 맞춤)에 해당하므로, API Ref 변경 이력에 `1.0(≠1)` 기록을 남긴다. 스키마·코드 변경 없음.

**Alternatives:** `"1"`을 정본으로 삼는 안 — `schemas.py`·API Ref·envelope 전역과 충돌하고 마이너 버전 표기(PRT-006
`MAJOR.MINOR`)에도 어긋난다.

**Consequences:** 엄격한 버전 비교를 하는 소비자는 `"1.0"`으로 고정된다. 런타임 동작 변화 없음.

**Validation:** `grep '"protocol_version": "1"'`가 SRS에서 사라지고, 관련 계약 시험이 그대로 통과한다.
