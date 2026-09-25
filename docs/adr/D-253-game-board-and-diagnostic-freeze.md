## D-253 게임·진단 마무리 — 관전 모드 없음과 진단 동결을 못박는다

**Status:** Accepted (2026-09-26). 관전 없음 + 진단 동결로 착지. 롤아웃 7분할이 닫혔다.

잇는 결정: [D-101](로봇 축구 게임 호스트) · [D-150](D-150-web-node-control-navigation-map.md) ·
[D-153](D-153-ui-ux.md)(진단 PARKED) · [D-201](D-201-fixed-grammar-surfaces-fit-contract.md)(halt 가시) ·
[D-218](D-218-web-dialogs-name-the-action.md)(게임 무확인) · D-92 제5항.

**Context (실측):**

경기 보드(`src/site/games/games/web/`)는 인증 없이 점수·피치·정지를 낸다.
`test_games_board_browser.py`가 halt 행 가시(1280×800)와 Space→`/stop`을
고정한다. 진단(`src/runtime/sensing/web/dashboard.html`)은 자체 `:root`+`T`+PNG
파이프라인을 들고, 토큰 합치는 `test_shared_controls.py`가 이미 녹색으로
지킨다(51 passed). 계획 §3-7이 말한 관전 readonly와 ScoreBoard 추출을 실측
대조했다.

**Decision (초안):**

1. **관전 readonly를 만들지 않는다.** 계획을 뒤집는다. 이유 셋: (a) halt를
   숨기면 D-201 게이트와 모순된다. (b) 노트북 호스트(D-101)는 물리적 근접이
   역할이다 — 그 자리에 있는 사람은 심판이다. (c) 11cm 탁상 로봇은 멈추는
   손이 많을수록 안전하다. 관전자는 브라우저 읽기(손대지 않음)로 충분하고,
   그 이상은 새 표면이 필요하다.
2. **ScoreBoard를 뽑지 않는다.** 점수 2칸은 단일 표면의 장식 + fetch 바인딩 한
   줄이다. D-130.2 미달.
3. **진단은 동결을 선언한다.** PARKED(D-153·D-201) 재확인. `:root`↔`T`↔PNG
   수동 동기화는 sensing 소유로 남기고, 운영 표면으로 이식하지 않는다(D-150
   경계 유지).
4. **파일럿 커밋은 이 ADR + 로그뿐이다.**

**Alternatives:** `?view` 관전 모드안 — halt 게이트 carve-out + 새 상태로
파일럿 초과. 진단 토큰 강제 일원화안 — PNG 파이프라인과 묶여 있어 토큰 파일
하나로 안 끝난다. 현상 유지 무기록안 — 계획과 실측의 어긋남이 다음 세션에
그대로 넘어간다.

**Consequences (Accepted되면):** 롤아웃 7분할이 닫힌다. 게임·진단의 다음 변경은
이것을 뒤집는 ADR부터 시작한다.

**Validation / Transition:** (1) 게임 브라우저 시험 + `hmi/web` 51 passed
(변경 없음 확인), (2) 이 문서가 계획 §3-7의 뒤집기를 명시. `ROSY ADR Log.md`에
`D-253 | 게임·진단 마무리 — 관전 없음·진단 동결 | Proposed` 1행 추가가 이
초안의 착지다.

**References:** D-92, D-101, D-130, D-150, D-153, D-201, D-218, D-233.

---
