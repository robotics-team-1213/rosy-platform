# ceiling_camera logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

이 모듈의 2026-09-30 이전 이력은 [`src/site/site_vision/logs.md`](../site_vision/logs.md)의 2026-09-30 이전 항목(`overhead-app`)이다.

## 2026-09-30 · uncommitted · refactor(ceiling-camera): D-374 stage 1 — split the phone app out of overhead

- 변경: `src/site/overhead/android` → `src/site/ceiling_camera`(`git mv`). `applicationId`·`namespace`·Kotlin 패키지 `io.github.livsbittt.rosy.overhead` → `io.github.livsbittt.rosy.ceilingcamera`, Gradle `rootProject.name` `rosy-ceiling-camera`, DataStore `ceiling_camera_settings`. 프로토콜 벡터는 `test/fixtures/protocol/overhead-ingest.v1.json`으로 옮겼고 JVM 시험 경로를 고쳤다. 런처 아이콘 원본은 `web_common/icons/ceiling-camera.svg`. 레지스트리 id `ceiling-camera`. 와이어 이름은 그대로(D-374 3항).
- 증거: `gradlew testDebugUnitTest assembleDebug` BUILD SUCCESSFUL, JVM 시험 130 passed, APK `app/build/outputs/apk/debug/app-debug.apk`의 applicationId `io.github.livsbittt.rosy.ceilingcamera` (2026-09-30 Windows, JDK 21).
- gate 변화: 새 모듈. SOURCE/LOCAL GO, DEVICE/FIELD PARKED(새 APK 설치·재페어링 전).
