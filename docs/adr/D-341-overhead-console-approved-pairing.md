## D-341 천장 카메라 앱은 mDNS로 사이트를 찾고, 관제 콘솔 승인으로 연결 자격을 받는다 — 발견은 여전히 자격을 주지 않는다

**Status:** Proposed (2026-09-29, 2026-09-29 독립 리뷰 반영 개정). 신뢰 모델과 첫 구현 조각(천장 카메라)의 계약을 정한다. 구현 GO, DEVICE·FIELD 승격, 로봇 FleetAgent 페어링 변경이 아니다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md) 2·4항 · [D-261](D-261-overhead-camera-app-skeleton.md) 5·6항 · [D-193](D-193-login-code-and-credential-lifecycle.md) 1항(일회용 코드 선례) · [D-269](D-269-device-server-contracts-and-ros-boundary.md) 4항 · [D-276](D-276-site-fleet-per-principal-api-authorization.md) · [D-302](D-302-site-registry-credential-separation.md) · [D-136](D-136-.md) 3항 · [D-95](D-95-device-observer-hold.md) · [D-345](D-345-design-philosophy-reaches-every-surface.md)(설치자 문구, 실행 파일 이름 `overhead`).
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
5. **지켜야 할 원칙.** 발견은 주소 **후보**일 뿐 자격·명령 경로를 주지 않는다(발견 규칙 v0.1, D-261, `deploy/site/README.md`). 이 ADR은 그 원칙을 없애지 않는다. 자격이 생기는 유일한 순간을 **이름 있는 운용자의 명시적 승인 + 설치자의 상호 확인**으로 못박고, 그 앞에 발견을 붙일 뿐이다.

### Decision

1. **새 절차 `rosy-pair/1`: 발견 → 요청 → 콘솔 승인 → 1회 수령 → 상호 확인.** 발견은 요청을 보낼 곳만 알려 준다. 자격은 승인과 상호 확인이 모두 끝나야 활성이 된다. 어느 단계든 끝나지 않으면 요청은 만료되고, 아무 흔적도 권한으로 남지 않는다.
2. **요청 경로와 요청자.**
   - 경로: 발견된 수신기와 같은 사이트 HTTPS 프록시(8443)의 Fleet 라우트 `/api/fleet/pairing/v1/...`. 라우트 이름은 `test_no_video_relay.py` 정규식(`camera|stream|proxy|preview|…`)에 걸리지 않는다. 역할 값 `overhead-camera`는 본문에만 싣는다.
   - 요청자: 같은 LAN에서 사이트 TLS 포트에 닿는 누구나 **요청**할 수 있다. 요청은 자격이 없는 유일한 Fleet 쓰기 라우트이며, 메모리의 대기 항목 하나를 만드는 것 말고 아무 부작용이 없다. 사용자 API 감사(`fleet_api_audit`)가 아닌 별도 페어링 감사 표에 남긴다.
   - Fleet이 TLS로 떠 있지 않으면(`--tls-cert` 없음) 페어링 라우트를 설치하지 않는다. TLS가 없는 광고(`tls` ≠ `required`)에는 앱이 요청 버튼을 띄우지 않는다.
3. **6자리 확인 코드 — 중계형 중간자를 막는다.**
   - 첫 요청 때 폰은 아직 사이트 CA를 모른다. 그래서 폰은 제시된 서버 leaf 인증서를 **검증하지 않고 기록**한다(leaf 인증서 DER의 SHA-256). 인증서 SAN에 광고된 `tls_host`가 없으면 즉시 중단한다. DER 해시는 Python 표준 라이브러리(`ssl.PEM_cert_to_DER_cert`)와 Android `X509Certificate.encoded`로 같게 계산되므로 `cryptography` 의존성이 필요 없다.
   - 커밋-공개 2단계로 코드를 만든다. (a) 폰이 `client_nonce`의 해시를 보내고 서버가 `request_id`와 `server_nonce`를 돌려준다. (b) 폰이 `client_nonce`를 공개한다. 양쪽이 `code = decimal6(SHA-256("rosy-pair/1" ‖ role ‖ request_id ‖ leaf_cert_sha256 ‖ client_nonce ‖ server_nonce))`를 계산한다. 서버는 자신의 실제 인증서로, 폰은 자기가 본 인증서로 계산한다.
   - 폰은 코드를 크게 띄운다. 운용자는 콘솔 승인 창에 **폰 화면의 코드를 직접 입력**한다. 콘솔은 코드를 보여 주지 않는다. 공개(b)가 끝난 요청만 코드를 받는다. 틀린 코드 3회면 그 요청은 거절로 닫힌다.
   - **이 코드가 막는 것과 못 막는 것.** 폰과 진짜 사이트 사이에 끼어 TLS를 중계하는 중간자는 두 쪽 인증서가 달라 코드가 어긋나고, 커밋 순서 때문에 코드를 맞출 확률이 시도당 10⁻⁶이다. 그러나 **가짜 `_rosy-overhead._tcp` 수신기가 스스로 사이트 행세를 하는 경우**(자기 Fleet으로 자기 요청을 승인)는 코드만으로 막지 못한다. 그 경우는 4항의 상호 확인이 막는다.
4. **상호 확인 — 폰이 사이트를 확인한다.**
   - 결과를 받은 폰은 자격을 **아직 저장하지 않고** 받은 사이트 CA 인증서의 짧은 지문(DER SHA-256 앞 16 hex, 4자씩 묶음)과 `credential_id`를 띄운다. 진짜 콘솔의 승인 완료 화면도 같은 두 값을 띄운다.
   - 설치자가 폰에서 "일치"를 누르면 폰이 저장하고 `confirm`을 보낸다. 서버는 이때 비로소 자격을 활성으로 바꾸고 Vision 동기화 목록에 넣는다. 가짜 수신기에 승인받은 폰은 진짜 콘솔에 같은 값이 없으므로 설치자가 확인할 수 없다.
   - 수령·확인 기한은 승인 후 120 s다. 기한을 넘긴 승인은 자동 회수된다.
5. **승인자는 이름 있는 `operator`다.** `require_named_operator`(D-276) 뒤에 둔다. `site-users.yaml`이 없는 단일 console 토큰 구성에서는 승인 라우트가 403을 낸다(403 문구는 라우트별로 매개변수화해 "mission admission" 문구를 재사용하지 않는다). `viewer`는 대기 요청을 볼 수만 있다. `policy-admin`은 D-276 표대로 정책 조건 전용이므로 승인 권한이 없다. 근거: 카메라 source 추가는 표시·대조용 관측 입력의 추가이며 sighting은 위치 추정·정책·`cmd_vel`에 들어가지 않는다(D-257 5항). 승인·거절·회수·확인은 principal_id와 함께 감사 표에 남는다.
6. **source는 `static` 또는 `paired` 하나다.** `site-cameras.yaml`의 source마다 자격 방식을 둔다. `static`은 지금처럼 `phone_token_env`가 필수이고 페어링 대상이 아니다. `paired`는 `phone_token_env`를 가질 수 없고 페어링으로만 자격을 받는다. Fleet과 Vision이 기동 때 이 규칙을 검사하고 어기면 기동을 거절한다. 운용자는 승인할 때 `paired` source 중 하나를 고른다. 폰이 보낸 기기 이름표는 표시용일 뿐 source를 정하지 않는다. `paired` source마다 활성 자격은 하나다. 폰 교체는 **먼저 회수, 그 다음 새 승인**이다. 활성 자격이 있는 source로의 승인은 409로 거절한다.
7. **대기 요청의 한도(사이트 전체 기준).** 원격 주소별 한도는 두지 않는다 — Caddy·uvicorn의 전달 주소 설정과 Docker Desktop NAT가 주소를 하나로 뭉개 공정하지도 믿을 만하지도 않다. 대신 대기 수명 300 s, 사이트 전체 동시 대기 16건, 사이트 전체 요청 30건/분, 요청별 조회 간격 ≥ 2 s, 요청 본문 4 KiB 상한, 알 수 없는 필드 거절(`extra=forbid`), 감사 행 보존 상한(최근 10,000행)을 둔다. 한도를 넘으면 429를 내고 기존 대기를 밀어내지 않는다.
8. **자격 수령은 1회, 서버 보관은 최소.**
   - 대기 요청은 **메모리에만** 둔다. `server_nonce`는 공개 때까지만 메모리에 있고, 공개 뒤에는 기동마다 새로 만든 메모리 키로 계산한 코드의 HMAC만 남긴다. 그래서 Fleet이 재시작하면 대기 요청은 사라지고 폰은 새로 요청한다(문서화된 동작).
   - 폰은 요청 때 `poll_secret`의 SHA-256만 보낸다. 결과 조회는 `poll_secret` bearer로만 되고, 조회 연결도 첫 요청 때 기록한 leaf로만 신뢰한다.
   - 응답: 카메라 토큰 원문(256 bit, 이때 한 번만), `source_id`, `tls_host`, 사이트 CA 인증서(PEM), `credential_id`, `expires_at`. 한 번 내려 준 뒤 서버는 원문을 버린다. 다시 조회하면 410이다. 폰이 확인 전에 죽으면 기한 만료 뒤 다시 페어링한다.
   - Fleet SQLite(기존 `/var/lib/rosy/fleet.sqlite3`)에는 자격 digest·메타데이터와 감사만 둔다. 원문 토큰, nonce, 코드, 폰 사진·영상은 저장하지 않는다.
9. **Android 신뢰: 사이트 CA 하나에만 고정.**
   - 수령 직후 폰은 (a) 기록한 leaf가 받은 CA로 체인 검증되고 (b) leaf SAN에 `tls_host`가 있는지 확인한다. 하나라도 틀리면 버린다.
   - 이후 모든 WSS 연결은 **받은 CA 하나만 든 전용 TrustManager**와 `tls_host` 호스트명 검사로 한다. 시스템·사용자 CA 저장소를 쓰지 않고, 사이트 CA를 Android 설정에 설치하지 않는다. 이 TrustManager는 오버헤드 링크의 OkHttp 클라이언트에만 붙고 앱 전역 신뢰를 바꾸지 않는다.
   - leaf 단독 고정은 쓰지 않는다. 사이트 leaf 교체마다 모든 폰을 다시 붙여야 하기 때문이다.
10. **인증서 교체.** 같은 CA로 leaf를 다시 발급하면(SAN 유지) 폰은 그대로 붙는다. CA가 바뀌면 고정 검증이 실패한다. 앱은 "사이트 인증서가 바뀌었습니다 — 다시 연결 요청이 필요합니다"를 띄우고 멈춘다. 다른 신뢰 저장소로 자동 전환하거나 새 인증서를 받아들이지 않는다.
11. **토큰 수명·회수·일시 장애.**
    - 기본 수명 180일. 콘솔은 자격 목록에 `expires_at`을 보여 준다. 만료 뒤에는 다시 페어링한다. 이 조각에는 자격 자체로 수명을 늘리는 경로가 없다.
    - 회수: 콘솔의 운용자가 즉시 회수한다. Vision은 Fleet에서 digest 목록을 **2 s마다** 동기화하고, 회수된 자격으로 붙어 있는 연결을 닫는다. 목표는 회수 후 5 s 안의 송신 중단이다.
    - **닫힘 코드를 둘로 나눈다.** `4401`은 "회수됐거나 모르는 자격"이며 최종이다 — 폰은 재시도를 멈추고 재페어링을 요구한다. 새 코드 `4503`은 "자격 상태를 지금 확인할 수 없음"(Vision이 아직 한 번도 동기화하지 못했거나, 마지막 정상 목록이 10분을 넘김)이며 재시도 대상이다 — 폰은 자격을 지우지 않고 백오프한다. WebSocket 업그레이드 단계도 같은 구분을 따른다(`401` 최종, `503`+`Retry-After` 재시도). 그래서 Fleet이 꺼진 채 Vision이 먼저 뜨더라도 폰은 멈추지 않고 기다린다.
    - 카메라 자격은 frames ingress 한 source 전용이다. Fleet 사용자 API, sighting 제출, preview, CORE에는 쓸 수 없다. 기존 자격 분리 규칙(D-302, `create_app`의 중복 거절)에 페어링 digest와 새 동기화 비밀을 더한다.
12. **Vision은 발급 자격을 동적으로 받는다.**
    - Vision은 새 전용 서비스 자격(`pairing_sync_token`, 다른 모든 비밀과 달라야 함)으로 Fleet의 `GET /api/fleet/pairing/v1/credentials?role=overhead-camera`를 **백엔드 주소 `https://fleet:8090`로 직접** 읽는다(Compose에서 프록시는 Vision보다 늦게 뜬다). 이 라우트는 사용자 `authorize`가 아닌 전용 인증 의존성을 쓴다 — `authorize`는 사용자 digest가 설정되면 다른 bearer를 모두 401로 막기 때문이다.
    - 응답은 `source_id`, token SHA-256, `credential_id`, `expires_at`뿐이다. 원문은 Vision에도 가지 않는다. Vision은 제시된 bearer의 SHA-256을 hello의 source에 묶인 digest와 상수 시간 비교한다. `static` source의 환경 변수 토큰은 지금처럼 동작한다.
13. **IP가 바뀌면 mDNS로 다시 찾는다.**
    - 폰은 페어링 결과로 `tls_host`, 포트, CA, source, 토큰을 저장한다. IP는 저장하지 않는다.
    - 연결이 **연속 3회** 실패하면 `_rosy-overhead._tcp`를 다시 찾는다(최대 30 s에 한 번). 앱이 켜질 때도 찾는다. TXT `tls_host`가 저장값과 같은 레코드만 본다. 해석된 주소가 정확히 하나면 그 IP로 접속하되 SNI·호스트명은 `tls_host`, 신뢰는 고정 CA로 한다(OkHttp `Dns` 주입).
    - 같은 `tls_host`에 서로 다른 주소가 보이면 자동 선택을 멈추고 충돌을 표시한다(발견 규칙 2항). 광고가 없으면 백오프로 계속 찾는다. 광고 내용이 자격이나 CA를 바꾸는 일은 없다. 페어링 연결은 평문 ws로 낮추지 않는다.
14. **광고 TXT.** `_rosy-overhead._tcp`에 공개 키 `pair=rosy-pair/1`을 더한다. 이 키가 없는 수신기는 수동·딥링크 페어링만 지원하는 것으로 본다. 알 수 없는 키 무시 규칙 때문에 기존 앱과 호환된다. TXT에는 여전히 토큰·CA·사이트 식별 비밀을 넣지 않는다.
15. **발견 규칙 3·4항과의 관계.** 첫 접촉(요청·조회)은 광고된 `tls_host`를 후보로 쓸 수 있다. 상호 확인이 끝난 뒤에는 **페어링 결과로 받은 `tls_host`와 사이트 CA가 정본**이며 이후 광고는 주소만 공급한다. 이것이 규칙 3항("설치자가 예상 호스트명을 지정")과 4항("별도로 배포된 사이트 CA")을 대신하는 유일한 경로다.
16. **평문 ws LAN 모드(D-261 5)와 되돌림 경로.** 평문 모드는 바뀌지 않는다. `overhead receive`(D-345 보충으로 바뀐 실행 파일 이름)의 평문 ws + 수동/딥링크 토큰은 신뢰된 로컬 벤치 전용이다. `rosy-pair/1`은 평문 자격을 발급하지 않는다. 사이트에서 페어링이 고장 나면 **되돌림 경로는 `static` source + `rosyov://...&tls=1` 수동 입력**이며, 이 경로는 지금처럼 사이트 CA를 Android 사용자 인증서 저장소에 손으로 설치해야 한다. 멀티캐스트가 막힌 VLAN·격리 Wi-Fi도 같은 경로를 쓴다.
17. **로봇 `_rosy._tcp` 결과는 정보용으로 남는다.** 앱은 로봇 CORE 레코드를 계속 보여 줄 수 있지만 페어링 요청·프레임 송신 대상으로 쓰지 않는다. 페어링 클라이언트는 `role=overhead-camera`가 아닌 레코드를 거절한다(시험으로 고정). 로봇 FleetAgent 페어링(D-269 4항, `robots.yaml` `fleet_pairing_token`)은 이 절차로 옮기지 않는다.
18. **다른 관제 구성 요소로의 재사용(방향만).** 첫 조각은 역할을 상수 하나(`overhead-camera`)로 구현한다. 앞으로 다른 역할(예: 벽걸이 관제 표시기, 다른 관측 장치)이 필요하면 그 ADR이 역할별로 광고 서비스 종류, 승인 역할, 자격 범위, 묶을 대상, 수명을 정하고, 그때 상수를 역할 등록표로 넓힌다. 요청·확인 코드·상호 확인·1회 수령·CA 고정·회수·감사는 공유한다. 사람의 관제 로그인(D-276 개인 credential)은 기기 자격과 다르며 이 절차로 발급하지 않는다.
19. **시험 벡터 공유.** 확인 코드 계산, 지문 표기, 요청·결과 JSON, 거절 사례를 `src/site/overhead/protocol/pairing_vectors.json`에 두고 Python(Fleet·Vision)과 Kotlin 시험이 같은 파일을 읽는다(D-261 1항과 같은 방식). 두 번째 역할이 생기면 공용 위치로 옮긴다.

### 판정 등급 (Acceptance gates)

| 등급 | 인정하는 증거 |
|---|---|
| SOURCE | 이 ADR, 계획, 발견 규칙·README·D-261 교차 참조. ADR Log 연속성 시험 녹색 |
| LOCAL | Fleet·overhead pytest, Kotlin JVM 시험이 같은 `pairing_vectors.json`으로 녹색. 페어링을 켠 구성에서도 `test_no_video_relay.py` 녹색. Compose 스택 + 합성 Python 클라이언트로 요청→승인→수령→상호 확인→WSS 고정 CA 송신→회수 후 `4401`, Fleet 정지 중 `4503` 후 재접속까지 재현. 중계형 중간자·가짜 수신기·CA 변경은 JVM/종단 시험으로 LOCAL에서 판정한다. Windows 벤치 PC에서 `compose up` + `https://<pc>.local:8443/healthz` 성공이 폰 작업 전 관문이다 |
| DEVICE | 실물 Android 폰(첫 기록은 S21)과 벤치 LAN, 사이트 CA를 Android 설정에 설치하지 않은 상태: 발견→요청→콘솔 코드 입력 승인→상호 확인→TLS 고정 송신 60 s 이상, 사이트 IP 변경 후 폰을 만지지 않고 재연결(옛/새 IP·재연결 시간 기록), 회수 후 5 s 안에 송신 중단, CA 변경 확인 1회. 같은 벤치 Fleet의 `robots.yaml`에 실제 로봇 `rosy-pinky-8kcn`(`http://192.168.1.202:8080`)을 두고 preview 비밀을 켜서, 콘솔 "관제 카메라"에 페어링된 카메라의 실시간 프레임과 로스터의 로봇이 함께 보이는 화면 캡처. 절차는 계획의 벤치 절차 |
| FIELD | 실제 Ubuntu 사이트 호스트(Avahi, Compose, 사이트 CA)와 천장 거치 폰 30분 이상, 사이트 DHCP 변경·재부팅 포함. D-210 범위 판단은 별도 |

로컬 시험 통과는 DEVICE가 아니고, 벤치 폰 통과는 FIELD가 아니다(D-95). 차선 지도 위 sighting 표시는 이 ADR의 판정 대상이 아니며 진행 중인 `feat/console-site-map-layer`(사이트 사각형 지도 + sighting 겹침)에 의존한다.

### 이 ADR이 정하지 않는 것

- CA 교체를 미리 알리는 "다음 CA" 사전 배포(지금은 CA가 바뀌면 재페어링).
- 자격으로 수명을 늘리는 in-band 갱신 경로, 180일 기본값의 현장별 조정, 만료 임박 경고 UI.
- 대기 한도(300 s, 16건, 30건/분, 120 s 수령 기한)의 현장 튜닝.
- 카메라 외 역할과 역할 등록표, 공용 벡터 위치 이전, `_rosy-fleet._tcp`에 `pair` 키를 광고할지.
- 페어링 승인을 `operator`보다 좁은 별도 역할(예: 사이트 관리자)로 옮길지.
- 릴리스 빌드에서 `cleartextTrafficPermitted`를 끄는 빌드 분리(평문 벤치 모드 유지 여부와 연결됨).
- 로봇 FleetAgent 페어링의 통합, 사람 관제 로그인의 기기 페어링화.
- 사이트 간 로밍(한 폰이 여러 사이트 자격을 가지는 것).

### Alternatives

- *발견만으로 자동 페어링(TOFU)* — 같은 LAN의 아무 광고가 카메라 입력 자리를 차지한다. 발견 규칙 원칙 위반. 기각.
- *QR 딥링크에 토큰 + CA 지문을 싣기(오늘 방식 확장)* — 운용자가 콘솔에서 QR을 띄우고 폰 기본 카메라로 찍는다. 신뢰 경로는 좋지만 URI 자체가 자격이라 사진·로그에 새고(README가 이미 경고), IP 변경 재연결 문제는 그대로다. 멀티캐스트가 막힌 망의 대체 경로로만 남긴다.
- *Android 사용자 CA 설치 유지* — 설정 메뉴 경고 화면, 기기별 수동 작업, 앱 밖 전역 신뢰 변경이 남는다. 오늘 공백 그 자체라 기각(되돌림 경로로만 남김).
- *leaf 인증서 고정* — 구현은 가장 작지만 사이트 leaf 갱신마다 모든 폰이 재페어링된다. 기각.
- *SPKI 해시* — 공개키만 묶어 인증서 재발급에 강하지만 Python 쪽에 `cryptography` 의존성이 생긴다. 첫 접촉 기록은 수명이 몇 분이라 DER 해시로 충분하다. 기각.
- *Vision이 직접 페어링 요청을 받기* — Vision에는 운용자 신원·역할·감사가 없다. 승인은 Fleet의 D-276 principal이 해야 한다. 기각.
- *확인 코드 없이 콘솔에서 목록 클릭 승인* — 동시에 두 폰이 요청하면 잘못 고를 수 있고, 첫 TLS를 검증하지 못해 중간자를 잡을 수 없다. 기각.
- *상호 확인 없이 코드만* — 가짜 수신기의 자기 승인을 막지 못한다. 기각.

### Consequences

Fleet에 자격 없는 쓰기 라우트가 처음 생긴다. 그래서 한도·감사·부작용 없음을 시험으로 고정해야 한다. Fleet SQLite에 자격·감사 표가 생긴다. Vision은 Fleet 백엔드에 대한 읽기 의존과 새 서비스 비밀 하나를 얻고, 닫힘 코드 `4503`이 프로토콜에 더해진다. 앱은 CA 고정 TrustManager, 상호 확인 화면, mDNS 재발견 루프를 갖게 되어 실기 검증 범위가 늘어난다. 운용자는 카메라 설치 때 콘솔 앞에서 코드를 입력하고, 설치자는 폰과 콘솔의 지문을 맞춰 보는 단계를 맡는다.

### Validation / Transition

계획 1–5단계 LOCAL 녹색 → 벤치 절차의 S21 기록으로 DEVICE 판정 → 사이트 호스트에서 FIELD. 그 사이 D-261 5·6항 경로와 사용자 CA 설치 안내는 그대로 유효하다. 이 ADR이 Accepted가 되면 발견 규칙·README의 "사이트 CA를 Android 신뢰 저장소에 설치" 안내는 `static` source 수동 경로 전용으로 줄어든다.

**References:** D-95, D-136, D-193, D-257, D-261, D-269, D-276, D-302, D-345.

---
