## D-801 관제 콘솔 로봇 실시간 영상: 사이트 계정 읽기 위임과 SFU+MCU 혼합 토폴로지

**Status:** Accepted (2026-10-18, 사용자 결정). D-789 Decision 3의 "사이트 계정만으로 로봇 영상을 열지 않는다"를 아래 규칙으로 대체한다. 구현·시험 결정이며 DEVICE·FIELD 수용이나 성능 달성을 뜻하지 않는다(D-789 부록 2026-10-18: 측정 생략).

### Context

관제 콘솔에는 로봇 실시간 영상 화면이 없었다. D-789는 CORE가 발급한 위임만 영상 세션을 열게 했고 사이트 계정만으로는 열지 못하게 했다. 사용자는 관제 콘솔에 로봇별 타일과 최대 6대 격자를 추가하고, 이를 위해 Decision 3을 바꾸기로 결정했다. 사용자는 WebRTC 토폴로지(Mesh·SFU·MCU·혼합)를 비교해 선택 근거를 ADR에 남기도록 요청했다.

기존 코드의 근거:
- Fleet 권한 모델은 `operations/fleet/fleet/server/auth/site_auth.py`의 `SitePrincipal.permits_site("fleet.read")`(관제 조회)와 `fleet.operate`(운전)다. 계정 원장(`account_ledger.py`)의 역할 변경은 세션을 지우고, 로그아웃은 `password_session.revoke`로 쿠키를 무효화한다.
- 사이트 카메라에는 이미 Fleet이 서명한 60초 직접 조회 lease가 있다(`/api/fleet/vision/lease`, Fleet은 프레임을 중계하지 않는다).
- Fleet 운영 경로에는 영상 중계 금지 시험(`operations/fleet/test/test_no_video_relay.py`)이 있다.

### Decision

1. **사이트 발급 읽기 위임.** 사이트 로그인 주체가 Fleet `fleet.read` 권한(기존 관제 조회 역할, 새 역할 체계 없음)을 가지면 Fleet은 로봇별 READ 전용 영상 위임을 발급한다. CORE 사용자 세션은 필요 없다. 위임은 `rosy-media+jwt`(Ed25519, iss=aud=`site:<id>`, robot/path/action=read, 최대 60초)이고 사이트 서명 키는 로봇 키와 분리한다. tokenless LAN 카메라 프록시 주체와 publish는 허용하지 않는다.
2. **수명과 회수는 D-789와 같다.** 입장 자격 ≤60초, 콘솔이 20초마다 갱신한다. 미디어 권한 서비스는 1초마다 Fleet의 `POST /api/fleet/media/validate`로 재확인한다. Fleet은 발급 때의 브라우저 자격(쿠키·Bearer, Fleet 메모리에만 보관)으로 자기 인증·권한 검사를 다시 수행한다. 로그아웃·역할 회수·계정 비활성은 다음 재확인에서 inactive가 되고 실제 MediaMTX 세션은 5초 안에 kick된다. Fleet에 닿지 못하면 거절한다.
3. **로봇 거부권.** 로봇 CORE의 `vision.media.enabled: false`(또는 site_url 미설정)는 사이트 위임도 거절한다. 권한 서비스는 재확인마다 CORE `POST /api/v1/vision/media/validate`의 영상 설정 상태(200=켜짐, 503 `MEDIA_UNAVAILABLE`=꺼짐)를 확인하며, 꺼진 로봇의 세션·타일은 5초 안에 닫힌다. 새 API 필드는 만들지 않았다.
4. **감사.** 사이트 발급 위임마다 `fleet_media_audit`에 grant_id·주체·역할·로봇·시작·마지막 갱신·종료 시각·종료 이유를 남긴다. 발급·갱신·종료 요청은 기존 `fleet_api_audit` POST 감사에도 남는다.
5. **불변 조건.** Fleet은 영상 중계자가 아니다(MediaMTX가 WHEP를 직접 제공). publish와 read는 분리한다. 영상 위임에는 명령 권한이 없고 DataChannel을 쓰지 않는다.

### 토폴로지 선택

우리 트래픽은 로봇당 1:N(로봇 한 대가 발행, 여러 뷰어가 시청)이며 N:M 회의가 아니다.

| 방식 | 판단 |
|---|---|
| Mesh/P2P(로봇→각 브라우저 직접) | 기각. 회의에서는 N(N-1)/2 연결, 여기서는 뷰어 수만큼 로봇 무선 uplink와 Pi 인코딩·세션 부하가 늘어난다. D-789 Alternatives의 기각을 이 이유로 다시 적는다. |
| SFU(MediaMTX가 로봇 한 스트림을 N reader에게 재인코딩 없이 전달) | 기본 경로로 유지. 로봇은 한 번 올리고 지연이 가장 낮다. Google Meet는 SFU 기반으로 알려져 있다. |
| 로봇 simulcast/SVC | 기각. Pi 5에는 H.264 하드웨어 인코더가 없어 두 번째 소프트웨어 인코딩은 CPU를 두 배로 쓰고 8Mbps 예산에 uplink를 더한다. 뷰어별 적응은 기존 D-789 규칙(느린 reader 차단)으로 한다. |
| MCU(서버가 디코딩·합성해 한 스트림으로 송출) | 서버 CPU가 크고 지연이 늘지만 약한 클라이언트에 유리하다. Zoom은 SFU+MCU 혼합으로 알려져 있다. |

**결정: Zoom과 같은 혼합, MCU는 유선 사이트 PC에서만.** 이 브랜치(feat/site-console-video)는 SFU 부분만 구현한다. MCU 모자이크(2~7항)는 결정했으나 구현은 후속 변경(feat/site-video-mosaic)으로 미룬다. 그 전까지 격자는 타일별 SFU(최대 6타일)다.
1. 단일 로봇 보기와 Pilot 주행은 항상 SFU 직접 경로다(제어에 중요, 최저 지연). 주행에는 모자이크를 쓰지 않는다.
2. 여러 로봇 격자(최대 6)는 사이트 PC가 로봇들의 기존 MediaMTX 스트림을 한 H.264 스트림(타일 수에 따라 960×720 또는 960×480, ≤2Mbps, ≤15fps, GOP ≤1초)으로 합성해 MediaMTX의 `mosaic/<key>` 경로에 다시 발행한다. 로봇 uplink는 그대로(로봇은 한 번만 발행)이고 AP의 뷰어 downlink는 약 6스트림에서 1스트림으로 준다. D-789가 뷰어 무선 downlink·airtime을 따로 세므로 이것이 목적이다.
3. 모자이크는 누군가 읽는 동안만 돈다(MediaMTX `runOnDemand`, reader가 없으면 5초 뒤 종료). 합성 프로세스는 사이트 PC의 미디어 컨테이너 자원 상한 안에서 돈다. 따라가지 못하거나 죽으면 격자는 유선 관제석에서만 타일별 SFU로 내려가고, 그 외에는 "영상 없음"을 표시한다. 고속 MJPEG는 없다. 로봇 발행자에는 손대지 않는다.
4. 격자 기본은 모자이크다. 유선 관제석은 "개별"(타일별 SFU)을 선택할 수 있다. 선택은 그 브라우저에만 저장한다.
5. 모자이크를 읽으려면 그 안의 모든 로봇에 대한 유효한 읽기 위임이 필요하다. 권한 서비스가 위임 묶음을 검증해 짧은 모자이크 ticket을 준다. 모자이크는 뷰어 주체마다 따로 합성한다(key = 주체와 로봇 목록의 해시). 그래서 한 뷰어의 권한 변화가 다른 뷰어 화면에 영향을 주지 않는다. 동시 모자이크는 2개로 제한한다. 로봇 거부권이나 회수가 생기면 그 로봇의 타일은 5초 안에 검은 타일과 라벨이 된다(그 로봇 프레임은 합성에 쓰지 않는다). 모든 로봇의 권한이 사라지면 세션을 끝낸다.
6. 신선도: 축소된 합성 영상의 watermark는 읽히지 않을 수 있다. 모자이크 프로세스가 축소 전 각 타일 프레임의 watermark로 타일별 마지막 capture sequence·시각을 권한 서비스에 보고하고(`/v1/mosaic/tiles`), 콘솔은 타일별로 1초 초과 경고·2초 초과 숨김을 그린다. 합성에는 로봇 ID 라벨을 그린다.
7. 예산: 모자이크 egress는 사이트→뷰어 egress 지표에 넣고 로봇 uplink에 넣지 않는다(D-789 측정 경계).

Zoom·Meet 구조에 대한 서술은 벤더 문서가 아니라 2차 자료(https://yong-nyong.tistory.com/99 블로그와 시스템 설계 해설)에 근거한다.

### 기존 결정과의 관계

| 결정 | 이번 변경 |
|---|---|
| D-789 | Decision 3의 사이트 계정 금지를 Decision 1~5로 대체한다. 수명·회수·publish/read 분리·Fleet 비중계·명령 권한 없음은 유지. 토폴로지 근거를 Alternatives 부록으로 연결한다 |
| D-136·D-152 | Fleet 비중계·raw DDS 외부 금지 유지. 모자이크는 사이트 미디어 서비스 안에서만 합성한다 |
| D-341 | Fleet 경로에 영상 단어를 쓰지 않고(`media-grant`, `media/validate`) 프레임을 지나가게 하지 않는다 |
| D-427 | 새 최상위 폴더 없음. operations/site_ui/media, operations/site_ui/console, operations/fleet 안에 둔다 |
| D-430 | 영상 위임에 명령 권한 없음. 안전 태그 경로를 바꾸지 않는다 |

### Alternatives

- CORE 사용자 세션을 콘솔에서 받게 하기: 사이트 계정과 로봇 계정을 사람이 두 번 관리해야 하고, 6대 격자에서 로봇마다 로그인해야 한다. 사용자 결정으로 기각.
- Fleet이 영상을 프록시하기: D-136·D-341 위반. 기각.
- 모든 격자를 타일별 SFU로 받기: 무선 뷰어의 downlink·airtime이 로봇 수만큼 늘어난다. 유선 관제석의 선택지로만 남긴다.

### Consequences / Validation

사이트 PC에 모자이크 합성(디코딩 최대 6, 인코딩 1)의 CPU 부하가 생긴다. 측정은 생략했다(D-789 부록). 이 변경의 계약 시험은 역할 허용·거부, 로봇 거부권, 회수·로그아웃, 감사 행과 콘솔 타일 수명(숨김 시 세션 종료)을 확인한다. 모자이크 권한·on-demand·실패 폴백·타일 신선도 시험과 실제 GStreamer 합성 시험은 모자이크 구현 변경에서 추가한다.

폴백: 관제 콘솔에는 로봇 JPEG 경로가 없다. Fleet은 영상을 중계하지 않으므로 WebRTC가 실패한 타일은 "영상 없음"으로 남고 고속 MJPEG나 Fleet 경유 JPEG를 열지 않는다. 제한된 JPEG 폴백이 필요하면 Fleet 비중계와 충돌하므로 별도 결정이 필요하다.
