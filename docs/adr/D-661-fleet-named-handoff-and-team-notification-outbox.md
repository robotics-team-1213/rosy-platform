## D-661 Fleet 이름 있는 사건 인수와 팀 알림 outbox

**Status:** Accepted (2026-10-11, D-656 단계별 실행 및 새 팀용 Discord 채널 사용자 선택). 코드·가짜 채널 시험의 범위이며 실제 서버/채널 개설·발송·현장 수용을 뜻하지 않는다.

### Context

D-660은 현재 필요성의 참고 기록이다. 기존 `line-stuck/claim`은 ABORT 확인 전 자동 해결기를 중지하는 요청이며 이름 있는 담당 인수나 재시작 복원을 증명하지 않는다. 새 팀 채널을 만들기 전 소스와 설정·수용 절차부터 준비한다.

### Decision

1. 기존 claim에 선택 `judgment_revision`을 추가한다. 없으면 기존 `resolver_pause`다. 있으면 이름 있는 운영자만 현재 사건을 `incident_handoff`로 인수한다. revision은 subject/case/CORE owner/필요성/사유/정책의 SHA-256이며 매 프레임 바뀌는 원본 CORE revision과 구별한다. 원본은 D-660에 그대로 보존한다. DB transaction에서 최신 판단·현재 열린 사건·조회 시각·경쟁 owner를 다시 확인하고 같은 사람의 중복은 같은 receipt를 반환한다. 보류 사례의 인수는 검토 책임이며 장치 admission이 아니다.
2. `fleet_incident_claims`는 기존 Fleet DB 안에 둔다. 단일 사건에 담당자 하나이며 현재 사건이 다시 관측될 때 재시작 후에도 자동 해결기를 중지한다. 이미 제출된 요청을 취소했다고 주장하지 않고, 아직 제출하지 않은 답은 제출 직전에 claim을 다시 확인한다. 다른 담당자의 이동 답은 거절하며 WAIT/ABORT 안전 정지는 계속 허용한다. 인수 원장 실패는 성공 receipt를 내지 않고 자동 해결기를 중지 상태로 둔다. 자동 해제/이양/기한 숫자는 이번 범위에서 추가하지 않는다.
3. 외부 알림은 같은 Fleet DB의 별도 durable outbox다. 판단 쓰기와 OPEN 알림 생성, 사건 종료 쓰기와 CLOSED 알림 생성을 각각 같은 transaction으로 기록한다. Mission model-turn outbox를 소비하지 않는다. 기본 외부 발송은 꺼짐이며 명시 비공개 설정으로 고정된 Discord/Slack/Telegram 목적지만 허용한다. 정상 비개입은 새 사건/알림/장치 요청을 만들지 않는다.
4. OPEN은 현재 case·의미 revision·최근 Fleet 판단·닫힘·담당 인수를 제출 직전에 재검사한다. ABSTAIN 알림은 재관측/사람 검토 요청이며 실행 허가가 아니다. 논리 중복은 사건/revision/채널/종류로 막는다. 초기 전달 정책은 채널당 60초 간격, 최대 3회, 10분 expiry다. 이는 통지 예산이며 독립 판단의 현장 정확도·응답 지연 수용 한계가 아니다. 429와 확실한 연결 전 실패만 제한 재시도하며 timeout/5xx/중간 취소·재시작 뒤 제출 불명은 UNKNOWN으로 남기고 맹목 재전송하지 않는다. 물리 메시지 exactly-once는 약속하지 않는다.
5. 메시지는 사건 식별·판단 분류·사유·현재 담당·관측 시각·통지 기한과 token 없는 인증 Console 링크만 포함한다. 원본 영상·주소·프레임·모델 자유 텍스트·secret은 내보내지 않는다. URL/수신자는 설정으로 고정하고 redirect를 따르지 않는다. HTTP/provider 수락은 수신/읽음/인수/해소가 아니며 상태와 실패를 Console에서 볼 수 있게 한다. 채팅 자유 응답을 명령으로 받지 않는다.

### Verification and next gates

소스 소유자는 `fleet/incidents/handoff.py`와 `fleet/incidents/notifications.py`다.
팀 통지·담당 인수를 별도 하위 패키지로 묶고 판단·resolver·장치 admission은 기존 소유자에 남긴다.
[분리 계획](../plans/2026-10-11-fleet-team-incidents-subpackage.md)에 직접 import·설치·크기 검증을 기록한다.

원격 fake에서 인수 경쟁/중복/만료/다른 사건/재시작/원장 실패, 대기 중 자동 답 억제, 정상 zero-send, outbox 원자성/재시작/종료/부분 실패/429/전송 불명/secret 비노출을 확인한다. 지정 팀 채널의 발송→실제 수신→이름 있는 Console 로그인→인수 readback→현장 결과→종료 통지는 별도 수용이다. Discord 서버와 채널·비공개 webhook은 아직 없으며 팀 관리자의 계정에서 준비해야 한다. D-644~D-646 전체 및 모델 런 관문은 이 ADR로 통과하지 않는다.

공식 전송 계약 확인: [Discord](https://docs.discord.com/developers/resources/webhook#execute-webhook), [Slack](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/), [Telegram](https://core.telegram.org/bots/api#sendmessage), 2026-10-11.
