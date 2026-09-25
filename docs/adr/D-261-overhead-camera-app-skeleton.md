## D-261 천장 카메라 안드로이드 앱 — 골격의 범위, 위치, 기술, 첫 버전의 약속

**Status:** Accepted (2026-09-26). 골격(LOCAL) 착수 결정이다. DEVICE·FIELD 승격이 아니며, D-257의 Proposed 상태를 바꾸지 않는다.

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md) 2·3항 · [D-61](../reference/ROSY%20ADR%20Log.md) 모듈 하네스 · [D-95](D-95-device-observer-hold.md) · [D-136](D-136-.md) 6항.
설계: [`docs/plans/2026-09-26-overhead-camera-android-app-design.md`](../plans/2026-09-26-overhead-camera-android-app-design.md).

**Context:** D-257은 폰이 전용 앱으로 JPEG 프레임을 현장 PC 관측 어댑터에 밀어 보낸다고 정했다. 저장소에는 안드로이드 코드도, 관측 어댑터도 없다. 설계 문서의 열린 질문(패키지 이름, 배포, TLS, 페어링) 중 골격 착수에 필요한 것만 여기서 닫는다. 이 PC에는 Android SDK(platforms 34–36), JDK 21, Gradle 8.11.1이 있다.

**Decision:**

1. **위치.** 새 사이트 모듈 `src/site/overhead/`를 만든다.
   - `android/` — 안드로이드 앱. `COLCON_IGNORE`를 둔다.
   - `overhead/` — Python 관측 어댑터(ROS-free). 이 ADR 범위에서는 **프레임 수신 전용 모드**만 만든다(인식 없음).
   - `protocol/vectors.json` — `rosy-overhead/1` 공통 시험 벡터. Kotlin과 Python 시험이 같은 파일을 읽는다.
   - 모듈은 `tools/harness/harness.yaml`에 등록하고 `progress.md`·`logs.md`를 둔다(D-61).
2. **기술.** Kotlin, Jetpack Compose, CameraX, OkHttp(WebSocket), DataStore. minSdk 26, compile/target 35. Gradle wrapper 8.11.1.
3. **applicationId는 `io.github.livsbittt.rosy.overhead`다.** 저장소 소유 GitHub 계정의 네임스페이스라 남의 도메인을 쓰지 않는다. 첫 외부 배포 전까지만 바꿀 수 있다.
4. **배포는 디버그 APK 직접 설치다.** 스토어, 릴리스 서명, 자동 업데이트는 범위 밖이다. 릴리스 키는 저장소에 두지 않는다.
5. **첫 버전 전송은 `ws://` + Bearer 토큰이다.** 현장 LAN 격리가 전제다. 토큰은 평문으로 흐르므로 공용망·인터넷 경유 운용은 금지한다. TLS는 후속 ADR로 연다.
6. **페어링은 `rosyov://` 딥링크 + 수동 입력이다.** 어댑터가 QR로 `rosyov://<host>:<port>/?t=<token>&s=<source>`를 띄우면, 폰 기본 카메라 앱이 QR을 읽어 딥링크로 앱을 연다. 앱 안 QR 스캐너(ML Kit 등)는 넣지 않는다 — 의존성을 줄인다. 주소·토큰은 저장소에 넣지 않는다.
7. **골격 범위 (설계 문서 A1 + A2).**
   - A1: `vectors.json`, Kotlin `FrameHeader`·`PairingUri`, Python 헤더 파서와 `hello`/`config` 검증. 양쪽이 같은 벡터로 녹색.
   - A2: 앱이 미리보기 → fps 제한 → JPEG → WebSocket으로 보내고, `config`를 따르며, 최신 1장만 보낸다(송신 중이면 버리고 센다). 포그라운드 camera 서비스, 재연결 백오프. 어댑터 수신 전용 모드가 fps·크기·`age_ms`·드롭을 기록한다.
   - 범위 밖: 노출 고정(A4), 발열 대응(A3), `status` 표시(A4), 마커 인식, Fleet 연동.
8. **증거 등급.** JVM 단위 시험 + Python 시험 + `assembleDebug` 성공 = LOCAL. 에뮬레이터 카메라 송신 = LOCAL. 실물 폰 + 현장 LAN 측정만 DEVICE다(D-95와 같은 이유).

**Alternatives:**
- *앱 안 QR 스캐너* — ML Kit/ZXing 의존성과 카메라 권한 흐름이 하나 더 생긴다. 기본 카메라 앱의 QR → 딥링크로 충분하다.
- *별도 저장소* — 프로토콜 변경이 두 저장소로 갈라진다. 같은 모듈 아래 공통 벡터가 어긋남을 시험으로 잡는다.
- *처음부터 TLS* — 현장 자체 인증서 배포·핀 고정이 골격을 막는다. 현장 LAN 격리 전제로 미룬다.
- *Flutter/React Native* — 카메라 세부 제어(AE/AWB lock, 이미지 분석 최신 1장)가 결국 네이티브 CameraX를 부른다. 한 플랫폼(안드로이드)만 필요하다.

**Consequences:** 저장소에 Gradle 빌드가 처음 들어온다. colcon과 Python 하네스는 `android/`를 무시해야 한다. 안드로이드 시험은 JVM 단위 시험만 CI 후보이며, 카메라·서비스는 실기에서만 검증된다.

**Validation / Transition:** (1) `python -m pytest src/site/overhead/test -q` 녹색, (2) `android/gradlew testDebugUnitTest assembleDebug` 녹색, (3) 에뮬레이터 → 수신 전용 어댑터에서 프레임 수신 기록, (4) `rosy_harness.py lint` 녹색. DEVICE(A3)는 실물 폰 30분 기록 후 별도 판정.

**References:** D-61, D-95, D-136, D-257.

---
