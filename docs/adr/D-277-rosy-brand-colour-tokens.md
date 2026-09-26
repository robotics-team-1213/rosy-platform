## D-277 ROSY 이름 색은 장미색 토큰으로 식별한다

**Status:** Accepted (2026-09-26). D-254의 닫힌 토큰 전집에 브랜드 전용 칸을 추가한다. 이 결정은 웹 시각 언어만 다루며 로봇·모터 수용 판정은 포함하지 않는다.

잇는 결정: [D-72](D-72-.md) · [D-82](D-82-oklch.md) · [D-92](D-92-l2.md) · [D-129](D-129-l1-d-92-1.md) · [D-194](D-194-shared-browser-controls.md) · [D-254](D-254-design-philosophy-and-token-inventory.md) · [D-274](D-274-local-core-browser-review-and-device-acceptance.md).

**Context:**

ROSY라는 이름의 웹 제품이 기존 중립·청색·상태색만으로는 브랜드 정체성을 드러내지 않았다. 반면 콘솔에 보인 얇은 빨간 테두리는 `ui-button`의 `kind` 누락 진단(`ui.js`)이었다. 브랜드 색으로 오인될 수 있고 실제 동적 패널에서 여러 번 나타났다. 기존 D-82는 의미 색의 온도와 분리를 정했으며 D-254는 토큰 집합을 닫았다. 그러므로 브랜드 색은 경고나 임무 데이터와 섞이지 않는 별도 의미 칸이어야 한다.

**Decision:**

1. `src/hmi/web/tokens.css`만 색상 값의 출처로 둔다. 브랜드 집합은 `--brand-rose: #f697e7` (OKLCH L .80 / C .15 / H 333)과 `--brand-rose-wash: #221620` 두 토큰이다. 값은 OKLCH에서 생성하고 팔레트 게이트로 고정한다.
2. 장미색은 ROSY 워드마크와 현재 선택된 역할 메뉴에만 사용한다. 옅은 wash는 선택 메뉴의 배경으로 쓴다. 전체 바탕, 일반 명령 버튼, 작업 데이터에는 브랜드색을 퍼뜨리지 않는다.
3. 상태·동작의 기존 의미는 유지한다. 위험/E-stop은 기존 위험 채움, 경고는 앰버, 키보드 포커스와 경로 데이터는 청색이다. 루틴 주 명령은 중립색이다.
4. `ui-button`의 빨간 누락 표시를 브랜드 장식으로 숨기지 않는다. 리터럴 생성과 헬퍼 생성 모두 명시적 `kind`를 선언해야 한다. 이 결정으로 테스트 스캔 범위를 `.js` 생성 헬퍼까지 확장하고, 발견된 호출부에 실제 동작에 맞는 `primary`, `quiet`, `segment`, `toggle`, `irreversible`을 지정했다.
5. 브라우저 크롬의 `theme-color`는 브랜드색이 아닌 중립 `--ground`와 일치해야 한다.

**Alternatives:**

- ROSY가 분홍 이름이므로 모든 버튼과 패널을 분홍으로 칠한다 — 명령의 우선순위와 위험 신호를 뒤섞으므로 기각.
- 빨강을 브랜드색으로 재사용한다 — 기존 누락 진단 및 위험 의미와 혼동하므로 기각.
- 청색만 계속 사용한다 — 기존 포커스·데이터 계약에는 맞지만 ROSY 정체성을 나타내지 못하므로 기각.

**Consequences:**

브랜드색의 새 사용처는 이 범위를 넓히는 근거와 함께 변경해야 한다. 브랜드 토큰은 status/series 집합에 넣지 않는다. 누락된 버튼 kind는 화면에 스타일 흔적으로 나타나는 대신 소스 계약 테스트에서 잡힌다. 이는 장치, 실물 색 재현, 모터 동작의 증거를 대신하지 않는다.

**Validation:**

- `src/hmi/web/test/test_palette_gates.py`: OKLCH 색상대, ground 대비, 브랜드와 critical-red의 구분, 토큰 사용처, theme-color 정합성.
- `src/hmi/web/test/test_shared_controls.py`: 헬퍼로 생성한 버튼의 명시 kind 계약.
- 실제 CORE의 데스크톱·모바일 화면 확인: 선택 메뉴와 워드마크 색, 누락 진단 흔적 및 overflow 확인.
- `python tools/harness/rosy_harness.py lint`와 `git diff --check`.

---
