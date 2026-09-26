## D-271 사이트 Fleet이 작업 순서를 소유하고 브로커는 실행 전달에만 쓴다

**Status:** Accepted (2026-09-26, architecture only). 작업 스케줄러나 RabbitMQ가 구현·배포되었다는 뜻이 아니다. 장비/현장 수용과 자동 실행 허가는 별도다.

**Context:** Ubuntu 현장 호스트의 Fleet API는 수동 navigation을 SQLite `fleet_tasks`와 append-only history에 기록한 뒤 CORE REST로 보낸다. `FleetConsole._queued`는 경로 충돌 시 대기하는 프로세스 메모리이며 영속적인 범용 작업 큐가 아니다. `/api/fleet/do`는 허용된 동사를 API 호출로 바꾸지만 복합 작업의 전체 계획·완료를 추적하지 않는다. Vision은 현재 최신 프레임을 처리해 작은 sighting만 Fleet에 보낸다. 관제 PC와 RTX worker, 향후 로봇암/Pinky가 늘 때 사용자/API는 목표를 요청하고 Fleet이 적격성·자원·순서를 결정해야 한다. D-59와 D-269는 로봇 내부 DDS, 사이트 REST/WSS, 영상 계약을 분리한다.

**Decision:**

1. **Fleet이 해석과 스케줄링을 소유한다.** 사용자/API의 구조화된 목표를 검증·감사하고, 서버 정책으로 우선순위·장비 적합성·동시 실행 제한·경로/자원 충돌을 결정한다. 브로커의 전달 순서나 클라이언트가 제출한 우선순위 값을 권한 판단으로 쓰지 않는다. Fleet은 미션 단계를 만들 수 있지만 경로 계획·속도·최종 정지·집기 안전은 장비 로컬 CORE/팔 제어기가 소유한다(D-12, D-59). 새 외부 verb나 필드는 이 ADR로 승인되지 않는다(D-18).
2. **첫 단계는 기존 SQLite의 영속 작업 원장을 확장한다.** 현재 task/history를 권위 있는 상태로 유지하고, 추후 `queued/reserved/dispatching`에 해당하는 스케줄링 상태, 장비별 단일 활성 작업 및 자원 점유, 만료·취소·공정성 정책을 명시적으로 구현한다. 기존 메모리 교통 대기열을 영속 작업 대기열로 간주하지 않는다. 저장 전/후 재시작·중복 요청 시험을 통과하기 전에는 큐의 복구를 주장하지 않는다.
3. **브로커가 필요해지면 사이트 내부 RabbitMQ를 첫 후보로 채택한다.** Fleet, RTX 영상 분석, 별도 실행 worker가 독립적으로 배치되고 DB polling/프로세스 결합이 실제 병목 또는 장애 전파를 만들 때 도입한다. 장비별·자원별 작업 큐를 분리하고 적은 수의 우선순위 등급을 사용한다. 단일 거대 우선순위 큐의 기아와 선취(prefetch)를 고려해 등급 간 공정성은 Fleet 스케줄러가 정한다. 브로커는 사이트 백엔드에만 두며 로봇/Pinky/폰에는 AMQP 자격 증명이나 브로커 주소를 배포하지 않는다. 현장 PC 한 대의 브로커는 고가용성 구성이 아니므로, 별도 호스트 다수와 복구 계획 없이 quorum queue를 HA 증거로 부르지 않는다.
4. **안전과 의미론은 큐보다 우선한다.** e-stop은 로봇 로컬 안전 경로를 유지한다. 운영자 stop/cancel은 일반 작업 대기열에 갇히지 않는 별도 인증된 CORE 명령 경로를 사용하되 네트워크 장애 시 즉시 정지를 보장한다고 주장하지 않는다. 현재 자동 정책 제출은 D-268이 수용되기 전까지 `HOLD`다. 영상 원본·DDS 센서 스트림·`cmd_vel`을 작업 큐에 넣지 않는다. Vision에는 제한된 분석 작업 또는 파생 증거만 전달하고 실시간 프레임은 최신 프레임 정책을 따른다.
5. **DB가 사실의 원장이고 메시지는 재전달될 수 있다.** 작업 ID, 요청자, idempotency key, 목표/제약, 장비/자원, 증거 출처·시각·revision, 만료시각, 정책 등급, 상태 이력, 명령 receipt와 최종 결과를 구분한다. DB와 브로커를 함께 사용할 때 transactional outbox/동등한 복구 가능한 발행 절차와 publisher confirm을 요구한다. consumer ACK는 기록 또는 안전한 인수 후에만 보낸다. 브로커 중복 전달이나 REST timeout 뒤 물리 명령을 무조건 재실행하지 않는다. 장비 수락 여부가 모호하면 `UNKNOWN`으로 보존하고 조회·현장 확인으로 조정한다. PRT-004 `correlation_id`/최종 결과 추적은 D-170/D-177의 중앙 Fleet 활성화 변경에 포함하며, 현재 사이트 Fleet이 구현했다고 표시하지 않는다.
6. **작업 우선순위 기본 방향은 운영자 요청 > 승인된 자동 작업 > 배경 분석이다.** 서버만 등급을 부여한다. 긴 작업의 기아 방지, 장비 점유, 중단 가능 지점, 기한 초과 동작과 자동/수동 충돌 정책은 구현 전에 작업별 계약으로 고정한다. 이미 수행 중인 물리 동작은 더 높은 우선순위 메시지가 들어왔다고 자동 선점하지 않는다.

**Alternatives:**

- *지금 RabbitMQ를 필수 서비스로 추가*: 현재 단일 Fleet/SQLite 원장·로컬 Vision 구성에서 복구·보안·백업 운영면이 늘고, 물리 명령의 중복 실행 문제도 해결하지 못한다. worker 분리 필요와 장애 시험이 확인되면 도입한다.
- *Kafka를 실행 큐로 사용*: 파티션별 순서와 재생 가능한 이벤트 로그에는 맞지만, 소수 장비의 자원 점유·작업 중요도·취소는 Fleet이 별도로 구현해야 한다. 장기간 다중 소비자 이벤트 분석 요구가 생기면 재평가한다.
- *NATS JetStream*: 내구성 있는 작업/이벤트 후보이나 priority groups는 소비자 배분 정책이며 작업 자체의 우선순위를 대체하지 않는다. 현장 fan-out·재생 요구가 RabbitMQ 작업 라우팅보다 커지면 비교한다.
- *Redis Streams/MQTT를 단일 제어 버스로 사용*: 각각 별도 pending/reclaim·영속 설정 또는 장비 pub/sub 계약이 필요하다. 현재 CORE REST/WSS와 별도 Fleet 원장을 대체하지 않는다.

**Consequences:** [사이트 작업 스케줄링 설계](../plans/2026-09-26-site-task-scheduling-and-broker-design.md)를 구현 기준으로 삼는다. D-59의 “로봇에 사이트 브로커 없음” 및 D-269의 장비별 REST/WSS 계약을 유지한다. 이 ADR은 D-267/D-268의 자동 실행 게이트, D-170/D-177의 명령 추적 시기를 변경하지 않는다. RabbitMQ 도입 시 큐의 지속성·한계·모니터링·백업/복원·접근 권한·버전별 우선순위 동작을 별도 수용한다.

**Validation / Transition:** 먼저 SQLite 기반 요청/대기/점유/재시작/중복/만료/stop 우회와 API 상태 의미를 SOURCE·LOCAL에서 검증한다. RabbitMQ 도입 변경에서는 outbox→confirm→consumer ACK, worker crash/재전달, broker 중단/복구, 중복 물리 명령 금지, backlog/기아, 전원 복귀를 Docker LOCAL과 실제 Ubuntu 호스트에서 검증한다. 실제 CORE/팔/Pinky 동작과 자동 정책은 장비별 DEVICE/FIELD 게이트를 별도로 통과해야 한다.

**Sources:** [RabbitMQ reliability](https://www.rabbitmq.com/docs/reliability), [RabbitMQ priority queues](https://www.rabbitmq.com/docs/priority), [RabbitMQ quorum queues](https://www.rabbitmq.com/docs/quorum-queues), [Kafka design](https://kafka.apache.org/design/), [NATS JetStream consumers](https://docs.nats.io/learn/jetstream/pull-consumers), [NATS priority groups](https://docs.nats.io/learn/jetstream/priority-groups).
