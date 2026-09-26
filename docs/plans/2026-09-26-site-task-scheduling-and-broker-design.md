# 사이트 Fleet 작업 스케줄링과 메시지 브로커 설계

작성일: 2026-09-26
상태: D-271 Accepted 설계. 스케줄러·RabbitMQ는 미구현이며 자동 작업과 장비 수용은 HOLD.

관련: [D-271](../adr/D-271-site-fleet-task-scheduling-and-broker.md), [D-269](../adr/D-269-device-server-contracts-and-ros-boundary.md), D-12, D-59, D-170, D-177, D-267, D-268, [현장 배포](../../deploy/site/README.md).

## 목적과 현재 기준선

사용자/API는 허용된 **목표**를 요청하고 Fleet이 우선순위, 실행 장비, 자원 점유 및 단계 순서를 계산한다. 로봇 CORE는 받은 원자 goal의 항법·속도·안전을 실행한다. 영상 worker는 관측 증거를 만들며 집기/이동 권한을 얻지 않는다.

현재 `/api/fleet/do`의 `interpret()`는 정해진 verb를 변환하고 단계들을 순서대로 호출한다. navigation은 SQLite `fleet_tasks`에 `REQUESTED`를 먼저 남기고 CORE REST receipt에 따라 `ACCEPTED`·`FAILED`·`UNKNOWN`을 기록한다. `FleetConsole._queued`는 경로 충돌을 위한 메모리 대기열이다. 현재 구현에 작업 전반의 영속 우선순위 스케줄러, RabbitMQ 서비스, 복합 미션 완료 조정은 없다. 외부 API/schema의 새 이름을 이 설계만으로 생성하지 않는다.

## 책임과 흐름

```text
브라우저/외부 API ─HTTPS→ Fleet 접수·권한·중복 검사 ─transaction→ SQLite 작업 원장
                                                        │
                                               Fleet 정책 스케줄러
                                       (등급, 자원, 장비, 기한, 충돌)
                                                        │
                          1단계: DB-backed worker  ─────┤
                          분리 필요 시: outbox→RabbitMQ→worker
                                                        │
                                                     CORE REST
                                                        │
                                            로봇 ROS 2/DDS·로컬 안전
CORE WSS event/상태 ─────────────────────────────→ Fleet 상태 조정 → 웹 관제
천장 폰 WSS 영상 → Vision 최신 프레임 처리 → 파생 sighting → Fleet 표시·대조
```

| 소유자 | 결정·데이터 | 경계 |
|---|---|---|
| Fleet API/스케줄러 | 작업 접수, 감사, 정책 등급, 장비 적합성, 자원 예약, 순서, 실패 표시 | `cmd_vel`/DDS 생성 금지 |
| SQLite 작업 원장 | 현재 상태, 요청·증거 참조, append-only 이력, 복구 판단 | 브로커 ACK를 작업 완료로 저장 금지 |
| 선택적 RabbitMQ | 적격 작업을 독립 worker에 전달, backlog와 압력 분리 | 사용자·장비와 직접 연결하지 않음; 상태 원장 아님 |
| CORE/팔 로컬 제어 | 원자 goal 수락, 로컬 경로·동작·안전, 실제 완료 결과 | Fleet가 로컬 안전을 우회할 수 없음 |
| Vision worker | 제한된 프레임 처리와 증거 생성 | raw video/프레임별 이벤트를 작업 큐로 보내지 않음 |

## 작업 정책과 규약

1. **접수:** 인증된 요청에서 actor/source, idempotency key, 허용된 goal과 제약을 검증한다. 서버가 생성한 task ID와 저장된 요청 hash를 반환한다. 같은 actor/key/내용은 동일 작업을 반환하고 다른 내용은 충돌로 거절한다. 현행 공용 `site-console` token은 개인 사용자 식별이 아니므로 역할 기반 원격 실행은 D-267의 인증 계약을 먼저 충족한다.
2. **자격:** 로봇 capability/online, 지도·좌표계, 현재 점유, 경로 충돌, deadline, 증거 출처·age·map/calibration/model revision을 검사한다. 검증되지 않은 정책 증거는 `HOLD`이며 D-268 수용 전 자동 명령을 내지 않는다. 후속 로봇암/Pinky 명령은 각자의 media/action 계약과 DEVICE 검증 후에만 적격 후보가 된다.
3. **우선순위:** e-stop은 로컬 안전, 원격 stop/cancel은 대기 작업과 별도 즉시 요청 경로다. 일반 작업 후보 사이에서는 `operator` > 수용된 `policy` > `background` 기본 등급을 적용한다. 사용자가 임의 등급을 제출해 승격할 수 없다. 같은 등급은 접수 순서와 기한을 고려하고, 운영자가 정한 대기 상한·aging/할당량으로 낮은 등급의 기아를 관찰·완화한다. 구체 수치와 실행 중 선점 가능 여부는 작업별 수용 계획에서 고정한다.
4. **예약/실행:** 로봇마다 활성 모션 작업은 한 개로 제한하고, 팔·충전대·공유 통로는 명시적 자원 점유를 사용한다. 높은 등급도 이미 실행 중인 안전 동작을 브로커 전달만으로 선점하지 않는다. 단계 사이의 재계획/취소만 검증된 로컬 cancel 계약으로 수행한다. 장비가 offline 또는 busy면 작업을 보류하고 사유를 보여준다.
5. **상태:** `REQUESTED`, `HOLD`, `ACCEPTED`, `RUNNING`, `COMPLETED`, `FAILED`, `UNKNOWN`은 기존/목표 의미를 구분한다. 미래의 `QUEUED`·`RESERVED`·`DISPATCHING`은 **설계 후보**이며 아직 외부 계약/현행 `FleetTaskStore` 전이가 아니다. 구현 전에 D-18에 따라 API Ref와 공유 schema/테스트를 함께 갱신한다. REST receipt는 수락/거절에만 사용하고 실제 완료는 D-170/D-177 활성화 이후 검증된 CORE 최종 결과와 연결한다. 그 전에는 완료를 추정하지 않는다.
6. **메시지 최소 계약(내부 후보):** `schema_version`, `message_id`, `task_id`, `idempotency_key`, `actor/source`, `action/target`, `parameters`, `priority_class`(서버 계산), `expires_at`, `evidence_ref`와 측정 시각/revision, `event_seq`, `occurred_at`, `status/reason`. 외부 API에 필드를 추가하거나 기존 PRT Envelope를 확장하는 결정은 아니다. 인증 토큰·원본 영상·전체 DDS 메시지는 넣지 않는다.

## 저장과 전달 장애

- **1단계:** SQLite transaction으로 요청+history를 원자 기록하고 단일 스케줄러가 적격 작업을 선택한다. 재시작 뒤 `REQUESTED`/전달 중 작업은 장비 상태를 재조회하기 전 자동 발행하지 않는다. 현재 구현의 `recover_interrupted_requests()`는 `UNKNOWN`으로 보존한다.
- **RabbitMQ 단계:** 작업/상태 원장은 SQLite에 남긴다. DB outbox 행과 작업 상태를 같은 transaction에 저장하고 publisher가 RabbitMQ confirm을 받은 뒤 발행 기록을 진전시킨다. 브로커 복구/중복 발행에도 같은 task ID로 소비자를 멱등하게 만든다. 물리 명령 발행 후 ACK 상실·REST timeout은 중복 실행 위험이 있으므로 자동 재하달하지 않고 `UNKNOWN`+조회/운전자 확인으로 넘긴다. consumer ACK는 장비 작업 완료가 아닌, 해당 전달을 안전하게 기록·인수한 시점의 확인이다.
- **격리:** 장비/자원 및 업무 등급에 따라 소수의 큐를 나눠 모션 worker와 영상 분석 worker를 분리한다. worker 동시성·prefetch·최대 backlog·TTL·실패 보관/DLQ·재처리 권한을 측정으로 정한다. RabbitMQ의 우선순위는 *대기 중인* 메시지 선택에만 적용되며 이미 선취된 작업과 실행 중 물리 동작을 역전시키지 않는다. 단일 Ubuntu 호스트에 컨테이너 하나를 더 올려도 호스트 장애에 대한 HA는 생기지 않는다.
- **복구:** 브로커 또는 RTX worker가 꺼져도 CORE의 로컬 안전은 유지한다. 새 사이트 작업은 `HOLD` 또는 명확한 접수 실패로 표시하고, 오래된 영상 증거를 재사용하지 않는다. Fleet/DB 장애와 broker 장애를 따로 감시한다.

## 도입 순서와 검증 기준

| 단계 | 작업 | 완료 근거 |
|---|---|---|
| 0. 계약 | 기존 task/API/PRT와 D-170/D-177/D-268 대조; 등급·자원·취소·만료·완료 의미를 시험 벡터로 고정 | API/schema 동시 개정 여부 결정; SOURCE 계약 시험 |
| 1. SQLite 스케줄러 | 영속 대기 상태와 단일 dispatcher, 장비/자원 예약, 수동·자동 공통 검증(자동은 `HOLD`) | 중복·재시작·충돌·기아·stop 우회·UNKNOWN 시험과 Docker LOCAL 복구 |
| 2. 분리 필요성 계측 | 동시 작업 수, DB 경합, GPU worker 대기·장애 전파, 운영 복구 비용 측정 | 독립 worker에 브로커가 필요한 근거와 운영 담당 확인 |
| 3. RabbitMQ 선택 도입 | 사이트 전용 Compose 서비스, outbox/confirm/ACK, 큐/권한/TTL/DLQ/monitoring/backup | Docker 장애 주입과 실제 Ubuntu 재부팅·복구; 중복 물리 명령 없음 |
| 4. 장비/현장 수용 | CORE 최종 결과 연계, 팔/Pinky 개별 계약, 정책 증거의 실측 승인 | 장비별 DEVICE/FIELD 기록; 자동 실행은 D-268 수용 전 계속 HOLD |

문서·로컬 Docker·합성 이벤트는 실제 장비 명령/영상·현장 안전의 대체 증거가 아니다.
