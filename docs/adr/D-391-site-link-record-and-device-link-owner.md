## D-391 앱은 사이트 연결을 같은 모양(이름·CA·자격, IP 없음)으로 저장하고, 기기 연결 서버는 Fleet "기기 연결"이 맡는다

**Status:** Proposed (2026-10-01). 사이트 연결 기록의 모양, 사이트 호스트 설정의 원천, 기기 연결(카메라 페어링) 서버의 자리와 구현 순서를 정한다.

**번호:** 처음 D-387로 적었으나 `docs/ota-roadmap-adr`가 먼저 선점해 D-390으로, 다시 Pilot OMX 시뮬 초안이 D-390을 잡아 D-391로 옮겼다(2026-10-01, main 88915131에 선점 기록).

**담당(2026-10-01 병행 세션 결정 회차):** 4항 1·2·3·5단계와 1항 벡터·FleetAgent 로더, 3항 일관성 검사 도구는 rosy-00. 4항 4단계(Rosy Cam 사이트 연결 저장·재발견·진단·페어링 클라이언트)와 1단계의 Kotlin 쪽은 rosy-84(사용자 직접 요청), rosy-75·63이 리뷰.

잇는 결정: [D-341](D-341-overhead-console-approved-pairing.md)(카메라 콘솔 승인 페어링) · [D-361](D-361-site-console-enrolls-robot-by-screen-code.md)(로봇 등록) · [D-370](D-370-site-app-roles-names-and-shared-link.md) 5.2–5.5(기기 연결·주소·전송·실패 어휘) · [D-382](D-382-robot-site-console-protocol-conformance.md)(계약 판) · [D-374](D-374-app-identity-follows-one-role-name.md)·[D-377](D-377-app-names-rosy-plus-one-english-word.md)(이름).

### Context

1. **2026-10-01 점검.** 앱들이 mDNS와 공통 구조를 공유하는지 main(20d43df0)을 읽기 전용으로 대조했다.
   - **발견은 하나로 모였다.** 공유 TXT 벡터 `test/fixtures/protocol/discovery-txt.v1.json`과 정본 파서 `core_common.protocol.discovery_txt`가 있고, 단독 스크립트 두 개와 Kotlin 파서도 같은 벡터로 시험한다(D-370 S1).
   - **데이터 전송도 정리돼 있다.** Rosy Cam → Vision(WSS, 적응 JPEG, hello `lens`), Vision → Fleet(자세만, 미리보기 lease), 로봇 → Fleet(`/ws/robots`, D-382 F6 수정).
   - **연결 설정은 앱마다 다르다.**

     | 앱 | 주소 | 신뢰 | 자격 | 저장 |
     |---|---|---|---|---|
     | Rosy Cam | mDNS 목록 또는 `rosyov://` 링크의 host | Android 사용자 CA 설치(오늘) 또는 링크의 CA pin(착지 중) | 링크의 토큰 | 앱 설정 |
     | FleetAgent(로봇) | 설정 `hub_url` 또는 mDNS + `expected_hostname` | `ca_file` | `pairing_token` | 로봇 카드 설정 |
     | Vision(사이트 호스트) | Compose 서비스 이름 | 사이트 CA 파일 | 환경 변수·Compose secret | `/run/rosy-config/`, secrets |
     | Fleet(사이트 호스트) | `robots.yaml`의 로봇 주소 | 로봇은 평문 HTTP(D-370 5.3) | `robots.yaml` 토큰, 등록 저장소 | `/run/rosy-config/`, SQLite |
     | Pilot·대시보드 | CORE same-origin | 해당 없음 | 로봇 로그인 코드 | 브라우저 세션 |

   - 같은 뜻의 값(사이트 이름, `tls_host`, CA, 자격 수명)이 앱마다 다른 이름·다른 곳에 있다. 사이트 인증서가 leaf만 담아 CA pin이 실패한 일(2026-09-30), 폰이 `.local`을 못 풀어 IP 링크에 IP SAN이 필요했던 일이 이 어긋남에서 나왔다.
2. **기기 연결 서버가 없다.** D-341(설계 Accepted)의 `pairing/v1` 서버, "기기 연결" 패널의 카메라 구역, 실패 분류 공유 벡터(D-370 S6)가 main에도 브랜치에도 없다. 로봇 등록(D-361 S1)은 먼저 착지해 `device_pairing_audit` 표와 콘솔 등록 화면(`enrollment.js`)을 만들었다. 담당이 정해지지 않아 Rosy Cam 연결은 여전히 링크·QR 수동 경로다.

### Decision

1. **사이트 연결 기록은 한 모양이다.** 사이트에 붙는 클라이언트(Rosy Cam, FleetAgent)는 같은 필드로 저장한다.
   - 필드: `site_name`, `tls_host`, `port`, `ca_pem`(사이트 CA; leaf 단독 금지), `role`(자기 역할), `credential_id`, `expires_at`, 자격 원문 또는 그 저장 참조.
   - **IP를 저장하지 않는다.** 주소는 (재)접속할 때마다 mDNS로 찾고, 신원은 `tls_host`와 고정 CA로 확인한다(D-341 13항, D-370 5.3 "이름을 따라가는 채널").
   - **접속 방법:** Android는 `*.local`을 일반 DNS로 풀지 못한다(S21 실측). 그래서 NSD가 준 IP로 TCP를 열되, TLS의 SNI와 호스트명 검사는 `tls_host`로 한다. 사이트 인증서 SAN에는 `tls_host`가 반드시 있다. IP SAN은 아래 수동 되돌림용이다.
   - **수동 되돌림 주소:** 멀티캐스트가 막힌 망에서는 `rosyov://` 링크에 IP를 담을 수 있다. 앱은 그 값을 `manual_host`로 따로 두고, mDNS가 사이트를 찾지 못할 때만 쓰며 화면에 "수동 주소"로 표시한다. 이 경로는 인증서에 그 IP SAN이 있어야 한다.
   - **"이 Wi-Fi에서 사이트가 보이지 않음" 진단:** 현재 망의 mDNS 탐색이 정해진 시간 안에 같은 `tls_host`를 못 찾으면, 일반 "연결할 수 없음" 대신 이 문구를 띄운다(같은 SSID를 쓰는 다른 AP·핫스팟에 붙은 경우가 실측됐다, 2026-10-01 태블릿). 실패 분류 벡터에 `not_discovered`로 둔다.
   - 예외는 D-370 5.3 그대로다. 평문 HTTP인 Fleet → CORE는 등록 때의 주소를 고정한다. Pilot·대시보드는 same-origin이라 기록이 없다.
   - 기계가 읽는 원천은 `test/fixtures/protocol/site-link.v1.json`(유효·무효 기록 예)이다. Kotlin 설정 저장소와 FleetAgent 설정 로더가 이 벡터로 시험한다. 새 클라이언트는 이 모양을 쓴다.
2. **기록을 얻는 길은 역할마다 하나이고, 저장 모양은 1항으로 같다.**
   - Rosy Cam: D-341 `rosy-pair/1`이 기본, `rosyov://` 링크(CA pin 포함)는 되돌림.
   - FleetAgent: D-361 등록이 자격을, 로봇 카드 설정의 `discovery`가 `tls_host`와 CA를 준다.
   - Vision·Fleet: 사이트 호스트 설정(3항).
   - 자격 모양과 보관 방식은 방향마다 다르다(D-370 5.2). 이 ADR은 저장 **필드 이름과 의미**만 맞춘다.
3. **사이트 호스트 설정의 원천은 `/run/rosy-config/` 하나다.** 새 파일 형식을 만들지 않는다.
   - `tls_host`, 사이트 CA, 공개 포트처럼 여러 서비스가 쓰는 값은 한 번만 적고(사이트 환경 파일), Compose·Caddy·광고 유닛·Vision·Fleet이 그 값을 읽는다.
   - `deploy/site`에 일관성 검사 도구를 둔다. 인증서 SAN에 `tls_host`와 광고 IP가 있는지, `site_cert`가 leaf + CA인지, TXT `tls_host`와 Caddy 호스트가 같은지 기동 전에 본다. 어기면 이유를 말하고 멈춘다.
4. **기기 연결 서버는 Fleet이 맡는다(D-341 결정 유지). 구현 순서:**
   1. **공통 조각:** `device_kind` 값(`overhead-camera`, `robot`)을 `core_common`의 상수 하나로 둔다. 실패 분류 벡터 `test/fixtures/protocol/failure-classes.v1.json`(D-370 5.5 분류 + `not_discovered`)을 D-341 11항 닫힘 코드 분류표와 HTTP 상태에서 만든다. 최소 행: WS 4400·4401·4403·4409·4503·1013, HTTP 401·403·409·429·503. 벡터는 "입력 → 분류"만 정하고, 각 클라이언트는 그 위에 자기 상태를 둔다(예: Pilot은 forbidden→FORBIDDEN, auth_final→OFFLINE, conflict→BLOCKED, 나머지→RETRYING). Rosy Cam `NetworkFailure`·`ProblemGuide`와 `web_common` 연결 코드가 이 벡터로 시험한다.
   2. **Fleet `pairing/v1` 서버:** D-341 1–12항. 감사는 `device_pairing_audit` 재사용(D-341 8항).
   3. **콘솔 "기기 연결" 패널:** 기존 로봇 등록 화면 옆에 카메라 연결 승인 구역을 더한다(D-361 11항).
   4. **Rosy Cam 페어링 클라이언트:** 요청·코드·상호 확인·1항 기록 저장.
   5. **Vision digest 동기화와 회수:** D-341 11·12항.
   - 각 단계는 LOCAL 녹색으로 main에 들어간다. DEVICE는 D-341 판정 등급을 따른다.
5. **공개 상태 모양 확장(D-370 5.5)은 로봇이 따라온 뒤에 한다.** 추가 필드를 허용하는 health 탐침(2026-10-01 수정)이 현장 로봇 모두에 깔리기 전에는 Fleet `/healthz`에 필드를 더하지 않는다. 옛 코드는 본문이 정확히 `{"status":"ok"}`여야 Fleet으로 인정한다. 이 탐침은 `src/`에 있어 이미지 재굽기 없이 payload push로 간다(rosy-0d 확인). 확장은 두 벤치 로봇이 그 payload를 받은 뒤 한다.

### 정하지 않는 것

- CORE TLS와 장치 신원 증명(D-370 8항). 그 전까지 Fleet → CORE는 고정 주소다.
- 한 클라이언트가 여러 사이트 기록을 갖는 로밍.
- Pilot 설치형의 사이트 설정(Pilot은 로봇 same-origin 앱이다).
- 사이트 환경 파일의 정확한 변수 이름. 3항 구현 회차가 정한다.

### Alternatives

- **공개 "사이트 설명서" 엔드포인트를 새로 둔다**(`GET /api/fleet/site/v1`에 이름·서비스·CA 지문). 기각. 설명서를 믿으려면 이미 CA를 알아야 하고, 신뢰는 어차피 역할별 절차(페어링·등록)에서 생긴다. 발견은 mDNS TXT가, 신원은 TLS가 이미 맡는다.
- **모든 앱이 하나의 사이트 토큰을 쓴다.** 기각. D-370 5.2대로 방향마다 원문 보관자가 다르다. 하나로 합치면 가장 약한 보관 방식에 맞춰진다.
- **Vision이 카메라 페어링을 직접 받는다.** 기각(D-341 대안 절). 운용자 신원·감사는 Fleet에 있다.

### Consequences

- 새 클라이언트는 연결 설정을 새로 설계하지 않고 1항 모양을 쓴다. 필드 이름이 같아 지원·문서·문제 안내 문구를 공유할 수 있다.
- 사이트 설치에서 인증서·광고·프록시 어긋남이 기동 전에 드러난다.
- Fleet에 기기 연결 서버와 패널이 생기고, 콘솔 운용자가 카메라 설치 때 코드를 입력한다(D-341 결과 그대로).

### Validation

- SOURCE: 이 ADR, ADR Log 행, D-370·D-341 교차 참조.
- LOCAL: `site-link.v1.json`·`failure-classes.v1.json`을 Kotlin·Python(·JS) 시험이 같이 읽어 녹색. 일관성 검사 도구가 leaf 단독 인증서·SAN 누락·TXT 불일치를 각각 거절하는 시험.
- DEVICE·FIELD: D-341 판정 등급.

**References:** D-341, D-361, D-370, D-374, D-377, D-382.
