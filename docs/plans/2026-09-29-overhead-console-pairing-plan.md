# 천장 카메라 콘솔 승인 페어링 — 실행 계획 (D-341)

- 날짜: 2026-09-29
- 결정: [D-341](../adr/D-341-overhead-console-approved-pairing.md) (Proposed)
- 잇는 문서: [D-261](../adr/D-261-overhead-camera-app-skeleton.md), [발견 규칙](../reference/site-lan-discovery-profile.md), [`deploy/site/README.md`](../../deploy/site/README.md)
- 등급 목표: 1–4단계 LOCAL, 5단계 DEVICE(S21 벤치), FIELD는 사이트 호스트에서 별도

## 목표

폰 앱이 `_rosy-overhead._tcp`로 사이트를 찾아 페어링을 요청하고, 운용자가 Fleet 콘솔에서 6자리 코드를 입력해 승인하면, 폰이 카메라 토큰과 사이트 CA를 한 번 받아 CA 고정 WSS로 송신한다. 사이트 IP가 바뀌면 mDNS로 다시 찾아 붙는다. 사이트 CA를 Android 설정에 설치하지 않는다.

## 지킬 것 / 하지 않을 것

**지킬 것**

- 모든 단계는 시험 먼저(TDD). 실패하는 시험 → 최소 구현 → 녹색 → 커밋. 단계마다 커밋한다.
- 발견만으로는 어떤 자격도 생기지 않는다. 자격은 `require_named_operator` 승인 + 코드 일치 + 1회 수령으로만 생긴다.
- 저장소·SQLite·로그에 토큰 원문, `poll_secret`, nonce 원문, 페어링 URI를 남기지 않는다. digest만 저장한다.
- `test_no_video_relay.py`는 계속 녹색이다. 새 Fleet 라우트 경로에 `camera|stream|proxy|preview|video|image|jpeg|mjpeg|relay`를 쓰지 않는다.
- 정적 환경 변수 토큰 경로(D-261, 현 Compose)와 `rosyov://` 수동 경로는 그대로 동작한다.
- Windows에서는 `python`을 쓴다. 임시 DB·인증서·로그는 `X:\DevTemp\` 아래에 둔다.

**하지 않을 것**

- 로봇 FleetAgent 페어링(`robots.yaml` `fleet_pairing_token`) 변경.
- 두 번째 역할 등록표 항목 추가, 사람 로그인의 기기 페어링화.
- in-band 수명 연장, "다음 CA" 사전 배포.
- 앱 전역 네트워크 보안 설정의 신뢰 저장소 변경(고정 TrustManager는 오버헤드 OkHttp 클라이언트에만 붙인다).

## 공통 계약 `rosy-pair/1` 요약

| 단계 | 요청 | 인증 | 응답 |
|---|---|---|---|
| 1 요청 | `POST /api/fleet/pairing/v1/requests` `{proto, role, device_label, app_version, client_commit, poll_secret_sha256}` | 없음(한도 적용) | `201 {request_id, server_nonce, expires_at}` |
| 2 공개 | `POST /api/fleet/pairing/v1/requests/{id}/reveal` `{client_nonce}` | `poll_secret` bearer | `200 {state:"pending"}` — 서버가 코드 계산 |
| 3 조회 | `GET /api/fleet/pairing/v1/requests/{id}` | `poll_secret` bearer | `pending` / `rejected` / `expired` / `approved`+자격(1회) / 이후 `410` |
| 콘솔 목록 | `GET /api/fleet/pairing/v1/pending` | viewer 이상 | 대기 요청(코드는 **싣지 않음**) |
| 콘솔 승인 | `POST /api/fleet/pairing/v1/requests/{id}/approve` `{code, source_id, replace}` | named operator | `200` / `409 CODE_MISMATCH` / `409 SOURCE_ACTIVE` |
| 콘솔 거절 | `POST .../{id}/reject` | named operator | `200` |
| 자격 목록 | `GET /api/fleet/pairing/v1/credentials?role=overhead-camera` | `pairing_sync_token`(Vision) 또는 viewer(콘솔, digest 제외) | `[{credential_id, source_id, token_sha256?, expires_at, revoked}]` |
| 회수 | `POST /api/fleet/pairing/v1/credentials/{id}/revoke` | named operator | `200` |

`client_commit = SHA-256(client_nonce)`. `code = decimal6(SHA-256("rosy-pair/1" ‖ role ‖ request_id ‖ leaf_spki_sha256 ‖ client_nonce ‖ server_nonce))`, 앞 8바이트를 big-endian 정수로 읽어 `% 10^6`, 0으로 채운 6자리. 정확한 바이트 배열(구분자, 인코딩)은 1단계 벡터 파일이 정본이다.

## 단계

### 1단계 — 공유 벡터와 코드 계산 (Python + Kotlin 순수 로직)

**파일**

- 새로 만든다: `src/site/overhead/protocol/pairing_vectors.json` — 코드 계산 3건 이상(서로 다른 leaf SPKI로 코드가 달라지는 쌍 포함), 요청/결과 JSON 정상·거절 사례(역할 불일치 `robot`, `proto` 불일치, `tls` 없음, 필드 누락, 과대 `device_label`).
- 새로 만든다: `src/site/overhead/overhead/pairing_code.py`(ROS-free, 표준 라이브러리만) — `commit(nonce)`, `confirmation_code(...)`, 요청·결과 검증.
- 새로 만든다: `src/site/overhead/test/test_pairing_vectors.py`.
- 새로 만든다: `android/app/src/main/java/.../settings/PairingCode.kt`, `android/app/src/test/java/.../settings/PairingCodeTest.kt`.
- 고친다: `android/app/build.gradle.kts` — 시스템 속성 `rosy.pairing.vectors`로 `../protocol/pairing_vectors.json`을 넘긴다(기존 `rosy.overhead.vectors`와 같은 방식). `Vectors.kt`에 로더 추가.

**수용 기준**

- Python과 Kotlin이 같은 벡터로 녹색. 벡터의 코드 한 자리를 바꾸면 양쪽이 모두 실패한다(시험 안에서 변조 사례로 확인).
- `role != overhead-camera` 결과는 Kotlin 파서가 거절한다(D-341 15항).

### 2단계 — Fleet 페어링 저장소·API

**파일**

- 새로 만든다: `src/site/fleet/fleet/server/pairing_store.py` — 기존 SQLite(`sqlite_policy.configure_connection`/`enable_wal`)에 `device_pairing_requests`, `device_credentials`, `device_pairing_audit` 표. 원문 토큰 컬럼 없음. 상태 전이 `pending → revealed → approved → delivered` / `rejected` / `expired`.
- 새로 만든다: `src/site/fleet/fleet/server/pairing.py` — 역할 등록표(첫 항목 `overhead-camera`: 승인 역할 `operator`, 대상 = sightings 설정의 `source_id`, 수명 180일), 한도(대기 300 s, 전체 16, 주소당 동시 1, 주소당 10/분, 조회 ≥ 2 s, 코드 3회 오류 시 거절), leaf SPKI 계산(`--tls-cert`의 인증서), CA PEM 로드.
- 고친다: `src/site/fleet/fleet/server/app.py` — 위 표의 라우트. 요청·공개·조회는 `authorize`를 거치지 않는다. 승인·거절·회수는 `require_named_operator`. 자격 목록은 `pairing_sync_token` 또는 viewer(viewer 응답에는 digest 없음). `pairing_sync_token`과 발급 digest가 기존 비밀(console, discovery, sighting, 사용자 digest, CORE REST/Agent)과 겹치면 기동 거절.
- 고친다: `src/site/fleet/fleet/cli.py` — `--pairing-db`, `--pairing-ca`, `--pairing-sync-token-env`. 셋 다 없으면 페어링 라우트 미설치.
- 새로 만든다: `src/site/fleet/test/test_pairing_store.py`, `test_pairing_api.py`.

**수용 기준(시험 이름으로 고정)**

- 요청은 대기 행 외 부작용이 없다(robots·sightings·사용자 표 불변).
- 한도 초과는 429이며 기존 대기 행을 밀어내지 않는다. 만료된 요청은 승인할 수 없다.
- 코드 불일치 409, 3회째 거절로 닫힘. viewer·policy-admin·단일 console 토큰 구성의 승인은 403.
- 결과 원문 토큰은 한 번만 나오고 두 번째는 410. DB 덤프에 원문 토큰·`poll_secret`·nonce가 없다.
- 활성 source에 `replace=false` 승인은 409, `replace=true`면 이전 자격이 회수된다.
- `test_no_video_relay.py` 녹색. 새 라우트는 감사 표에 principal과 함께 남는다.
- `python -m pytest src/site/fleet/test -q` 녹색.

### 3단계 — 콘솔 패널과 Vision 동적 자격

**파일**

- 고친다: `src/site/fleet/fleet/server/web/index.html`, `console.js`(필요하면 새 `pairing.js`), `styles.css` — "기기 연결 요청" 패널: 대기 목록(이름표·요청 시각·남은 시간·원격 주소), 코드 6자리 입력, source 선택, 교체 확인, 거절. 활성 자격 목록(만료 30일 전 경고, 회수 버튼). 코드는 콘솔에 표시하지 않는다(운용자가 폰에서 읽어 입력). 기존 발견 패널과 같은 역할 게이트 문법(`authorization.js`).
- 고친다: `src/site/overhead/overhead/ingest.py` — `IngestServer`에 digest 기반 동적 자격 공급자 추가. hello의 source에 묶인 digest와 상수 시간 비교. 회수·만료된 자격으로 붙은 연결을 `CLOSE_UNAUTHORIZED`(4401)로 닫는다. 정적 토큰 경로는 그대로.
- 새로 만든다: `src/site/overhead/overhead/pairing_sync.py` — 5 s 간격 Fleet 조회, 마지막 정상 목록 최대 10분, 이후 페어링 자격 전부 거절.
- 고친다: `src/site/overhead/overhead/vision_config.py` — source별 `phone_token_env`를 선택으로(페어링만 쓰는 source 허용). `cli.py vision`에 `--pairing-sync-url`, `--pairing-sync-token-env`.
- 새로 만든다: `src/site/overhead/test/test_pairing_sync.py`, `test_ingest_paired_credentials.py`. 고친다: 관련 브라우저 계약 시험(`test/test_fleet_console_browser.py` 계열, 패널 존재·역할 게이트).

**수용 기준**

- 회수 후 5 s 안에 활성 WS가 4401로 닫힌다(가짜 시계). 동기화 실패 10분 뒤 페어링 자격 거절, 정적 토큰은 계속 동작.
- 다른 source의 digest로는 hello가 거절된다. Vision 로그·통계에 bearer가 나오지 않는다.
- viewer는 패널을 보되 승인·회수 버튼이 없다. `python -m pytest src/site/overhead/test -q` 녹색.

### 4단계 — Avahi TXT, Compose 배선, 합성 종단 시험

**파일**

- 고친다: `deploy/site/fleet-mdns.py` — `OVERHEAD_TXT`에 `pair=rosy-pair/1`. `test/test_site_fleet_mdns.py`에 키 존재와 비밀 키 부재 시험.
- 고친다: `deploy/site/compose.yaml` — 새 secret `pairing_sync_token`(Fleet·Vision), Fleet에 `--pairing-*` 인자와 `site_ca` 경로, Vision에 동기화 인자. 관련 계약 시험(`test/test_site_fabric_roles.py`, D-302 매핑 시험) 갱신.
- 고친다: `deploy/site/README.md` — 설치 절차에 `pairing_sync_token` 생성과 콘솔 승인 절차 추가(교차 참조는 이미 있음).
- 새로 만든다: `test/test_overhead_pairing_e2e.py`(또는 `src/site/overhead/test/` 아래) — 임시 CA·leaf(SAN `<host>.local`)를 만들고 Fleet + Vision을 띄워 합성 Python 폰 클라이언트가 요청→공개→운용자 승인(시험 토큰)→수령→CA 고정 WSS 송신→회수→4401까지 한 번에 재현. 중간자 사례(다른 leaf로 첫 연결) → 코드 불일치로 승인 실패.

**수용 기준**

- 종단 시험 녹색, 기존 site 계약 시험 녹색, `python tools/harness/rosy_harness.py lint` 녹색.

### 5단계 — Android 요청·조회, CA 고정, mDNS 재연결 + S21 벤치 스크립트

**파일**

- 고친다: `settings/OverheadServiceRecord.kt` — `pair` TXT와 해석된 주소를 보존(주소는 연결 후보로만). 시험 `OverheadServiceRecordTest.kt` 확장.
- 새로 만든다: `settings/PairingClient.kt` — 첫 연결 leaf SPKI 기록용 TrustManager(검증 없이 기록, SAN에 `tls_host` 없으면 중단), 요청·공개·조회, 결과 검증(leaf가 받은 CA로 체인 검증 + SAN). `settings/PinnedTrust.kt` — CA 하나만 든 `X509TrustManager` + `tls_host` 호스트명 검사. `link/DiscoveredDns.kt` — `tls_host` → mDNS 주소 매핑 OkHttp `Dns`.
- 고친다: `settings/SettingsStore.kt` — 페어링 결과(`tls_host`, 포트, CA PEM/SPKI, source, 토큰, `credential_id`, `expires_at`) 저장, IP 미저장. `link/OverheadLink.kt` — 페어링 연결에 고정 TrustManager·`DiscoveredDns` 사용, 4401이면 재시도 중단 + 재페어링 상태, 백오프 한 주기마다 재발견. `ui/SettingsScreen.kt` — 발견 목록에서 "연결 요청", 코드 크게 표시, 대기·승인·거절·만료·충돌·CA 변경 상태.
- 새로 만든다: JVM 시험 `PairingClientTest.kt`(MockWebServer + 시험 CA로 정상·중간자·SAN 불일치·410), `PinnedTrustTest.kt`(다른 CA 거부, 같은 CA 새 leaf 허용), `ReconnectPolicyTest.kt`(같은 `tls_host` 다중 주소 → 충돌, 0개 → 대기).
- 새로 만든다: `tools/overhead_pairing_bench.py` — 오늘 S21 벤치를 재현하는 스크립트(아래).

**수용 기준**

- `android/gradlew testDebugUnitTest assembleDebug` 녹색(LOCAL).
- DEVICE는 아래 벤치 기록으로만 판정한다.

## S21 벤치 스크립트 (`tools/overhead_pairing_bench.py`)

2026-09-29 벤치(S21 SM-G991N, Android 15, Wi-Fi `1213_device`, PC 192.168.1.102)를 TLS·페어링 경로로 다시 하는 절차다. 스크립트는 LOCAL 도구이며 결과 기록만 DEVICE 증거가 된다.

1. `python tools/overhead_pairing_bench.py prepare --host-label <pc>.local --out X:\DevTemp\overhead-pairing\<날짜>` — 일회용 벤치 CA와 leaf(SAN `<pc>.local`) 생성, 벤치 사용자 파일(operator 1명, digest만) 생성, 임시 SQLite 경로 준비. 비밀 원문은 출력 폴더에만 두고 화면에는 경로만 찍는다.
2. `python tools/overhead_pairing_bench.py run --out ...` — Fleet(페어링 켬) + Vision(`--pairing-sync-*`, TLS 8443 직결 또는 로컬 프록시)을 띄우고, python-zeroconf로 `_rosy-overhead._tcp`(`tls_host=<pc>.local`, `pair=rosy-pair/1`)를 광고. 통계는 JSONL로 남긴다.
3. 폰: Android 설정에 CA를 **설치하지 않은** 상태 확인(설정 → 보안 → 사용자 인증서 목록 캡처). 앱 → 발견 목록에서 수신기 선택 → 연결 요청 → 코드 표시.
4. 콘솔(`https://<pc>.local:8443/console`, 벤치 operator 토큰): 대기 요청에 폰 코드 입력, source 선택, 승인.
5. 60 s 이상 송신. 기록: fps, bytes/s, 프레임 수, `seq_gaps`, 드롭, `age_ms` p50·max(오늘 평문 ws 기준선: 3 fps, ~70 KB/s, 178 프레임/60 s, gaps 0, p50 ~110–120).
6. IP 변경: PC Wi-Fi 재연결 또는 DHCP 갱신으로 주소를 바꾸고 광고를 다시 낸다. 폰을 만지지 않고 재연결까지 걸린 시간 기록.
7. 회수: 콘솔에서 회수 → 송신 중단까지 시간(목표 ≤ 5 s)과 폰 상태("재페어링 필요") 기록.
8. CA 변경: `prepare --rotate-ca`로 다른 CA의 leaf로 바꿔 재기동 → 폰이 연결을 거부하고 "사이트 인증서 변경" 상태인지 기록. 같은 CA로 leaf만 다시 발급하면 그대로 붙는지 기록.
9. 중간자 점검(선택): 다른 CA의 leaf를 내는 두 번째 수신기로 요청 → 콘솔 코드 입력이 불일치로 거절되는지 기록.
10. `python tools/overhead_pairing_bench.py report --out ...` — 위 결과를 요약한 JSON을 만든다(비밀 없음). 이 요약과 폰 화면 캡처만 DEVICE 증거로 `src/site/overhead/logs.md`에 옮긴다.

로봇 `_rosy._tcp`(예: `rosy-pinky-8kcn`)가 같은 LAN에 보이면 목록에 정보로만 뜨고 "연결 요청" 버튼이 없어야 한다 — 이것도 기록한다.

## 증거 기록

- 단계마다 `src/site/overhead/logs.md`·`src/site/fleet/logs.md`·`docs/logs.md`에 시험 명령과 결과를 남긴다. `progress.md`의 `adrs`에 D-341을 더한다.
- 5단계 벤치 전까지 D-341은 Proposed다. 판정은 별도 리뷰 뒤에 한다.

## 열린 질문

D-341 "이 ADR이 정하지 않는 것" 목록을 따른다. 구현 중 새로 생기면 ADR이 아니라 이 계획 아래에 추가하고 리뷰에서 닫는다.
