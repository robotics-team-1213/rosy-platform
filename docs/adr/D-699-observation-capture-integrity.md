# D-699 Fleet 관측 capture 식별과 기록 창 무결성

**Status:** Accepted (2026-10-12, source contract)

D-697의 정상 명령·재발 평가에는 완전한 관측 범위를 구분할 근거가 필요하다. 기존 Fleet judgment는 60초 coalescing과 7일 retention으로 전체 poll 기록이 아니다. 기존 ObservationStore를 재사용하며 정상 상태에 가짜 incident case를 만들지 않는다.

## Decision

기존 CORE event journal과 ObservationStore의 실제 구현을 `fleet.observe`에 분리한다. 기존 server 경로는 같은 클래스의 identity alias로 유지한다. 새 SIZE_UNIT의 이전 기준은 137+74+init 1 = 212줄이며 기존 Fleet 부모의 54,074+150과 모든 파일 한도를 유지한다. 소유자·호출자·설치와 동시 측정은 [분리 계획](../plans/2026-10-12-observation-journal-owner.md)에 기록한다.

기존 관측 payload에 선택 `capture {run_id, sequence, monotonic_at, robot_ids}`를 추가한다. run_id는 저장소 인스턴스마다 생성한 UUID hex다. sequence는 append 시도마다 증가하므로 실패·빈 roster 뒤의 성공 기록에 누락이 드러난다. 한 snapshot의 모든 행은 같은 capture를 가지며 중복 robot_id는 전체 snapshot을 거절한다. 성공 기록은 기존 SQLite transaction과 retention으로 저장한다. 이전 기록에 metadata를 추정해 채우지 않는다.

후속 read-only window 도구는 subject와 start/end/max_gap을 명시해 불변 읽기 snapshot의 제한된 행을 검증한다. 양끝 관측, 같은 run의 연속 sequence, clock·간격·subject·내용 hash를 대조한다. 재시작·누락·오래된 자료·retention으로 범위를 입증할 수 없으면 HOLD한다. 원문 state·좌표·계정·endpoint를 결과에 복사하지 않는다.

이는 Fleet 관측 capture 범위만 검증한다. CORE 명령 전체, 실제 모델 호출 0건, 재발 없음, 독립 정답·학습·현장 수용을 승인하지 않는다. 같은 snapshot의 필요성 판단과 실제 규칙 처리 기록은 후속으로 연결하며 rule-only 전략을 가짜 프로파일이나 호출 수로 추정하지 않는다.

| 기존 계약 | 관계 |
|---|---|
| D-427 | Fleet은 관측 원장을 소유하고 learning은 불변 산출물만 소비한다. 역방향 import를 추가하지 않는다. |
| D-429 | 기존 holder와 저장·읽기 책임을 유지하고 새 프로세스·장치 writer를 만들지 않는다. |
| D-430 | 관측 메타데이터는 명령 권한이 아니다. CORE 안전 guard와 최종 명령 경로를 유지한다. |

## Verification

같은 poll의 동일 metadata, 실패·빈 roster gap, restart identity, 중복 거절, 기존 API·export·retention 호환을 원격 시험한다. window 양끝·중간 누락·clock/내용 변조와 JSON CLI도 검증한다. source 시험과 실제 제공자·배포·현장 수용은 구분한다.
