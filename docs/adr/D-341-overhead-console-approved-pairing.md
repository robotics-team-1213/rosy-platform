## D-341 천장 카메라 앱은 mDNS로 사이트를 찾고, 관제 콘솔 승인으로 연결 자격을 받는다 — 발견은 여전히 자격을 주지 않는다

**Status:** Proposed (2026-09-29). 신뢰 모델과 첫 구현 조각(천장 카메라)의 계약을 정한다. 구현 GO, DEVICE·FIELD 승격, 로봇 FleetAgent 페어링 변경이 아니다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md) 2·4항 · [D-261](D-261-overhead-camera-app-skeleton.md) 5·6항 · [D-193](D-193-login-code-and-credential-lifecycle.md) 1항(일회용 코드 선례) · [D-269](D-269-device-server-contracts-and-ros-boundary.md) 4항 · [D-276](D-276-site-fleet-per-principal-api-authorization.md) · [D-302](D-302-site-registry-credential-separation.md) · [D-136](D-136-.md) 3항 · [D-95](D-95-device-observer-hold.md).
발견 규칙: [`docs/reference/site-lan-discovery-profile.md`](../reference/site-lan-discovery-profile.md). 실행 계획: [`docs/plans/2026-09-29-overhead-console-pairing-plan.md`](../plans/2026-09-29-overhead-console-pairing-plan.md).

### Context

1. **현재 연결 경로.** 폰은 `rosyov://<host>:<port>/?t=<token>&s=<source>[&tls=1]` 딥링크 또는 수동 입력으로 주소·토큰·source를 받는다(D-261 6). 사이트 수신기는 `_rosy-overhead._tcp`로 광고되고(`deploy/site/fleet-mdns.py`, TXT `product`·`role`·`proto`·`tls=required`·`tls_host`), 앱의 `OverheadServerDiscovery`가 이를 목록으로 보여 준다. Vision은 source별 토큰을 환경 변수에서만 읽는다(`overhead/vision_config.py` `phone_token_env`, Compose secret `phone_ingress_token`). 토큰을 발급·회수하는 서버 쪽 경로는 없다.
2. **2026-09-29 벤치 실측(LOCAL, DEVICE 아님).** Galaxy S21(SM-G991N, Android 15), Wi-Fi `1213_device`, PC 192.168.1.102, 디버그 APK.
   - 앱 NSD가 시험용 `_rosy-overhead._tcp`(python-zeroconf로 Avahi 대역, `tls_host` `perpros.local`, 포트 8095)와 실제 로봇 `_rosy._tcp` `rosy-pinky-8kcn` 192.168.1.202:8080을 함께 찾았다.
   - `rosyov://` 딥링크 + 평문 ws(TLS 끔)로 약 60 s 송신: 3 fps, 약 70 KB/s, 178 프레임, `seq_gaps=0`, 드롭 0, `age_ms` p50 약 110–120.
3. **드러난 공백.**
   - 발견한 수신기를 고르면 host/port/TLS만 채워진다. 토큰은 여전히 손으로 넣는다.
   - TLS 경로는 사이트 CA를 Android 사용자 인증서 저장소에 손으로 설치해야 한다. 그래서 TLS 전용으로 광고되는 수신기는 오늘 끝까지 쓸 수 없다. 평문 ws는 D-261 5항대로 신뢰된 로컬 개발에만 허용된다.
   - 사이트 PC의 IP가 바뀌면 저장된 주소가 낡는다. 폰은 다시 페어링해야 한다.
4. **사용자 결정(2026-09-29): 콘솔 승인 모델.** 앱이 mDNS로 Site Vision 수신기를 찾아 페어링 요청을 보낸다. 운용자가 Fleet 콘솔에서 승인한다. 사이트는 카메라별 토큰과 사이트 CA를 준다. 이후 앱은 IP가 바뀌어도 mDNS로 다시 찾아 붙는다. 같은 방식을 다른 관제 구성 요소에도 쓸 수 있어야 한다.
5. **지켜야 할 원칙.** 발견은 주소 **후보**일 뿐 자격·명령 경로를 주지 않는다(발견 규칙 v0.1, D-261, `deploy/site/README.md`). 이 ADR은 그 원칙을 없애지 않는다. 자격이 생기는 유일한 순간을 **이름 있는 운용자의 명시적 승인**으로 못박고, 그 앞에 발견을 붙일 뿐이다.

### Decision

1. **새 절차 `rosy-pair/1`: 발견 → 요청 → 콘솔 승인 → 1회 수령.** 발견은 요청을 보낼 곳만 알려 준다. 자격은 승인 뒤 1회 수령으로만 생긴다. 승인이 없으면 요청은 만료되고, 아무 흔적도 권한으로 남지 않는다.
2. **요청 경로와 요청자.**
   - 경로: 발견된 수신기와 같은 사이트 HTTPS 프록시(8443)의 Fleet 라우트 `/api/fleet/pairing/v1/...`. 라우트 이름은 `test_no_video_relay.py` 정규식(`camera|stream|proxy|preview|…`)에 걸리지 않는다. 역할 값 `overhead-camera`는 본문에만 싣는다.
   - 요청자: 같은 LAN에서 사이트 TLS 포트에 닿는 누구나 **요청**할 수 있다. 요청은 자격이 없는 유일한 Fleet 쓰기 라우트이며, 대기 행 하나를 만드는 것 말고 아무 부작용이 없다. 사용자 API 감사(`fleet_api_audit`)가 아닌 별도 페어링 감사 표에 남긴다.
   - 평문 HTTP·ws로는 요청할 수 없다. TLS가 없는 광고(`tls` ≠ `required`)에는 요청 버튼을 띄우지 않는다.
3. **잘못된 기기·중간자 승인을 막는 6자리 확인 코드(SAS).**
   - 첫 요청 때 폰은 아직 사이트 CA를 모른다. 그래서 폰은 제시된 서버 인증서를 **검증하지 않고 기록**한다(leaf SPKI SHA-256). 인증서 SAN에 광고된 `tls_host`가 없으면 즉시 중단한다.
   - 커밋-공개 2단계로 확인 코드를 만든다. (a) 폰이 `client_nonce`의 해시를 보내고 서버가 `request_id`와 `server_nonce`를 돌려준다. (b) 폰이 `client_nonce`를 공개한다. 양쪽이 `code = decimal6(SHA-256("rosy-pair/1" ‖ role ‖ request_id ‖ leaf_spki_sha256 ‖ client_nonce ‖ server_nonce))`를 계산한다. 서버는 자신의 실제 인증서로, 폰은 자기가 본 인증서로 계산한다. 중간자가 끼면 두 인증서가 달라 코드가 어긋나고, 커밋 순서 때문에 중간자가 코드를 맞출 확률은 시도당 10⁻⁶이다.
   - 폰은 코드를 크게 띄운다. 운용자는 콘솔 승인 창에 **폰 화면의 코드를 직접 입력**한다. 서버가 계산값과 같을 때만 승인된다. 목록에서 클릭만으로는 승인되지 않는다. 틀린 코드 3회면 그 요청은 거절로 닫힌다.
4. **승인자는 이름 있는 `operator`다.** `require_named_operator`(D-276) 뒤에 둔다. `site-users.yaml`이 없는 단일 console 토큰 구성에서는 승인 라우트가 403을 낸다. `viewer`는 대기 요청을 볼 수만 있다. `policy-admin`은 D-276 표대로 정책 조건 전용이므로 승인 권한이 없다. 근거: 카메라 source 추가는 표시·대조용 관측 입력의 추가이며 sighting은 위치 추정·정책·`cmd_vel`에 들어가지 않는다(D-257 5항). 승인·거절·회수는 principal_id와 함께 감사 표에 남는다.
5. **승인은 요청을 사이트 설정의 source에 묶는다.** 운용자는 Fleet이 이미 아는 source 목록(sightings 설정의 `source_id`) 중 하나를 고른다. 폰이 보낸 기기 이름표는 표시용일 뿐 source를 정하지 않는다. `(role, source_id)`마다 활성 자격은 하나다. 이미 활성 자격이 있는 source를 고르면 콘솔이 "교체"를 한 번 더 확인하고, 승인과 동시에 이전 자격을 회수한다(폰 교체 경로).
6. **대기 요청의 한도.** 대기 수명 300 s, 사이트 전체 대기 상한 16건, 원격 주소당 동시 대기 1건, 원격 주소당 요청 10건/분, 결과 조회 간격 ≥ 2 s. 한도를 넘으면 429를 내고 기존 대기 행을 밀어내지 않는다. 만료·거절 행은 감사에만 남고 승인 대상에서 사라진다.
7. **자격 수령은 1회, 보관은 digest만.**
   - 폰은 요청 때 `poll_secret`의 SHA-256만 보낸다. 승인 뒤 결과 조회는 `poll_secret` bearer로만 된다. 조회 연결도 첫 요청 때 기록한 leaf SPKI로만 신뢰한다.
   - 응답: 카메라 토큰 원문(256 bit, 이때 한 번만), `source_id`, `tls_host`, 사이트 CA 인증서(PEM), CA SPKI SHA-256, `credential_id`, `expires_at`. 한 번 내려 준 뒤 서버는 원문을 버린다. 다시 조회하면 410이다. 폰이 저장 전에 죽으면 다시 페어링한다.
   - Fleet SQLite(기존 `/var/lib/rosy/fleet.sqlite3`)에는 요청·자격 모두 digest와 메타데이터만 둔다. 원문 토큰, nonce 원문, 폰 사진·영상은 저장하지 않는다.
8. **Android 신뢰: 사이트 CA 하나에만 고정.**
   - 수령 직후 폰은 (a) 기록한 leaf가 받은 CA로 체인 검증되고 (b) leaf SAN에 `tls_host`가 있는지 확인한다. 하나라도 틀리면 저장하지 않는다.
   - 이후 모든 WSS 연결은 **받은 CA 하나만 든 전용 TrustManager**와 `tls_host` 호스트명 검사로 한다. 시스템·사용자 CA 저장소를 쓰지 않고, 사이트 CA를 Android 설정에 설치하지 않는다. 이 TrustManager는 오버헤드 링크의 OkHttp 클라이언트에만 붙고 앱 전역 신뢰를 바꾸지 않는다.
   - leaf 단독 TOFU 고정은 쓰지 않는다. 사이트 leaf 교체마다 모든 폰을 다시 붙여야 하기 때문이다.
9. **인증서 교체.**
   - 같은 CA로 leaf를 다시 발급하면(SAN 유지) 폰은 그대로 붙는다.
   - CA가 바뀌면 고정 검증이 실패한다. 앱은 "사이트 인증서 변경 — 재페어링 필요"를 띄우고 멈춘다. 다른 신뢰 저장소로 자동 전환하거나 새 인증서를 받아들이지 않는다. 운용자가 다시 승인해야 한다.
10. **토큰 수명·회수.**
    - 기본 수명 180일. 콘솔은 만료 30일 전부터 경고한다. 만료 뒤에는 다시 페어링한다. 이 조각에는 자격 자체로 수명을 늘리는 경로가 없다.
    - 회수: 콘솔의 운용자가 즉시 회수한다. Vision은 Fleet에서 digest 목록을 5 s마다 동기화하고, 회수된 자격으로 붙어 있는 연결을 `4401`로 닫는다. 폰은 `4401`을 받으면 재시도 루프를 멈추고 재페어링을 요구한다.
    - 카메라 자격은 frames ingress 한 source 전용이다. Fleet 사용자 API, sighting 제출, preview, CORE에는 쓸 수 없다. 기존 자격 분리 규칙(D-302, `create_app`의 중복 거절)에 페어링 digest를 더한다.
11. **Vision은 발급 자격을 동적으로 받는다.**
    - Vision은 새 전용 서비스 자격(`pairing_sync_token`, 다른 모든 비밀과 달라야 함)으로 `GET /api/fleet/pairing/v1/credentials?role=overhead-camera`를 읽는다. 응답은 `source_id`, token SHA-256, `credential_id`, `expires_at`뿐이다. 원문은 Vision에도 가지 않는다.
    - Vision은 제시된 bearer의 SHA-256을 hello의 source에 묶인 digest와 상수 시간 비교한다. 환경 변수 정적 토큰(D-261·현 Compose)은 벤치와 비상용으로 계속 동작한다.
    - Fleet에 닿지 못하면 마지막 정상 목록을 최대 10분 쓰고, 그 뒤에는 페어링 자격을 모두 거절한다(정적 토큰만 남음).
12. **IP가 바뀌면 mDNS로 다시 찾는다.**
    - 폰은 페어링 결과로 `tls_host`, 포트, CA SPKI, source, 토큰을 저장한다. IP는 저장하지 않는다.
    - 연결이 끊겨 백오프가 한 주기를 돌거나 앱이 켜질 때 `_rosy-overhead._tcp`를 다시 찾는다. TXT `tls_host`가 저장값과 같은 레코드만 본다. 해석된 주소가 정확히 하나면 그 IP로 접속하되 SNI·호스트명은 `tls_host`, 신뢰는 고정 CA로 한다(OkHttp `Dns` 주입).
    - 같은 `tls_host`에 서로 다른 주소가 보이면 자동 선택을 멈추고 충돌을 표시한다(발견 규칙 2항). 광고가 없으면 백오프로 계속 찾는다. 광고 내용이 자격이나 CA를 바꾸는 일은 없다.
13. **광고 TXT.** `_rosy-overhead._tcp`에 공개 키 `pair=rosy-pair/1`을 더한다. 이 키가 없는 수신기는 수동·딥링크 페어링만 지원하는 것으로 본다. 알 수 없는 키 무시 규칙 때문에 기존 앱과 호환된다. TXT에는 여전히 토큰·CA·사이트 식별 비밀을 넣지 않는다.
14. **평문 ws LAN 모드(D-261 5)와의 관계.** 바뀌지 않는다. `overhead.cli receive`의 평문 ws + 수동/딥링크 토큰은 신뢰된 로컬 벤치 전용으로 남는다. `rosy-pair/1`은 평문 ws 자격을 발급하지 않는다. 앱은 페어링으로 받은 연결을 평문으로 낮추지 않는다. 멀티캐스트가 막힌 VLAN·격리 Wi-Fi에서는 기존 `rosyov://...&tls=1` 수동 경로를 쓴다.
15. **로봇 `_rosy._tcp` 결과는 정보용으로 남는다.** 앱은 로봇 CORE 레코드를 계속 보여 줄 수 있지만 페어링 요청·프레임 송신 대상으로 쓰지 않는다. 페어링 클라이언트는 `role=overhead-camera`가 아닌 레코드를 거절한다(시험으로 고정). 로봇 FleetAgent 페어링(D-269 4항, `robots.yaml` `fleet_pairing_token`)은 이 절차로 옮기지 않는다.
16. **다른 관제 구성 요소로의 재사용.**
    - `rosy-pair/1`은 역할(role) 단위로 일반화한다. Fleet은 역할 등록표를 가진다. 항목마다 광고 서비스 종류, 승인 역할, 자격 범위(어떤 소비자가 어떤 경로에서만 받는지), 묶을 대상 목록의 출처, 수명을 정한다.
    - 첫 항목은 `overhead-camera` 하나다: `_rosy-overhead._tcp`, `operator`, Vision frames ingress 한 source, sightings 설정의 source, 180일.
    - 새 역할(예: 벽걸이 관제 표시기, 다른 관측 장치)은 **자기 ADR로 등록표 항목을 추가**한다. 요청·확인 코드·1회 수령·CA 고정·회수·감사는 공유하고, 자격 범위와 승인 역할만 역할별로 정한다.
    - 사람의 관제 로그인(D-276 개인 credential)은 기기 자격과 다르다. 이 절차로 사람 역할을 발급하지 않는다.
17. **시험 벡터 공유.** 확인 코드 계산, 요청·결과 JSON, 거절 사례를 `src/site/overhead/protocol/pairing_vectors.json`에 두고 Python(Fleet·Vision)과 Kotlin 시험이 같은 파일을 읽는다(D-261 1항과 같은 방식). 두 번째 역할이 생기면 공용 위치로 옮긴다.

### 판정 등급 (Acceptance gates)

| 등급 | 인정하는 증거 |
|---|---|
| SOURCE | 이 ADR, 계획, 발견 규칙·README·D-261 교차 참조. ADR Log 연속성 시험 녹색 |
| LOCAL | Fleet·overhead pytest, Kotlin JVM 시험이 같은 `pairing_vectors.json`으로 녹색. `test_no_video_relay.py` 녹색. Compose 스택 + 합성 Python 클라이언트로 요청→승인→수령→WSS 고정 CA 송신→회수 후 `4401`까지 한 번에 재현. 에뮬레이터 결과도 LOCAL이다 |
| DEVICE | 실물 Android 폰(첫 기록은 S21)과 벤치 LAN: 사이트 CA를 Android 설정에 설치하지 않은 상태에서 발견→요청→콘솔 코드 입력 승인→TLS 고정 송신 60 s 이상, PC IP 변경 후 수동 조작 없이 재연결, 회수 후 5 s 안에 송신 중단, 다른 CA 인증서로 바꾸면 연결 거부. 기록 스크립트는 계획 5단계 |
| FIELD | 실제 Ubuntu 사이트 호스트(Avahi, Compose, 사이트 CA)와 천장 거치 폰 30분 이상, 사이트 DHCP 변경·재부팅 포함. D-210 범위 판단은 별도 |

로컬 시험 통과는 DEVICE가 아니고, 벤치 폰 통과는 FIELD가 아니다(D-95).

### 이 ADR이 정하지 않는 것

- CA 교체를 미리 알리는 "다음 CA" 사전 배포(지금은 CA가 바뀌면 재페어링).
- 자격으로 수명을 늘리는 in-band 갱신 경로, 180일 기본값의 현장별 조정.
- 대기 한도(300 s, 16건, 10건/분)의 현장 튜닝.
- 카메라 외 역할의 등록표 항목, 공용 벡터 위치 이전, `_rosy-fleet._tcp`에 `pair` 키를 광고할지.
- 페어링 승인을 `operator`보다 좁은 별도 역할(예: 사이트 관리자)로 옮길지.
- 릴리스 빌드에서 `cleartextTrafficPermitted`를 끄는 빌드 분리(평문 벤치 모드 유지 여부와 연결됨).
- 로봇 FleetAgent 페어링의 통합, 사람 관제 로그인의 기기 페어링화.
- 사이트 간 로밍(한 폰이 여러 사이트 자격을 가지는 것).

### Alternatives

- *발견만으로 자동 페어링(TOFU)* — 같은 LAN의 아무 광고가 카메라 입력 자리를 차지한다. 발견 규칙 원칙 위반. 기각.
- *QR 딥링크에 토큰 + CA 지문을 싣기(오늘 방식 확장)* — 운용자가 콘솔에서 QR을 띄우고 폰 기본 카메라로 찍는다. 신뢰 경로는 좋지만 URI 자체가 자격이라 사진·로그에 새고(README가 이미 경고), IP 변경 재연결 문제는 그대로다. 멀티캐스트가 막힌 망의 대체 경로로만 남긴다.
- *Android 사용자 CA 설치 유지* — 설정 메뉴 경고 화면, 기기별 수동 작업, 앱 밖 전역 신뢰 변경이 남는다. 오늘 공백 그 자체라 기각.
- *leaf 인증서 SPKI 고정* — 구현은 가장 작지만 사이트 leaf 갱신마다 모든 폰이 재페어링된다. 기각.
- *Vision이 직접 페어링 요청을 받기* — Vision에는 운용자 신원·역할·감사가 없다. 승인은 Fleet의 D-276 principal이 해야 한다. 기각.
- *확인 코드 없이 콘솔에서 목록 클릭 승인* — 동시에 두 폰이 요청하면 잘못 고를 수 있고, 첫 TLS를 검증하지 못해 중간자를 잡을 수 없다. 기각.

### Consequences

Fleet에 자격 없는 쓰기 라우트가 처음 생긴다. 그래서 한도·감사·부작용 없음을 시험으로 고정해야 한다. Fleet SQLite에 페어링 요청·자격·감사 표가 생긴다. Vision은 Fleet에 대한 읽기 의존과 새 서비스 비밀 하나를 얻는다. 앱은 CA 고정 TrustManager와 mDNS 재발견 루프를 갖게 되어 실기 검증 범위가 늘어난다. 운용자는 카메라 설치 때 콘솔 앞에서 6자리 코드를 입력하는 한 단계를 맡는다.

### Validation / Transition

계획 1–4단계 LOCAL 녹색 → 5단계 S21 벤치 기록으로 DEVICE 판정 → 사이트 호스트에서 FIELD. 그 사이 D-261 5·6항 경로와 사용자 CA 설치 안내는 그대로 유효하다. 이 ADR이 Accepted가 되면 발견 규칙·README의 "사이트 CA를 Android 신뢰 저장소에 설치" 안내는 수동 경로 전용으로 줄어든다.

**References:** D-95, D-136, D-193, D-257, D-261, D-269, D-276, D-302.

---
