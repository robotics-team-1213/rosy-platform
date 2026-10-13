# D-684 사건 예산 원장 구현 계획

범위는 Fleet의 opt-in 부모/시도 원장이다. 기존 D-640 원장, 제공자 활성화, 관측 실행, 장치 명령은 포함하지 않는다.

1. 부모 사건을 subject/case, owner, 프로파일 전체 SHA-256, 정책 revision에 고정한다. 전체 deadline은 시작 후 120초 이내, 모델 호출과 관측은 각각 최대 8회, 비용은 최대 10 USD다. 값은 호출자가 명시하며 기본 활성화는 없다.
2. 동일 SQLite 정책과 `BEGIN IMMEDIATE`로 실행 전 예산을 예약한다. 금액은 USD 마이크로 단위로 보수적으로 계산한다. 새 관측 revision·재시작·프로파일 교체로 부모 값을 바꾸지 않는다.
3. 예약자만 RESERVED를 SUBMITTING으로 전환한다. 외부 효과는 이 전환이 성공한 뒤에만 가능하다. 동일 시도는 재발행하지 않는다. 복구는 RESERVED와 SUBMITTING 모두 UNKNOWN으로 보존하고 부모를 HOLD한다.
4. 완료 비용이 예약을 초과하면 실제 비용을 기록하고 HOLD한다. 비용 불명은 UNKNOWN이며 예약을 환급하지 않는다. 결과가 UNKNOWN이어도 알려진 실제 비용은 지출로 기록하고 미사용 예약을 남겨 지출+예약이 최소 기존 예약을 보존하도록 한다. receipt는 고정 필드의 1 KiB 이하 요약만 저장한다.
5. 정상은 호출·관측 0회 상태에서 NOT_NEEDED로 기록할 수 있다. 성공 종결 API는 제공하지 않는다. 실제 readback과 종결 증명은 후속 worker 계약에서 연결한다.
6. 원격 RED/GREEN에서 동시 예약, 재시작, 새 revision, 비용 초과/불명, deadline, 다른 owner/profile, 재발행 금지를 확인한다. source·원격 시험과 운영 호출·현장 수용은 별도 증거다.

구현 경로는 `fleet.incidents.automation.contract`, `fleet.incidents.automation.store`다. 실제 worker/catalog와 인수 outbox 연결은 root 통합 단계에서 별도로 처리한다.

## 책임 단위 분리

서버 부모에 추가한 첫 구현 238줄은 부모 성장 한도를 넘어 등록된 책임 단위로 분리한다. `fleet/incidents/automation`은 실제 Python 하위 패키지이며 지속 사건 원장과 후속 관측/worker 생명주기를 소유한다. 기존 `fleet/incidents/handoff.py`와 `notifications.py`의 사람 인수·팀 전달 360줄 책임에 판단/자동 루프를 섞지 않는다. 기존 server 경로는 남기지 않고 모든 소비자가 새 경로를 직접 import한다. 같은 DB와 SQLite 정책을 사용하고 프로세스·권한·활성화는 추가하지 않는다.

독립 accounting 편집자 `responsibility_review`가 dated split plan과 nested SIZE_UNITS/VERDICTS를 등록하고 부모·incidents·automation을 중복 없이 재측정한다. 현재 원장 실측은 `__init__.py`를 포함한 241줄이며 기존 +150 allowance와 임계값을 바꾸지 않는다. 이후 관측 port와 사건 worker는 같은 책임 단위에서 성장 한도를 다시 검증한다. 실제 측정·독립 검토·원격 구조 시험이 끝나기 전 착지하지 않는다.
