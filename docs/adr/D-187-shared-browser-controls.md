## D-187 브라우저 조작 부품은 한 벌이다

**Status:** Accepted (2026-09-24). D-92의 "표면 사이에 CSS를 import 하지 않는다"는
조작 부품에 한해 이 결정이 대신한다. 레이아웃은 표면이 가진다.

**Context:** 색 토큰은 하나였지만 글자 크기와 버튼은 표면마다 숫자로 박혀 있었다.
콘솔 바닥이 9.3px였고, Fleet은 0.6rem부터 1.25rem까지를 직접 썼으며, 게임 보드와
control 진단 페이지는 11px와 36px를 한 화면에 두었다. 같은 이름이라도 구현이
달라 현장 화면의 글자가 안 보이거나 한 화면 안에서 비율이 세 배까지 벌어졌다.

**Decision:**

1. 빌드 없는 조작 부품은 `web_common`의 `components.css`와 `ui.js`다.
   `ui-button`, `ui-field`, `ui-tag`, `ui-text`. 로봇 로컬 화면은 이 파일을
   `/common/`으로 서빙하고 npm이나 번들러를 들이지 않는다(D-75).
2. 글자 계단은 `tokens.css` 한곳이다. 바닥 `--text-micro`는 0.75rem(12px),
   본문 `--text-body`는 1rem(16px), 점수처럼 키우는 숫자만 `--text-display`다.
   표면 시트의 `font-size`는 `var(--text-*)`만 허용한다.
3. 콘솔, Fleet, 게임 호스트 크롬, control 진단 페이지가 이 부품을 쓴다.
   배치(콘솔의 세 칸, Fleet의 예외 목록, 피치 캔버스)는 각 표면 시트에 남긴다.
4. 로봇 얼굴 LCD는 DOM 부품을 올리지 않는다. 색 숫자는 토큰과 같게 유지한다.

**Consequences:** D-92의 어휘 이름(라벨, 값, 버튼 셋, 필드, 태그)은 유지되고,
그 렌더링의 소스는 표면 시트가 아니라 `components.css`다. 진단 페이지의 지도
래스터 색(`--unk`, `--free`, `--wall`)은 서버 PNG와 짝을 이루므로 그대로다.

**Validation:** `src/core/web_common/test/test_shared_controls.py`. 버튼은
`kind`를 표시에 적고, 표면 시트는 그 부품의 면·글자·테두리를 다시 칠하지
않는다. 얼굴 LCD의 색 튜플은 토큰 hex와 같아야 한다. 경기 피치의 원시 색은
그 시트의 `:root` 한 블록 안에만 있다.

**References:** D-72, D-75, D-92, D-129, D-157, concept 16 §4.
