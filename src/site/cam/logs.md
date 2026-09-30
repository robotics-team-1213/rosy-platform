# ceiling_camera logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

이 모듈의 2026-09-30 이전 이력은 [`src/site/vision/logs.md`](../vision/logs.md)의 2026-09-30 이전 항목(`overhead-app`)이다.

## 2026-09-30 · uncommitted · refactor(ceiling-camera): D-374 stage 1 — split the phone app out of overhead

- 변경: `src/site/overhead/android` → `src/site/ceiling_camera`(`git mv`). `applicationId`·`namespace`·Kotlin 패키지 `io.github.livsbittt.rosy.overhead` → `io.github.livsbittt.rosy.ceilingcamera`, Gradle `rootProject.name` `rosy-ceiling-camera`, DataStore `ceiling_camera_settings`. 프로토콜 벡터는 `test/fixtures/protocol/overhead-ingest.v1.json`으로 옮겼고 JVM 시험 경로를 고쳤다. 런처 아이콘 원본은 `web_common/icons/ceiling-camera.svg`. 레지스트리 id `ceiling-camera`. 와이어 이름은 그대로(D-374 3항).
- 증거: `gradlew testDebugUnitTest assembleDebug` BUILD SUCCESSFUL, JVM 시험 130 passed, APK `app/build/outputs/apk/debug/app-debug.apk`의 applicationId `io.github.livsbittt.rosy.ceilingcamera` (2026-09-30 Windows, JDK 21).
- gate 변화: 새 모듈. SOURCE/LOCAL GO, DEVICE/FIELD PARKED(새 APK 설치·재페어링 전).

## 2026-09-30 · uncommitted · refactor(cam): D-377 ceiling_camera becomes Rosy Cam in src/site/cam
- 변경: `src/site/ceiling_camera` → `src/site/cam`(`git mv`, 이동 커밋 분리). `applicationId`·`namespace`·Kotlin 패키지 `io.github.livsbittt.rosy.cam`, `rootProject.name` `rosy-cam`, `app_name` `Rosy Cam`, DataStore `cam_settings`, 인텐트 action `io.github.livsbittt.rosy.cam.action.*`, 런처 아이콘 원본 `web_common/icons/cam.svg`(주석·`LauncherIconParityTest`). 하네스 모듈 `ceiling_camera` → `cam`.
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug` BUILD SUCCESSFUL, JVM 시험 130 passed, 0 failed (2026-09-30 Windows, JDK 21). APK `src/site/cam/app/build/outputs/apk/debug/app-debug.apk`.
- gate 변화: 없음. SOURCE/LOCAL GO, DEVICE/FIELD PARKED(새 APK 설치·재페어링 전). `…rosy.ceilingcamera`는 현장에 설치된 적이 없어 재페어링은 여전히 한 번(`…rosy.overhead` → `…rosy.cam`).
- 결정: D-377. `Overhead*` 클래스와 와이어 이름은 그대로.

## 2026-09-30 · 5358ce49 · feat(cam): ultra-wide lens (화각 넓게/기본)
- 변경: `LensSelector`(순수, JVM 시험 12개)가 후면 카메라 중 가로 화각이 가장 넓은 것(초점거리 `LENS_INFO_AVAILABLE_FOCAL_LENGTHS` 최솟값과 `SENSOR_INFO_PHYSICAL_SIZE` 긴 변으로 계산, 물리 카메라 우선)을 WIDE로, CameraX 첫 후면 카메라를 STANDARD로 고른다. 3° 이상 넓지 않으면 WIDE는 STANDARD로 물러나고 화면이 그렇게 말한다. `LensProbe`가 `Camera2CameraInfo`로 특성을 읽고, `CameraController`는 카메라 필터로 그 id를 바인딩한다. 설정 `lens`(DataStore `cam_settings`, `wide`|`standard`, 미설정이면 wide)를 연결 설정 화면의 "화각"에서 고른다. 촬영 중 바꾸면 다시 바인딩(적응 JPEG 품질 초기화, 타임스탬프 소스·센서 크기 다시 읽기)하고 링크를 즉시 다시 연결해 새 hello를 보낸다. 송출 화면·알림에 "렌즈: 초광각 2.2 mm · 화각 104°". hello에 선택 필드 `lens {kind, focal_mm, hfov_deg}`(벡터 `hello_with_lens`, `hello_lens`).
- 근거: S21(Android 15)의 기본 카메라 zoomRatioRange는 [1.0, 8.0]이라 `setZoomRatio(0.5)`는 불가능하고, 초광각은 별도 camera id 2(2.2 mm, 가로 104.1°; 기본 5.4 mm, 67.8°)로 노출된다(`dumpsys media.camera`).
- 증거: `gradlew testDebugUnitTest --rerun assembleDebug` BUILD SUCCESSFUL, JVM 시험 146 passed, 0 failed; `lintDebug` 0 errors, 42 warnings(모두 기존 항목) (2026-09-30 Windows, JDK 21).
- gate 변화: 없음. DEVICE PARKED: S21이 다른 세션(rosy-84, 옛 `…ceilingcamera` 앱, `:18448`)에 물려 있어 설치·실기 비교를 미뤘다.
- 교훈: 0.5×는 줌 비율이 아니라 다른 카메라 id일 수 있다. 카메라 id를 고를 때는 `DEFAULT_BACK_CAMERA`가 아니라 특성으로 고른다.
