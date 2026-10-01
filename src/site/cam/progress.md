---
module: cam
logical_modules: []
owner: SITE
last_verified: { commit: "05280213", date: 2026-10-01 }
gates:
  SOURCE:
    state: GO
    evidence: "D-374 stage 1 moved it from src/site/overhead/android; D-377 renamed src/site/ceiling_camera -> src/site/cam: applicationId/namespace io.github.livsbittt.rosy.cam, DataStore cam_settings, Gradle root rosy-cam, app_name Rosy Cam. Wire names (rosy-overhead/1, /overhead/v1/frames, _rosy-overhead._tcp, rosyov://, Overhead* classes) unchanged. JVM unit tests 130 passed at a8199fd9 (2026-09-30 Windows, JDK 21)"
    cmd: "cd src/site/cam && gradlew testDebugUnitTest"
  LOCAL:
    state: GO
    evidence: "testDebugUnitTest --rerun 130 passed and assembleDebug built app-debug.apk with applicationId io.github.livsbittt.rosy.cam at a8199fd9 (2026-09-30 Windows). Host contract: test_app_roles.py, test_surface_icons.py green. No phone install on this change"
    cmd: "cd src/site/cam && gradlew testDebugUnitTest assembleDebug"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-261, D-341, D-370, D-374, D-377, D-391]
plans:
  - docs/plans/2026-09-26-overhead-camera-android-app-design.md
  - docs/plans/2026-09-30-app-identity-rename-plan.md
---
## 현재 상태 (2026-09-30)

- 이름은 D-377: 표시 이름 `Rosy Cam`, id `cam`. `…rosy.ceilingcamera`는 현장 폰에 설치된 적이 없으므로 재페어링은 `…rosy.overhead` → `…rosy.cam` 한 번이다.

- D-374 단계 1로 `src/site/overhead/android`에서 떼어 냈고, D-377로 `src/site/ceiling_camera` → `src/site/cam`이 됐다. 새 applicationId `io.github.livsbittt.rosy.cam`는 **다른 앱으로 설치된다**. 옛 앱(`io.github.livsbittt.rosy.overhead`)의 페어링 설정은 옮겨지지 않는다.
- 와이어 이름(`rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`, `rosyov://`, `OverheadLink`·`OverheadServiceRecord`·`OverheadServerDiscovery`)은 그대로다.
- 이전 이력(2026-09-30 이전)은 `src/site/vision/logs.md`에 있다.
- SOURCE/LOCAL은 JVM 단위 시험과 debug APK 빌드 범위에서 GO다. DEVICE는 새 APK 설치·재페어링 전이라 PARKED다.
- 2026-10-01 D-391 공유 벡터(`feat/cam-d391-shared-vectors`): Kotlin 시험이 `failure-classes.v1.json`(28)·`site-link.v1.json`(42)을 모두 돌린다. `tls_host`는 `.local` 이름만 받고, 시스템 DNS 경로는 없앴다. 닫힘 4403은 최종이다(재페어링 안내 없음). JVM 시험 250 passed.
- 2026-10-01 D-391 E1/E2(`feat/cam-site-link-mdns`, main 미병합): 저장은 사이트 연결 기록(`SiteLink`)이고 IP를 다이얼 대상으로 저장하지 않는다. 접속마다 mDNS로 `tls_host`를 찾고(→ `manual_host` "수동 주소" → `not_discovered`), SNI·호스트명 검사는 `tls_host`다. 태블릿 실기와 독립 리뷰(M1–M3, m1–m9)를 반영해 JVM 시험 235 passed. 태블릿(Android 11)에서 이름 재발견과 `not_discovered` 진단을 확인했다.
- 2026-10-01 D-341 페어링 클라이언트(`feat/cam-rosy-pair-client`, main 미병합): `pairing/`에 `rosy-pair/1` 코드·커밋·CA 지문·pairable 규칙, 요청·공개·결과·응답 모양, 상태 기계(`PairingClient`), S2 라우트 HTTPS transport(`HttpPairingTransport`, 첫 leaf 기록 후 그 leaf만 신뢰), 2 s 조회·Retry-After(`PairingSession`), 설정의 "사이트에 연결 요청"과 페어링 화면이 있다. `pairing.v1.json`(rosy-00 93336f48과 바이트 동일)의 모든 사례를 Kotlin이 돌린다. JVM 시험 291 passed, lint 0 errors. 실기는 아직이다.
- 페어링에서 남은 것:
  1. rosy-00: `_rosy-overhead._tcp` TXT `pair=rosy-pair/1` 광고와 Compose 배선. 광고가 없으면 앱은 요청 버튼을 띄우지 않는다(D-341 14). 그 전에는 실기에서 이 경로를 열 수 없다.
  2. 병합 순서: `feat/d341-fleet-pairing-server`(S1–S3, 920bef4d)가 먼저 main에 간다. 벡터 파일은 바이트 동일이라 충돌하지 않는다.
  3. DEVICE(D-341 판정 등급): S21에서 발견 → 요청 → 콘솔 코드 입력 → 지문 확인 → 고정 CA 송출 60 s, 회수 후 4401로 멈춤, 사이트 IP 변경 후 재연결.
  4. 화면 회전 등으로 Activity가 다시 만들어지면 진행 중인 페어링은 사라진다(서버는 300 s/120 s 뒤 스스로 만료). 필요하면 ViewModel로 옮긴다.
  5. confirm 응답이 오는 길에 끊기면 서버는 자격을 활성으로 두었는데 폰은 버린다. 운용자가 회수한 뒤 다시 요청한다.
  6. lint `CustomX509TrustManager` 경고 1건(`FirstContactTrust`)은 D-341 3 첫 접촉 기록 때문에 의도된 것이다.

## 다음 gate

1. 장치 절차(계획 단계 1 "장치"): 옛 앱 송출 중지·삭제(`adb uninstall io.github.livsbittt.rosy.overhead`), 새 APK 설치, 사이트 QR 또는 D-341 콘솔 승인으로 재페어링, 관제 카메라 패널에서 프레임과 sighting 확인.
2. 옛 폰을 재사용하면 그 source의 폰 토큰을 교체한다.
3. D-341 9 인증서 고정 DEVICE 점검(S21): (a) 프록시가 leaf+CA(`site-fullchain.crt`)를 보내고 `rosy-vision pair-link --pin-ca --pin-cert`의 CA pin 링크로 60 s 이상 송출, (b) leaf만 보내는 프록시에 CA pin 링크 → `TLS_PIN` 안내 후 정지, (c) 위조 체인(다른 CA leaf + 진짜 사이트 CA) 거절, (d) 사이트 CA 서명이 SHA-1이 아님을 `openssl x509 -text`로 확인. 수신기 hello 대기가 4400 "no hello"로 닫혀도 카메라가 멈추지 않고 다시 붙는지도 본다.
4. 열린 후속: `network_security_config.xml`에 user 인증서 trust-anchor가 없어 D-341 16항의 되돌림 경로(`static` source + 사용자 CA 설치)는 이 앱에서 동작하지 않는다. NSC는 바꾸지 않았다 — 되돌림 경로를 살릴지 ADR에서 정한다.
5. D-391 재발견 DEVICE 점검(S21·태블릿): (a) `tls_host` 기록으로 송출 중 사이트 PC IP를 바꿔도 30 s 캐시 뒤 재접속이 새 주소로 붙는다, (b) 같은 SSID 다른 AP에 붙으면 5 s 안에 "사이트가 이 Wi-Fi에서 보이지 않습니다"와 두 서브넷이 보인다, (c) 멀티캐스트가 막힌 망에서 `manual_host`로 붙고 화면에 "수동 주소"가 뜬다, (d) 옛 IP 저장값이 이관되어 그대로 붙고 광고에서 `tls_host`를 배운다, (e) API 34 미만 폰에서 resolve 충돌(설정 화면 검색과 동시) 없이 찾는다. 공유 벡터 `failure-classes.v1.json`·`site-link.v1.json`이 main에 오면 Kotlin 시험을 그 벡터로 옮긴다.
