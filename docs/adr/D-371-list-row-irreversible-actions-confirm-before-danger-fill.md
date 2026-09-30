## D-371 목록 행의 되돌릴 수 없는 행동은 조용한 버튼으로 시작하고, 위험 채움은 확인 단계에만 둔다

**Status:** Accepted (2026-09-30, 사용자 확인). D-292 §2·§7과 D-359 §5의 "되돌릴 수 없는 행동 = 위험색 채움"을 **목록 행에 한해** 좁힌다. 비상정지, 단일 대상 화면의 되돌릴 수 없는 명령, 확인 대화상자의 실행 버튼은 그대로 위험 채움이다.

잇는 결정: [D-202](D-202-danger-is-a-fill-alarm-text-contrast-contract.md) · [D-218](D-218-web-dialogs-name-the-action.md) · [D-280](D-280-calm-intelligence-product-design-philosophy.md) · [D-292](D-292-design-tokens-and-component-layout-contract.md) · [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md).

### Context

2026-09-30 D-359 최종 캡처 비평에서 `/device` 토큰 목록이 행마다 위험 채움 `삭제` 버튼을 그려, 한 화면에 빨간 채움이 비상정지를 포함해 네 개 나타났다(`system/security.js`, `components.css`의 `--button-irreversible-bg`). D-280 원칙 2(중요한 것이 먼저 보인다)는 위험 행동을 일상 명령과 다른 위계로 두라고 하지만, 같은 색이 반복되면 비상정지의 위계가 흐려지고 빨강이 경보 예산(D-82)을 소모한다.

### Decision

1. **목록 행**(같은 종류 항목이 반복되는 표·목록의 행 단위 조작)의 되돌릴 수 없는 행동은 조용한 버튼 `삭제…`로 시작한다. 말줄임표는 다음 단계가 있다는 표시다.
2. 누르면 D-218 확인 대화상자가 열린다. 대화상자는 대상 이름을 말하고, 실행 버튼만 `kind="irreversible"`(위험 채움, 58px 대상)이다.
3. 한 화면(첫 화면 기준)에서 위험 채움은 비상정지 외에 **하나를 넘지 않는다**. 목록은 이 예산을 쓰지 않는다.
4. 비상정지와 단일 대상의 되돌릴 수 없는 명령은 변하지 않는다.

### Alternatives

- **현행 유지(모든 되돌릴 수 없는 버튼 위험 채움):** 목록이 길수록 빨강이 늘어 비상정지와 경쟁한다. 거부.
- **행 버튼을 위험색 글자로:** D-202는 위험을 글자가 아니라 채움으로 말한다. 거부.
- **삭제를 숨긴 메뉴로:** 발견성이 떨어지고 터치에서 한 단계가 더 는다. 거부.

### Consequences

목록의 삭제는 두 단계가 된다. 비상정지가 화면에서 유일한 상시 빨간 면으로 남는다. DESIGN.md의 버튼 규칙에 이 예외를 적는다.

### Validation

- 계약 시험: 목록 행 안의 `ui-button`은 `kind="irreversible"`가 아니다. 확인 대화상자의 실행 버튼만 irreversible이다.
- 브라우저: 토큰 목록 `삭제…` → 대화상자에 대상 이름 → 실행 버튼 위험 채움. 첫 화면의 위험 채움 수(비상정지 제외) ≤ 1.
- SOURCE/LOCAL 증거다. 사람 G3 평가는 별도다.

### Refinement (2026-09-30)

- **확인 대화상자는 비모달로 열고 정지 조작은 살아 있다** (2026-09-30 US-010 측정: showModal이 비상정지를 inert로 만듦). `confirmIrreversible`은 `dialog.show()`로 열고, 대화상자와 `[data-always-live]`(각 표면 마크업이 정지 컨트롤에 단다) 밖만 `inert`로 만든다. `--scrim` 막은 정지 자리에 구멍을 내고, Tab 순환은 취소 → 실행 → 정지다. 정지를 누르면 정지가 실행되고 대화상자는 취소로 닫힌다(삭제 없음). 지키는 시험: `test_stop_always_live.py`(호스트, 변이 증명), `test_list_row_confirm_browser.py`·`test_dashboard_browser.py -k waypoint_delete`(브라우저).
- **D-218 §1과의 관계:** D-218 §1은 확인을 네이티브 `window.confirm`으로 하고 커스텀 확인 대화상자를 만들지 않는다고 정했다. 목록 행의 되돌릴 수 없는 확인은 공유 `confirmIrreversible` 대화상자를 쓴다 — `window.confirm`은 위험 채움 실행 버튼과 행동 이름(`토큰 삭제`)을 보일 수 없기 때문이다. 이 좁힘은 D-371 경우(목록 행 삭제)에만 적용되고, 나머지 확인은 D-218 §1대로 `window.confirm`이다.
