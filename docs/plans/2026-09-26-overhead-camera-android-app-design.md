# 천장 카메라 안드로이드 앱 — 구조 설계

**결정:** [D-257](../adr/D-257-site-lane-map-and-overhead-sightings.md) 2항(개정). 상위 계획: [사이트 차선 관제 + 폰 천장 카메라](2026-09-26-site-overhead-lane-console-design.md).
**상태:** 설계. 코드 0줄.

## 1. 앱이 하는 일 (그리고 하지 않는 일)

**한다:** 폰 카메라 프레임을 JPEG로 만들어 **지정된 주소(현장 PC의 관측 어댑터)로 밀어 보낸다.**

**하지 않는다:** 마커 인식, 좌표 계산, 로봇 제어, Fleet 호출, 영상 저장·녹화. 인식은 어댑터가 한다(D-257 3항). 앱은 Fleet 주소도 모른다.

왜 끌어오기(IP카메라 앱이 서버가 되고 PC가 접속)가 아니라 밀어 보내기인가:
- 폰 IP는 DHCP로 바뀐다. PC 주소 하나만 고정하면 된다.
- 속도·해상도를 어댑터가 정해 내려보낼 수 있다 — 대역 예산(D-136)을 한 곳에서 쥔다.
- 어댑터가 "코너 3/4 보임" 같은 **글자 상태**를 되돌려 보내 폰 거치를 도울 수 있다.

기성 IP카메라 앱(MJPEG 끌어오기)은 어댑터의 시험용 대체 입력으로 남긴다.

## 2. 전체 흐름

```
[폰 앱]                                               [현장 PC: 관측 어댑터]
 CameraX ImageAnalysis (최신 1장만)
   → JPEG 인코딩 (회전 안 함)
   → WebSocket 바이너리 1메시지 = 헤더 + JPEG ──────▶  /overhead/v1/frames
                                                        최신 1장만 보관 → ArUco → 호모그래피
 ◀──────────── 텍스트 JSON: config / status ─────────   → Fleet sightings (D-257 4항)
 화면: 미리보기 + 연결·fps·kbps + "코너 n/4, 로봇 k대"
```

## 3. 전송 프로토콜 `rosy-overhead/1`

**연결:** `ws://<어댑터>:<포트>/overhead/v1/frames`, 업그레이드 요청에 `Authorization: Bearer <token>`. 현장 LAN 전용이며 v1은 TLS를 쓰지 않는다(토큰이 평문 — 현장 LAN 격리가 전제, §8).

**1) 폰 → 어댑터, 첫 텍스트 메시지 `hello`:**
```json
{"type": "hello", "proto": "rosy-overhead/1", "source": "overhead-1",
 "app_version": "0.1.0", "device": "<모델명>",
 "sensor": {"width": 1280, "height": 720, "rotation_deg": 90}}
```

**2) 어댑터 → 폰, `config` (연결 직후 + 바뀔 때마다):**
```json
{"type": "config", "fps": 3, "width": 1280, "jpeg_quality": 70, "max_bytes": 200000}
```
폰은 어댑터가 준 값을 따르고 스스로 올리지 않는다. 발열이 오르면 스스로 **내릴** 수는 있다(§5).

**3) 폰 → 어댑터, 바이너리 프레임** (리틀엔디언, 헤더 20바이트 + JPEG):

| 오프셋 | 크기 | 필드 | 뜻 |
|---|---|---|---|
| 0 | 4 | `magic` | ASCII `ROF1` |
| 4 | 4 | `seq` u32 | 연결마다 0부터, 1씩 증가 |
| 8 | 4 | `age_ms` u32 | 보내는 순간 기준, 촬영 후 경과 ms (인코딩·대기 포함) |
| 12 | 2 | `width` u16 | JPEG 폭 |
| 14 | 2 | `height` u16 | JPEG 높이 |
| 16 | 2 | `rotation_deg` u16 | 센서 기준 회전 (정보용, 어댑터는 무시해도 됨) |
| 18 | 2 | `reserved` u16 | 0 |
| 20 | … | JPEG | `max_bytes` 이하 |

- **시각:** 폰과 PC 시계는 맞지 않는다. 어댑터가 `captured_at = 수신시각 − age_ms`로 자기 시계 기준 촬영 시각을 만든다. 오차는 LAN 전송 지연(수 ms)뿐이다.
- **회전하지 않는다:** 호모그래피가 회전·뒤집힘을 흡수하므로 폰은 프레임을 돌리지 않는다(CPU 절약).
- **최신 1장:** 이전 프레임이 아직 송신 큐에 있으면 새 프레임을 버리고 버린 수를 센다. 폰도 어댑터도 큐를 늘리지 않는다(D-136 6항).

**4) 어댑터 → 폰, `status` (1 Hz, 거치 도움용, 글자만):**
```json
{"type": "status", "corners_seen": [30, 31, 33], "corners_needed": 4,
 "robots_seen": ["rosy_01"], "rx_fps": 2.9, "dropped": 0}
```

**거절:** 토큰 틀림 → 업그레이드 401. `proto` 불일치 → close 4400. 같은 `source`가 이미 연결됨 → 새 연결을 받고 옛 연결을 close 4409(폰 재부팅 후 재접속이 이겨야 한다). `max_bytes` 초과 프레임 → 버리고 카운트, 연결 유지.

**공통 시험 벡터:** 헤더 인코딩 예시 바이트를 `src/site/overhead/protocol/vectors.json`에 두고 Kotlin 단위 시험과 Python 시험이 같은 파일을 읽는다. 한쪽만 바뀌면 양쪽 중 하나가 깨진다.

## 4. 페어링

로컬 개발은 `rosyov://<host>:<port>/?t=<token>&s=overhead-1`, TLS reverse proxy가 있는 사이트는 여기에 `&tls=1`을 붙여 Android가 `wss://`를 쓰게 한다. 앱은 QR을 스캔해 주소·토큰·source 이름을 저장한다. 수동 입력도 둔다. 주소·토큰은 저장소에 넣지 않는다(공개 저장소).

## 5. 카메라와 폰 수명주기

- **CameraX** `Preview` + `ImageAnalysis`(`STRATEGY_KEEP_ONLY_LATEST`, YUV_420_888). 분석 콜백에서 fps 제한 → YUV→JPEG 인코딩 → 링크로 전달.
- **노출·초점·화이트밸런스 고정:** 마커 인식은 밝기 흔들림에 약하다. 거치 후 "노출 고정" 버튼 → Camera2 interop으로 AE/AWB lock, 초점 고정. 조명이 바뀌면 다시 누른다. (실물 조건: 흰 벽·카펫 — 실측 필요)
- **렌즈:** 기본 후면 광각 1배. 트랙 전체가 안 들어오면 초광각 선택 옵션(기기마다 다름).
- **포그라운드 서비스:** `foregroundServiceType="camera"`(Android 14+는 `FOREGROUND_SERVICE_CAMERA` 권한, 앱이 보이는 상태에서 시작). 화면 켜짐 유지(밝기 최저 허용), partial wake lock, Wi-Fi 고성능 lock(절전으로 인한 지연 튐 방지).
- **발열:** `PowerManager` 열 상태가 `SEVERE` 이상이면 fps를 스스로 반으로, `CRITICAL`이면 송신 중단 + 화면 경고. 전원 연결 운용을 권장한다.
- **재연결:** 끊기면 1 s → 2 s → 5 s 백오프. 끊긴 동안 프레임을 쌓지 않는다.

## 6. 앱 구조

위치 제안: `src/site/overhead/android/` (+ `COLCON_IGNORE`, colcon이 건드리지 않게). 관측 어댑터(`src/site/overhead/overhead/`)와 같은 사이트 모듈 아래에 둬서 프로토콜 변경이 한 커밋에 묶이게 한다.

```
src/site/overhead/
  protocol/vectors.json            # 공통 시험 벡터 (§3)
  overhead/                        # Python 관측 어댑터 (상위 계획 Stage 2)
  android/
    COLCON_IGNORE
    settings.gradle.kts  build.gradle.kts  gradle/libs.versions.toml  gradlew
    app/
      build.gradle.kts
      src/main/AndroidManifest.xml
      src/main/java/<패키지>/
        MainActivity.kt            # Compose 진입점, 권한 요청
        ui/StreamScreen.kt         # 미리보기, 시작/정지, 상태, 노출 고정
        ui/SettingsScreen.kt       # 주소·토큰·source 수동 입력
        ui/PairScanner.kt          # QR 스캔
        camera/CameraController.kt # CameraX 바인드, fps 제한, AE/AWB/AF lock
        camera/JpegEncoder.kt      # YUV_420_888 → JPEG
        link/FrameHeader.kt        # §3 헤더 pack/unpack (순수 Kotlin)
        link/OverheadLink.kt       # OkHttp WebSocket, hello/config/status, 최신 1장, 백오프
        service/StreamService.kt   # 포그라운드 camera 서비스, wake/Wi-Fi lock, 열 감시
        settings/SettingsStore.kt  # DataStore
        settings/PairingUri.kt     # rosyov:// 파싱 (순수 Kotlin)
      src/test/java/…              # JVM 단위 시험: FrameHeader(벡터), PairingUri, fps 제한기, 백오프
```

**기술 선택:** Kotlin, Jetpack Compose, CameraX, OkHttp(WebSocket), DataStore, QR은 ML Kit 바코드 또는 ZXing. minSdk 26, target/compile 35. 이 PC에 SDK(platforms 34–36, build-tools 35/36)와 JDK 21, Gradle 8.11.1이 있어 로컬 빌드가 가능하다.

**순수 로직을 떼어 둔다:** `FrameHeader`, `PairingUri`, fps 제한기, 백오프는 안드로이드 API 없이 JVM 시험으로 검증한다. 카메라·서비스는 실기에서만 검증된다.

## 7. 단계와 게이트

| 단계 | 내용 | 증거 등급 |
|---|---|---|
| A1 | 프로토콜 벡터 + Kotlin `FrameHeader`/`PairingUri` + Python 수신 쪽 파서, 양쪽 시험 녹색 | LOCAL |
| A2 | 앱 골격: 미리보기 → JPEG → WebSocket, 어댑터의 수신 전용 모드가 fps·크기·`age_ms` 기록 | LOCAL(에뮬레이터 카메라) |
| A3 | 실기 폰 + 현장 LAN: 30분 연속, 평균/최대 `age_ms`, 드롭률, 대역(kbps), 열 상태, Wi-Fi 끊김 후 재접속 | DEVICE |
| A4 | 거치 도움: 어댑터 `status`로 "코너 n/4" 표시, 노출 고정 전후 검출률 비교 | DEVICE |

에뮬레이터 통과는 DEVICE가 아니다(D-95와 같은 이유).

**대역 초기값(실측으로 조정):** 1280×720, JPEG 70, 3 fps → 프레임당 약 50–90 KB → 약 1.2–2.2 Mbps. 트랙이 약 2.4 m 폭으로 찍히면 1280 px에서 약 530 px/m, 5 cm 마커는 약 26 px다. 이보다 작으면 검출이 불안정할 수 있어 해상도를 먼저 내리지 않는다 — fps를 먼저 내린다.

## 8. 열린 질문

1. 앱 패키지 이름(applicationId) — 공개 저장소에 들어간다.
2. 배포 방식 — v1은 APK 직접 설치(사이드로드)로 충분한가?
3. 현장 Wi-Fi가 로봇과 같은 망인가? 같다면 폰 스트림이 로봇 제어 트래픽과 경쟁한다(D-136 안전계 1 Mbps 예약). 분리 SSID/대역이 가능한가?
4. v1 평문 토큰(ws://)으로 충분한가, 아니면 처음부터 TLS(자체 인증서 핀 고정)가 필요한가?
5. 폰 기종 — 초광각 렌즈 유무가 거치 높이를 정한다.
