## D-398 증거 어휘의 단일 출처와 철학 범위 게이트 — 전 레이어 감사가 남긴 간극을 닫는다

**Status:** Accepted (2026-10-01, 사용자 승인 2026-09-29 "이번 개선 계획에서 ADR 확장 허용" 범위).

잇는 결정: [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) · [D-220](D-220-stillness-contract-zero-motion-budget.md) · [D-277](D-277-rosy-brand-colour-tokens.md) · [D-396](D-396-uiux-consistency-goal-system.md).

### Context

2026-10-01 전 레이어 감사(ADR·DESIGN.md·PRODUCT.md·tokens.css·surfaces.yaml·9개 표면·시험)에서
뼈대는 정합이었으나 네 곳에서 철학이 실제로 깨져 있었고, 세 곳에서 "규칙은 있는데 지키는 자가
없는" 간극이 확인됐다.

깨진 네 곳(P0):

1. 대시보드 `console-detail.css` 가 존재하지 않는 토큰(`--muted`·`--paper`·`--radius-1`)을
   참조 — D-359 이전 어휘의 잔재로 값이 풀리지 않는 깨진 참조.
2. 로봇 얼굴 LCD 의 장미색 사본이 `#e31b5d`(주석마저 `--rose` 로 잘못) — `--brand-rose
   #f697e7` 과 다르다. RGBA 4-튜플+소문자 이름이라 `test_token_parity` 의 정규식을
   통과했고, 소비자 시험이 오히려 드리프트 값을 고정했다.
3. Pilot 가 드라이브 스틱 **활성 상태**(인터랙션)에 `--brand-rose` 를 사용 — D-277 은
   이름 식별(워드마크·현재 선택 역할 메뉴)에만 허용한다.
4. Fleet 관측(sighting)이 클라이언트 임계로 닫힌 증거 네 상태 밖의 다섯째 상태 `stale` 을
   만들고, 대시보드/Pilot 카메라 문장이 영어 `STALE` 을 노출.

간극 세 곳: D-220 정지 계약에 정적 금지 게이트가 없어 대시보드 스켈레톤 펄스가 깨진
디밍 계약과 함께 들어왔고, D-277 장미색의 부정 방향 검사가 없었으며(P3 이 남용이
통과한 이유), 증거 한국어 어휘가 아홉 파일에서 각자 재정의되고 있었다(D-396 G1 의
정확한 승격 트리거).

### Decision

1. **증거 어휘의 단일 출처.** `core_ui_logic.js` 에 `EVIDENCE_LABEL`(최신·지연·연결 끊김·
   정보 없음)과 `evidenceAgeText()`(규격 뒤처리 ` · N초 전`, 나이는 서버 값만 받아 **판단은
   하지 않는다**)를 둔다. 대시보드(overview·pose-evidence·operations·triage·telemetry·vision)와
   Fleet(roster)이 이 표에서 말을 만든다. 주어를 앞에 붙인 문장(`위치 지연`, `릴레이 끊김`)은
   표를 참조해 조립한다. 예외: `site-layer.js` 는 노드 순수 시험이 돌아야 해서 `/common`
   import 를 못 한다 — 같은 문구를 로컬에 두고 표를 참조한다(주석으로 명시). Pilot 의
   "대기" 도 `MODE_LABEL.IDLE` 재사용으로 바꾸고 `/common/core_ui_logic.js` 를 PWA 셸에 추가했다.
2. **컴포넌트 수는 실측으로 말한다.** ui.js 커스텀 엘리먼트는 16개(+클래스 부품)다.
   D-254·D-396 이 세던 "13종"은 그 시점의 역사적 수치다 — 이후 문서는 실측 수를 쓴다.
3. **범위 게이트 네 종**(`test_design_scope_gates.py`, 제품 웹 표면에 적용, PARKED·개발
   도구는 사유와 함께 예외 목록): ① D-220 정지 — `transition:`·`animation:`·`@keyframes`
   금지, ② D-277 장미색 부정 범위 — `--brand-rose*` 참조는 워드마크·위치 표식 파일
   목록 안에서만, ③ 역할 우선 — 역할 토큰이 이미 있는 두 바탕색(`--ground-soft`→
   `--surface-flat`, `--ground-card`→`--surface-raised`)은 역할 이름으로, ④ 온뷰포트 높이 —
   `100vh` 금지(비례값 `45vh` 등은 프레임이 아니므로 허용).
4. **중복 제거.** 스타일가이드 시트가 공용 부품 얼굴을 재구현하던 죽은 `.demo-*` 규칙을
   지웠다(견본은 실제 `ui-*` 요소가 그린다). Fleet 빈 로그 `.log-empty` 를 공용 `ui-empty` 로,
   roster 의 죽은 `s{index}` 클래스를 제거했다. 대시보드 스켈레톤 펄스와 액션 메시지
   페이드, Pilot 의 두 전이를 걷어내 D-220 을 회복했다 — 상태 변화는 점프 컷이고 기다림은
   조용한 뮤트 대시다.

### Alternatives

- **위반 네 곳을 파일별 예외로 등록:** 감사가 아니라 빚 장부 만들기. 거부.
- **문서만 고치고 코드는 방치:** 권위 사슬(ADR > 코드)이 반대 방향으로만 읽힌다. 거부.
- **게이트 없이 관례로 유지:** D-396 Context 가 이미 "관례는 한계"라고 결론 내렸다. 거부.
- **펄스·페이드를 D-220 수정 ADR으로 예산화:** 기다림 표시의 실사용 가치는 인정하나
  운용 화면의 "차분함"(D-280 P4)이 계약 우선이다. 필요해지면 그때 예산을 명시한
  수정 ADR 을 쓴다.

### Consequences

- LCD 부팅 카드의 장미색 점이 `#f697e7` 로 바뀐다 — 실물 LCD 사진 증거가 있다면 다시
  찍어야 한다(PRODUCT.md "없는 것" 목록은 그대로).
- 대시보드 값 자리의 기다림이 숨쉬지 않고 조용한 대시가 된다. 운용자 관찰(G3)에서
  불만이 오면 그때 예산화를 다시 논의한다.
- Pilot 조종 스틱 활성·프레임 교차가 즉시 바뀐다(전이 제거). 조종 지연 예산(D-367)에는
  영향 없다(입력→명령 경로만이 그 예산을 쓴다).
- `site-layer.js` 예외는 노드 시험이 사라지거나 `/common` import 가 가능해지면 회수한다.
- 역할 우선 게이트의 쌍 목록에 항을 더하는 것은 tokens.css 에 역할을 더하는 ADR 과 같은
  커밋에서만 한다.

### Validation

- `test_token_parity.py` — RGBA 4-튜플·소문자 이름 사본도 비교한다(변이 증명 포함).
- `test_enum_labels.py` — 어휘 표가 닫힌 네 상태와 키가 같고 나이 뒤처리가 규격임.
- `test_design_scope_gates.py` — 네 게이트 + 실제 파일 위반 심기(transition/장미색/
  ground-soft/100vh 동시)로 전부 붉어지는 것과 회복을 확인(2026-10-01).
- 갱신된 pin: `test_info_screen.py`(장미색), `test_dashboard_package.py`(정지 계약),
  `site-layer.test.mjs`(delayed·`초 전`), `test_fleet_console_browser.py`(ui-empty),
  `test_console_camera_pairing.py`(allSettled 안의 갱신 호출).
