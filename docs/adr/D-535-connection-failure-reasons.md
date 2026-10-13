## D-535 연결이 안 되면 이유 코드 하나와 할 일을 보인다

**Status:** Proposed (2026-10-09, 8kcn 연결 실패 조사에서 나온 계약; SOURCE 구현, Pilot 앱 채택·DEVICE·FIELD 별도)

### Context

2026-10-09 Pilot 태블릿이 8kcn(rosy_60)에 다시 연결하지 못했다. 망은 정상이었다: 같은 주소(.202, DHCP 예약), mDNS 이름 풀이, TCP 8080, TLS 1.3, `rosy-pinky-8kcn.local` 인증서, 공개 identity 응답, CORE_READY, 방화벽 없음. 실패는 승인 층이었다. 8kcn의 유일한 Pilot 관계는 2026-10-06 만료였고 태블릿은 그 관계를 지웠다. 새 요청에는 승인이 필요한데, 릴리스 055 카드에는 `/run/rosy-peer-display`가 없어 LCD가 D-483 승인 코드를 보이지 못했다. 9dfk는 관제 승인으로 연결됐다. 어떤 화면도 이 이유를 말하지 않았다. 피어 경로는 거의 모든 거절을 409 `request unavailable or changed`로 돌려주고, 클라이언트는 이름 풀이·TCP·TLS 실패를 "닿지 않음" 하나로 보였다.

D-370의 `failure-classes.v1.json`은 재시도 정책(11개 class)이고 사람이 읽을 이유가 아니다. D-460은 Pilot 좌석을 만들지 않았다.

### Decision

1. **이유 코드 표 하나.** `test/fixtures/protocol/connect-reasons.v1.json`이 기계 원천이고 `core_common.protocol.connect_reason`이 같다(계약 시험). 코드마다 `retry`(`auto`: 클라이언트가 백오프로 다시 시도, `person`: 사람이 먼저 할 일), 운영자 문장 `message`, 할 일 `action`이 있다. 코드(21): `ROBOT_UNREACHABLE`, `TLS_REQUIRED`, `TLS_NAME_MISMATCH`, `CA_UNKNOWN`, `CORE_NOT_READY`, `API_VERSION_TOO_OLD`, `PAIRING_UNAVAILABLE`, `PAIRING_REQUIRED`, `IDENTITY_CHANGED`, `LAN_REQUIRED`, `APPROVAL_PENDING`, `APPROVAL_CODE_WRONG`, `CONSOLE_APPROVAL_REQUIRED`, `APPROVAL_TIMEOUT`(대기 요청이 승인 없이 끝남), `APPROVAL_CANCELLED`, `APPROVAL_EXPIRED`(승인된 관계의 기한 끝), `APPROVAL_DENIED`, `APPROVAL_REVOKED`, `RATE_LIMITED`, `SESSION_TAKEN`, `UNEXPECTED_RESPONSE`. 이름은 Pilot `LinkReason`(24136dec2)과 맞췄다. Pilot의 `REFUSED`·`UNKNOWN`은 `UNEXPECTED_RESPONSE` 하나다.
2. **CORE가 거절에 코드를 싣는다.** `/api/v1/auth/peer-pairing/*`와 `/api/v1/auth/connection`의 거절은 기존 HTTP 상태와 기존 `detail`을 그대로 두고 ERR-101 `error {code, message, detail{action, retry, …}}`을 더한다(additive; Pilot의 `detail.remaining_attempts`는 그대로). 응답은 `no-store`다. 주요 대응: HTTP로 온 피어 요청 403 `TLS_REQUIRED`, 수신 초기화 불가 503 `PAIRING_UNAVAILABLE`, LAN 밖 최초 요청 403 `LAN_REQUIRED`, 없는 관계 409 `PAIRING_REQUIRED`, 철회된 관계와 발급자 토큰이 회수·변경된 관계 409 `APPROVAL_REVOKED`, 다른 수신 키·id의 관계와 옛 수신 키로 온 요청 `IDENTITY_CHANGED`, 만료된 관계 409 `APPROVAL_EXPIRED`, 사라진 요청(없는 id와 틀린 비밀을 가르지 않는다) 409 `APPROVAL_TIMEOUT`, 끝난 요청의 확인·취소·결정은 그 상태대로(`expired`→`APPROVAL_TIMEOUT`, `rejected`→`APPROVAL_DENIED`, `cancelled`→`APPROVAL_CANCELLED`), 틀린 화면 코드 400 `APPROVAL_CODE_WRONG`(다섯째는 `APPROVAL_DENIED`), 역할 초과·전체 틀린 코드 한도 `CONSOLE_APPROVAL_REQUIRED`, 모든 한도 `RATE_LIMITED`와 `Retry-After`(상태 읽기 간격은 2 s, 나머지 60 s; 예전 409인 한도는 409 그대로). 이미 승인된 요청의 확인·취소는 409 기본값 `PAIRING_REQUIRED`이고, 요청자는 상태를 읽어 `approved`를 본다. 익명 challenge가 같은 관계 id에 대해 만료와 없음·철회를 가르는 것은 받아들인다: id는 요청자와 소유자만 아는 32자 난수이고 출처별 30회/분이다.
3. **도달 확인은 기존 `GET /api/v1/auth/connection`을 넓힌다.** 새 경로를 만들지 않는다. 인증 없음, LAN 출발지(`client_allowed`)만, 출발지별 30회/분(넘으면 429 `RATE_LIMITED` + `Retry-After`). 전체 한도는 두지 않는다: LAN 호스트 하나가 별칭 몇 개로 모든 Pilot의 연결을 막지 못하게 한다. 수신 초기화가 어떤 예외로 실패해도 이 응답은 `pairing: unavailable`로 답한다. 더하는 필드: `connect_contract`(이 계약의 정수, 지금 1), `api`(`v1`), `core_ready`, `stage`, `release`, `tls_hostname`(TLS일 때만), `pairing`(`open`|`console_only`|`full`|`unavailable`). `transport: https`가 TLS 필수라는 뜻이다. `stage`·`release`·`tls_host`·`tls`는 mDNS TXT가 이미 광고하는 값이고, `pairing`은 대기 요청 수가 상한인지와 LCD 넘김 디렉터리를 쓸 수 있는지만 말한다(요청 내용·출처·코드 없음). 이 응답은 신뢰 앵커가 아니다. 클라이언트는 이 값으로 CA·이름·권한을 정하지 않는다.
4. **로봇에 닿지 못한 실패는 클라이언트가 같은 코드로 분류한다.** 전송 어휘는 닫혀 있다: `dns_failure`·`timeout`·`no_route`→`ROBOT_UNREACHABLE`, `connection_refused`→`CORE_NOT_READY`, 평문 HTTP가 TLS 리스너에서 끊김→`TLS_REQUIRED`, 인증서 이름 불일치(OpenSSL 62)→`TLS_NAME_MISMATCH`, 그 밖의 검증·핸드셰이크·핀 불일치→`CA_UNKNOWN`. 답이 있으면 `error.code`(이유 코드, 또는 `robot_codes`의 기존 ERR-102 코드: `UNAUTHORIZED`→`PAIRING_REQUIRED`, `CALIBRATION_ACTIVE`→`SESSION_TAKEN` 등), 없으면 HTTP 상태(401 `PAIRING_REQUIRED`, 404 `API_VERSION_TOO_OLD`, 409 `PAIRING_REQUIRED`, 429 `RATE_LIMITED`, 5xx `CORE_NOT_READY`, 그 밖 `UNEXPECTED_RESPONSE`). D-456 요청 상태 읽기(200)는 `pending`→`APPROVAL_PENDING`, `rejected`→`APPROVAL_DENIED`, `expired`→`APPROVAL_TIMEOUT`, `cancelled`→`APPROVAL_CANCELLED`, `approved`인데 `authorization_available: false`→`APPROVAL_EXPIRED`다. 기억한 수신 키와 다른 identity는 클라이언트가 `IDENTITY_CHANGED`로 막는다(자동으로 기록을 지우지 않는다).
5. **`API_VERSION_TOO_OLD`는 버전 문자열 비교가 아니다.** 필요한 경로가 404이거나 `connect_contract`가 클라이언트가 요구하는 값보다 작을 때다. API Reference 문서 버전은 코드에 두지 않는다(브랜치마다 다시 고르는 값이라).
6. **`SESSION_TAKEN`은 새 좌석이 아니다.** D-460대로 CORE에 Pilot 좌석은 없다. 다른 토큰의 보정 lease(`CALIBRATION_ACTIVE`)처럼 이미 있는 "다른 사람이 쥠" 거절을 클라이언트가 이 코드로 보인다. teleop last-wins는 바뀌지 않는다.
7. **Fleet 관제**는 로봇 행에 `link_reason {code, message, action, retry}`을 더하고 명단 태그의 title로 보인다(D-499 `link` 단어는 그대로). **Pilot 앱**은 같은 벡터를 시험에서 읽어 같은 코드를 쓴다. Pilot 링크 상태는 그 앱 브랜치가 맡는다.

### Consequences

- 거절 본문이 커질 뿐 상태 코드·기존 필드는 그대로라 지금 클라이언트는 바뀌지 않는다.
- `/auth/connection` 반복 조회에 한도가 생긴다. 지금 Pilot·대시보드는 연결 때 한 번 부른다.
- 8kcn 사례는 `pairing: console_only`와 `CONSOLE_APPROVAL_REQUIRED` 안내로 "관제에서 승인"을 말하게 된다. LCD 디렉터리 자체의 수리는 `rosy-core.service` ExecStartPre(dc0694a0d)이고 다음 릴리스로 간다.
- 검증: 계약 벡터 시험, CORE 경로 시험, Fleet 분류 시험(모델 PC). Pilot 채택, 서명 ARM64 설치물, 실물 태블릿·로봇에서 각 코드가 보이는지는 따로다.

**References:** [D-193](D-193-login-code-and-credential-lifecycle.md), [D-370](D-370-site-app-roles-names-and-shared-link.md), [D-432](D-432-common-discovery-and-development-link-mode.md), [D-456](D-456-lan-receiver-approval-and-persistent-pairing.md), [D-460](D-460-no-pilot-seat-lease-ownership-stays.md), [D-483](D-483-robot-screen-approval-code-for-peer-requests.md), [D-499](D-499-console-site-path-and-robot-link.md), [D-533](D-533-fleet-identity-poll-budget.md).
