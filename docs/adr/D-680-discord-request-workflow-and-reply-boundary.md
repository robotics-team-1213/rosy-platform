# D-680 — Discord 요청의 Fleet 작업 연결과 결과 회신

**Status:** Accepted (source design only, 2026-10-12). 사용자의 완전한 연동 구현 지시를 반영한다. 실제 운영 설정·전송·장치 수용은 각각 검증한다.

## Context

D-671 접수는 원문과 기명 요청자만 저장한다. D-675 Gateway는 이를 수신하지만 기존 작업·승인·결과와 연결하지 않는다. D-669의 기본 Console 관리와 위험 대응 분리를 유지하면서 접수 후 경로를 완성해야 한다. 모델 CLI의 provider/broker 수용은 별도 세션 소유다.

## Decision

Fleet의 기존 tasks DB가 요청과 기존 작업의 관계 및 회신 상태를 소유한다. Task/Mission/Cell Job의 원장을 복제하거나 Bot을 operator로 만들지 않는다. transport는 Discord message create/read만 맡고 승인·작업 상태를 판단하지 않는다.

Console의 주행 제출은 API v1.212의 `/channel-requests/{request_id}/submit`으로 한다. 기존 FleetTaskService와 TaskStore의 생성 트랜잭션 안에 현재 원문 owner/hash/revision/READY/candidate 검증과 관계 예약을 함께 둔다. 다른 탭의 HOLD·목표 변경은 Task 생성 전에 거절한다. Task를 먼저 만든 뒤 관계를 연결하는 UI 순서는 사용하지 않는다. 동일 확인 revision 재시도는 기존 Task key로 복구한다. 결과 회신도 생성·claim·발송 직전 원래 receipt의 현재 Discord user mapping과 guild/channel을 검증한다.

첫 구현은 현재 접수 원문을 Console에서 확인하여 구조화 작업 또는 보류·거절 사유를 남기는 경로다. 일반 이동은 기존 Task 제출의 기명 사용자·idempotency 계약을 사용한다. Mission/Cell Job은 기존 proposal/resolve/admit 소유자·독립 승인 규칙을 유지한 어댑터로 연결하며 이동 제출로 대체하지 않는다. 의미가 모호한 원문과 실제 provider 미수용 입력은 질문·보류로 남긴다. 자연어를 실행 JSON이나 임의 URL로 직접 전달하지 않는다.

요청 관계는 request ID, 원문 hash, 요청자, 확인자, 원장 종류와 ID를 묶는다. 현재 기명 계정·요청 소유권·기존 작업 소유권·원문 hash를 확인한다. 동일 요청의 다른 작업 연결은 conflict다. 기존 idempotency를 사용하여 제출 후 연결 실패나 재시작이 작업을 새로 만들지 않게 한다. 불명 제출은 UNKNOWN이며 자동 실행을 재시도하지 않는다.

회신은 receipt의 고정 channel과 원래 message에만 보낸다. message reference, mentions 차단, 고정 문구의 상태·원장 ID를 사용하고 사용자 원문이나 임의 목적지를 전달하지 않는다. 접수와 처리 결과는 durable outbox에 한 번씩 등록한다. Discord message ID가 검증된 응답만 provider 수락으로 기록하며 장치 성공으로 표현하지 않는다. 전송 중 재시작·timeout·5xx는 UNKNOWN, 명확한 미접속과 429만 bounded retry한다. 실제 Discord readback은 provider 수락과 별도 증거다.

위험 요청은 현재 사건 ID·revision·기명 인수와 기존 정지/취소 경로를 사용한다. 추가 이동·rearm·E-stop 해제는 이 계약에서 승인하지 않는다. 사건 종류별 기존 owner와 fence를 유지하며 오래된 사건의 답변을 새 사건에 적용하지 않는다. 권한과 revision을 보존하는 별도 어댑터·시험 없이 위험 조치를 활성화하지 않는다.

## 구조 계약

| 기존 계약 | 관계 |
|---|---|
| D-427/D-429 | 기존 Fleet 및 integrations/messaging/discord holder 사용. 새 최상위 폴더·배포 서비스 없음 |
| D-430 | CORE/OMX 최종 권한, Fleet admission/transaction/fence 유지. 관련 변경은 독립 검토 |
| D-669/D-671/D-675 | 기명 접수와 수신을 유지하고 Console 작업 연결·결과 회신을 추가. 기존 API 의미를 변경하지 않음 |
| D-640/D-672 | 모델은 후보 전용. provider 수용과 FIELD HOLD는 별도 gate |

## Validation

owner·권한 철회·원문 hash·작업 소유권·다른 작업 재연결·중복 승인·UNKNOWN 복구·실패한 원장 저장·회신 목적지·Bot 자기 메시지를 검증한다. 회신 timeout/5xx와 재시작 후 SENDING은 맹목 재전송되지 않아야 한다. 정상 비개입은 위험 알림을 새로 만들지 않는다. wheel/sdist/source image와 실제 Console 경로를 확인한 뒤 서명 배포와 실제 대화 readback을 별도 기록한다.

실제 로봇이 오프라인이면 장치 목표/FIELD를 완료로 집계하지 않는다. 이 ADR 수용만으로 운영 모델이나 로봇을 활성화하지 않는다.

실행 계획: [완전한 연동](../plans/2026-10-12-discord-fleet-end-to-end.md).
