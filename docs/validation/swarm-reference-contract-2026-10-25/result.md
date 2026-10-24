# D-870 원본 자세 시각 공유 계약 검증

이 기록은 공유 모델과 순수 remaining helper만 검증한다. CORE/Fleet consumer·혼합 peer 관문·실물 운행을 구현 또는 수용했다는 기록이 아니다.

- RED `aa11139494`: 공식 원격 schema20개가 sampled_at 누락/무검증으로 실패했다. helper 시험은 예상한 새 모듈 ImportError로 수집되지 않았다. 이를35개 실행 실패로 계산하지 않는다.
- `22f8ca17b2`: 코드 구현 전에 큰 정수 overflow 거절 회귀를 추가했다.
- 구현 `6d79c46bf8`: PoseSample.sampled_at 선택 strict positive finite UTC field와30줄 leaf helper. 새 의존성이나 clock 품질 측정·deadline 실행 기능은 없다.
- 공식 원격 `contract-green/run-1.txt`: 신규58개(schema20/helper38)와 기존 protocol/schema/API pin을 합쳐86개 통과, skip0. FULL 착지 gate는 후속 공식 landing에서 수행한다.

외부 로그 root는 `%LOCALAPPDATA%/Temp/rosy-swarm-freshness/`다. pytest를 노트북에서 실행하지 않았다.

legacy payload는 sampled_at=None으로 남고 현재 시각으로 채워지지 않는다. bool·문자열·NaN/무한대·0/음수는 거절한다. helper는 두 endpoint의 UTC 오차가 각±50ms 안이라는 별도 운영 수용을 전제로100ms를 보수적으로 더하고 양수 remaining만 반환한다. 미래 경계·만료·너무 짧은 timeout·큰 정수·양쪽±50ms 조합을 검증했다. 이 전제를 직접 측정하거나 단순 NTPSynchronized로 입증하지 않는다.

API v1.316·app·관련 시험 pin은 공식 도구로 함께 갱신했다. D-870과 ADR Log에 계약을 기록하고, 충돌하던 protocol/AGENTS의 한 줄 버전 지침을 기존 API§7.7/schema header/정렬 시험과 일치시켰다. envelope1.0은 유지한다. 새 helper를 safety module/public pure anchor로 등록했다.

독립 `/root/time_sync_review`는 이 공유 계약과 보수적 계산만 승인했고 source에 범위를 제한한 Safety-Review trailer가 있다. 검토자는 pytest·장치를 실행하지 않았다. 기존 Swarm source의 의미 보존 추출 baseline `b29f3ff855`는 별도7개 suite에서137개 통과했다.

추출·새 consumer·capability·모노 시계 통합의 증거는 다음 기록으로 분리한다. NTP50ms·radio·재부팅·실물 정지·FIELD는 계속 미수용이다.

CE: 해당 없음 — 시계 전제·수식·호환성은 D-870과 경계 회귀에 직접 보존했다. 새 해결 교훈 문서를 중복 생성하지 않는다.
