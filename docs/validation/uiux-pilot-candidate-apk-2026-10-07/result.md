# Pilot 현재 후보 APK 빌드와 실물 설치본 차이 — 2026-10-07

로컬 `main` `db30e1a0a`의 Pilot Android **debug** 후보를 2026-10-07에 설치 없이 빌드했다. 소스는 F:의 격리 worktree, Gradle 캐시·출력은 X:에 두었다.

| 항목 | 읽은 결과 |
|---|---|
| 후보 APK | `X:/DevTemp/rosy-current-pilot-apk/build/app/outputs/apk/debug/app-debug.apk`, SHA-256 `53a38d31b54252e8fc699942c0e3c4760de5dfb346cec0bed7646f73c628822f` |
| 빌드·시험 | `:app:testDebugUnitTest :app:assembleDebug` 성공. JVM 12 suite, **93 tests**, 실패·오류 0. Gradle 로그 `X:/DevTemp/rosy-current-pilot-apk/gradle.txt`, SHA-256 `c33af3c70ad601265e26b121bea74fd16b40c2077e861b301526512d9513eff7`. |
| 번들 소스 동일성 | 후보 APK의 `assets/pilot/`·`assets/common/` 50개 모두 `db30e1a0a` 소스 파일과 SHA-256 일치. |
| Lenovo 설치 APK | [읽기 전용 장치 기록](../uiux-current-width-device-2026-10-07/result.md)의 SHA-256 `e69fac43e2b08ad533073ebdc8d35da5ecdcc662e686e03855a2603db06cd578`. 후보와 다른 번들 파일은 `pilot/screens/connect.js`, `pilot/screens/drive.js`, `pilot/styles.css` 3개다. |

이 후보 APK는 **빌드·JVM 시험·번들 출처**까지 확인한 LOCAL 산출물이다. 태블릿에 설치하지 않았고, 실제 로봇 연결·페어링·주행·비상 정지 readback 또는 요청자 G3 작업 독회가 아니다. 현재 설치본의 로비 캡처를 이 후보의 실물 G2/G3로 대체하지 않는다. 설치 후보와 기기 상태가 확인된 후 선언 상태·폭 화면을 다시 읽고 사용자가 작업 독회를 완료하기 전까지 Pilot과 제품 전체 UI/UX 판정은 **HOLD**다.
