# Pilot Android 목록 초점과 시스템 바 안전 여백

2026-10-29 · `fix/pilot-native-focus` · 기준 `59e918dfdd` · 최종 runtime `b3ab108ca322` · 최종 촬영 시험 `177706a581`.

## 변경과 범위

발견 목록을 다시 만들 때 현재 초점의 endpoint(host/port/secure)를 보존하고 enabled인 같은 행에 복구한다. 해당 행이 없거나 비활성화되면 보이는 상태 안내로 이동한다. 목록 밖 초점과 초기 렌더는 명시적으로 이동시키지 않는다. 본문 기본 크기는 생성 RosyMetrics.TextBody를 소비한다.

실제 캡처에서 상태 안내가 status bar 아래로, 하단 제어가 navigation bar 아래로 겹치는 것을 발견했다. 기존 PilotViews에 공통 surface를 두고 fitsSystemWindows를 적용해 MainActivity와 debug preview/fixture가 같은 루트를 소비하게 했다. 상태 안내의 focused drawable은 기존 색·테두리·모서리 토큰을 재사용한다. 일반 라벨은 fallback 전까지 focusable로 만들지 않는다.

AndroidJUnitRunner와 Cam에서 이미 사용하는 버전의 시험 의존성만 사용한다. private debug fixture는 발견·계정·연결·명령을 실행하지 않는다. 기존 UiuxPreviewActivity 등록은 보존했다. 최초 debug manifest 추가 때 기존 등록을 덮은 실수는 `37dd3f0cf9`에서 바로 복구했다. 실제 CORE·인증·선택 자격·명령 경로는 바꾸지 않았다.

## 실제 빌드와 반례

승인된 시험 PC의 기존 Android SDK35·google_apis x86_64 이미지·KVM·Java21로 SHA별 Git archive를 별도 디렉터리에 빌드했다. 기존 Cam Gradle wrapper와 생성 토큰 작업을 사용했다. SDK 설치·다운로드·license 승인은 수행하지 않았다. Gradle `:app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest`가 최종 `177706a581`에서 BUILD SUCCESSFUL이었다. JVM은17 suites, 110 passed/1 skipped/0 failed/0 errors이며 skip은 선택적 ShellPageProbe.bundledPageThroughTheAppProxy다.

| 소스 / 원본 경로(scratch 기준) | 실제 결과 | 증명 범위 |
|---|---|---|
| `0241f4f24a4b`, pilot-native-evidence/red/instrumentation.txt | 4 run/3 failures | 초점 복구 전 반례. repro 전용 ref는 제품에 통합하지 않음 |
| `3b2c529858f7`, pilot-native-safe-evidence/pilot-safe-red/instrumentation.txt | 5 run/3 failures | focus가 status/navigation bar 아래에 있는 반례 |
| `b3ab108ca322`, pilot-native-safe-affected/run-1.txt | 615 passed/166 skipped/47 warnings, NEW0 | Python affected 계약. native 실행과 구분 |
| `177706a581`, pilot-native-frame-evidence/pilot-frame-narrow/instrumentation.txt | 5 passed/0 failed | 600×1000, density160, fontScale1.3 |
| `177706a581`, pilot-native-frame-evidence/pilot-frame-wide/instrumentation.txt | 5 passed/0 failed | 1280×800, density160, fontScale1.0 |

native 시험은 실제 Android Views와 DPAD를 사용한다. 같은 표시 이름의 endpoint 구분, 추가·재정렬, 삭제·disabled·빈 목록, host/port/secure 각각 변경, 20행 아래로 이동한 대상의 전체 가시성, 목록 밖 초점 유지와 callback0을 검사한다. bounds는 상하좌우 시스템 바 안에 있고 전체 View가 잘리지 않아야 한다. instrumentation의 adb exit0만으로 합격시키지 않고 JUnit 결과를 확인했다. 두 폭의5개는 같은 사례의 반복이며 고유10개 사례로 합산하지 않는다.

## 캡처와 검토

scratch 정본은 `C:/DevTemp/rosy-ui-standardization/`이다. manifests는 reports27개와 최종 PNG22개의 SHA256을 보존한다. 최종 파일은 pilot-native-frame-evidence의 각 phase/captures에11개씩 있다. 테스트명과 순번으로 상태에 대응시킨다. UIAutomation 촬영 전 frameCommitCallback과 bounded latch로 갱신된 프레임을 기다린다. idle만 기다린 이전 UUID 캡처에서는 상태 안내 초점 표시를 확인할 수 없었으므로 해당 표시의 최종 근거로 쓰지 않는다. 다음 APK 설치 전에 앱 외부 캡처를 host로 회수하고 로컬 복사도 확인했다.

A는 runtime과 최종 촬영 시험을 독립 검토해 추가 P1/P2를 찾지 못했다. B는 새22장을 모두 직접 확인해 상태 안내 fallback의 초점 테두리, 긴 목록의 대상 행 전체, 시스템 바 분리와 외부 제어 초점을 확인했으며 추가 P1/P2는 없었다. 이전 UUID 캡처와 합산하지 않았다. Root도 narrow 상태 안내와 wide 긴 목록의 최종 캡처를 직접 확인했다. 등록된 Pilot native dark 범위이며 밝은 테마 수용으로 확대하지 않는다.

자기 AVD만 명시 serial/AVD/qemu/boot를 확인한 뒤 설치했다. 실제 장치나 공유 adb 서버는 종료하지 않았다. 자기 emulator unit 정리는 stop 후 timeout/ExecMainStatus15로 끝났고 MainPID0·failed를 실제 확인했다. 이를 정상 종료나 UI 실패로 바꾸어 기록하지 않는다. 빌드·instrumentation unit은 실제 종료를 확인했으며 관측 timeout만으로 재시작하지 않았다.

## 게이트와 CE

debug APK·에뮬레이터 fixture의 증거다. 실제 연결 Lobby 전체·TalkBack·실물 태블릿·로봇 명령/정지·서명 release·설치 패키지 배포·ARTIFACT/DEVICE/FIELD 수용이 아니다. Cam·LCD·전체 표면 이행표·다른 브랜치와 통합 검증은 남아 있다. 공개 push/merge·착지는 수행하지 않았다.

CE: 해당 없음 — 초점 경계·공통 시스템 바 여백·실제 그려진 프레임 촬영의 원인과 해결은 소스·회귀 시험·이 기록에서 복원된다. 일반화한 중복 교훈은 만들지 않는다.
