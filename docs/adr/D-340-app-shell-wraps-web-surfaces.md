## D-340 설치형 앱은 웹 표면을 감싸는 셸로 만든다 — PWA가 먼저, Capacitor 셸은 저장소 루트 `apps/`에 둔다

**Status:** Proposed (2026-09-29). 방향과 소스 위치만 정한다. `apps/` 폴더, npm 프로젝트, 스토어 배포, 서명 키를 지금 만들거나 승인하지 않는다. D-75(로봇 런타임과 표면의 무번들러)와 D-323(Pilot PWA)을 바꾸지 않는다.

### Context

브라우저로 여는 표면은 다섯 곳이다. 로봇 화면(`src/hmi/dashboard`, CORE same-origin), 사이트 관제(`src/site/fleet/fleet/server/web`), 경기 보드(`src/site/games/games/web`), PARKED 제어 진단(`src/runtime/sensing/web`), 공용 자산(`src/hmi/web`, 패키지 `web_common`)이다. 모두 손으로 쓴 정적 HTML과 ES 모듈이고 빌드 단계가 없다(D-75). 휴대폰용 원격 조종은 D-323이 CORE가 same-origin으로 서빙하는 PWA(`src/hmi/pilot`)로 정했다. 네이티브 앱은 천장 카메라용 Kotlin 앱 하나다(`src/site/overhead/android`, D-261). 이 앱은 CameraX가 필요하고 수신기와 wire 형식(`protocol/vectors.json`)을 공유한다.

앞으로 운용자 앱을 스토어로 배포하거나, PWA가 못 하는 기기 기능(백그라운드 유지, 푸시, 로컬 네트워크 탐색, 기기 등록용 BLE·Wi-Fi)을 쓰고 싶어질 수 있다. 그때 화면을 새 프레임워크로 다시 쓰면 표면이 둘로 갈라진다. Capacitor는 기존 정적 웹 자산을 그대로 네이티브 WebView에 담는 셸이다. 다만 셸 프로젝트 자체는 npm과 Node 도구를 쓴다.

### Decision

1. **화면 코드는 하나다.** 설치형 앱이 생겨도 화면은 지금처럼 `src/hmi/<surface>`의 무번들러 정적 ES 모듈로 남는다. 셸은 그 파일을 복사해 담을 뿐 화면을 다시 구현하지 않는다. React·Vue·Flutter 등으로 같은 화면을 다시 쓰지 않는다(D-75, D-329).
2. **순서는 PWA가 먼저다.** Pilot은 D-323대로 PWA로 먼저 낸다. Capacitor 셸은 아래 조건 중 하나가 실제 요구로 기록될 때만 만든다.
   - 스토어 배포나 MDM 설치가 필요하다.
   - PWA에서 막히는 기기 기능이 필요하다. 예: 백그라운드 연결 유지, 푸시 알림, mDNS 로봇 탐색, BLE·Wi-Fi 기기 등록.
   - iOS Safari의 PWA 제약(홈 화면 추가, 저장소 정리 등)이 운용을 막는다는 현장 증거가 있다.
3. **셸의 자리는 저장소 루트 `apps/<앱 이름>/`이다.** `src/` 밖이라 colcon이 보지 않고, 로봇 이미지와 `deploy/` closure에 들어가지 않는다. npm의 `package.json`·lock 파일·`node_modules`는 이 폴더 안에만 둔다. 로봇 런타임과 `src/` 표면에는 계속 npm·번들러·Node가 없다. 셸의 `webDir`에는 복사 스크립트가 `src/hmi/<surface>`와 `web_common` 공유 자산을 옮겨 담는다. 번들러를 쓰지 않는다.
4. **네이티브 앱의 자리 규칙.** 앱이 한 사이트 서비스의 전용 클라이언트이고 그 서비스와 wire 형식을 공유하면 서비스 옆에 둔다. 예: `src/site/overhead/android`(`COLCON_IGNORE`). 여러 표면을 감싸거나 운용자 전반을 위한 앱이면 `apps/`에 둔다.
5. **셸은 origin을 바꾼다.** 이 점을 먼저 풀고 셸을 만든다. Capacitor 앱의 화면은 `https://localhost`(Android)나 `capacitor://localhost`(iOS)에서 뜬다. 그래서 D-275의 CORE same-origin 전제가 깨진다. 셸을 만드는 ADR은 다음을 정해야 한다.
   - 기준 주소: 로봇 주소를 설정으로 받는다.
   - CORE 쪽 CORS 허용 origin: 셸 origin만 허용하고 `*`는 금지한다.
   - CSP `connect-src`
   - 토큰 보관: 네이티브 보안 저장소
   - 평문 `ws://` 허용 범위: Android network security config, iOS ATS
   
   로봇 페이지를 원격 URL로 띄우는 `server.url` 방식은 개발용으로만 쓴다.
6. **공유 JS는 web_common에 둔다.** 인증 fetch 래퍼, WS 재연결·백오프, 폴링 루프가 지금 dashboard `client.js`·`app.js`와 Fleet `console.js`에 따로 있다. 이것을 기준 주소를 인자로 받는 ES 모듈 하나로 `web_common`에 모은다. 대상은 두 번째 실제 소비자인 Pilot이 착수하는 회차다(D-306: 두 화면 이상이 쓸 때 추출). 셸은 이 모듈의 기준 주소만 바꿔서 쓴다.

### Alternatives

- **Capacitor 셸을 지금 만든다.** 거부한다. Pilot 구현이 HOLD라 감쌀 화면이 없다. 빈 골격을 미리 만들지 않는다는 원칙(D-231, D-317)과도 맞지 않는다.
- **React Native나 Flutter로 앱을 따로 만든다.** 거부한다. 화면이 웹과 앱 두 벌이 되고, D-75·D-329의 단일 화면 어휘가 깨진다. D-261은 카메라 앱만 예외로 두었다. CameraX가 필요하고 화면이 거의 없기 때문이다.
- **셸을 `src/hmi/<surface>` 안에 둔다.** 거부한다. npm 프로젝트가 colcon 작업 공간 안에 들어오고, `test_dashboard_no_bundler.py` 류의 무번들러 검사 범위와 섞인다.
- **로봇 런타임까지 npm을 허용한다.** 거부한다. D-75가 거부한 Pi 런타임 표면 증가가 그대로 돌아온다.

### Consequences

- 표면 코드는 하나로 유지되고, 설치형 앱은 포장 문제로 한정된다.
- 셸 ADR이 생기면 CORE는 same-origin이 아닌 클라이언트를 처음 받는다. 그래서 CORS·CSP·토큰 정책을 그 ADR에서 함께 바꾼다.
- 무번들러 검사 범위를 `src/`로 명시한다. `apps/`에는 CI 작업을 따로 둔다.

### Validation

지금 검증할 코드는 없다. 셸 ADR을 Accepted로 올릴 때 확인할 것:
- `apps/` 밖에 `package.json`이 없음을 검사한다.
- 셸 빌드가 `src/hmi/<surface>` 파일의 해시를 그대로 담는지 확인한다.
- CORE CORS 허용 목록 시험을 둔다.
- 실제 폰에서 WS 연결과 끊김·재연결을 확인한다.

### References

[D-75](D-75-d-7-react.md), [D-231](D-231-layered-source-roots-keep-package-names.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-306](D-306-surface-ownership-and-uiux-closure.md), [D-317](D-317-control-and-shared-contract-source-boundaries.md), [D-323](D-323-rosy-pilot-teleop-app.md), [D-329](D-329-surface-registry-and-visual-baseline.md), [D-339](D-339-surface-and-folder-role-names.md).
