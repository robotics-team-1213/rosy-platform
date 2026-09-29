## D-335 브랜드 홈 링크를 ui-brand 공용 동작으로 넣는다

**Status:** Accepted (2026-09-29, 웹 공용 부품 동작 확장). 새 토큰·새 ui-* 부품·표면 문법을 추가하지 않고 기존 ui-brand의 행동을 확장한다.

### Context

`/console`·`/setup`·`/device`의 상단 바 브랜드는 일반 텍스트여서 ROSY 표시를 클릭해도 홈(`/dashboard`)으로 돌아갈 수 없었다. 첫 시행(feat/surface-home-link, 2026-09-29)은 `surface.html`에 앵커를 직접 적었는데, 이 링크는 페이지마다 다시 적히는 마크업이고 hover·포커스 상태를 표면 CSS에 복제하는 길도 열어 둔다. 임페커블 비평(`.impeccable/critique/2026-09-26T13-04-30Z__src-hmi-dashboard-surface-html.md`)의 일관성 계획은 "페이지 CSS는 배치와 밀도를 가진다"고 기록했고, `/dashboard`는 D-204 이행이 끝날 때까지 인증·브리지 역할을 유지한다. PRODUCT.md는 부품 동작 추가에 ADR 동반을 요구한다(사용자 확인 2026-09-29).

### Decision

1. **`ui-brand`는 `href` 속성을 받아 자식을 하나의 링크로 감싼다**(web_common `ui.js`). `aria-label`이 함께 있으면 링크 쪽으로 옮겨 접근성 이름이 한 곳에만 붙는다. `href`가 없으면 지금처럼 평문 브랜드다 — Fleet 콘솔과 경기 보드는 자기가 목적지인 화면이라 링크를 선언하지 않는다(D-275: 호스트가 다른 화면으로 링크를 걸지 않는다).
2. **링크의 상태는 components.css가 소유한다.** hover 밑줄과 포커스 링을 공용 스타일시트가 그리고, 표면 CSS는 ui-brand 링크 상태를 복제하지 않는다. hover·focus만이라 휴면 픽셀은 바뀌지 않는다.
3. **소비자는 선언만 한다.** `<ui-brand href="/dashboard" aria-label="Rosy OS 대시보드 홈">` — CORE 역할 화면(`surface.html`)이 첫 소비자다. `/dashboard` 자신의 레거시 `.brand`는 palette 계약(`test_palette_gates`)이 고정한 별도 표현으로 남고, D-204 브리지 정리 회차에서 공용 표현으로 모은다.
4. **이 ADR은 새 토큰·새 ui-* 부품·표면 문법을 만들지 않는다.** 공용 13종 가운데 하나의 행동 확장이며, 공용 계약(`test_shared_controls`)과 표면 계약(`test_surface_home_link`)이 같은 변경에서 고정한다.

### Alternatives

- **페이지마다 `<a>`를 직접 적는다(첫 시행):** 링크와 상태가 표면마다 복제되고 새 표면이 패턴을 알아야 하므로 거절한다.
- **공용 `ui-nav` 내비게이션 부품을 새로 만든다:** 소비자가 역할 화면 스위치 하나뿐이라 두 구현 요건을 채우지 못하므로 거절한다. 둘째 소비자가 나타나면 그때 별도 ADR을 낸다.
- **브랜드를 항상 링크로 바꾼다:** Fleet·경기 보드에서 자기 자신으로의 링크가 되므로 거절한다. href 선언이 소비자 선택을 남긴다.

### Transition / validation

1. SOURCE/LOCAL: `src/hmi/web/test`(공용 동작과 스타일 소유 고정), `src/hmi/dashboard/test/test_surface_home_link.py`(표면 선언 고정 + Chromium에서 공용 ui.js를 로드한 클릭 통과)을 실행한다. 역할 화면·다이얼로그·D-283 브라우저 회귀에서 pageerror 0과 overflow 0을 확인한다.
2. hover·포커스는 휴면 픽셀을 바꾸지 않으므로 D-329 기준선 캡처의 갱신 대상이 아니다.
3. DEVICE/FIELD: 브라우저 표면 판정과 무관하다.

**Consequences:** 홈으로 돌아가는 길이 페이지 마크업이 아니라 공용 부품 계약이 된다. 새 표면은 속성 하나로 같은 행동을 얻고, 링크 상태는 한 파일에서만 고친다. 비평 P1의 "`/dashboard` 목적지 명시"는 이 ADR로 닫히지 않는다 — 역할 화면으로의 가시 경로와 퇴역 기준은 별도 회차가 판다.

**References:** [D-194](D-194-shared-browser-controls.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [D-329](D-329-surface-registry-and-visual-baseline.md), D-204(브랜치 착수 대기 — `tools/harness/harness.yaml` adr_gaps).
