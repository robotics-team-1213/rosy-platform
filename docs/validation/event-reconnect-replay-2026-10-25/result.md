# D-869 이벤트 재접속·재전송 검증

기준 main `bbc9fae1316`, RED `49915942fc`, 구현 `85838e52ea`.

Agent는 WELCOME의 producer scope 없는 최대 seq로 미응답 이벤트를 삭제하지 않는다. 원래 event_id·내용·seq를 유지한 재전송과 기존 durable 중복 제거를 사용한다. 새 Hub의 WELCOME0은 구 Agent도 보호하며 registry의 최대 seq 진단값을 바꾸지 않는다. 메모리 Hub는 기존 history에서 동일 ID·본문 중복을 한 번만 기록하고 본문 충돌을 거절한다. 새 stream UUID·schema 필드·envelope 버전 협상을 추가하지 않았다.

## 검증 증거

공식 remote runner만 사용했다. 로그는 저장소 밖 `%LOCALAPPDATA%/Temp/rosy-event-replay/`에 보존했다.

- `red-agent/run-1.txt`: 새 CORE와 미응답 재접속의 2개 사례에서 WELCOME50이 seq1의 원본 이벤트 버퍼를 지워 실패했다.
- `red-hub/run-1.txt`: 높은 seq 뒤의 구멍, 메모리 중복, 동일 ID 본문 충돌의 3개 사례 실패. 기존 durable ACK 유실 재전송 guard는 통과했다.
- `green/run-1.txt`: `85838e52ea`의 Agent link/loop, 기존 gateway Agent, Hub/server, API 문서 pin 관련 98개 통과, skip0. known_failures NEW0/known0/flaky0.
- 저장 실패·projection 실패 응답 경로와 기존 reconnect/backoff·heartbeat·개별 ACK 경로는 유지한다. 새 시험은 원본 EventBus ID/내용/seq와 durable audit/projection 한 번 기록도 확인한다.
- 독립 `/root/time_sync_review`가 최종 소스와 D-869 호환성 경계를 검토해 차단점 없음을 확인했다. 검토자는 pytest나 장치를 실행하지 않았다.

API v1.315의 정본·app 설명·관련 시험 pin은 공식 api_reserve bump로 함께 갱신했다. envelope1.0과 기존 모델 필드를 유지한다. D-869와 ADR Log는 RED 계약 커밋에 함께 있다. D-867·D-868은 다른 가지의 예약으로 gap에 기록했다.

## 한계

이 변경은 영속 outbox가 아니다. CORE 종료 전 메모리 이벤트 유실, 버퍼1000개 한도, 메모리 Hub 재시작 뒤 중복 기억 유실은 남는다. 구 Agent+구 Hub 결함과 새 Agent+구 메모리 Hub의 중복은 해당 peer 갱신 없이는 해결되지 않는다. 실제 Pinky 단절·재부팅·배포 수용, NTP 품질, pose 신선도는 별도다. SOURCE 회귀를 현장 수용으로 올리지 않는다.

CE: 해당 없음 — scalar 확인의 잘못된 전제와 기존 ID 재사용 선택은 D-869, 코드 주석과 회귀에 직접 보존했다. 별도 교훈 문서는 중복 생성하지 않는다.
