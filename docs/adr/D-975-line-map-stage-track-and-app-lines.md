## D-975 단계 스트립은 노선 모양이고 앱마다 노선 색 하나를 갖는다 — 흐름은 노선, 단계는 번호 역

**Status:** Accepted (2026-11-04, 사용자 결정: 노선도 방향 선택, "어둡게 유지 + 노선만", "앱 노선 색 추가", 적용 순서 P1→P5). D-82 의미 집합에 `app-line` 집합을 더한다.

잇는 결정: [D-82](D-82-oklch.md)(색 의미 집합) · [D-461](D-461-task-first-workspace-compositions-and-learning-ux.md)(작업 우선 조합) · [D-220](D-220-stillness-contract-zero-motion-budget.md)(정지) · [D-277](D-277-rosy-brand-colour-tokens.md)(장미색 범위) · [D-926](D-926-ui-reading-order-depth-and-wording.md)(읽는 순서·깊이) · [D-766](D-766-size-limits-split-on-exceed.md)(components.css 동결)

### Context

- 공용 단계 스트립 `ui-stage-track`(`shared/web/stage-strip.css`)은 견본에만 있고 생산 화면이 쓰지 않는다. Learning `pipeline-stages`, Fleet 설치 `install-step`, OMX `learning-step-menu`가 같은 개념을 따로 구현했다.
- 화면들이 접힘으로 단계를 숨긴다(2026-11-04 실측: Fleet 관제 `details` 14, 현장 지도 11, Learning 학습센터 7). D-926은 접힘을 한 겹으로 제한한다.
- 사용자는 impeccable 방향 비교에서 「지하철 노선도와 역 안내」를 골랐다. 시안은 Design 캔버스 「ROSY 노선도 재디자인」(비공개)에 있다. 기본 테마는 어둡게로 유지한다.

### Decision

1. **단계 스트립은 노선이다.** 단계는 번호 역(원 표식, 순번 `--mono`)이고 역 사이를 굵은 선(`--size-stage-line`)이 잇는다. 단계는 같은 폭을 나눠 쓰고, 30rem 미만에서는 세로 노선으로 접는다. class-only이고 JS·움직임이 없다(D-220).
2. **상태 어휘는 그대로 넷이다.** `done`·`now`·`blocked`·`todo`(`ui-tag`와 같다). `now`는 잉크 채움과 `aria-current="step"`이 나르고, 막힘은 `--status-warn` 글자·테가 나른다.
3. **앱 노선 색 세 개를 팔레트에 둔다.** `--app-line-learning`(청록 H 185/195) · `--app-line-fleet`(남보라 H 285) · `--app-line-robot`(보라 H 315), 두 테마 모두. 화면은 `data-line`으로 고르고, 없으면 중립 선이다.
4. **노선 색은 정체성이지 상태가 아니다.** 지난 역의 테·지난 구간·지금 역의 바깥 고리에만 칠한다. 남은 구간은 중립이다. 팔레트는 `tokens.css`에서 나고 `stage-strip.css`만 소비한다.
5. **노선 색의 게이트**(`test_palette_gates.py`, 테마마다): 색상각 150 이상 320 미만(차가운 띠, 장미색 대역 밖), 채도 0.08 이상(밝은 청록의 sRGB 한계), 바탕·올린 면 대비 3:1 이상, status·series·brand와 OKLab 거리 0.08 이상.
6. **화면 적용은 단계별이다.** 공용 부품(이 결정) → Learning → Fleet → Robot·Pilot·Games → 나머지. 각 화면은 자체 단계 UI를 이 부품으로 바꾸고, 노선의 역을 하위 화면 단위로 써서 접힘을 줄인다. 계획: 작업 공간 `docs/superpowers/plans/2026-11-04-rosy-line-map-uiux.md`.

### Consequences

- 표식 지름이 22px에서 28px로 커진다. 단계 스트립을 쓰는 곳은 견본뿐이라 생산 화면 영향은 없다.
- 기존 시안의 '막힌 역 = 위험 채움'은 채택하지 않는다. 막힘은 주의이고, 위험은 기존 status 계약이 나른다.
- 밝게를 기본으로 바꾸는 일, 비웹 표면(LCD·Android)의 노선 사본은 범위 밖이다.
- 검증 범위: G1 시험(팔레트·내용 어휘·범위 게이트)만 이 결정에서 본다. 화면별 G2 캡처·G3 검토는 각 적용 단계에서 기록한다.
