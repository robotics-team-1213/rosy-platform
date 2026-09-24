## D-195 치수와 진단 팔레트도 닫힌 집합이다

**Status:** Accepted (2026-09-24). concept 16의 Law 1·Law 2를 D-194 다음에
치수까지 시험으로 내린다.

**Context:** 색·글자·버튼 종류는 한 파일로 잠겼다. 간격과 모서리는 토큰이
있었는데 콘솔 시트만 그 토큰을 썼다. Fleet·경기 보드·진단 페이지는
`0.4rem`, `9px`, `10px`를 다시 골랐다. 진단 페이지는 `--muted`를 토큰과
다른 값으로 다시 선언해 공유 부품의 흐린 색까지 바꿨고, 위험색 `#d03b3b`는
토큰의 `#c40921`과 다른 빨강이었다. 같은 법인데 숫자가 둘이었다.

**Decision:**

1. 브라우저 표면의 `padding`, `margin`, `gap`, `border-radius`는
   `--space-*`와 `--radius-*`만 쓴다. `1px`은 실선이라 계단이 아니다.
   너비·격자·위치는 표면의 문법이라 이 계단의 대상이 아니다.
2. 진단 페이지의 바탕·잉크·상태·경로색은 `tokens.css`와 같은 hex다.
   지도 래스터(`--unk`, `--free`, `--wall`)와 아직 토큰이 없는 핀·대체
   경로색만 그 페이지의 숫자로 남는다.
3. 표면이 `tokens.css`에 있는 이름을 다른 값으로 다시 선언하지 않는다.

**Validation:** `src/core/web_common/test/test_shared_controls.py`.

**References:** concept 16 §3·§4, D-82, D-194.
