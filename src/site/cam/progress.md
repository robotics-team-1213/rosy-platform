---
module: cam
logical_modules: []
owner: SITE
last_verified: { commit: "c8dfa0dd", date: 2026-09-30 }
gates:
  SOURCE:
    state: GO
    evidence: "D-374 stage 1: moved from src/site/overhead/android; applicationId/namespace io.github.livsbittt.rosy.cam, DataStore cam_settings, Gradle root rosy-cam. Wire names (rosy-overhead/1, /overhead/v1/frames, _rosy-overhead._tcp, rosyov://, Overhead* classes) unchanged. JVM unit tests 130 passed (2026-09-30 Windows, JDK 21)"
    cmd: "cd src/site/cam && gradlew testDebugUnitTest"
  LOCAL:
    state: GO
    evidence: "testDebugUnitTest 130 passed and assembleDebug built app-debug.apk with applicationId io.github.livsbittt.rosy.cam (2026-09-30 Windows). Host contract: test_app_roles.py, test_surface_icons.py green. No phone install on this change"
    cmd: "cd src/site/cam && gradlew testDebugUnitTest assembleDebug"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-261, D-370, D-374, D-377]
plans:
  - docs/plans/2026-09-26-overhead-camera-android-app-design.md
  - docs/plans/2026-09-30-app-identity-rename-plan.md
---
## 현재 상태 (2026-09-30)

- D-374 단계 1로 `src/site/overhead/android`에서 떼어 냈다. 새 applicationId `io.github.livsbittt.rosy.cam`는 **다른 앱으로 설치된다**. 옛 앱(`io.github.livsbittt.rosy.overhead`)의 페어링 설정은 옮겨지지 않는다.
- 와이어 이름(`rosy-overhead/1`, `/overhead/v1/frames`, `ROF1`, `_rosy-overhead._tcp`, `rosyov://`, `OverheadLink`·`OverheadServiceRecord`·`OverheadServerDiscovery`)은 그대로다.
- 이전 이력(2026-09-30 이전)은 `src/site/vision/logs.md`에 있다.
- SOURCE/LOCAL은 JVM 단위 시험과 debug APK 빌드 범위에서 GO다. DEVICE는 새 APK 설치·재페어링 전이라 PARKED다.

## 다음 gate

1. 장치 절차(계획 단계 1 "장치"): 옛 앱 송출 중지·삭제(`adb uninstall io.github.livsbittt.rosy.overhead`), 새 APK 설치, 사이트 QR 또는 D-341 콘솔 승인으로 재페어링, 관제 카메라 패널에서 프레임과 sighting 확인.
2. 옛 폰을 재사용하면 그 source의 폰 토큰을 교체한다.
