## D-1030 선택 표지는 새 색 없이 `--selection`(= `--series-secondary`) 별칭 하나와 굵은 줄·체크로 그린다

**Status:** Accepted (2026-11-14, 사용자가 위임한 S0 결정). 화면 채택과 실물 수용은 별도다.

잇는 결정: [콘셉트 2026-11-14](../plans/2026-11-14-rosy-ui-concept.md) 규칙 1~18 · [영역 규칙](../superpowers/plans/2026-11-14-rosy-ui-region-rules.md) S3 · D-202(위험은 채움) · D-220(정지 계약).

### Context

1. 선택 표지가 화면마다 달랐다: 행 전체 채움(`robot-row`), 색만 바뀐 칩, 채운 토글(`series-primary`), 표 행 `aria-selected` 바탕. 지도 표지와 3D 보기는 표지가 아예 없었다.
2. 포커스 링은 `--focus-ring`(= `--series-primary`)이다. 선택에 같은 색을 쓰면 포커스와 선택이 한 모양이 된다.
3. 새 색은 팔레트 게이트(`test_palette_gates.py`)와 색약 시험 예산을 다시 써야 한다.

### Decision

1. `tokens.css`의 파생 블록에 `--selection: var(--series-secondary);` 한 줄을 둔다. 새 색은 만들지 않는다.
2. 선택 표지 = `--selection` 색의 굵은 inline-start 줄(`--space-1`, 4px) + 색 없는 신호(체크 아이콘 또는 `선택됨` 글자). 행 전체를 칠하지 않는다. 지도 표지·3D 보기도 같은 색·같은 신호를 쓴다.
3. `--selection`은 `--focus-ring`과 다른 계열 단계다(포커스는 밝은 파랑, 선택은 진한 파랑).
4. `test_ui_token_contracts.py`가 두 테마의 작업 바탕(`ground`·`ground-deep`·`ground-raise`·`ground-soft`) 위 대비 3:1 이상을 지킨다. 선택 표지는 `ground-card` 이상 층에 놓지 않는다.

측정 대비(WCAG, `test_palette_gates.py`의 `contrast`):

| 테마 | ground | ground-deep | ground-raise | ground-soft | ground-card | ground-card-2 |
|---|---|---|---|---|---|---|
| dark `#2870bd` | 3.72 | 3.84 | 3.47 | 3.14 | 2.85 | 2.58 |
| light `#0d419d` | 8.84 | 9.06 | 8.17 | 7.60 | 7.12 | 6.62 |

dark의 `ground-card`(2.85)·`ground-card-2`(2.58)는 3:1 미만이라 그 위에는 표지를 두지 않는다(규칙). 포커스 링 `--series-primary`와 비교: dark 7.47, light 4.53(`ground`).

### Alternatives

- `--series-primary` 재사용: 포커스와 겹친다.
- 새 `--select-accent`: 팔레트 시험·색약 예산을 다시 열어야 한다.
- 행 전체 채움: 상태색과 섞이고 위험 채움(D-202)과 읽기가 겹친다.

### Consequences

- `--series-secondary`를 쓰는 지도 시작점·교습선과 같은 색이지만 모양(굵은 줄+체크)이 다르다. 색만 보는 사용자는 선택과 구분되지 않을 수 있으므로 표지는 늘 줄·체크·글자를 함께 쓴다.
- 이 파랑을 바꾸면 선택 대비 시험이 먼저 거른다.

### Validation / Transition

`shared/web/test/test_ui_token_contracts.py`(대비·별칭), `test_choice_controls.py`(채움 금지·정지 계약), `test_choice_*_browser.py`(표지가 같은 색인지). 화면 채택은 표면 슬라이스가 한다.

**References:** D-202, D-220, [영역 규칙 S3](../superpowers/plans/2026-11-14-rosy-ui-region-rules.md).

---
