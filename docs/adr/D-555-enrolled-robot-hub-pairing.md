## D-555 콘솔 등록 로봇의 허브 페어링 — Fleet이 로봇마다 허브 자격을 만들어 digest만 남기고, TLS로 묶인 등록으로만 로봇에 보낸다

**Status:** Accepted (2026-10-09, 사용자 설계 승인 `.omc/plans/hub-pairing-via-enrollment.md`: Q1 "TLS 신원에 묶인 관리자급 자리", Q2 "TLS로 묶인 등록만, 평문 HTTP는 거절"). 새 자격 경로라 **독립 보안 검토 대상**이다. SAF-003이 실행 중 페어링에도 붙으므로(5항) **Safety-Review 대상**이기도 하다. SOURCE 구현과 호스트 테스트, 로봇 이미지(payload release), 현장 적용은 각각 따로다. 현장 적용은 [D-550](D-550-fleet-robot-communication-contract.md) 11항대로 사용자가 로봇마다 "진행"을 말한 뒤 하나씩 한다.

잇는 결정: [D-5](D-5-outbound-ws-fleet-rest.md)(로봇이 WS로 나감) · [D-382](D-382-robot-site-console-protocol-conformance.md)(허브 HELLO가 소켓을 로봇 하나에 묶음) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(화면 코드 등록, 봉인한 REST 토큰) · [D-419](D-419-saf003-fleet-link-loss-policy.md)(SAF-003) · [D-452](D-452-network-peer-discovery-and-identity-targets.md)(승인된 발견 프로필: 기대 호스트 이름 + 사이트 CA) · [D-550](D-550-fleet-robot-communication-contract.md) J4(지금 페어링, 받아들인 비용).

### Context

2026-10-09 코드에서 확인했다.

- 현장 로봇(rosy_26, rosy_60)은 콘솔 등록으로 들어왔다. 등록이 만드는 끝점은 REST 토큰만 가진다(`operations/fleet/fleet/server/enrollment.py:281`, TLS 묶음이면 `enrollment_tls.py:175`). `fleet_pairing_token`이 없다.
- Fleet은 `robots.yaml` 로봇에 `fleet_pairing_token`이 있을 때만 허브 경로 `/ws/robots`를 켠다(`operations/fleet/fleet/cli.py:439,481`). 현장 `robots.yaml`의 로봇 목록은 비어 있어 허브가 돌지 않는다.
- 로봇 FleetAgent는 `fleet.pairing_token`과 `hub_url` 또는 승인된 발견 프로필이 있을 때만 돈다(`middleware/core/services/core_features/fleet_agent/agent.py:63-70`). 설정은 기동 때 한 번 읽는다(`agent.py:160-184`, `middleware/core/gateway/core/services.py:558-559`).
- 허브는 HELLO 토큰을 평문 사본과 `hmac.compare_digest`로 비교한다(`operations/fleet/fleet/hub/hub.py:166-170`). REST 토큰과 허브 토큰은 달라야 한다(`operations/fleet/fleet/swarm/robots.py:53`).
- SAF-003 `link_configured`는 CORE 기동 때 한 번 정해진다(`middleware/core/gateway/core/fleet_loss_wiring.py:30,57`). 실행 중 페어링하면 CORE를 다시 띄울 때까지 SAF-003이 붙지 않는다.
- CORE 설정 덮어쓰기는 `~/.rosy/rosy.yaml` 또는 `ROSY_CONFIG`이고 대시보드·API가 쓰는 파일이다(`contracts/foundation/core_common/config.py:46-49,185`). 비밀을 둘 자리가 아니다.
- CORE의 TLS 전용 동작은 이미 같은 꼴이 있다: `request.url.scheme == "https"`와 `network.tls`(`middleware/core/api_web/core_api_web/api/v1/host.py:41`, D-418 SSH 키).
- Fleet의 등록 토큰은 화면 코드로 받은 운영자 토큰이고 라벨은 `site:<fleet_name>`이다(`enrollment.py:429`). CORE는 관리자 코드를 등록에 쓰지 않는다(`enrollment.py:486-487`).

### Decision

1. **Fleet이 로봇마다 허브 자격 하나를 만든다.** 콘솔 "허브 연결"(이름 있는 운영자, `POST /api/fleet/robots/{robot_id}/hub-link`)에서 Fleet은 `secrets.token_urlsafe(32)`(32바이트 난수)로 토큰을 만든다. 등록 행에는 SHA-256 hex digest(`hub_digest`)와 허브 호스트 이름(`hub_host`)만 쓴다. 평문은 그 한 번의 전달 호출 동안만 메모리에 있고 행·감사·로그·응답·예외 문구에 들어가지 않는다. REST 토큰과 다른 비밀이다.
2. **전달은 TLS로 묶인 등록으로만 한다.** Fleet은 등록 클라이언트(고정 주소, 승인된 CA와 신원 확인 `EnrollmentIdentityTransport`)로 로봇 `PUT /api/v1/fleet/link {pairing_token, expected_hostname, ca_pem}`을 부른다. 그 로봇에 승인된 TLS 묶음(`--enrolled-tls-bindings-file`)이 없으면 `409 tls_binding_required`로 거절한다. 평문 HTTP로는 토큰이 LAN을 그대로 지나가기 때문이다. 로봇이 받는 위치는 D-452 발견 프로필(사이트 `.local` 이름 + 사이트 CA)뿐이다. Fleet은 `--hub-link-hostname`·`--hub-link-ca`로 그 값을 받는다. 평문 `hub_url`은 받지 않는다(HELLO 토큰이 평문 WS로 나가고, `wss` `hub_url`은 사이트 CA를 고정할 수 없다).
3. **CORE 자리(Q1).** `PUT`·`DELETE /api/v1/fleet/link`는 CORE 자신의 TLS 리스너(`https`, `network.tls`)로 온 요청만 받는다(아니면 `403 TLS_REQUIRED`). 호출자는 관리자이거나, 화면 코드로 받은 운영자 토큰(`pair-physical`·`pair-admin`) 가운데 라벨이 `site:`로 시작하는 것(Fleet 등록 토큰)이다. 공용 개발 토큰은 거절한다. "관리자급"은 이 조합에서 온다: 평문 경로가 없고, Fleet 쪽은 승인된 CA와 신원 확인을 지난 뒤에만 Bearer와 토큰을 보내며, 그 운영자 토큰은 이미 로봇을 움직일 수 있는 자격이다. **한계:** 라벨은 호출자가 고른 문자열이라 인증이 아니다. 화면 코드로 운영자 토큰을 받은 사람은 라벨을 흉내 낼 수 있다. 그가 얻는 것은 이 로봇의 허브 위치 변경(상태 밀기 방향)이고, 허브는 로봇에 명령하지 못한다(D-5). CORE가 Fleet 자리를 증명하려면 사이트 전용 토큰 종류가 따로 필요하다(다시 볼 때).
   - `PUT`은 비밀 덮어쓰기 파일 `~/.rosy/fleet-link.yaml`(`ROSY_FLEET_LINK`로 바꿀 수 있음)과 CA `~/.rosy/fleet-link-ca.pem`을 CORE 사용자 소유 0600으로 원자적으로 쓴다(`mkstemp` + `fsync` + `os.replace`). `load_config`는 이 파일의 `fleet` 블록만 마지막에 병합하고, 그 전에 아래 층의 `pairing_token`·`hub_url`·`discovery`를 지운다. POSIX에서 그룹·남에게 열린 파일은 경고하고 읽지 않는다.
   - 그 다음 FleetAgent 작업만 다시 시작한다(`FleetAgent.relink`). CORE와 다른 서비스는 그대로다. `DELETE`는 두 파일을 지우고 아래 층의 링크(있으면)로 돌아가 에이전트를 다시 시작한다.
   - `GET /api/v1/fleet/link`(viewer)는 `{configured, provisioned, expected_hostname, hub_url, enabled, connected}`만 준다. 토큰은 어떤 응답·사건·로그에도 없다. 사건 `fleet.link_provisioned`·`fleet.link_cleared`는 호출 토큰 id만 싣는다.
   - 능력: `GET /system/capabilities` 최상위 `fleet_link_provisioning: true`(주행이 없는 로봇도 페어링하므로 `controls` 항목이 아니다). Fleet은 이 플래그가 없는 로봇에 보내지 않는다(`409 robot_unsupported`).
4. **허브는 등록 로봇을 digest로 확인한다.** `SiteHub`는 등록 로봇의 digest를 들고, HELLO 토큰의 SHA-256을 `hmac.compare_digest`로 비교한다(상수 시간). Fleet 기동 때 등록 행의 digest를 허브에 올린다. 허브 경로는 `robots.yaml` 페어링이 있거나, 등록 저장소·`--events-db`·콘솔 토큰이 있고 `--hub-link-*`가 설정됐거나 digest가 있는 등록 행이 있으면 켠다. 콘솔은 지금처럼 허브 상태가 신선하면(≤ 3 s) 허브, 아니면 REST로 모으고, 등록 행에 "수집: 허브|REST"를 보인다.
5. **SAF-003은 살아 있는 설정을 보되, 새 링크는 처음 WELCOME 또는 유예 마감 뒤에 센다.** `link_configured`는 기동 때 값 대신 지금 `config["fleet"]`로 판정하고, 실행 중 relink 뒤에는 에이전트가 허브의 WELCOME을 받거나 relink에서 `FLEET_LINK_ARM_GRACE_S` = 35 s(HELLO 5 s + 발견 25 s(mDNS 3, DNS 대체 12, TLS health 연결 5 + 읽기 5) + 여유 5 s)가 지날 때까지 링크를 세지 않는다. 유예가 지나도 WELCOME이 없으면(틀린 이름·CA, 거절된 HELLO, 닿지 않는 허브, 인증서 오류로 에이전트가 멈춤) 기동 때와 같이 끊긴 링크다(보안 재검토 A: 무장이 영원히 꺼져 있지 않게). 유예 안에 시작한 Fleet 목표는 유예가 끝날 때 상실 시작으로 잡혀 `fleet_loss_timeout_s` 뒤 정책이 걸린다. `GET /api/v1/fleet/link`는 `arm_state`(`armed`·`pending`·`grace_expired`)와 `arm_deadline_s`를 보이고, 콘솔 행은 "허브 연결 · 수집: 허브" / "허브 연결 · 확인 중" / "허브 연결 실패 · SAF-003 적용"을 보인다(Fleet이 같은 35 s를 자기 허브 기록으로 잰다). 그래서 실행 중 페어링이 CORE 재시작 없이 SAF-003을 붙이고, 해제가 뗀다. 거절된 HELLO나 `stop()`은 여전히 끊긴 링크다(설정은 PUT·DELETE만 바꾼다).
   - **Fleet 목표 중에는 바꾸지 않는다(보안 검토 HIGH).** relink·회수·교체는 링크를 잠깐 끊는다. 목표가 진행 중이면 SAF-003이 STOP/HOLD/RETURN_HOME(움직임)을 걸 수 있다. CORE `PUT`·`DELETE`는 `nav.fleet_goal()`이 있으면 `409 FLEET_GOAL_ACTIVE`이고, Fleet은 연결·해제 전에 자기 목표 표(`console._goals`)와 로봇 `GET /fleet/link`의 `fleet_goal_active`를 보고 같은 이유(`fleet_goal_active`)로 거절한다. 콘솔은 "Fleet 목표가 진행 중입니다"를 보인다.
   - **강제 해제(보안 재검토 B).** 이름 있는 운영자가 확인 대화상자에서 "강제 해제"를 고르면(`DELETE /api/fleet/robots/{robot_id}/hub-link?force=true`) 목표 중에도 Fleet digest와 허브 세션을 지운다. 로봇은 링크를 잃고 SAF-003 STOP/HOLD(정책대로)가 걸린다 — 안전한 쪽이다. 로봇 `DELETE`는 CORE가 목표 중 409로 거절하므로 보통 `robot_cleared: false`이고, 남은 토큰은 HELLO에서 거절된다. 감사 결과는 `forced_…`. 보통 해제는 목표 중 계속 거절한다.
   - 기동 때 잘못된 Fleet 설정(`fleet.heartbeat_reply_timeout_s`, SAF-003 시간)을 기본값으로 대신했으면 CORE는 그 사실을 기억하고 `PUT`을 `409 FLEET_LINK_CONFIG_INVALID`로 거절한다. 기본값 위에서 SAF-003이 무장되지 않게 한다.
6. **회수와 교체.**
   - "허브 연결 해제"(`DELETE /api/fleet/robots/{robot_id}/hub-link`): Fleet digest를 **먼저** 지우고 허브의 그 로봇 세션을 끊는다. TLS가 필요한 것은 그 다음 로봇 `DELETE /api/v1/fleet/link` 한 번뿐이다. TLS 묶음이 바뀌었거나 없거나 로봇에 닿지 못하면 응답이 `robot_cleared: false`이고, 남은 토큰은 HELLO에서 `PAIRING_INVALID`로 거절되어 에이전트가 스스로 멈춘다.
   - 등록 해제: 같은 로봇 `DELETE`를 한 번 시도하고 행과 함께 digest가 사라진다.
   - 교체: 연결된 로봇에 "허브 연결"을 다시 하면 새 토큰이 옛것을 대신한다. Fleet은 새 digest를 먼저 저장·적용하고(옛 토큰으로 맺은 허브 세션은 그때 끊는다) 전달이 실패하면 옛 digest로 되돌린다. 로봇이 새 토큰으로 곧바로 HELLO 해도 거절되지 않는다. 로봇마다 `asyncio.Lock` 하나가 저장·전달·되돌림을 한 덩어리로 묶는다.
   - 자동 재시도는 없다. 감사 행(`hub_link`, `hub_unlink`)은 결과 단어만 남긴다.

### 보안

| 항목 | 결정 |
|---|---|
| 생성 | `secrets.token_urlsafe(32)`: 32바이트 난수, 로봇마다 하나, REST 토큰과 다름 |
| 저장(Fleet) | SHA-256 hex digest만. 평문·봉인본 없음. digest 유출은 토큰을 주지 않는다(256비트 난수의 원상 찾기) |
| 비교(허브) | `hmac.compare_digest(sha256(presented), stored)`, 상수 시간 |
| 평문 수명 | 생성부터 로봇 PUT 응답까지 한 호출. 로그·감사·응답·예외 문구에 없음(테스트가 로그를 검사) |
| 전달 | TLS로 묶인 등록만(승인 CA + 신원 확인 뒤 Bearer). 평문 HTTP 등록은 `409 tls_binding_required`. CORE도 `https`가 아니면 `403 TLS_REQUIRED` |
| 로봇 저장 | `~/.rosy/fleet-link.yaml` 0600, CORE 사용자 소유, 대시보드가 쓰는 `rosy.yaml`과 다른 파일. 새로 만드는 `~/.rosy`는 0700. 읽을 때 `lstat`로 심볼릭 링크·다른 소유자·그룹/남 읽기 권한이면 경고하고 무시. 읽기·YAML 오류도 경고하고 무시(기동을 깨지 않음) |
| 목표 중 변경 | CORE `409 FLEET_GOAL_ACTIVE`, Fleet `fleet_goal_active`. 새 링크는 첫 WELCOME 또는 35 s 유예 뒤에 SAF-003 입력(`arm_state`). 강제 해제만 목표 중 허용(SAF-003 정지 쪽) |
| 기동 기본값 | 잘못된 Fleet·SAF-003 설정을 기본값으로 대신한 CORE는 `PUT`을 `409 FLEET_LINK_CONFIG_INVALID`로 거절 |
| 해제 경로 | `DELETE`는 `load_config(fleet_link=False)`로 아래 층 링크를 다시 계산한다(덮어쓰기 파일만이 아님) |
| 로봇→허브 | 발견 프로필만(사이트 CA 고정 `wss`). 평문 `hub_url` 없음 |
| 회수 | 해제는 Fleet digest와 허브 세션을 먼저 지우고, TLS 울타리 뒤의 로봇 `DELETE`는 그 다음이다(실패해도 Fleet 쪽은 지워짐). 로봇에 남은 토큰은 HELLO에서 거절 |
| 교체 | 다시 "허브 연결". 옛 토큰은 새 digest 저장 순간 죽고, 옛 토큰으로 맺은 허브 세션도 그때 끊긴다 |
| CORE 자리 | **받아들인 남은 위험(사용자 결정 2026-10-09: "인증서말고 그렇게 감수해").** CORE `/auth/pair`가 받는 `purpose`·`label`은 화면 코드를 가진 호출자가 고르므로, CORE가 그 값으로 출처를 기록해도 Fleet을 증명하지 못한다. **의도한 고침:** 사이트 CA가 서명한 Fleet 사이트 클라이언트 인증서를 CORE TLS 리스너가 확인한다(`ssl.CERT_OPTIONAL`로 받고 `/fleet/link`에서는 검증된 피어 인증서를 요구). 대안은 관리자가 발급한 등록 코드(`pair-admin`)만 받는 것이다. 사용자는 인증서도 `pair-admin`도 하지 않고 이 자리를 그대로 쓰기로 했다: 관리자, 또는 화면 코드 출처(`pair-physical`·`pair-admin`)이고 라벨이 Fleet 등록 호출의 `site:`인 운영자 토큰, CORE TLS 리스너로만. 남는 위험: 로봇 화면 코드로 운영자 토큰을 받은 사람이 이 로봇의 허브 위치를 바꿀 수 있다(상태 밀기 방향, SAF-003 무장; 명령은 아님). 인증서·`pair-admin`은 지금 계획에 없다. 위험이 현실이 되면(화면 코드 유출, 허브 위치 변경 이벤트) 다시 연다 |

### Alternatives

| 대안 | 판단 |
|---|---|
| 관리자 로그인 코드로 PUT(Q1 다른 선택) | 기각(사용자). 로봇마다 관리자 코드가 한 번 더 필요하다 |
| 평문 HTTP 등록에도 전달(Q2 다른 선택) | 기각(사용자). 토큰이 LAN을 평문으로 지난다 |
| 허브 토큰을 REST 토큰처럼 봉인해 보관 | 기각. Fleet은 허브 토큰을 다시 쓸 일이 없다. 확인에는 digest면 된다 |
| 등록 때 자동으로 허브 연결 | 기각. D-550 11항: 살아 있는 로봇마다 사용자가 "진행"을 말한다 |
| `rosy.yaml` 덮어쓰기에 함께 저장 | 기각. 대시보드·API가 쓰는 파일이고 권한이 그룹 읽기다 |
| CORE 전체 재시작 | 기각. 페어링 하나에 주행·센서 서비스를 내릴 이유가 없다. FleetAgent만 다시 시작한다 |
| 평문 `hub_url` 전달 | 기각. HELLO 토큰이 평문으로 나간다. 발견 프로필만 쓴다 |

### Consequences

- 현장은 콘솔에서 로봇마다 허브에 페어링할 수 있다. SSH·파일 편집이 없다. 로봇 이미지가 이 엔드포인트를 가져야 하므로 payload release 뒤에 쓴다.
- D-550 J4 비용이 페어링한 로봇에 생긴다: D-407 `console_linked` 디바운스가 바뀌고, Fleet 목표 중 Fleet이 재시작하면 STOP·HOLD 정책 로봇이 `fleet_loss_timeout_s`(5 s) 뒤 선다. 로봇마다 자격 하나를 더 다룬다(발급·교체·회수).
- 허브 경로가 등록 사이트에서도 열린다. 등록 digest가 없는 로봇의 HELLO는 모두 거절된다.
- CORE 자리는 Fleet임을 증명하지 못한다(3항 한계). 사용자가 2026-10-09 이 위험을 받아들였다("인증서말고 그렇게 감수해"): `site:` 라벨 자리를 그대로 쓰고 클라이언트 인증서·`pair-admin`은 하지 않는다. 고칠 길(사이트 CA 서명 클라이언트 인증서를 CORE TLS 리스너가 확인, 또는 `pair-admin`)은 기록으로 남긴다. 허브 위치가 바뀌면 `fleet.link_provisioned` 이벤트로 보이므로, 뜻밖의 변경은 그 이벤트로 찾는다.
- SAF-003이 실행 중 설정 변경을 따른다(5항). 기동 때 검증한 SAF-003 시간 값은 그대로 쓴다.
