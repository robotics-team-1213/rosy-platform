## D-645 Fleet 판단 4단계 외부 알림과 사람 처리 파이프라인

**Status:** Proposed (2026-10-11, 사용자 요구: Fleet 중앙 판단 규약을 D-640보다 먼저 단계별로 다듬고 비개입과 외부 사람 처리를 포함). 문서만이며 구현·배포·모델 호출·외부 발송·장치 수용은 미실행.

### Context
중앙 관제 밖의 담당자도 새 문/장애물, 암 실패, 판단 보류·장기 미해결을 받고 처리해야 한다. Discord·Slack·Telegram은 통지·사람 응답 경계이며 로봇 제어 채널이 아니다. 현재 D-632 Console inbox의 읽음은 개입 해결이 아니다.

### 책임·배포 선행 관문
[D-647 공통 판단 책임·배포 0단계](../adr/D-647-shared-judgment-ownership-and-deployment.md)을 먼저 따른다. 이 ADR의 Fleet은 현재 소비자·서비스 문맥이다. 공통 상황평가 holder와 초기 배포는 아직 미결정이며 권고와 작업/자원 승인·원장 소유를 구별한다. 기존 Fleet transaction과 CORE/OMX 권한은 유지한다.

### Decision
1. 흐름은 Fleet 판단/위험도/담당 → 같은 원장 transaction의 durable 알림 outbox → 설정된 Discord/Slack/Telegram adapter → 담당자 확인과 처리 → 단계 3의 Fleet 중재 → 실제 결과와 사건 종료다. 기존 ER2 outbox의 unique claim/SQLite 정책 패턴을 재사용하되 그 큐를 채널 전송용으로 소비하지 않는다.
2. 최초 버전은 세 채널의 발송 adapter와 인증된 Console 사건 처리 링크다. 메시지에는 공개 가능한 사건 식별, 발생 시각, 증상·개입 필요/보류 이유, 검증된 근거/누락, 현재 owner와 처리 기한을 넣는다. 링크는 bearer token 없이 Console 로그인·scope 검사를 거친다. 채널/수신자는 명시 설정되며 기본 외부 발송은 꺼짐이다. 실제 채널·secret·담당 매핑 없이 발송을 주장하지 않는다.
3. 비개입 정상은 원장 기록만 남긴다. 정상 대기와 해소는 필요 시 묶음/기존 사건 종료 알림으로 처리한다. 새 위험·사람 필요·기한 초과는 정책대로 즉시 또는 상향 통지한다. 사건/판단 revision/위험 단계/채널로 논리 중복을 막고 재알림 간격·담당 인계·최대 시도·expiry·rate limit을 고정한다. 전송 직전에 현재 사건 상태를 확인하며 닫힌 사건의 오래된 개입 요청을 보내지 않는다.
4. provider 수락, 사람 확인, 처리 중, Fleet 조치 수락, 실제 해결을 구분한다. 읽음/이모지/메시지 성공은 재개 승인 또는 해결이 아니다. 네트워크 timeout의 전송 여부는 불명으로 남기며 채널이 idempotency를 제공하지 않으면 물리 메시지 exactly-once를 약속하지 않는다. 모든 채널 실패·장기 무응답은 Console에 보여 주고 기존 안전 대기를 유지한다. 알림 실패가 안전 정지를 지연시키지 않는다.
5. 채팅 내 응답 연동은 알림+Console 처리 인수 뒤 같은 ADR의 두 번째 관문이다. 플랫폼 요청 검증, 외부 사용자↔Fleet 운영자/사이트 권한 매핑, 사건·revision·세대 binding, nonce/expiry·중복/위조/재전달 거절이 갖춰져야 접수·검토 응답을 받는다. 장치 영향 선택은 Fleet의 현행 정책·필요한 재확인/admission을 다시 거친다. 자유 문장을 실행 명령으로 변환하거나 채팅에서 E-stop 해제를 제공하지 않는다.
6. secret/webhook URL과 실제 설치 정보는 비공개 설정에 둔다. 최소 비식별 메타데이터만 내보내고 원본 영상·위치/개인 정보는 승인된 범위만 허용한다. 설정된 목적지/제공자를 고정하고 모델이 목적지·URL을 만들지 못한다. 비공개 영상은 알림에 첨부하지 않는 것이 최초 기본이다.

### 완료 관문
세 채널 fake 계약에서 정책 라우팅, outbox 원자성/재시작/중복, 429/5xx/timeout·부분 실패·전송 불명, 종료/위험도 변경, 비개입 zero-send, 미설정·secret 로그 노출 거절을 확인한다. 실채널 인수는 지정 수신자 발송→수신→인증 Console 처리→Fleet readback→실제 종료 알림으로 확인한다. 메시지 수락만으로 처리 파이프라인 완료라고 하지 않는다. 채팅 응답은 서명/인증·권한 매핑·stale/위조/중복 회귀와 별도 수용이 필요하다.

### 공식 자료
[Slack 요청 검증](https://docs.slack.dev/authentication/verifying-requests-from-slack/), [Telegram webhook secret token](https://core.telegram.org/bots/api#setwebhook), [Discord interaction 검증](https://docs.discord.com/developers/interactions/receiving-and-responding).
조회 2026-10-11. 구체 요청/인증 구현은 설치 버전과 공식 규약을 다시 확인한다.

### 기존 계약과 범위

D-427의 소유 분류, D-429의 후보/실행 분리, D-430의 safety gate와 CORE/OMX 최종 writer를 유지한다. D-608/D-619의 사건·상황 및 D-632의 inbox 의미를 재사용한다. 새 공개 API는 producer/consumer와 API Reference를 함께 변경할 때 확정한다.

단계 순서·수용 시나리오·파일별 작업은 [중앙 판단 선행 계획](../plans/2026-10-11-fleet-central-judgment-stages.md)을 따른다.
