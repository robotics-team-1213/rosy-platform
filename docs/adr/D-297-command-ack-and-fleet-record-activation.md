## D-297 명령 ACK와 Fleet 추적 레코드를 분리한 PRT-004 활성화 설계

**Status:** Proposed (2026-09-27). D-177을 대체하며 D-170의 중앙 Fleet 착수 조건은 유지한다. 이 문서 자체는 `correlation_id` 송수신, 새 API, 로봇 ACK 발행을 활성화하지 않는다.

**Context:** D-177은 API Reference §9.5의 Fleet 추적 레코드를 로봇 `AckPayload`와 혼동해 `TIMEOUT`, `issued_by`, `ts_issued`, `ts_final`을 로봇 ACK 확장 필드로 적었다. 뒤에 Accepted된 D-215는 `TIMEOUT`을 Fleet 기록 전용으로 확정했다. 현재 Site Fleet은 REST 수락 응답을 작업의 `ACCEPTED`로 저장하지만, 상관관계가 검증된 CORE 실행/최종 결과 경로는 아직 없다(D-293). 이 셋을 하나의 상태기로 취급하면 타임아웃이나 수락을 실물 완료로 오인할 수 있다.

**Decision (중앙 Fleet 착수 시 적용):**

1. **ID 발행과 소유.** 중앙 Fleet만 명령별 `correlation_id`를 생성하고 명령 발행 전 영속 기록한다. 로봇은 수신 ID를 보존해 ACK에 되돌린다. `task_id`는 Fleet 작업 ID, `correlation_id`는 개별 장치 명령 ID로 분리한다. 재발행이 필요한 경우에도 기존 결과를 먼저 조정하며, 같은 ID를 새 물리 명령의 증거로 재사용하지 않는다.
2. **로봇 ACK.** 로봇이 outbound WS로 보내는 `AckPayload.status`는 `ACCEPTED|STARTED|COMPLETED|FAILED` 네 가지다. Envelope은 해당 `correlation_id`와 `seq`를 가진다(D-5, D-10, D-215). ACK의 발행자와 명령 대상이 일치하고, 해당 ID의 발행 기록이 있으며, 중복·순서·재접속 재전송을 검증한 뒤에만 Fleet이 반영한다. 로봇은 `TIMEOUT` ACK를 만들지 않는다.
3. **Fleet 추적 레코드.** API Reference §9.5의 `issued_by`, `ts_issued`, `ts_final`, `TIMEOUT`은 Fleet 원장이 소유한다. 기본 10초 동안 ACK가 없으면 중앙 Fleet은 자기 추적 레코드를 `TIMEOUT`으로 기록한다(D-215). 이는 명령의 물리적 중단·실패 증거가 아니다. 늦은 ACK나 로봇 재접속 후 상태는 같은 ID와 seq로 별도 감사 기록에 남겨 조정한다. 기존 `TIMEOUT` 이력을 덮어쓰거나 타임아웃만으로 명령을 자동 재발행하지 않는다.
4. **사이트 작업 투영.** 현재 Site Fleet의 `REQUESTED|QUEUED|ACCEPTED|RUNNING|COMPLETED|FAILED|UNKNOWN`은 작업 상태이며 로봇 ACK enum과 다르다. 긍정적 CORE receipt만 `ACCEPTED`를 허용한다. `STARTED`와 최종 ACK를 작업의 `RUNNING`/`COMPLETED`/`FAILED`에 연결하려면 대상 robot ID, 명령 ID, 작업 ID, 명령 종류, 실행 시각과 결과의 일치를 검증하는 별도 전이가 필요하다. 그 전까지 범용 전이는 실행·완료를 만들 수 없고 모호한 발행 결과는 `UNKNOWN`으로 보존한다(D-293).
5. **활성화 단위.** D-170의 FLEET SRS Phase 4 중앙 Fleet 서버가 착수할 때, `core_common.protocol.schemas`, Fleet 명령 원장·수신부, 로봇 `FleetAgent`, `HttpRobotClient`/SiteHub, API Reference §7.5·§9.5·§10, 계약 시험을 같은 변경에서 맞춘다(D-18). `correlation_id` 없는 기존 v1 요청의 호환성을 유지하고 PRT-006에 따라 프로토콜 버전을 검토한다. 구현·검증 증거가 갖춰지기 전에는 이 ADR을 Accepted로 바꾸지 않는다.

**Alternatives:** D-177의 로봇 ACK 필드 확장을 그대로 구현하면 D-215와 충돌한다. 현재 Site Fleet에서 임의의 task ID나 REST receipt를 명령 결과 상관관계로 간주하면 실행·완료의 출처를 증명할 수 없다. 중앙 Fleet보다 로봇 ACK 발행을 먼저 켜면 받는 쪽의 내구성·중복 처리·재접속 조정을 검증할 수 없다.

**Validation / gate:** 현재는 문서 정합과 `AckStatus`의 네 값, Site Fleet의 보수적 상태 전이만 SOURCE/LOCAL로 검증한다. 활성화 변경에서는 잘못된 ID·robot ID·명령 종류, 재전송·역순·늦은 ACK, 서버 재기동, REST timeout 후 조정, 미발행 ID, 타임아웃 후 재발행 금지를 계약 시험으로 증명한다. 실제 로봇의 실행·정지·최종 결과는 별도 DEVICE/FIELD readback이 필요하다.

**References:** D-5, D-10, D-18, D-170, D-177 (superseded), D-215, D-271, D-293; API Reference §7.5·§9.5·§10; FLEET SRS FAT-03.
