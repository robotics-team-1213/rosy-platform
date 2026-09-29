## D-345 D-280 디자인 철학은 사람이 보는 모든 표면에 같은 방식으로 적용한다 — 웹이 아닌 표면도 레지스트리·토큰 사본 검사·이름 규칙을 받는다

**Status:** Accepted (2026-09-29, 적용 범위·색 원본·이름·알림 규칙). D-280의 다섯 원칙을 바꾸지 않는다. 새 토큰, 새 부품, 새 문법, 라이트 팔레트를 만들지 않는다.

### Context

D-280은 제품 전체의 디자인 판단 기준이다(아는 만큼 말한다, 중요한 것이 먼저 보인다, 복잡함을 다룰 수 있게, 따뜻함은 작은 곳에, 정교한 품질). 그런데 이 기준을 지키는 장치는 웹 표면에만 걸려 있다.
- 표면 레지스트리 `surfaces.yaml`(D-329)
- 토큰과 공용 컨트롤 계약 시험(D-292, D-300)
- 무번들러 규칙(D-75)

웹이 아닌 표면은 두 가지다.
- **천장 카메라 앱**(`src/site/overhead/android`, D-261): Compose의 기본 `darkColorScheme()`·`lightColorScheme()`를 그대로 쓴다. 그래서 운용 화면과 다른 보라 계열 강조색이 나온다. D-277(장미색은 이름 식별에만)과 D-292(`tokens.css`가 유일한 색 원본)를 어긴다.
- **로봇 LCD 얼굴과 정보 화면**(`src/hmi/face`): 토큰 값을 주석과 함께 옮겨 적었다. 하지만 D-73(기능 시험은 자기 모듈 코드만 단언) 때문에 사본이 원본과 같은지 확인하는 시험이 없다.

D-340은 웹 표면을 감싸는 설치형 셸을 예고했다. D-323의 Pilot PWA는 홈 화면 이름을 `Pilot`으로 두어 Rosy 제품임이 드러나지 않는다.

### Decision

1. **범위: 사람이 보는 모든 표면이 레지스트리에 있다.**
   - `surfaces.yaml` 항목은 `medium`을 가진다: `web`, `native`(휴대폰·태블릿 앱), `lcd`(로봇 화면).
   - 계약은 매체마다 다르다. `web`은 `shared_controls`, `typography_focus`, `dialog`를 받는다. `native`와 `lcd`는 `token_parity`를 받는다.
   - 설치형 셸(D-340)은 새 표면이 아니다. 감싸는 웹 표면의 항목을 따른다.
2. **색 원본은 `tokens.css` 하나다.** CSS를 못 읽는 표면은 값을 옮겨 적는다.
   - 사본의 줄마다 토큰 이름을 단다. 형식은 Python `(r, g, b)  # --이름 #hex`, Kotlin `Color(0xFFRRGGBB) // --이름`이다. `surfaces.yaml`의 `token_copy`가 그 파일을 가리킨다.
   - 사본이 원본과 같은지는 원본의 주인인 `web_common`이 `test_token_parity.py`로 확인한다. 소비자 시험은 D-73대로 자기 코드만 본다.
   - 토큰이 아닌 색(예: QR 코드의 순흑·순백)은 같은 줄에 `token-exempt: <이유>`를 적는다. 이유 없는 색은 시험이 막는다.
3. **네이티브 화면은 플랫폼 기본 테마를 쓰지 않는다.**
   - Material 기본 색표 대신 토큰 사본으로 색 역할을 채운다. `tokens.css`에 라이트 팔레트가 생기기 전에는 시스템 밝기 설정과 무관하게 같은 팔레트를 쓴다.
   - 주요 버튼과 강조는 웹 운용 화면(`components.css`)과 같은 역할의 토큰을 쓴다.
   - 장미색은 ROSY 이름에만 쓴다(D-277).
4. **이름과 문구.**
   - **앱 이름**(런처·홈 화면·PWA `name`)은 `Rosy <이름>`이다. `Rosy`를 떼지 않는다. 홈 화면에 잘리는 짧은 이름(`short_name`)도 `Rosy`로 시작한다. 예: `Rosy 천장 카메라`, `Rosy Pilot`. D-323의 고유 제품명 `Pilot`은 유지하되 `Rosy Pilot`으로 쓴다.
   - **브라우저 탭 제목**은 D-339 §4의 `Rosy <범위> — <화면 이름>`이다.
   - **운용 문구**는 한국어 평문이다. 상태 문구는 출처와 신선도를 드러낸다(D-280 원칙 1). 예: `연결 끊김 — 다시 연결 중`.
5. **알림은 사람이 행동해야 할 때만 소리를 낸다**(D-280 원칙 2).
   - OS가 요구하는 상시 알림(Android foreground service)은 낮은 중요도 채널에 조용히 둔다.
   - 사람이 조치해야 하는 상태만 별도 채널로 알린다. 예: 인증 실패, 권한 거부, 저장 공간 부족.
6. **실행 파일 이름**은 ROS 패키지 이름을 따르고 `rosy_` 접두를 쓰지 않는다(D-147). 바꾸는 조건은 D-339의 2026-09-29 보충을 따른다.

### Alternatives

- **플랫폼마다 따로 디자인 시스템을 둔다**(Android는 Material 기본). 거부한다. 같은 제품이 표면마다 다른 성격을 보이면 D-280 원칙 5(정교한 품질의 일관성)가 깨진다.
- **Kotlin·Python 시험이 `tokens.css`를 직접 읽는다.** 거부한다. D-73을 어기고, 원본이 바뀔 때 어느 소비자가 깨졌는지를 원본 쪽에서 한 번에 볼 수 없다.
- **토큰에서 Kotlin·Python 코드를 생성한다.** 지금은 거부한다. 생성 단계와 산출물 관리가 생기는데, 사본이 두 파일뿐이다. 사본이 늘어 손으로 맞추기 어려워지면 다시 본다.

### Consequences

- LCD는 이번에 `robot-face`로 등록되고 `token_parity`를 받는다.
- 천장 카메라 앱은 토큰 사본 테마(`ui/RosyTheme.kt`)로 바뀐 뒤 `overhead-camera-app`으로 등록된다.
- Pilot 브랜치(D-323)는 합칠 때 PWA `name`·`short_name`과 탭 제목을 §4에 맞춘다.
- `tokens.css`의 값을 바꾸면 `test_token_parity.py`가 사본을 가진 표면을 알려준다.

### Validation

- `src/hmi/web_common/test/test_token_parity.py`: 사본 일치, 이유 없는 색 차단, 변이 확인.
- `test_surface_registry.py`: `medium`과 매체별 계약.
- Android `testDebugUnitTest`·`assembleDebug`.

이는 SOURCE/LOCAL 증거다. 실제 폰 화면, LCD 실물, 현장 수용은 별도 회차다.

### References

[D-73](D-73-.md), [D-75](D-75-d-7-react.md), [D-147](D-147-src-6.md), [D-261](D-261-overhead-camera-app-skeleton.md), [D-277](D-277-rosy-brand-colour-tokens.md), [D-280](D-280-calm-intelligence-product-design-philosophy.md), [D-292](D-292-design-tokens-and-component-layout-contract.md), [D-323](D-323-rosy-pilot-teleop-app.md), [D-329](D-329-surface-registry-and-visual-baseline.md), [D-339](D-339-surface-and-folder-role-names.md), [D-340](D-340-app-shell-wraps-web-surfaces.md).
