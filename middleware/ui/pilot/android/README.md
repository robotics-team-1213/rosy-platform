# Rosy Pilot Android

앱을 열면 같은 LAN에서 켜진 로봇을 찾아 목록에 보여준다. 로봇을 누르면 연결한다.
연결 화면의 `두 번째 로봇`에서 다른 로봇을 고르면 두 화면을 나란히 연다(D-582).
두 화면은 각자 인증한 로봇에만 카메라·조종 요청을 보낸다. 각 화면에서 `주행 시작`을
따로 눌러야 조종 모드가 열리며, 앱을 닫거나 화면을 끄면 두 연결 모두 종료한다.
두 로봇의 동시 실물 주행은 별도 FIELD 수용 대상이다.
파일 가져오기, 주소 입력, CA 설정은 사용자 흐름에 없다. 선택한 CORE의
`/api/v1/auth/connection`이 개발 모드이면 한 시간짜리 세션을 자동으로 받고,
페어링이 필요하면 기존 숫자·영문 8자리 코드를 한 번 입력한다. 4자리 단축은 후속 ADR 제안이다.
개발 모드는 서버의 명시적 설정과 개발 배포 환경을 함께 요구한다.

페어링 자격은 Android Keystore의 AES-GCM으로 암호화해 저장한다. 다음 선택 때
같은 로봇·전송·주소·포트에만 재사용하고 `/auth/whoami`로 유효성을 확인한다.
401과 로그아웃은 저장 자격을 지운다. 개발 세션은 저장하지 않는다.
백그라운드 전환은 조종 세션을 닫으며 재실행 때 로봇 목록을 다시 찾는다.
이전 CORE가 연결 모드 조회에 404를 반환하면 기존 8자리 코드 페어링만 제공한다.
페어링 후 인증된 로봇 ID를 확인한다. 자동 개발 승인은 제공하지 않는다.

현재 CORE의 HTTP와 HTTPS를 광고된 전송대로 지원한다. HTTP 세션은 선택한 주소에
고정하며 주소가 바뀌거나 lost 이벤트를 받으면 기존 자격을 새 주소로 넘기지 않는다.
HTTPS는 기본 플랫폼 CA와 hostname 검증을 사용한다. TLS 오류를 무시하거나 HTTP로
내리지 않는다. 광고는 인증이 아니며 조종 화면 전에 인증된 `/system/info`의 ID를 대조한다.

D-340 native shell의 조건은 태블릿 설치와 Android NSD다. 기존 `middleware/ui/pilot`의 JS·화면과
shared/web의 canonical allowlist 자산을 APK 안에 묶는다. 로봇에서 UI를 내려받지 않는다.
로봇이 없어도 앱의 선택 화면은 실행되며 bundled 화면은 네트워크 없이 제공된다.
private loopback proxy는 무작위 HttpOnly
cookie(두 로봇에서는 프록시마다 다른 이름), 정확한 Host/Origin 검사, 경로 allowlist로 제한한다. JS bridge·외부 탐색·파일
접근은 없다. CORE 응답의 `X-Rosy-*` 카메라 증명 헤더(출처·시퀀스·촬영시각·변형)는
번들 화면의 프레임 검증(web_common evidence.js)을 위해 그대로 전달한다. PWA의 sessionStorage 자격을 URL·로그에 넣지 않고 쿠키를 CORE로 전달하지
않는다. CORE로는 API와 WS만 전달하며 API는 PWA의 Authorization을 사용한다.
앱이 연 세션만 쓴다. 번들 화면은 앱 안에서 두 번째 개발 연결, 코드 입력, 로봇 콘솔이나
다른 로봇으로의 이동을 열지 않는다.
HTML에는 CSP를 보낸다. 원본 JS는 복제 구현하지 않고 X:의 generated assets에서 묶는다.

후보 64개·60초, legacy resolve 직렬 처리·갱신 jitter, WS 대기 8개/64 KiB,
서버 WS 프레임 1 MiB, HTTP 요청 256 KiB, HTML·JSON 8 MiB, 동시 연결 12개/WS 4개로
제한한다. 녹화 내려받기는 256 MiB까지 스트리밍한다. 세션 종료는 기존 blur 정지를
호출하고 off-main 400 ms zero 요청을 보낸 뒤 소켓을 닫는다. CORE deadman은 도달할
수 없는 로봇의 최종 정지를 맡는다. 실제 로봇 정지는 APK/JVM 시험과 별도 수용이다.

태블릿 선택 화면은 왼쪽 앱 정보·태블릿 상태와 오른쪽 검색·로봇 목록으로 나눈다.
검색은 하나의 주 동작이고 로봇 행은 이름·설명·연결 동작을 읽는 순서대로 배치한다.
네이티브 공통 `PilotViews`는 버튼·텍스트·로봇 행을 제공하고, 색은 공통 `tokens.css`의
어두운 테마에서 빌드 시 생성한다. 별도의 수동 색상 사본을 유지하지 않는다.
연결 중에는 목록 복귀·선택한 로봇·태블릿 메뉴를 작은 상단 줄에 모아 조종 화면의
공간을 확보한다. 태블릿 메뉴의 배터리·온도·발열 상태는 로봇 상태와 구분한다.
화면 끄기는 이 메뉴에 있다. Cam의 공통 화면 보호 규약을
재사용하고 심각한 발열 때는 조종을 닫은 뒤 화면을 끈다. 직접 화면 끄기를 누를 때만
Android의 force-lock 승인을 선택적으로 요청한다. 승인 없이는 밝기와 화면 깨움 유지를
내리고 OS 절전 시간을 따른다. 자동 보호는 권한 팝업을 띄우지 않는다. 발열 회복 전에는
재연결을 막는다. 원본 조종 UI의 주행 안전장치는 그대로 사용한다.

Windows 빌드(F: 소스, X: 출력·캐시):

```powershell
$env:JAVA_HOME = 'X:\java\jdk-21.0.8'
$env:GRADLE_USER_HOME = 'X:\DevCaches\gradle'
..\..\..\..\operations\ui\cam\gradlew.bat -p . --project-cache-dir X:\DevTemp\rosy-pilot-d432\project-cache :app:testDebugUnitTest :app:assembleDebug
```

APK: `X:\DevTemp\rosy-pilot-d432\build\app\outputs\apk\debug\app-debug.apk`.
package: `io.github.livsbittt.rosy.pilot`; activity: `.MainActivity`.
`-Prosy.buildRoot=<scratch>/build`와 Kotlin persistent 경로로 다른 scratch를 지정할 수 있다.
공통 Kotlin 규약은 Cam 원본을 빌드 출력의 generated source로 가져온다.
`PilotProfile`은 신뢰된 bootstrap의 내부 호환 어댑터/회귀 시험이며 앱에 가져오기 UI가 없다.

[OkHttp](https://square.github.io/okhttp/)는 Apache-2.0,
[NanoHTTPD/NanoWSD](https://github.com/NanoHttpd/nanohttpd)는 BSD-3-Clause다.
[Lucide](https://github.com/lucide-icons/lucide)의 action icon은 ISC/일부 Feather MIT이며
원문 라이선스를 APK의 `assets/licenses/lucide.txt`에 포함한다.
