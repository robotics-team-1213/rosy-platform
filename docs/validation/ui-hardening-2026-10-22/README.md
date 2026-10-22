# UI hardening — 2026-10-22

Learning 제외. Impeccable의 harden·Android 지침에 따라 기존 동작을 보존하며 긴 이름과 오류 복구 조작의 넘침을 수정했다. Fleet에는 같은 문제를 재현하지 못해 변경하지 않았다.

## 검증 증거

| 대상 | 시험한 소스 | 실행 결과 |
| --- | --- | --- |
| Pilot·Games | a4d2200d86 | 원격 Chromium 전체 206 passed, skipped 0, NEW 0 |
| Robot 접속 홈 | ed783cbaf5 | 원격 Chromium 전체 16 passed, NEW 0 |
| Pilot 캡처 | b3b416fb13 | 긴 이름 세 폭 3 passed, NEW 0 |
| Cam | dadf5eed1f | JDK 21 / SDK 35: testDebugUnitTest·assembleDebug·assembleDebugAndroidTest·lintDebug 성공. JVM 440 passed, skipped 0 |
| Cam 렌더링 | dadf5eed1f | 격리한 API 35 에뮬레이터에서 StreamRecoveryTest 3 passed, 16.956초 |

Cam은 실제 StreamScreen에 가짜 Unauthorized 상태를 주입했다. 320·390·800dp, 글꼴 배율 1.3에서 복구 조작 표시·48dp 누름면·폭 경계·자세히 토글·정지 후 설정 순서를 검사했다. 실제 카메라 서비스는 시작하지 않았다. 시험 후 에뮬레이터를 종료했다.

`captures/`에는 Cam 여섯 장, Pilot 세 장, Games 세 장, Robot 두 장을 보존했다. Cam 320·800, 웹 세 화면의 320px 캡처를 직접 확인했다. 원본 로그·JUnit·lint XML·Compose semantics는 시스템 TEMP의 `rosy-cam-ui-refactor/`에 있다.

## lint와 크기 검사

Cam의 값 상태를 mutableIntStateOf로 바꾸고 minSdk 26에서 불필요한 SDK 분기를 지웠다. BouncyCastle 1.83은 버전을 유지해 카탈로그로 옮겼다. 기존 경고 두 건·정보 한 건을 해결했으나 시험 runner 의존성의 업데이트 알림 세 건이 추가되어 최종 lint는 오류 0·경고 43·정보 0이다. 버전 일괄 갱신과 LAN·인증서·백업·wake lock 정책 변경은 하지 않았다.

Android 표준 src/androidTest를 시험으로 분류하되 파일당 1,500줄 제한은 유지한다. 기존 Cam ui Kotlin 패키지를 크기 단위로 등록하고 경로와 package 선언의 일치를 검증한다. Pilot의 로비 시험은 공통 fixture를 사용해 별도 파일로 이동했다. 한도를 높이지 않았다.

## 최종 재검증

| 소스 | 실행 | 결과 |
| --- | --- | --- |
| 5cce9acaaf | Pilot 두 브라우저 파일·Games·Robot 접속 홈, ROSY_RUN_BROWSER_TESTS=1 | 222 passed, skipped 0, 400.76초, NEW 0 |
| 5cce9acaaf | 크기·모듈 구조·하네스·브라우저 선택기 | 181 passed, NEW 0 |
| 0312f5a9b9 | Pilot 상태 폴링 브라우저 회귀, ROSY_RUN_BROWSER_TESTS=1 | 1 passed, 7.04초, NEW 0 |
| 0312f5a9b9 | mapped affected 1 | 1,214 passed, 334 skipped, 125.87초, NEW 0 |
| 0312f5a9b9 | mapped affected 2 (overhead) | 736 passed, 51.24초, NEW 0 |

시험 중 누락도 수정했다. 분리한 로비 파일을 자동 브라우저 선택기에 등록하고 OMX의 기존 선택 범위를 유지했다. 전체 affected 수집에서 발견한 상태 폴링 시험의 옛 fixture import도 공통 conftest 사용으로 고쳤다. 독립 코드 검토 승인 후 후자의 실제 브라우저 실행까지 확인했다. 원본 실행 로그는 위 TEMP 경로의 final-browser·final-guards·final-pilot-poll·final-affected-fixed에 있다. 334 skipped는 이 선택 실행의 결과이며 별도 브라우저 실행이 모든 선택적 시험의 수용을 뜻하지 않는다.

중간 RED 커밋들은 로컬 archive/ui-hardening-trials-20261022에 보존하고 제품 변경을 5cce9acaaf로 합쳤다. 합친 직후 보존 참조와 tree 차이 0을 확인했다. 뒤이은 fixture import 수정은 0312f5a9b9다. 원래 기준 9d13caf9ba504ea5a009120f9506399d69d7c553부터 두 커밋 모두 size_range를 통과했다. 마지막 기록 추가는 문서만 바꾼다.

하네스·구조 변경으로 CI FULL 선택이 필요하다. 위 mapped affected 통과는 CI FULL 증거를 대신하지 않으며 이번에는 전체 CI·착지를 요청하지 않았다. 기존 PRODUCT.md의 혼합 Platform 값과 원문을 확보하지 못한 설치 경고는 해결된 것으로 기록하지 않는다. Cam 평가는 별도 Android 지침과 네이티브 실행 증거를 사용했다.

## 수용 범위

실물 폰·태블릿, 실제 송출·주행, 음성 TalkBack, DEVICE/FIELD, 전체 제품 수용은 확인하지 않았다. main 병합·push·배포는 수행하지 않았다. CE: 해당 없음 — 원인과 해결을 코드 및 회귀 시험으로 설명할 수 있다.
