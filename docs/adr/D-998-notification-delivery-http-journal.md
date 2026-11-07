## D-998 전환 전 알림 전달의 HTTP·기계 자격·독립 원장

**Status:** Accepted (2026-11-08, D-997 단계별 구현 지시). 소스·fake 계약 검증 범위다. 기존 Fleet 발송 owner 교체·채널 개설·실제 발송·배포를 승인하지 않는다.

### Context

D-997 Decision 6의 독립 전달 서비스에는 접수·중복 대조·재시작 상태가 필요하다.
Fleet의 현재 worker는 사건 검사와 전송이 붙어 있어 그대로 import하면 서비스가 Fleet 사건 원장을 알아야 한다.
채널 검증과 HTTP adapter만 `core_common.notification_channels`로 추출해 양쪽에서 재사용한다.
기존 `fleet.incidents.notifications.Channel` import도 같은 클래스를 계속 노출한다.

### Decision

1. 소스는 `operations/notifications`, wheel은 `rosy-notifications`, import는 `rosy.notifications`다.
   POSIX 단일 프로세스가 자체 SQLite schema 1과 전용 lock 파일을 소유한다.
   다른 서비스의 SQLite·업무 outbox를 열지 않는다. 같은 원장에 두 번째 프로세스를 열면 실패한다.
   운영 배치는 추가하지 않는다. launcher는 loopback으로만 열고 worker는 명시적으로 켜야 한다.
2. 독립 서비스의 `POST /api/notifications/v1/deliveries`와 같은 경로의 `GET /{notification_id}`를 제공한다.
   CORE나 Fleet에 mount하지 않는다. DTO는 `core_common.protocol.schemas`의 DeliveryRequest/Receipt/OwnerReply다.
   본문은 4096 bytes 이내이며 추가 키·임의 URL·수신자·자유 텍스트를 받지 않는다.
   세부 필드와 상태는 API v1.377이 소유한다. 최초 설치 단위의 Fleet·Harbor 두 생산자만 등록한다.
3. 보호 설정이 각 생산자의 독립 기계 bearer SHA-256·허용 채널·owner HTTPS URL·별도 callback 자격·보호 업무 화면 URL을 결속한다.
   자격은 환경변수로 주입하고 생성·등록·회수는 설치 운영자 책임이다. Account 사람 토큰이나 장치 자격을 사용하지 않는다.
   raw bearer는 최소 32자, 원장에는 넣지 않는다. 목적지는 기존 Discord/Slack/Telegram만 허용한다.
   TLS 입구·인증서·credential rotation과 callback의 생산자 서버 구현은 전환 수용 전에 별도 검증한다.
4. `(producer, notification_id)`가 접수 identity다. 같은 정규화 본문은 같은 receipt, 다른 본문은409다.
   한 identity는 한 채널 전달 건이다. 여러 채널 생산자는 원본 outbox identity에 채널을 결속한다.
   생산자의 원래 사건/업무 발생 identity와 UNKNOWN은 원본 outbox에 보존한다.
   새 접수는 관측≤현재<만료≤관측+설정 TTL을 만족해야 한다. 만료된 요청을 새 건으로 되살리지 않는다.
5. 생산자별 최대1000건·분당20건·7일 보관이며 더 작은 보호 설정을 허용한다.
   초과 시429로 거절하고 다른 생산자는 계속 받는다. 중복 대조는 예산을 소비하지 않는다.
   Fleet은 채널당60초·최대3회·600초 TTL을 그대로 고정한다. Harbor는 설치자가 다섯 예산 값을 명시해야 한다.
   최초 구현의 상한은60초 이상 간격·3회 이하·600초 이하 TTL이다. Harbor의 업무 기한을 이 숫자로 판정하지 않는다.
   terminal 기록은7일 뒤 다음 신규 접수에서 제거하며, 유효 요청은 모두 그보다 먼저 만료된다.
6. worker는 매 건 전송 직전에 등록된 owner에게 원래 요청 전체를 HTTPS POST한다.
   callback은 원본 업무·발생 회차·revision·현재 허용 수신 범위를 검증하고 identity/revision과 valid bool을 반환한다.
   서비스가 owner 판단을 복제하지 않는다. 3초 안에 일치 응답을 못 받으면 PENDING, false면 SUPERSEDED다.
   owner 응답 뒤 만료를 다시 검사한다. owner 회신과 HTTP 진입 사이에 다른 await를 넣지 않는다.
   callback 경로는 생산자별 보호 설정이며 상대 서버가 별도 ADR로 구현할 HTTP 표면이다. 여기서 상대 endpoint를 신설하지 않는다.
7. 실제 전송 전 SENDING·시도 수·목적지별 간격을 durable하게 기록한다.
   429·확실한 연결 전 실패만 제한 재시도하고, timeout·5xx·취소·예상 밖 제출 오류는 UNKNOWN이다.
   재시작 시 SENDING은 UNKNOWN이며 자동 재전송하지 않는다. SENT는 provider 수락만 뜻한다.
   worker는 직렬이며 생산자 순서를 교대로 처리하고 같은 목적지의 별칭 등록을 거절한다.
   설정에서 목적지가 바뀌거나 채널 허용이 사라지면 대기 건은 SUPERSEDED다.
8. Fleet producer seam은 기본 비활성이며 두 발송 owner 동시 활성과 아직 수용되지 않은 전환 모두 거절한다.
   기존 Fleet의 사건 outbox·본문·현재 필요성 검사·전송 경로는 정본으로 유지한다.
   새로운 최소 DTO만으로 Fleet의 기존 본문 전체를 대체하지 않는다. 실제 전환에는 D-997의 두 생산자 HTTP 수용이 먼저 필요하다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-997 | Decision 6의 목표 경로·전달 원장·owner 확인을 구현하되 전환 조건은 미통과로 유지 |
| D-427 | 새 최상위 폴더 없이 operations의 실제 wheel·manifest·CI 시험·카탈로그를 함께 등록 |
| D-429 | 독립 프로세스·DB·기계 자격을 유지하며 Fleet/Harbor DB나 내부 코드 import를 요구하지 않음 |
| D-430 | 장치 명령·CORE 최종 발행·OMX owner·정지/복구·admission을 변경하지 않음 |
| D-661 | 같은 채널 검증·payload adapter·60초/3회/600초·UNKNOWN을 재사용. 기존 Fleet worker와 outbox 유지 |
| D-807 | 사람 로그인 자격과 서비스 기계 자격을 분리 |
| D-841·D-987 | 같은 의미인 채널 전송만 추출하고 업무 판단·원장은 각 owner에 유지 |

### Consequences

서비스 단절은 로컬 사건/HOLD를 바꾸지 않는다. 접수와 provider 수락·사람 열람·인수·업무 해결은 각각 별도다.
저장 실패 시 성공 receipt를 내지 않는다. schema가 모르면 시작을 거절한다.
백업은 운영자가 worker를 중지하고 원장 전체·등록 설정·별도 보관 자격을 같은 revision으로 복원한다.
복원 뒤 미해결 UNKNOWN과 producer 원본 outbox를 대조하기 전 전환하지 않는다.
프로세스 lock은 같은 DB 경로를 쓰는 배치에 대한 방어다. 서로 다른 복제 DB의 다중 발송은 배치 수용에서 막아야 한다.
현재 Compose·서명 이미지·현장 TLS·실제 채널·Harbor 양 끝 SHA HTTP 시험·N100 부하·DEVICE/FIELD 증거는 없다.

### Verification

`operations/notifications/test/test_delivery.py`는 중복/충돌·기계 범위·owner 실패/무효·만료·예산·UNKNOWN·재시작·단일 writer를 fake HTTP로 확인한다.
기존 Fleet `test_notifications.py`·`test_final_notifications.py`는 adapter 추출의 회귀를 검증한다.
원격 결과는 커밋 SHA와 외부 run 로그에 연결한다. 통과 전 수용을 주장하지 않는다.
