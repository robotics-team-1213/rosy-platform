# D-869 원본 신원에 결속된 이벤트 재전송과 명령 후처리

**Status:** Accepted for implementation (2026-10-25, 사용자의 통신 개선 즉시 구현 승인). 소스·시험·배포·실물 수용은 별도다.

## Context

CORE FleetAgent는 프로세스마다 이벤트 seq를 0부터 매긴다. Fleet의 registry는 이전 프로세스의 최대 seq를 보존한다. WELCOME의 scalar를 기준으로 새 버퍼를 지우면 새 부팅에서 연결을 기다리며 생성한 이벤트가 삭제된다. 높은 번호가 저장됐어도 그 이전 이벤트의 저장 실패를 배제할 수 없다.

기존 EventMessage에는 전역 UUID인 event_id가 있고 CoreEventStore는 `(robot_id,event_id)`로 중복을 제거하며 같은 ID의 본문 충돌을 거절한다. Agent도 미응답 이벤트를 원래 객체로 재큐잉한다. 이 기존 경계를 활용하면 새 stream ID나 wire 필드 없이 잘못된 scalar 확인을 제거할 수 있다.

또한 목표·전체 취소 fence·bay의 늦은 후처리에서 현재 목표를 무조건 취소하면, 과거 요청을 정리하다 새 실행을 취소할 수 있다. D-855의 원본 실행 scoped 취소를 이 경로에도 적용한다.

## Decision

1. 이벤트 재전송은 원본 `event_id`·내용·seq를 유지한다. Agent는 WELCOME의 `last_event_seq`로 미응답 버퍼를 삭제하지 않는다. 개별 EVENT의 정상 응답만 확인 근거다. 기존 저장·projection 실패 응답을 성공으로 바꾸지 않는다.
2. 현재 HELLO에는 producer scope가 없으므로 Hub의 WELCOME은 `last_event_seq=0`을 반환한다. 구 Agent가 새 프로세스의 작은 seq를 삭제하지 않게 한다. Registry의 최대 seq는 진단값이며 누락 없는 수신 확인이나 실행 완료 증거가 아니다.
3. durable Hub는 기존 CoreEventStore의 ID/본문 검증을 사용한다. 메모리 Hub도 기존 로봇별 history에서 같은 event_id의 동일 본문 재전송을 한 번만 기록하고, 다른 본문은 `EVENT_NOT_AUDITABLE`로 거절한다. 별도 중복 캐시나 DB를 추가하지 않는다.
4. 늦은 목표 응답 정리는 `accepted is True`인 원본 receipt의 native boot/run/kind와 원래 correlation을 검증한 뒤 기존 scoped 취소만 사용한다. 응답 유실·미지원·잘못된 receipt·404·409는 UNKNOWN이다. 현재 상태에서 다른 실행의 신원을 추측하거나 global cancel로 강등하지 않는다.
5. 전체 취소의 바깥 fence는 안쪽에서 끝난 정리를 반복하지 않는다. 원본 승인 receipt가 없는 예외에서는 작업 표식과 UNKNOWN을 보존한다. 현재 yielder 목록은 과거 요청의 실행 증거가 아니다. bay는 임대가 꺼져도 원래 제출 correlation을 보유한다. 늦은 응답은 새 제출 세대·장치 연결·대체 임대를 덮어쓰지 않는다.
6. 운영자의 명시적 cancel·전체 주행 취소 fanout·E-stop은 기존 의미를 유지한다. 목표 임대 갱신은 로봇별 하나의 in-flight 작업으로 격리하고 각 요청을 TTL/3으로 제한한다. 한 로봇의 지연이 다른 로봇의 갱신을 순차 차단하지 않는다. 원래 소유·정지·취소 task 경계를 유지한다.

이 결정은 D-421 2-6의 무조건적인 자동 재취소와 API PRT-005의 scalar 기반 재전송 삭제 규칙만 대체한다. D-421의 명시적 주행 취소, D-419/550/760의 링크·임대 정책, D-855의 실행 소유권과 scoped 취소는 유지한다. API 문서 v1.315로 명시하며 envelope 1.0과 기존 wire 필드를 유지한다.

## Consequences and verification

- 새 Agent + 기존 durable Hub는 기존 ID 중복 제거로 재전송을 처리한다. 구 Agent + 새 Hub는 WELCOME0으로 잘못된 버퍼 삭제를 방지한다. 구 Agent + 구 Hub 결함은 남는다. 새 Agent + 구 메모리 전용 Hub의 중복 방지는 Hub 갱신이 필요하다.
- 영속 outbox를 추가하지 않는다. 프로세스 종료 전 메모리 버퍼 유실, 기존 1000개 버퍼 한도, 메모리 Hub 재시작 뒤 중복 기억 유실은 이 변경으로 해결되지 않는다. 새 구현은 이를 보장했다고 보고하지 않는다.
- 원본 실행을 확인하지 못하는 구형·임대 없는 목표의 자동 정지는 보장할 수 없다. UNKNOWN은 물리 정지나 완료가 아니다. D-760의 능력·보호 설정·현장 수용은 별도로 유지한다.
- 회귀는 새 CORE의 작은 seq, 수신 번호의 구멍, 저장 뒤 ACK 유실, 동일 ID 재전송·본문 충돌, 저장·projection 실패를 durable/메모리 Hub에서 확인한다. 명령 회귀는 A→정지→B→A 늦은 응답/예외에서 B 실행과 임대를 보존하고 명시적 정지를 별도로 단언한다.
- 실제 Pinky radio·재부팅·물리 정지·UTC 품질 수용은 호스트 시험과 구분한다. 원본 pose 신선도와 혼합 버전 군집은 별도 계약이다.
