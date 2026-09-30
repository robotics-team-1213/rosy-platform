# 천장 카메라 콘솔 승인 페어링 — 실행 계획 (D-341)

- 날짜: 2026-09-29 (같은 날 독립 리뷰 반영 개정)
- 결정: [D-341](../adr/D-341-overhead-console-approved-pairing.md) (Proposed)
- 경로 읽기(2026-10-01): 이 계획의 `src/site/overhead/overhead/…`(Python)는 `src/site/vision/rosy_vision/…`, `src/site/overhead/android/…`는 `src/site/cam/…`, CLI `overhead`는 `rosy-vision`이다(D-374·D-377). 닫힘 코드는 D-341 11항 분류표를 따른다.
- 잇는 문서: [D-261](../adr/D-261-overhead-camera-app-skeleton.md), [발견 규칙](../reference/site-lan-discovery-profile.md), [`deploy/site/README.md`](../../deploy/site/README.md)
- 의존: 콘솔의 사이트 사각형 지도 + sighting 겹침은 진행 중인 `feat/console-site-map-layer`(`GET /api/fleet/site-map`)가 맡는다. 이 계획은 그것을 다시 계획하지 않는다.
- 등급 목표: 1–5단계 LOCAL, 벤치 절차로 DEVICE(S21), FIELD는 사이트 호스트에서 별도

## 목표

폰 앱이 `_rosy-overhead._tcp`로 사이트를 찾아 페어링을 요청하고, 운용자가 Fleet 콘솔에서 폰의 6자리 코드를 입력해 승인하고, 설치자가 폰과 콘솔의 사이트 지문·자격 번호가 같음을 확인하면, 폰이 카메라 토큰과 사이트 CA를 저장해 CA 고정 WSS로 송신한다. 사이트 IP가 바뀌면 mDNS로 다시 찾아 붙는다. 사이트 CA를 Android 설정에 설치하지 않는다.

## 지킬 것 / 하지 않을 것

**지킬 것**

- 모든 단계는 시험 먼저(TDD). 실패하는 시험 → 최소 구현 → 녹색 → 커밋. 단계마다 커밋한다.
- 발견만으로는 어떤 자격도 생기지 않는다. 자격은 `require_named_operator` 승인 + 코드 일치 + 1회 수령 + 상호 확인으로만 활성이 된다.
- 저장소·SQLite·로그에 토큰 원문, `poll_secret`, nonce, 코드, 페어링 URI를 남기지 않는다.
- 페어링을 켠 구성에서도 `test_no_video_relay.py`는 녹색이다. 새 Fleet 라우트 경로에 `camera|stream|proxy|preview|video|image|jpeg|mjpeg|relay`를 쓰지 않는다.
- `static` source의 환경 변수 토큰 경로와 `rosyov://` 수동 경로는 그대로 동작한다.
- 실행 파일 이름은 `overhead`(D-345 보충), `fleet`이다. Windows에서는 `python`을 쓴다. 임시 DB·인증서·로그는 `X:\DevTemp\` 아래에 둔다.

**하지 않을 것**

- 로봇 FleetAgent 페어링(`robots.yaml` `fleet_pairing_token`) 변경.
- 역할 등록표(첫 조각은 상수 `overhead-camera` 하나), 사람 로그인의 기기 페어링화.
- in-band 수명 연장, "다음 CA" 사전 배포, 만료 임박 경고 UI(`expires_at` 표시만).
- 원격 주소별 한도.
- 앱 전역 네트워크 보안 설정의 신뢰 저장소 변경.

## 공통 계약 `rosy-pair/1` 요약

| 단계 | 요청 | 인증 | 응답 |
|---|---|---|---|
| 1 요청 | `POST /api/fleet/pairing/v1/requests` `{proto, role, device_label, app_version, client_commit, poll_secret_sha256}` | 없음(사이트 전체 한도) | `201 {request_id, server_nonce, expires_at}` |
| 2 공개 | `POST .../requests/{id}/reveal` `{client_nonce}` | `poll_secret` bearer | `200 {state:"revealed"}` |
| 3 조회 | `GET .../requests/{id}` | `poll_secret` bearer | `pending`/`rejected`/`expired`/`approved`+자격(1회)/이후 `410` |
| 4 확인 | `POST .../requests/{id}/confirm` `{credential_id}` | `poll_secret` bearer | `200` — 이때 자격 활성 |
| 콘솔 목록 | `GET /api/fleet/pairing/v1/pending` | viewer 이상 | 대기 요청(코드 없음) |
| 콘솔 승인 | `POST .../requests/{id}/approve` `{code, source_id}` | named operator | `200 {credential_id, site_ca_fingerprint}` / `409 CODE_MISMATCH` / `409`(활성 자격 있음 — 먼저 회수) |
| 콘솔 거절 | `POST .../requests/{id}/reject` | named operator | `200` |
| 자격 목록(Vision) | `GET /api/fleet/pairing/v1/credentials?role=overhead-camera` | `pairing_sync_token`(전용 의존성) | `[{credential_id, source_id, token_sha256, expires_at}]` 활성만 |
| 자격 목록(콘솔) | `GET /api/fleet/pairing/v1/credentials/summary` | viewer 이상 | digest 없는 요약 + `expires_at` |
| 회수 | `POST .../credentials/{id}/revoke` | named operator | `200` |

`client_commit = SHA-256(client_nonce)`. `code = decimal6(SHA-256("rosy-pair/1" ‖ role ‖ request_id ‖ leaf_cert_sha256 ‖ client_nonce ‖ server_nonce))`. `leaf_cert_sha256`은 leaf 인증서 DER의 SHA-256(Python `ssl.PEM_cert_to_DER_cert`, Android `cert.encoded`). 사이트 지문은 CA 인증서 DER SHA-256 앞 16 hex를 4자씩 `-`로 묶는다. 정확한 바이트 배열은 1단계 벡터 파일이 정본이다.

## 단계

### 1단계 — 공유 벡터와 코드·지문 계산 (Python + Kotlin 순수 로직)

**파일**

- 새로 만든다: `test/fixtures/protocol/pairing.v1.json`(D-341 19항, 2026-10-01 개정) — 코드 계산 3건 이상(leaf만 다른 쌍 포함), 지문 표기, 요청·결과 JSON 정상·거절 사례(역할 `robot`, `proto` 불일치, `tls` 없음, 필드 누락, 알 수 없는 필드, 4 KiB 초과).
- 새로 만든다: `src/site/overhead/overhead/pairing_code.py`(표준 라이브러리만), `src/site/overhead/test/test_pairing_vectors.py`.
- 새로 만든다: `android/app/src/main/java/.../settings/PairingCode.kt`, `android/app/src/test/java/.../settings/PairingCodeTest.kt`.
- 고친다: `android/app/build.gradle.kts` — 시스템 속성 `rosy.pairing.vectors`(기존 `rosy.overhead.vectors`와 같은 방식). `Vectors.kt`에 로더 추가.

**수용 기준**

- Python과 Kotlin이 같은 벡터로 녹색. 벡터 변조 사례에서 양쪽이 실패한다.
- `role != overhead-camera` 결과는 Kotlin 파서가 거절한다.

### 2단계 — Fleet 페어링 상태·API

**파일**

- 새로 만든다: `src/site/fleet/fleet/server/pairing.py` — 메모리 대기 표(상태 `pending → revealed → approved → delivered → confirmed`, `rejected`, `expired`), 기동마다 새 HMAC 키, 공개 뒤 코드 HMAC만 보관, `server_nonce`는 공개 때 폐기. 한도: 대기 300 s, 사이트 전체 동시 16, 사이트 전체 30건/분, 요청별 조회 ≥ 2 s, 본문 4 KiB, 틀린 코드 3회 거절, 승인 후 120 s 안에 확인 없으면 자동 회수. leaf DER 해시는 `--tls-cert`에서 `ssl.PEM_cert_to_DER_cert`로 계산.
- 새로 만든다: `src/site/fleet/fleet/server/pairing_store.py` — 기존 SQLite(`sqlite_policy.configure_connection`/`enable_wal`)에 `device_credentials`(digest·source·만료·상태), `device_pairing_audit`(보존 상한 10,000행). 원문·nonce·코드 컬럼 없음.
- 고친다: `src/site/fleet/fleet/server/app.py` — 위 표의 라우트. Pydantic 모델은 `extra="forbid"`. 요청·공개·조회·확인은 `authorize`를 거치지 않는다. 승인·거절·회수는 `require_named_operator` — 403 문구를 라우트별로 받도록 매개변수화한다(지금 문구는 "mission admission ..."이다). 자격 목록(Vision)은 `pairing_sync_token` 전용 의존성(`authorize()`는 사용자 digest가 있으면 다른 bearer를 401로 막는다). `pairing_sync_token`이 기존 비밀(console, discovery, sighting, 사용자 digest, CORE REST/Agent, preview)과 겹치면 기동 거절. `--tls-cert`가 없으면 페어링 라우트를 설치하지 않는다.
- 고친다: `src/site/fleet/fleet/server/sightings_config.py` — source별 `credential: static|paired`. `paired`는 `token_env`와 무관하게 페어링 대상 목록에 들어간다(Fleet 쪽 sighting 자격 `token_env`는 그대로 필수 — 폰 자격과 다른 비밀이다).
- 고친다: `src/site/fleet/fleet/cli.py` — `--pairing-db`, `--pairing-ca`, `--pairing-sync-token-env`.
- 새로 만든다: `src/site/fleet/test/test_pairing_state.py`, `test_pairing_store.py`, `test_pairing_api.py`. 고친다: `test_no_video_relay.py`에 페어링을 켠 앱 경우 추가.

**수용 기준(시험 이름으로 고정)**

- 요청은 메모리 대기 외 부작용이 없다. Fleet 재시작 뒤 대기 요청은 사라진다(문서화된 동작).
- 사이트 전체 한도 초과는 429이며 기존 대기를 밀어내지 않는다. 만료 요청은 승인 불가. `revealed`가 아닌 요청은 코드를 받지 않는다.
- 코드 불일치 409, 3회째 거절. viewer·policy-admin·단일 console 토큰 구성의 승인은 403(라우트 고유 문구).
- 활성 자격이 있는 source로의 승인은 409. `static` source는 승인 대상이 아니다.
- 원문 토큰은 한 번만 나오고 두 번째는 410. 확인 전 자격은 Vision 목록에 없다. 120 s 안에 확인이 없으면 자동 회수.
- DB 덤프에 원문 토큰·`poll_secret`·nonce·코드가 없다. `--tls-cert` 없는 앱에는 페어링 라우트가 없다.
- `python -m pytest src/site/fleet/test -q` 녹색.

### 3단계 — 콘솔 패널과 Vision 동적 자격

**파일**

- 고친다: `src/site/fleet/fleet/server/web/index.html`, `console.js`(필요하면 새 `pairing.js`), `styles.css` — "기기 연결 요청" 패널: 대기 목록(이름표·요청 시각·남은 시간), 코드 6자리 입력, `paired` source 선택, 거절. 승인 완료 화면에 사이트 지문 + `credential_id`를 크게(설치자 상호 확인용). 활성 자격 목록(`expires_at`, 확인 여부, 회수). 코드는 콘솔에 표시하지 않는다. 역할 게이트는 기존 `authorization.js` 문법. 설치자 문구는 D-345·D-280의 쉬운 한국어.
- 고친다: `src/site/overhead/overhead/ingest.py`
  - `__init__`(현재 125–126행 "at least one source token is required"): 정적 토큰이 0개여도 페어링 공급자가 있으면 기동을 허용한다.
  - `_process_request`(현재 178–184행, 정적 토큰만 대조): 업그레이드 단계에서 정적 토큰 **또는** 동기화된 digest를 대조한다. 동기화 상태를 모르면 `503` + `Retry-After`, 모르는 자격이면 `401`.
  - `_handler`: hello의 source가 `paired`면 그 source의 digest와만 대조. 상태 불명은 새 닫힘 코드 `4503`(재시도), 회수·모름은 `4401`(최종). 동기화에서 빠진 자격으로 붙은 연결을 `4401`로 닫는다.
- 고친다: `src/site/overhead/overhead/protocol.py`와 `protocol/vectors.json` — `CLOSE_STATUS_UNAVAILABLE = 4503`. Kotlin `Protocol.kt`도 같이.
- 새로 만든다: `src/site/overhead/overhead/pairing_sync.py` — `https://fleet:8090` 직접(프록시 경유 아님), 2 s 간격, 마지막 정상 목록 최대 10분, 그 뒤엔 상태 불명(`4503`). 첫 동기화 전에도 상태 불명.
- 고친다: `src/site/overhead/overhead/vision_config.py` — `credential: static|paired`. `static`은 `phone_token_env` 필수, `paired`는 금지. 어기면 기동 거절.
- 고친다: `src/site/overhead/overhead/cli.py` — `vision`에 `--pairing-sync-url`, `--pairing-sync-token-env`. 현재 134–137행의 preview 비밀 고유성 검사가 `paired` source(폰 토큰 없음)에서 `None`을 다루고, 동기화 비밀과도 겹치지 않는지 검사하도록 고친다.
- 새로 만든다: `src/site/overhead/test/test_pairing_sync.py`, `test_ingest_paired_credentials.py`, `test_vision_config.py` 확장. 고친다: 콘솔 브라우저 계약 시험(`test/test_fleet_console_browser.py` 계열).

**수용 기준**

- 회수 후 5 s 안에 활성 WS가 `4401`로 닫힌다(가짜 시계, 동기화 2 s).
- Fleet 없이 Vision이 먼저 떠도 `paired` 폰은 `503`/`4503`을 받고, Fleet이 뜬 뒤 재접속된다. 10분 넘게 동기화 실패 시 `4503`. `static` 토큰은 계속 동작.
- 다른 source의 digest로는 hello가 거절된다. 로그·통계에 bearer가 없다.
- viewer는 패널을 보되 승인·회수 버튼이 없다. `python -m pytest src/site/overhead/test -q` 녹색.

### 4단계 — Avahi TXT, Compose 배선, 합성 종단 시험

**파일**

- 고친다: `deploy/site/fleet-mdns.py` — `OVERHEAD_TXT`에 `pair=rosy-pair/1`. `test/test_site_fleet_mdns.py`에 키 존재와 비밀 키 부재 시험.
- 고친다: `deploy/site/compose.yaml` — 새 secret `pairing_sync_token`(Fleet·Vision), Fleet에 `--pairing-*`와 `site_ca`, Vision에 `--pairing-sync-url https://fleet:8090`. `site-cameras.yaml.example`에 `credential:` 키. 계약 시험(`test/test_site_fabric_roles.py`, D-302 매핑 시험) 갱신.
- 고친다: `deploy/site/README.md` — `pairing_sync_token` 생성, `static`/`paired` 설명, 콘솔 승인·상호 확인 절차, 되돌림 경로(`static` + `rosyov://...&tls=1` + 사용자 CA 설치).
- 새로 만든다: `test/test_overhead_pairing_e2e.py` — 임시 CA·leaf(SAN `<host>.local`)로 Fleet + Vision을 띄워 합성 Python 폰이 요청→공개→승인→수령→상호 확인→CA 고정 WSS 송신→회수→`4401`, Fleet 정지→`4503`→재기동 후 재접속까지. 중계형 중간자(다른 leaf로 첫 연결) → 코드 불일치. 가짜 수신기(다른 CA로 자기 승인) → 지문 불일치로 저장 안 됨. CA 변경 → 거부, 같은 CA 새 leaf → 허용.

**수용 기준**

- 종단 시험 녹색, 기존 site 계약 시험 녹색, `python tools/harness/rosy_harness.py lint`가 이 브랜치로 새 오류를 만들지 않는다.

### 5단계 — Android 요청·확인, CA 고정, mDNS 재연결

**파일**

- 고친다: `android/gradle/libs.versions.toml` — `okhttp-tls`(같은 `okhttp` 버전 4.12.0; 시험의 `HeldCertificate`, 본체의 `HandshakeCertificates`).
- 고친다: `settings/OverheadServiceRecord.kt` — `pair` TXT와 해석된 주소 보존(주소는 연결 후보로만). `OverheadServiceRecordTest.kt` 확장.
- 새로 만든다: `settings/PairingClient.kt` — 첫 연결 leaf 기록용 TrustManager(검증 없이 DER 해시 기록, SAN에 `tls_host` 없으면 중단), 요청·공개·조회·확인, 결과 검증(leaf가 받은 CA로 체인 검증 + SAN). `settings/PinnedTrust.kt` — CA 하나만 든 `X509TrustManager` + `tls_host` 호스트명 검사. `link/DiscoveredDns.kt` — `tls_host` → mDNS 주소 OkHttp `Dns`.
- 고친다: `settings/SettingsStore.kt` — 페어링 결과(`tls_host`, 포트, CA PEM, source, 토큰, `credential_id`, `expires_at`, 모드 `paired`) 저장, IP 미저장. 기존 저장 형식(host/port/token/source/secure)은 `static` 모드로 이전(migration). 페어링 모드는 `secure=false`로 내려가지 않는다.
- 고친다: `link/OverheadLink.kt` — 페어링 모드에서 고정 TrustManager·`DiscoveredDns` 사용. 현재 275–280행은 업그레이드 `401`을 `fatal = false`로 넘긴다 — 페어링 모드에서는 `401`과 `4401`을 최종(재시도 중단 + 재페어링 상태), `503`과 `4503`은 재시도(자격 유지). 연속 3회 실패 뒤 재발견(최대 30 s에 한 번).
- 고친다: `ui/SettingsScreen.kt` — 발견 목록의 "연결 요청", 코드 크게 표시, 상호 확인 화면(사이트 지문 + 자격 번호, "일치"/"다름"), 대기·거절·만료·충돌·인증서 변경 상태. 문구는 D-345 설치자용 쉬운 한국어.
- 새로 만든다: JVM 시험 `PairingClientTest.kt`(MockWebServer + `HeldCertificate`: 정상, 중계형 중간자, **다른 CA의 가짜 수신기 → "다름" 또는 확인 전 종료 시 아무것도 저장 안 됨**, SAN 불일치, 410), `PinnedTrustTest.kt`(다른 CA 거부, 같은 CA 새 leaf 허용), `ReconnectPolicyTest.kt`(3회 실패 뒤 재발견, 30 s 간격, 같은 `tls_host` 다중 주소 → 충돌, 0개 → 대기), `SettingsStoreMigrationTest.kt`(기존 형식 → `static`, 페어링 모드의 평문 강등 거부), `OverheadLinkTest.kt` 확장(401/4401 최종, 503/4503 재시도).

**수용 기준**

- `android/gradlew testDebugUnitTest assembleDebug` 녹색(LOCAL).

## 벤치 절차 — Windows PC + S21 (`tools/overhead_pairing_bench.py`)

2026-09-29 벤치(S21 SM-G991N, Android 15, Wi-Fi `1213_device`, PC 192.168.1.102)를 TLS·페어링 경로로 다시 한다. 스택은 **Compose로만** 띄운다(개별 프로세스 벤치 금지 — 배포와 같은 경로를 본다). 스크립트는 LOCAL 도구이고 결과 기록만 DEVICE 증거다.

**준비(LOCAL 관문 — 폰 작업 전에 통과해야 한다)**

1. 의존성: `tools/requirements-bench.txt`에 `zeroconf`를 버전 고정으로 선언하고 `python -m pip install -r tools/requirements-bench.txt`. 사이트 이미지 요구 사항에는 넣지 않는다.
2. `python tools/overhead_pairing_bench.py prepare --host-label <pc> --out X:\DevTemp\overhead-pairing\<날짜>` — 일회용 벤치 CA와 leaf. SAN은 `<pc>.local`, `proxy`, `fleet`, `vision`, `localhost`. 벤치 사용자 파일(operator 1명, digest만), 비밀 파일(`pairing_sync_token`, preview 비밀, sighting 토큰 등), `site-cameras.yaml`(`credential: paired` source 하나), 그리고 **실제 로봇이 든 `robots.yaml`**: `rosy-pinky-8kcn`, `http://192.168.1.202:8080`(CORE 토큰은 기존 기록 PC 저장소에서, 출력 폴더에만). 비밀 원문은 출력 폴더에만 두고 화면에는 경로만 찍는다.
3. 운용자 브라우저(같은 PC)에 벤치 CA를 가져온다(Windows 사용자 인증서 저장소, `certutil -user -addstore Root <ca>`). 폰에는 설치하지 않는다.
4. 방화벽: 관리자 PowerShell에서 인바운드 TCP 8443, UDP 5353 허용 규칙을 벤치 이름으로 추가(끝나면 제거).
5. `python tools/overhead_pairing_bench.py up --out ...` — `ROSY_SITE_BIND_ADDRESS=0.0.0.0`, `ROSY_SITE_CONFIG_DIR`, `ROSY_SITE_SECRETS_DIR`를 출력 폴더로 두고 `docker compose -f deploy/site/compose.yaml up -d`.
6. 광고: `python tools/overhead_pairing_bench.py advertise --iface-ip 192.168.1.102 --tls-host <pc>.local --port 8443` — `deploy/site/fleet-mdns.py`의 `OVERHEAD_TXT`를 import해 그대로 쓰고(`pair` 포함), `--iface-ip`로 Wi-Fi 주소 하나에만 광고한다(지정하지 않으면 Windows가 vEthernet/WSL/Docker NIC 주소도 광고한다).
7. **관문:** PC에서 `https://<pc>.local:8443/healthz`가 벤치 CA 검증으로 `200 {"status":"ok"}`. 다른 LAN 기기(또는 폰 브라우저의 인증서 경고 확인)로 8443 도달 확인. 여기서 실패하면 폰 단계로 가지 않는다.

**폰 단계(DEVICE 기록)**

8. 폰: Android 설정의 사용자 인증서 목록에 벤치 CA가 **없음**을 캡처. 앱 → 발견 목록에서 수신기 선택 → 연결 요청 → 코드 표시. 같은 목록에 로봇 `rosy-pinky-8kcn`이 정보로만 보이고 "연결 요청" 버튼이 없음을 캡처.
9. 콘솔(`https://<pc>.local:8443/console`, 벤치 operator 토큰): 대기 요청에 폰 코드 입력, `paired` source 선택, 승인. 승인 완료 화면의 지문·자격 번호와 폰 화면을 함께 캡처하고 폰에서 "일치".
10. 60 s 이상 송신. 기록: fps, bytes/s, 프레임 수, `seq_gaps`, 드롭, `age_ms` p50·max(오늘 평문 ws 기준선: 3 fps, ~70 KB/s, 178 프레임/60 s, gaps 0, p50 ~110–120). 콘솔 "관제 카메라"에 이 카메라의 실시간 프레임, 로스터에 로봇 `rosy-pinky-8kcn`이 함께 보이는 화면을 캡처(preview 비밀 켬). 차선 지도 위 sighting 겹침은 `feat/console-site-map-layer`가 들어온 뒤의 별도 기록이다.
11. IP 변경: 관리자 PowerShell에서 `netsh interface ipv4 set address name="Wi-Fi" static <새 IP> 255.255.255.0 <게이트웨이>`로 주소를 바꾸고 `advertise --iface-ip <새 IP>`로 다시 광고한다. 폰을 만지지 않고 재연결까지 걸린 시간과 옛/새 IP를 기록한다. 끝나면 `netsh interface ipv4 set address name="Wi-Fi" dhcp`로 되돌린다.
12. 회수: 콘솔에서 회수 → 송신 중단까지 시간(목표 ≤ 5 s)과 폰 상태(재페어링 필요) 기록.
13. CA 변경 1회: `prepare --rotate-ca` 후 `up` 재기동 → 폰이 연결을 거부하고 인증서 변경 상태를 띄우는지 기록. (중계형 중간자·가짜 수신기·같은 CA 새 leaf는 4·5단계 LOCAL 시험으로 판정하고 실기에서는 반복하지 않는다.)
14. `python tools/overhead_pairing_bench.py report --out ...` — 비밀 없는 요약 JSON. 이 요약과 캡처만 DEVICE 증거로 `src/site/overhead/logs.md`에 옮긴다. `down`으로 스택을 내리고 방화벽 규칙을 지운다.

## 증거 기록

- 단계마다 `src/site/overhead/logs.md`·`src/site/fleet/logs.md`·`docs/logs.md`에 시험 명령과 결과를 남긴다. `progress.md`의 `adrs`에 D-341을 더한다.
- 벤치 기록 전까지 D-341은 Proposed다. 판정은 별도 리뷰 뒤에 한다.

## 열린 질문

D-341 "이 ADR이 정하지 않는 것" 목록을 따른다. 구현 중 새로 생기면 이 계획 아래에 추가하고 리뷰에서 닫는다.
