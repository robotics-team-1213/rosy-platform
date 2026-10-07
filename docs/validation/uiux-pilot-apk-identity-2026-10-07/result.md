# Pilot 태블릿 설치 APK와 현재 후보 비교 — 2026-10-07

[실물 태블릿 로비 관찰](../uiux-pilot-tablet-2026-10-07/result.md)의 설치 빌드 경계를 확인했다. 로컬 `main` `42d04a9b9`에서 분기한 소스로 Pilot Android debug APK를 빌드했다. Gradle 출력·캐시는 X:에 두고 태블릿 설치 상태는 바꾸지 않았다.

| 항목 | 확인 결과 |
|---|---|
| 현재 소스 후보 APK | `0f3677550c43a0aeb805801c6d464e8befb584d75e9a57f83a8db3470913f905` (SHA-256) |
| 태블릿 설치 APK | `1c6216992abfbf053f77ebf667f98e3528c7dcaeac909b0f7b43dd5cd5cf2d44` (SHA-256) |
| 번들 UI 파일 비교 | `assets/pilot/`·`assets/common/` 50개 중 8개가 다르다. Pilot `styles.css`, `app.js`, `screens/drive-view.js`, `screens/drive.js`, `screens/robot-recording.js`와 공용 `components.css`, `fleet-client.js`, `icons/console.svg`가 포함된다. |
| 빌드·시험 | `:app:testDebugUnitTest :app:assembleDebug` 성공, JVM **93 tests**, 실패·오류·건너뜀 0. |

빌드 원본: `X:/DevTemp/projects/rosy-platform/2026-10-07--pilot-apk-identity/`의 `build/app/outputs/apk/debug/app-debug.apk`, `installed/base.apk`, `asset-diff.json` (SHA-256 `0babba090131991c1a34485dcd5a1530d0b41341308e3ca356f2fa1bfaba32c5`), `logs/gradle.txt` (SHA-256 `da3f19a5868d9c84327e1c0ffee8cae45de742b47bd5c174f1e7ab83b0624248`). 설치 APK는 ADB로 읽어 X:에만 저장했다. APK 해시 차이만으로 소스 차이를 추정하지 않고, 번들 UI 파일을 각각 해시해 차이를 확인했다.

**판정: 현재 후보의 태블릿 G2/G3 HOLD.** 앞선 실물 로비 캡처는 설치 앱의 상태만 증명한다. 현재 후보의 일부 화면·스타일 파일이 태블릿에 없으므로 해당 캡처를 현재 후보의 실물 UI 수용에 쓰지 않는다. 후보를 설치한 뒤 동일 빌드 해시를 확인하고 선언 상태·폭의 화면 및 사용자 독회를 다시 수행해야 한다. 이번 작업은 빌드와 읽기 전용 비교였으며 설치·페어링·주행·푸시는 하지 않았다.
