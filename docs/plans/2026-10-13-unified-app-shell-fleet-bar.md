# 통합 셸 · Fleet 앱 바와 레일 이름 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rosy Fleet 네 문서(`/console`, `/console/install`, `/console/site-map`, `/console/cell`)의 머리를 D-741 3항의 앱 바로 바꾸고, 탐색 레일의 아이콘 아래에 짧은 이름을 적는다. 이 계획은 [통합 셸 계획](2026-10-13-unified-app-shell.md)의 조각 4와 5다. 둘이 `test_fleet_header_browser.py`의 같은 반복문을 고치므로 한 계획으로 묶었다.

**Architecture:** 머리는 지금처럼 네 문서의 정적 마크업이고 글자 그대로 같다. 비상 정지와 알림 단추는 스크립트가 만들지 않는다. 한 줄 앱 바의 자리는 왼쪽부터 맥락(R 심볼, `Fleet`, 현장 이름), 연결(연결 글과 시각), 알림과 나(알림 단추, 로그인 링크, 역할 이름이 붙은 계정 단추), 정지다. 계정 단추는 지금의 `#topbar-more`이고, 그 아래 `#topbar-extra`에 계정·화면 표시·토큰 접속이 들어간다. 접힘은 `@media`가 아니라 셸 칸(`ui-shell.fleet-shell`)의 폭에 답하는 `@container`다.

**Tech Stack:** 정적 HTML, 순수 CSS, ES 모듈(번들러 없음). CSP는 `style-src 'self'; script-src 'self'`라 인라인 스타일과 `el.style`을 쓰지 않는다. 소스 시험은 pytest, 단위 시험은 `node --test`(pytest `test_site_map_api.py::test_console_web_node_unit_tests_pass`가 원격에서 돌린다). 시험은 노트북에서 돌리지 않는다. 원격 러너는 커밋한 HEAD만 보내고 호출마다 `run-1.txt`부터 다시 쓴다.

**읽고 시작할 것:** `rosy-platform/AGENTS.md`의 「같이 하는 깃」, `operations/ui/console/AGENTS.md`, `operations/fleet/AGENTS.md`, `shared/web/AGENTS.md`, [D-741](../adr/D-741-unified-app-shell-seats.md) 3·5·6항, D-658, D-668, D-683, D-632, D-473, D-421 7항, D-359 §6.

---

## 설계가 지키는 것

| 제약 | 이 계획이 하는 일 |
|---|---|
| 머리 마크업은 네 문서에서 글자 그대로 같다(`test_fleet_header.py`) | 머리를 고치는 Task는 네 HTML을 같은 커밋에서 같은 글로 고친다 |
| 비상 정지를 동적 로딩 뒤로 옮기지 않는다(D-658 5항) | `#estop`은 정적 마크업 그대로다. 지금 스크립트가 만드는 `#fleet-inbox`도 Task 3에서 정적 마크업이 된다 |
| 시험이 쓰는 id를 지킨다 | `console-token`, `token-save`, `user-role`, `password-login`, `token-access`, `fleet-theme`, `development-badge`, `online-pill`, `topbar-more`, `topbar-extra`, `estop`, `clock`, `fleet-inbox`, `header-unread`, `fleet-login`, `fleet-account`, `fleet-account-identity`, `fleet-profile`, `fleet-name`, `estop-feedback`은 전부 남는다. 새 id는 `link-state` 하나다 |
| 바뀌는 것은 자리와 요소 종류다 | `#online-pill`은 관제 문서의 지도 머리로 간다(다른 세 문서에는 없다). `#clock`은 푸터에서 머리로 간다. `#user-role`은 접힌 칸에서 계정 단추 안으로 간다. `#fleet-theme`은 머리 줄에서 계정 단추 아래로 간다. `#fleet-account`는 `<details>`에서 계정 단추 아래의 `<div>`가 된다(`#fleet-account > summary`를 누르던 시험을 같은 Task에서 고친다) |
| `data-always-live`와 래치를 드러내는 정지 이름(D-421 7항) | `#estop` 줄은 한 글자도 바꾸지 않는다. `<small>래치 · 로봇별 관리자 해제</small>`가 64rem 아래에서 접히는 지금 동작도 그대로 둔다(열린 결정 6) |
| 로그인 링크·계정 동작·복귀 허용 목록(D-683) | `#fleet-login`은 머리 줄에 보이는 글 `로그인`으로 남는다. `login-return.js`와 `password-login.js`의 인증 흐름은 고치지 않는다 |
| 역할 토큰만, 원시 색 없음, 표면 시트는 사용자 정의 속성을 선언하지 않는다 | 새 규칙은 색을 정하지 않는다. 치수는 `--appbar-height`, `--rail-track`, `--inset-rail`, `--gap-rail`, `--target-secondary`를 쓴다. `shared/web`의 공용 시트는 고치지 않는다 |
| D-168 줄 수 | `console.js` 1035 → 1037(상한 1175). `shared/styles.css` 862 → 863(기록 802, 허용 +150). `shared/fleet-header.js` 206 → 약 225. `shared/fleet-header.css` 98 → 약 105. `shared/doc-tabs.css` 65 → 약 62. `install.js` 358 → 348. `shared/password-login.js` −5. `test_over_budget_code_has_a_recorded_verdict`가 패키지 합계로 실패하면 그 문구의 숫자로 판정을 다시 적는다 |

## 320px 한 줄의 폭 계산

토큰 값으로 셈한 것이고 글자 폭은 추정이다. 판정은 CI의 `test_fleet_header_browser.py`(가로 넘침 0)와 Task 7의 사람 확인이다.

| 요소 | 30rem 아래 | 근거 |
|---|---|---|
| 앱 바 안쪽 여백 | 8 + 8 | `var(--space-2)` |
| 맥락 | 20 | R 심볼 1em. `Fleet` 글은 가린다(접근 이름 `Rosy Fleet 관제 홈`은 남는다) |
| 연결 | 0–62 | 남는 폭을 받는 칸. `실시간`과 시계는 48rem 아래에서 접고 `연결 대기`·`지연`·`연결 끊김`만 보인다 |
| 알림 단추 | 48–64 | 읽지 않은 수 두 자리까지 |
| 계정 단추 | 90 | 아이콘 18 + 4 + `운영자` 42 + 여백 24 + 선 2. 폭이 모자라면 역할 이름이 줄임표로 줄어든다 |
| 비상 정지 | 106 | 아이콘 16 + 4 + `비상 정지` 60 + 여백 24 + 선 2 |
| 사이 간격 | 4 × 4 | `var(--space-1)` |

운영자·읽지 않은 수 없음: 16 + 20 + 48 + 4 + 90 + 106 + 12 = 296. 로그인 전: 알림 단추를 숨기고 `로그인`(아이콘 없이 68)과 계정 단추(최소 48)가 서서 16 + 20 + 68 + 4 + 48 + 106 + 12 = 274다. 넓은 역할 이름(`정책 관리자`)이나 개발 표지가 붙으면 계정 단추의 역할 이름이 먼저 줄고, 비상 정지는 밀리지 않는다.

---

### Task 0: 작업 위치와 선행 조건

- [ ] **Step 1: 워크트리를 확인한다**

이 계획 문서를 담은 워크트리가 이미 있다. 새로 만들지 않는다.

```bash
cd F:/Dev/Control/Robot/Rosy/rosy-platform
git status --short --branch
git worktree list | grep fleet-app-bar
cd .worktrees/fleet-app-bar
git branch --show-current
git merge main
mkdir -p X:/DevTemp/fleet-bar
```

Expected: `git worktree list`에 `.worktrees/fleet-app-bar ... [feat/fleet-app-bar]`, `git branch --show-current`가 `feat/fleet-app-bar`. `git merge main`이 충돌 없이 끝난다.

- [ ] **Step 2: 결정이 Accepted인지 본다**

```bash
grep -n "^\*\*Status:\*\*" docs/adr/D-741-unified-app-shell-seats.md
grep -n "D-668" docs/adr/D-741-unified-app-shell-seats.md
```

Expected: 첫 줄이 `**Status:** Accepted`이고, 둘째 명령이 "바뀌는 기존 결정" 표의 D-668 행을 찍는다.

둘 중 하나라도 아니면 **Task 1을 시작하지 않고 멈춘다.** 이 계획의 Task 1·2·3·5는 Accepted 결정의 조항을 바꾸고 그 조항을 고정한 시험을 고친다. 시험만 고쳐서는 풀리지 않는 조항은 아래다. 조각 0(D-741을 Accepted로, 바뀌는 항을 각 ADR에 적음)이 먼저 들어가야 한다.

| 결정 | 조항 | 이 계획과 부딪치는 곳 |
|---|---|---|
| D-658 | 2항 "시각·진단은 푸터", 두 줄 배치. 3항 접속·테마 펼침. 7항 계정 위치 | Task 1(푸터 제거), Task 3, Task 5 |
| D-668 | 1항 테마 단추는 머리 줄의 actions 영역. 2항 status 영역은 연결 비율·읽지 않은 수·개발 표지를 담은 상태 센터 단추 하나. 7항 모바일 두 줄 | Task 2, Task 3, Task 5. **D-741의 "바뀌는 기존 결정" 표에 D-668이 없다** |
| D-683 | 2항 "계정 메뉴는 테마/고급 토큰을 소유하지 않는다" | Task 3 |
| D-641 | 1항 다섯 영역의 푸터. 4항 전역 탐색은 아이콘 단독. D-741 표에는 4항만 있다 | Task 1, Task 4 |
| D-466 | 1항 머리의 자리는 셋. 2항 64rem 두 줄 | Task 5 |
| D-359 | 2026-10-04 부기 "머리 접힘은 64rem". §6.2 `@media` 세 단 | Task 5 |
| D-632 | 1항 "공통 머리에 알림 단추". 30rem 아래 로그인 전에는 알림 단추를 숨긴다 | Task 5(열린 결정 3) |
| D-654 4항, D-377 | 제품 이름 `Rosy Fleet`. 워드마크 글이 `Fleet`이 된다(접근 이름과 `<title>`은 그대로) | Task 3(열린 결정 7) |

---

### Task 1: 시계와 연결 상태를 앱 바로, 푸터 제거

검증: **원격 pytest (소스)** — `test_fleet_header.py`, node 단위 시험. **CI 브라우저** — `test_fleet_header_browser.py`. **자동 증거 없음** — `test/test_fleet_console_browser.py`(CI는 `operations/fleet/test`에만 브라우저를 켠다).

**Files:**
- Modify: `operations/ui/console/index.html`, `install.html`, `site-map.html`, `cell/cell.html`
- Modify: `operations/ui/console/shared/fleet-header.js`, `shared/fleet-header.css`, `shared/doc-tabs.css`, `console.js`
- Test: `operations/fleet/test/test_fleet_header.py`, `operations/fleet/test/web/fleet-header.test.mjs`, `operations/fleet/test/test_fleet_header_browser.py`, `test/test_fleet_console_browser.py`

- [ ] **Step 1: 소스 시험을 먼저 고친다**

`operations/fleet/test/test_fleet_header.py`의 `test_header_ids_and_one_sheet`에서:

```python
        for element_id in ("console-token", "token-save", "user-role", "password-login", "token-access",
                           "fleet-theme", "development-badge", "online-pill", "topbar-more", "estop"):
            assert f'id="{element_id}"' in header, (name, element_id)
```

을

```python
        for element_id in ("console-token", "token-save", "user-role", "password-login", "token-access",
                           "fleet-theme", "development-badge", "online-pill", "topbar-more", "estop",
                           "clock", "link-state"):
            assert f'id="{element_id}"' in header, (name, element_id)
```

로, 같은 함수의:

```python
        assert re.search(r'<footer[^>]*class="fleet-footer".*?id="clock"', page, re.S), name
        assert 'id="clock"' not in header, name
```

을

```python
        # D-741 3: 푸터는 없다. 시계는 앱 바의 연결 자리에 있고, 푸터의 알림 링크는 머리의 알림 단추가 대신한다.
        assert "<footer" not in page and "fleet-footer" not in page and "관제 알림" not in page, name
        status = header.split('data-header-region="status"', 1)[1].split('data-header-region="actions"', 1)[0]
        assert status.index('id="link-state"') < status.index('id="clock"'), name
```

로 바꾼다. `test_document_sheets_do_not_paint_the_header`의 마지막 줄 다음에 한 줄을 더한다:

```python
    assert ".fleet-footer" not in (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")
```

`operations/fleet/test/web/fleet-header.test.mjs`에서 import를:

```js
const {
  SESSION_REASON, bindEstop, bindTopbarToggle, estopReason, roleLabel, showFleet, showInboxCount, showSession, showSignedOut,
} = await import("../../../ui/console/shared/fleet-header.js");
```

에서

```js
const {
  LATE_MS, SESSION_REASON, bindEstop, bindTopbarToggle, estopReason, linkState, noteLink, roleLabel, showFleet,
  showInboxCount, showSession, showSignedOut, tickClock,
} = await import("../../../ui/console/shared/fleet-header.js");
```

로 바꾸고, `fakeHeader()`의 id 목록에서 `"fleet-login", "fleet-account", "fleet-account-identity"`를 `"fleet-login", "fleet-account", "fleet-account-identity", "link-state"`로 바꾼다. 파일 끝에 붙인다:

```js
test("the link word follows Fleet's answers: live, late after LATE_MS, down on a failed request", () => {
  const nodes = fakeHeader();
  noteLink(null, 1000);
  assert.equal(nodes["link-state"].textContent, "실시간");
  assert.equal(nodes["link-state"].dataset.link, "live");
  assert.equal(linkState(1000 + LATE_MS), "live");
  assert.equal(linkState(1001 + LATE_MS), "late");
  noteLink(Object.assign(new Error("denied"), {status: 401}), 2000);  // the server answered
  assert.equal(nodes["link-state"].textContent, "실시간");
  noteLink(Object.assign(new Error("bad gateway"), {status: 502}), 3000);
  assert.equal(nodes["link-state"].textContent, "연결 끊김");
  assert.equal(nodes["link-state"].getAttribute("status"), "crit");
  noteLink(new TypeError("fetch failed"), 4000);
  assert.equal(linkState(4000), "down");
  noteLink(Object.assign(new Error("aborted"), {name: "AbortError"}), 5000);
  assert.equal(linkState(5000), "down");  // an aborted read says nothing either way
  noteLink(null, 6000);
  assert.equal(nodes["link-state"].textContent, "실시간");
  assert.equal(nodes["link-state"].getAttribute("status"), "neutral");
});

test("the clock tick writes the time and repaints the link word when answers stop", () => {
  const nodes = fakeHeader();
  noteLink(null, Date.now() - LATE_MS - 1000);
  tickClock();
  assert.match(nodes.clock.textContent, /^\d\d:\d\d:\d\d$/);
  assert.equal(nodes["link-state"].textContent, "지연");
  assert.equal(nodes["link-state"].getAttribute("status"), "warn");
});
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add operations/fleet/test/test_fleet_header.py operations/fleet/test/web/fleet-header.test.mjs
git commit -m "test(fleet): pin the clock and link state in the app bar, no footer (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_site_map_api.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t1-red.txt
```

Expected: `test_header_ids_and_one_sheet`가 `('index.html', 'clock')`으로, `test_document_sheets_do_not_paint_the_header`가 `.fleet-footer`로, `test_console_web_node_unit_tests_pass`가 `linkState is not a function` 또는 import 오류로 실패한다. 원격 PC에 node가 없으면 마지막 시험은 `SKIPPED`이고 그 증거는 CI다.

- [ ] **Step 3: 네 문서의 머리에 연결 글과 시계를 넣고 푸터를 지운다**

네 HTML 모두에서 같은 글로:

```html
    <div class="fleet-link-status" data-header-region="status" role="group" aria-label="관제 상태">
      <ui-button kind="quiet" id="topbar-more" type="button" aria-expanded="false" aria-controls="topbar-extra" aria-label="상태 센터: 연결·권한·메시지 확인">
```

을

```html
    <div class="fleet-link-status" data-header-region="status" role="group" aria-label="관제 상태">
      <ui-tag id="link-state" variant="inline" status="neutral" data-link="wait">연결 대기</ui-tag>
      <ui-text id="clock" scale="value">--:--:--</ui-text>
      <ui-button kind="quiet" id="topbar-more" type="button" aria-expanded="false" aria-controls="topbar-extra" aria-label="상태 센터: 연결·권한·메시지 확인">
```

로 바꾼다. 네 HTML 모두에서 아래 한 줄을 지운다(`</ui-shell>` 바로 앞 줄이다):

```html
  <footer class="fleet-footer" aria-label="운영 정보"><span>현재 시각</span><ui-text id="clock" scale="value">--:--:--</ui-text><a href="/console?inbox=1" data-action-icon="notification" data-icon-only="">관제 알림</a></footer>
```

- [ ] **Step 4: 연결 상태를 머리 모듈에 넣는다**

`operations/ui/console/shared/fleet-header.js`의 `const $ = id => document.getElementById(id);` 줄 바로 다음에:

```js

// D-741 3 — 브라우저와 Fleet 사이의 연결. 답이 오면 실시간, LATE_MS 넘게 새 답이 없으면 지연,
// 요청이 닿지 않았거나 서버가 5xx로 답하면 연결 끊김이다. 401·403은 서버가 답한 것이라 실시간이다.
// 로봇과의 연결은 여기 것이 아니다. 그것은 관제 화면의 연결 수와 로봇 카드가 말한다.
const LINK = {wait: ["연결 대기", "neutral"], live: ["실시간", "neutral"], late: ["지연", "warn"], down: ["연결 끊김", "crit"]};
export const LATE_MS = 12000;  // 5초 조회 두 번을 놓치고 2초
let answeredAt = null, linkFailed = false;
export function linkState(now = Date.now()) {
  if (linkFailed) return "down";
  if (answeredAt === null) return "wait";
  return now - answeredAt > LATE_MS ? "late" : "live";
}
function paintLink(now) {
  const tag = $("link-state"), state = linkState(now);
  if (tag.dataset.link === state) return;
  tag.dataset.link = state;
  tag.textContent = LINK[state][0];
  tag.setAttribute("status", LINK[state][1]);
}
export function noteLink(error = null, now = Date.now()) {
  if (error?.name === "AbortError") return;
  linkFailed = Boolean(error) && !(typeof error.status === "number" && error.status < 500);
  if (!linkFailed) answeredAt = now;
  paintLink(now);
}
```

같은 파일의 `watchFleet` 안에서:

```js
    try {
      const state = await request("/api/fleet/state");
      showFleet(state.fleet, state.robots);
    } catch (error) {
      if (error.name === "AbortError" || error.status === 401 || error.status === 403) return;
```

을

```js
    try {
      const state = await request("/api/fleet/state");
      noteLink();
      showFleet(state.fleet, state.robots);
    } catch (error) {
      noteLink(error);
      if (error.name === "AbortError" || error.status === 401 || error.status === 403) return;
```

로, `tickClock`을:

```js
export function tickClock() {
  $("clock").textContent = new Date().toTimeString().slice(0, 8);
}
```

에서

```js
export function tickClock() {
  const now = Date.now();
  $("clock").textContent = new Date(now).toTimeString().slice(0, 8);
  paintLink(now);  // 답이 끊긴 채 시간이 가면 이 틱이 지연으로 바꾼다
}
```

로 바꾼다. 네 문서가 이미 1초마다 `tickClock`을 부르므로 새 타이머는 없다.

`operations/ui/console/console.js`에서 import 줄:

```js
import { bindEstop, showFleet, showSession, showSignedOut, stopNotice, tickClock } from "/console/assets/fleet-header.js";
```

을

```js
import { bindEstop, noteLink, showFleet, showSession, showSignedOut, stopNotice, tickClock } from "/console/assets/fleet-header.js";
```

로 바꾸고, `refreshState` 안의:

```js
    pathSample.fleet = { finished: true, status: 200 };
    fleetAnswered = true;
```

다음 줄에 `    noteLink();`를, 같은 함수의:

```js
  } catch (err) {
    if (err.name === "AbortError") return;
    if (!fleetAnswered) {
```

에서 `AbortError` 줄 다음에 `    noteLink(err);`를 넣는다. `console.js`는 두 줄 늘어 1037줄이다.

- [ ] **Step 5: 시트를 고친다**

`operations/ui/console/shared/fleet-header.css`에서 `.fleet-link-status ui-tag { ... }` 줄 바로 다음에:

```css
#clock { flex: none; white-space: nowrap; }
```

같은 파일의 `@media (width < 48rem) {` 블록 안, `#estop { gap: var(--space-1); }` 줄 바로 앞에:

```css
  /* 좁은 폭의 연결 자리는 평상시 조용하다. 연결 대기·지연·연결 끊김은 보인다. */
  #clock, #link-state[data-link="live"] { display: none; }
```

`operations/ui/console/shared/doc-tabs.css`에서:

```css
.fleet-shell { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-height: 100dvh; }
```

을

```css
.fleet-shell { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 100dvh; }
```

로 바꾸고, `.fleet-footer {`, `.fleet-footer a {`, `.fleet-footer a:focus-visible {`로 시작하는 세 줄과 마지막 `@media (width < 64rem)` 블록 안의 `  .fleet-footer { padding-inline: var(--space-3); }` 줄을 지운다.

- [ ] **Step 6: 브라우저 시험을 같은 커밋에서 고친다**

`operations/fleet/test/test_fleet_header_browser.py`의 `test_four_documents_draw_one_header_and_one_estop`에서:

```python
            expect(page.locator("#clock")).not_to_have_text("--:--:--")
```

다음 줄에 더한다:

```python
            expect(page.locator("#link-state")).to_have_text("실시간", timeout=15000)
```

같은 함수에서:

```python
                footer = page.get_by_role("contentinfo")
                expect(footer.locator("#clock")).not_to_have_text("--:--:--")
```

을

```python
                expect(page.get_by_role("contentinfo")).to_have_count(0)
                expect(page.locator('[data-header-region="status"] #clock')).not_to_have_text("--:--:--")
                if width >= 768:
                    expect(page.locator("#clock")).to_be_visible()
                    expect(page.locator("#link-state")).to_be_visible()
                else:  # 48rem 아래: 시계와 평상(실시간) 글은 접힌다
                    expect(page.locator("#clock")).to_be_hidden()
                    expect(page.locator("#link-state")).to_be_hidden()
```

로 바꾸고, 아래 한 줄을 지운다:

```python
                assert footer.bounding_box()["y"] >= main["y"] + main["height"] - 1
```

`test/test_fleet_console_browser.py`의 `test_mobile_console_has_no_horizontal_overflow`에서:

```python
    assert layout["headerRows"] <= 2, layout  # D-641: identity/connection and status/inbox, clock in footer.
```

을

```python
    assert layout["headerRows"] <= 2, layout  # 48rem 아래의 두 줄은 한 줄 접힘 Task에서 한 줄이 된다.
```

로, 같은 함수의:

```python
        # D-641/D-668: compact header keeps the status center and theme on one row; the clock belongs to the flow footer.
        status, inbox = layout["status"], layout["inbox"]
        assert min(status["bottom"], inbox["bottom"]) - max(status["top"], inbox["top"]) > 1, layout
        assert layout["clock"]["height"] > 0, layout
        assert layout["clock"]["top"] >= layout["stop"]["bottom"], layout
```

을

```python
        # D-741 3: the clock lives in the app bar and folds below 48rem; the status center and theme share a row.
        status, inbox = layout["status"], layout["inbox"]
        assert min(status["bottom"], inbox["bottom"]) - max(status["top"], inbox["top"]) > 1, layout
        assert layout["clock"]["height"] == 0, layout
```

로 바꾼다. `test_compact_header_budget_keeps_the_stop_in_view`에서:

```python
            clockInFooter: !!document.querySelector('footer.fleet-footer #clock'),
```

을

```python
            footer: !!document.querySelector('footer'),
```

로, 같은 함수의:

```python
    assert folded["status"] and folded["clock"] and folded["clockInFooter"], folded
    assert not folded["clockInHeader"], folded
```

을

```python
    assert folded["status"] and not folded["clock"] and not folded["footer"], folded
    assert folded["clockInHeader"], folded
```

로 바꾼다.

- [ ] **Step 7: 커밋하고 원격에서 통과를 확인한다**

```bash
git add operations/ui/console/index.html operations/ui/console/install.html operations/ui/console/site-map.html operations/ui/console/cell/cell.html operations/ui/console/shared/fleet-header.js operations/ui/console/shared/fleet-header.css operations/ui/console/shared/doc-tabs.css operations/ui/console/console.js operations/fleet/test/test_fleet_header_browser.py test/test_fleet_console_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): move the clock and link state into the app bar, drop the footer (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_server_app.py operations/fleet/test/test_document_imports.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t1-fleet-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t1-fleet-$(basename "$f")"; done
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test test/architecture test/test_remaining_platform_installed.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t1-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t1-web-$(basename "$f")"; done
```

Expected: `test_fleet_header.py` 5 passed, node 단위 시험 통과(또는 `SKIPPED`), 로그마다 `NEW` 0. `*_browser.py`는 원격에서 전부 `SKIPPED`다.

---

### Task 2: 로봇 연결 수를 관제 지도 머리로

제안된 순서(계정 단추 → 연결 수)를 뒤집었다. 연결 수는 지금 상태 센터 단추(`#topbar-more`) 안에 있고 Task 3이 그 단추를 다시 짠다. 연결 수를 먼저 빼야 Task 3이 단추를 한 번만 고친다.

검증: **원격 pytest (소스)** — `test_fleet_header.py`, `test_action_icon_contract.py`. **CI 브라우저** — `test_fleet_header_browser.py`. **자동 증거 없음** — `test/test_fleet_console_browser.py`.

**Files:**
- Modify: 네 HTML, `operations/ui/console/shared/fleet-header.js`, `shared/styles.css`, `install.js`
- Test: `operations/fleet/test/test_fleet_header.py`, `shared/web/test/test_action_icon_contract.py`, `operations/fleet/test/test_fleet_header_browser.py`, `test/test_fleet_console_browser.py`

- [ ] **Step 1: 소스 시험을 먼저 고친다**

`operations/fleet/test/test_fleet_header.py`의 `test_header_ids_and_one_sheet`에서:

```python
                           "fleet-theme", "development-badge", "online-pill", "topbar-more", "estop",
                           "clock", "link-state"):
            assert f'id="{element_id}"' in header, (name, element_id)
```

을

```python
                           "fleet-theme", "development-badge", "topbar-more", "estop",
                           "clock", "link-state"):
            assert f'id="{element_id}"' in header, (name, element_id)
        # D-741 3: 로봇 연결 수는 앱 바가 아니라 관제 화면의 내용이다.
        assert 'id="online-pill"' not in header, name
        assert page.count('id="online-pill"') == (1 if name == "index.html" else 0), name
```

로, `test_header_regions_keep_identity_status_actions_and_safety_separate`에서:

```python
    for element_id in ("online-pill", "header-unread", "development-badge"):
        assert f'id="{element_id}"' in entry
    assert entry.count("<ui-button") == 1
    assert 'data-action-icon="connect"' in entry and 'data-action-icon="notification"' in entry
```

을

```python
    for element_id in ("header-unread", "development-badge"):
        assert f'id="{element_id}"' in entry
    assert entry.count("<ui-button") == 1
    assert 'data-action-icon="connect"' not in entry and 'data-action-icon="notification"' in entry
```

로 바꾼다.

`shared/web/test/test_action_icon_contract.py`의 `test_fleet_documents_share_the_stop_and_chrome_icons`에서:

```python
        for icon in ("connect", "notification", "theme-dark", "refresh"):
            assert f'data-action-icon="{icon}"' in page, (name, icon)
```

을

```python
        for icon in ("notification", "theme-dark", "refresh"):
            assert f'data-action-icon="{icon}"' in page, (name, icon)
        # D-741 3: 로봇 연결 수와 그 아이콘은 관제 문서의 지도 머리에만 있다.
        assert ('data-action-icon="connect"' in page) == (name == "index.html"), name
```

로 바꾼다.

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add operations/fleet/test/test_fleet_header.py shared/web/test/test_action_icon_contract.py
git commit -m "test(fleet): pin the robot count outside the app bar (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t2-red.txt
```

Expected: `2 failed, 3 passed`. `test_header_ids_and_one_sheet`가 `assert 'id="online-pill"' not in header`로 실패한다.

- [ ] **Step 3: 머리에서 연결 수를 빼고 관제 지도 머리에 넣는다**

네 HTML 모두에서 `#topbar-more` 안의 아래 한 줄을 지운다:

```html
        <span class="header-status-item"><span data-action-icon="connect" data-icon-only="" aria-label="로봇 연결"></span><ui-tag id="online-pill" variant="inline" status="neutral">연결 대기</ui-tag></span>
```

`operations/ui/console/index.html`에서만:

```html
      <div class="map-head">
        <div>
          <h2 id="map-heading" title="로봇 카드의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다">현장 지도</h2>
        </div>
        <div class="spacer"></div>
```

을

```html
      <div class="map-head">
        <div>
          <h2 id="map-heading" title="로봇 카드의 목표 지정을 누른 뒤 지도를 찍으면 그 로봇에게만 목표가 갑니다">현장 지도</h2>
        </div>
        <!-- D-741 3 — 로봇 연결 수는 앱 바가 아니라 관제 화면의 내용이다. -->
        <span class="map-robots"><span data-action-icon="connect" data-icon-only="" aria-label="로봇 연결"></span><ui-tag id="online-pill" variant="inline" status="neutral">연결 대기</ui-tag></span>
        <div class="spacer"></div>
```

로 바꾼다. `operations/ui/console/shared/styles.css`의 `.map-head .spacer { flex: 1; }` 줄 바로 다음에:

```css
.map-robots { display: inline-flex; align-items: center; gap: var(--gap-button-detail); white-space: nowrap; }
```

- [ ] **Step 4: 머리 모듈과 설치 문서에서 연결 수 쓰기를 걷는다**

`operations/ui/console/shared/fleet-header.js`의 `summarize()`에서:

```js
    const label = `상태 센터 · 로봇 연결 ${$("online-pill").textContent} · ${messages}${development}`;
```

을

```js
    const label = `상태 센터 · ${messages}${development}`;
```

로, `showFleet`에서:

```js
  const pill = $("online-pill");
  delete pill.dataset.locked;
```

을

```js
  const pill = $("online-pill");
  if (!pill) return;  // 연결 수는 관제 문서에만 있다(D-741 3)
  delete pill.dataset.locked;
```

로 바꾼다. `watchFleet` 위의 주석 두 줄:

```js
// Pages without their own state poll (설치·보정, 현장 지도, Cell) read the count every 5 s. A 401/403 leaves
// the pill to the page's lock words; anything else says the server is missing.
```

을

```js
// Pages without their own state poll (설치·보정, 현장 지도, Cell) read Fleet every 5 s for the site name
// and the link word. They show no robot count.
```

로 바꾸고, `watchFleet`의 catch:

```js
    } catch (error) {
      noteLink(error);
      if (error.name === "AbortError" || error.status === 401 || error.status === 403) return;
      const pill = $("online-pill");
      pill.textContent = "Fleet 서버 없음";
      pill.setAttribute("status", "crit");
    }
```

을

```js
    } catch (error) {
      noteLink(error);
    }
```

로 바꾼다.

`operations/ui/console/install.js`의 `markLocked`에서 아래 네 줄을 지운다:

```js
  const pill = el("online-pill");
  pill.textContent = "접속 전";
  pill.setAttribute("status", "neutral");
  pill.dataset.locked = "true"; // 해제 때 문구가 아니라 이 표시로 잠금 pill을 알아본다
```

같은 파일의 `refreshAuthorization`에서 `showSession(identity);` 다음의 아래 여섯 줄을 지운다:

```js
    const pill = el("online-pill");
    if (pill.dataset.locked === "true") {
      delete pill.dataset.locked;
      pill.textContent = "설치 준비 중";
      pill.setAttribute("status", "neutral");
    }
```

`console.js`의 `online-pill` 쓰기 세 곳(`markLocked`, `refreshState`의 catch, `refreshAuthorization`)은 그대로 둔다. 관제 문서에는 그 요소가 있다.

- [ ] **Step 5: 브라우저 시험을 같은 커밋에서 고친다**

`operations/fleet/test/test_fleet_header_browser.py`에서:

```python
            expect(page.locator("#online-pill")).to_have_text("2/3", timeout=15000)
```

을

```python
            if name == "console":
                expect(page.locator('main [aria-labelledby="map-heading"] #online-pill')).to_have_text("2/3", timeout=15000)
            else:
                expect(page.locator("#online-pill")).to_have_count(0)
```

로, 같은 함수의:

```python
                expect(page.locator('#topbar-more')).to_have_attribute("aria-label", re.compile("상태 센터.*2/3"))
```

을

```python
                expect(page.locator('#topbar-more')).to_have_attribute("aria-label", re.compile("상태 센터"))
```

로 바꾼다.

`test/test_fleet_console_browser.py`의 `test_mobile_console_has_no_horizontal_overflow`에서 Task 1이 남긴 블록:

```python
        # D-741 3: the clock lives in the app bar and folds below 48rem; the status center and theme share a row.
        status, inbox = layout["status"], layout["inbox"]
        assert min(status["bottom"], inbox["bottom"]) - max(status["top"], inbox["top"]) > 1, layout
        assert layout["clock"]["height"] == 0, layout
```

을

```python
        # D-741 3: the clock lives in the app bar and folds below 48rem; the robot count sits in the map head.
        assert layout["status"]["top"] >= layout["stop"]["bottom"], layout
        assert layout["clock"]["height"] == 0, layout
```

로 바꾼다. 같은 파일의 `#online-pill` 글 시험(`0/0`, `2/3`, `3/3`, `Fleet 서버 없음`, `접속 전`)은 그대로 통과해야 한다. 관제 문서의 그 요소는 id와 글이 같다.

- [ ] **Step 6: 커밋하고 원격에서 통과를 확인한다**

```bash
git add operations/ui/console/index.html operations/ui/console/install.html operations/ui/console/site-map.html operations/ui/console/cell/cell.html operations/ui/console/shared/fleet-header.js operations/ui/console/shared/styles.css operations/ui/console/install.js operations/fleet/test/test_fleet_header_browser.py test/test_fleet_console_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): show the robot count in the console map head, not the app bar (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_server_app.py operations/fleet/test/test_document_imports.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t2-fleet-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t2-fleet-$(basename "$f")"; done
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test test/architecture test/test_remaining_platform_installed.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t2-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t2-web-$(basename "$f")"; done
```

Expected: `test_fleet_header.py` 5 passed, `test_action_icon_contract.py` 2 passed, 로그마다 `NEW` 0. `test_fleet_header.py::test_document_sheets_do_not_paint_the_header`가 `styles.css`에서 `ui-topbar`·`.estop`·`#topbar-more`를 찾지 못해야 하므로 Step 3의 새 규칙 선택자가 `.map-robots`인지 본다.

---

### Task 3: 알림 단추와 계정 단추

상태 센터 단추를 푼다. 읽지 않은 수는 알림 단추로, 역할 이름과 개발 표지는 계정 단추(`#topbar-more`)로 간다. 화면 표시와 토큰 접속과 계정 정보는 계정 단추 아래(`#topbar-extra`)에 모인다. 워드마크 글은 `Fleet`이 된다. `#topbar-extra`는 지금처럼 머리 아래에 한 줄을 더 펼치는 칸으로 둔다(열린 결정 2).

검증: **원격 pytest (소스)** — `test_fleet_header.py`, node 단위 시험. **CI 브라우저** — `test_fleet_header_browser.py`, `test_development_console_browser.py`, `test_password_login_browser.py`, `test_fleet_account_browser.py`, `test_site_map_browser.py`. **자동 증거 없음** — `test/test_fleet_console_browser.py`, `shared/web/test/test_theme_browser.py`.

**Files:**
- Modify: 네 HTML, `operations/ui/console/shared/fleet-header.js`, `shared/fleet-header.css`, `shared/password-login.js`
- Test: `operations/fleet/test/test_fleet_header.py`, `web/fleet-header.test.mjs`, `test_fleet_header_browser.py`, `test_development_console_browser.py`, `test_password_login_browser.py`, `test_fleet_account_browser.py`, `test_site_map_browser.py`, `shared/web/test/test_theme_browser.py`, `test/test_fleet_console_browser.py`

- [ ] **Step 1: 소스 시험을 먼저 고친다**

`operations/fleet/test/test_fleet_header.py`의 `test_header_ids_and_one_sheet`에서:

```python
                           "fleet-theme", "development-badge", "topbar-more", "estop",
                           "clock", "link-state"):
```

을

```python
                           "fleet-theme", "development-badge", "topbar-more", "topbar-extra", "estop",
                           "clock", "link-state", "fleet-inbox", "header-unread", "fleet-login",
                           "fleet-account", "fleet-account-identity", "fleet-profile", "fleet-name"):
```

로 바꾼다. `test_header_regions_keep_identity_status_actions_and_safety_separate` 전체를 아래로 바꾼다:

```python
def test_header_regions_keep_identity_status_actions_and_safety_separate():
    _, header = _header("index.html")
    assert re.findall(r'data-header-region="([^"]+)"', header) == [
        "identity", "status", "actions", "safety"]
    assert 'id="fleet-header-actions"' in header
    # D-741 3: 연결 자리에는 조작이 없다. 알림, 로그인, 나(계정 단추) 순서로 정지 앞에 선다.
    status = header.split('data-header-region="status"', 1)[1].split('data-header-region="actions"', 1)[0]
    assert 'id="link-state"' in status and 'id="clock"' in status and "<ui-button" not in status
    actions = header.split('data-header-region="actions"', 1)[1].split('data-header-region="safety"', 1)[0]
    assert actions.index('id="fleet-inbox"') < actions.index('id="fleet-login"') < actions.index('id="topbar-more"')
    inbox = re.search(r'<ui-button[^>]*id="fleet-inbox".*?</ui-button>', header, re.S).group(0)
    assert 'id="header-unread"' in inbox and 'data-action-icon="notification"' in inbox
    entry = re.search(r'<ui-button[^>]*id="topbar-more".*?</ui-button>', header, re.S).group(0)
    for element_id in ("user-role", "development-badge"):
        assert f'id="{element_id}"' in entry
    assert entry.count("<ui-button") == 1 and 'data-action-icon="account"' in entry
    assert 'aria-controls="topbar-extra"' in entry
    assert header.index('data-header-region="safety"') < header.index('id="topbar-extra"')
    menu = header.split('id="topbar-extra"', 1)[1]
    for element_id in ("fleet-account", "password-login", "fleet-theme", "token-access", "console-token", "token-save"):
        assert f'id="{element_id}"' in menu, element_id
    assert "<details id=\"fleet-account\"" not in header, "계정 정보는 계정 단추 하나 아래에 있다"
    controller = (WEB / "shared/fleet-header.js").read_text(encoding="utf-8")
    assert "createElement(\"ui-button\")" not in controller, "알림 단추는 정적 마크업이다(D-658 5항)"
```

`operations/fleet/test/web/fleet-header.test.mjs`의 첫 시험에서 `bindTopbarToggle();` 줄 다음에 두 줄을 더한다:

```js
  assert.match(nodes["topbar-more"].getAttribute("aria-label"), /^계정과 접속/);
  assert.equal(typeof nodes["fleet-inbox"].listeners.click, "function");
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add operations/fleet/test/test_fleet_header.py operations/fleet/test/web/fleet-header.test.mjs
git commit -m "test(fleet): pin the alerts button and the account button in the app bar (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_site_map_api.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t3-red.txt
```

Expected: `test_header_ids_and_one_sheet`가 `('index.html', 'fleet-inbox')`로, `test_header_regions_...`가 `<ui-button`이 연결 자리에 있다는 단언으로 실패한다.

- [ ] **Step 3: 네 문서의 머리를 바꾼다**

네 HTML 모두에서 `<ui-topbar>`부터 `</ui-topbar>`까지를 아래 글로 바꾼다. 네 문서의 글이 한 글자도 다르면 안 된다.

```html
  <ui-topbar>
    <div class="fleet-header-identity" data-header-region="identity" role="group" aria-label="제품과 현장">
    <ui-brand href="/console" aria-label="Rosy Fleet 관제 홈"><b><span class="fleet-wordmark">Fleet</span></b><small id="fleet-name">사이트</small></ui-brand>
    </div>
    <div class="fleet-link-status" data-header-region="status" role="group" aria-label="연결 상태와 시각">
      <ui-tag id="link-state" variant="inline" status="neutral" data-link="wait">연결 대기</ui-tag>
      <ui-text id="clock" scale="value">--:--:--</ui-text>
    </div>
    <div id="fleet-header-actions" class="fleet-header-actions" data-header-region="actions" role="group" aria-label="알림과 계정">
    <ui-button kind="quiet" id="fleet-inbox" type="button" aria-label="알림 창"><span data-action-icon="notification" data-icon-only="" aria-label="알림"></span><span id="header-unread" hidden></span></ui-button>
    <a id="fleet-login" class="ui-disclosure-row" href="/console/login" data-action-icon="login">로그인</a>
    <!-- D-473 — 개발 접속 경고는 닫힌 계정 단추에서도 보인다. -->
    <ui-button kind="quiet" id="topbar-more" type="button" aria-expanded="false" aria-controls="topbar-extra" aria-label="계정과 접속">
      <span class="header-status-item"><span data-action-icon="account" data-icon-only="" aria-label="계정"></span><ui-tag id="user-role" variant="inline" status="neutral">인증 필요</ui-tag></span>
      <ui-tag id="development-badge" variant="inline" status="warn" hidden aria-label="개발 연결 모드: 같은 망 PC에 1시간 운영자 세션 제공" title="같은 망 PC 누구나 1시간 운영자 세션을 받는다 (D-473)">개발</ui-tag>
    </ui-button>
    </div>
    <div class="fleet-header-safety" data-header-region="safety" role="group" aria-label="안전 조작">
    <ui-button kind="irreversible" id="estop" data-always-live class="estop" type="button" data-action-icon="estop"><span>비상 정지</span><small>래치 · 로봇별 관리자 해제</small></ui-button>
    </div>
    <div id="topbar-extra" class="topbar-extra" data-open="false" role="region" aria-label="계정과 접속 상세">
      <div id="fleet-account" class="fleet-account-panel" hidden>
        <p id="fleet-account-identity"></p>
        <a id="fleet-profile" href="/console/profile" hidden>내 계정</a>
        <div id="password-login" class="password-login" hidden></div>
      </div>
      <ui-button kind="quiet" id="fleet-theme" data-theme-cycle="" data-icon-only="" type="button" aria-label="테마 변경" data-action-icon="theme-dark"></ui-button>
      <!-- D-519 — 사람은 /console/login에서 로그인한다. 토큰 접속은 계정 단추 아래에 남는다. -->

      <details id="token-access" class="token-access">
        <summary>토큰으로 접속</summary>
        <input id="console-token" class="ui-field token" type="password" placeholder="관제 토큰"
               autocomplete="off" aria-label="관제 토큰">
        <ui-button kind="quiet" id="token-save" type="button">접속</ui-button>
      </details>
    </div>
  </ui-topbar>
```

`#estop` 줄은 지금 글 그대로다. `#topbar-more`와 `#fleet-inbox`에 `data-action-icon`을 직접 달지 않는다. `actionIcon()`이 단추의 자식을 아이콘과 글 하나로 바꿔 `#user-role`·`#header-unread`를 지우기 때문이다. 지금 상태 센터 단추와 같은 방식으로 안쪽 `<span>`이 아이콘을 갖는다.

`login.html`과 `profile.html`은 고치지 않는다. 두 문서의 머리는 워드마크와 부제만 있는 다른 머리이고(`<b>Rosy Fleet</b><small>관제 로그인</small>`), 링크의 접근 이름이 그 글에서 나온다(열린 결정 7).

- [ ] **Step 4: 머리 모듈을 고친다**

`operations/ui/console/shared/fleet-header.js`의 맨 위 주석 세 줄을:

```js
// D-540 2 / D-741 3 — the one Rosy Fleet app bar. 관제·설치·보정·현장 지도·Cell carry the same <ui-topbar>
// markup (test_fleet_header.py pins it) and drive it only through this module: link word and clock, alerts
// count, role words on the account button, development badge, the account fold and the one E-stop rule.
```

로 바꾼다. `// Every Fleet document has one inbox entry; ...` 주석부터 `showInboxCount` 함수 끝까지(`inboxButton` 함수 포함)를 아래로 바꾼다:

```js
// The alerts button is static markup on every Fleet document; only the console owns the unread count.
function openInbox() {
  const request = new CustomEvent("rosy:inbox", {cancelable: true});
  if (document.dispatchEvent(request)) location.assign("/console?inbox=1");
}
export function showInboxCount(count) {
  const inbox = $("fleet-inbox"), unread = $("header-unread");
  unread.textContent = count ? String(count) : "";
  unread.hidden = !count;
  inbox.setAttribute("aria-label", `알림 창 · 미확인 메시지 ${count}개`);
  inbox.setAttribute("data-ui-tooltip", `${inbox.getAttribute("aria-label")} · 읽음은 개입 해소가 아닙니다`);
  inbox.title = "읽음 표시는 개입 해소나 로봇 상태 변경이 아닙니다";
}
```

`bindTopbarToggle`에서:

```js
  inboxButton();
  bindThemeCycle(listen);
  const entry = $("topbar-more");
  function summarize() {
    const count = $("header-unread").textContent;
    const messages = count === "—" ? "미확인 메시지 수는 관제에서 확인" : `미확인 메시지 ${count}개`;
    const development = $("development-badge").hidden ? "" : " · 개발 연결 모드";
    const label = `상태 센터 · ${messages}${development}`;
    entry.setAttribute("aria-label", label);
    entry.setAttribute("data-ui-tooltip", `${label} · 연결·권한·메시지 확인`);
  }
```

을

```js
  listen($("fleet-inbox"), "click", openInbox);
  bindThemeCycle(listen);
  const entry = $("topbar-more");
  function summarize() {
    const development = $("development-badge").hidden ? "" : " · 개발 연결 모드";
    const label = `계정과 접속 · ${$("user-role").textContent}${development}`;
    entry.setAttribute("aria-label", label);
    entry.setAttribute("data-ui-tooltip", `${label} · 계정·화면 표시·토큰 접속`);
  }
```

로 바꾼다. `showSignedOut`에서 아래 한 줄을 지운다(`#fleet-account`는 이제 `<details>`가 아니다):

```js
  $('fleet-account').open = false;
```

`operations/ui/console/shared/password-login.js`에서:

```js
    const account = document.getElementById('fleet-account');
    part('logout').disabled = true;
    part('logout').setAttribute('reason', '계정 상태 확인 중');
    account.addEventListener('keydown', event => {
      if (event.key === 'Escape') { account.open = false; account.querySelector('summary').focus(); }
    });
```

을

```js
    part('logout').disabled = true;
    part('logout').setAttribute('reason', '계정 상태 확인 중');
```

로 바꾼다. Escape는 `fleet-header.js`의 `#topbar-extra` 처리기가 이미 받아 계정 단추로 초점을 돌린다. 같은 파일에서 아래 한 줄을 지운다:

```js
        document.getElementById('fleet-account').open = false;
```

- [ ] **Step 5: 시트를 고친다**

`operations/ui/console/shared/fleet-header.css`에서:

```css
#user-role { max-width: 12rem; overflow: hidden; text-overflow: ellipsis; }
/* 계정 패널은 actions 영역의 오른쪽 끝에 맞춘다 — 테마 버튼이 계정 뒤에 있어도 좁은 화면 밖으로 나가지 않는다. */
.fleet-header-actions { grid-area: actions; position: relative; display: flex; align-items: center; gap: var(--space-1); }
.fleet-header-actions [hidden] { display: none; }
#fleet-login,
#fleet-account > summary { display: inline-flex; align-items: center; gap: var(--space-1); white-space: nowrap; }
.fleet-account-panel { position: absolute; inset-block-start: 100%; inset-inline-end: 0; box-sizing: border-box; width: min(18rem, calc(100vw - var(--space-3) * 2)); padding: var(--space-3); background: var(--surface-raised); border: 1px solid var(--border-default); overflow-wrap: anywhere; }
.fleet-account-panel .password-login-who { flex-wrap: wrap; }
.fleet-account-panel [data-login="principal"] { display: none; }
.fleet-header-safety { grid-area: safety; justify-self: end; }
#topbar-more { display: inline-flex; max-width: 100%; }
.header-status-item { display: inline-flex; align-items: center; gap: var(--space-1); }
```

을

```css
#user-role { min-width: 0; max-width: 12rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* D-741 3: 알림, 로그인, 나(계정 단추). 폭이 모자라면 계정 단추의 역할 이름이 먼저 줄고 정지는 밀리지 않는다. */
.fleet-header-actions { grid-area: actions; display: flex; align-items: center; gap: var(--space-1); min-width: 0; }
.fleet-header-actions [hidden], .topbar-extra [hidden] { display: none; }
#fleet-inbox { flex: none; }
#fleet-login { flex: none; display: inline-flex; align-items: center; gap: var(--space-1); white-space: nowrap; }
/* 계정 정보는 계정 단추 아래 펼침 칸의 한 묶음이다. 떠 있는 패널이 아니라 흐름 안에 있다. */
.fleet-account-panel { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); min-width: 0; overflow-wrap: anywhere; }
.fleet-account-panel .password-login-who { flex-wrap: wrap; }
.fleet-account-panel [data-login="principal"] { display: none; }
.fleet-header-safety { grid-area: safety; justify-self: end; }
#topbar-more { display: inline-flex; flex: 0 1 auto; min-width: var(--target-secondary); max-width: 100%; }
.header-status-item { display: inline-flex; align-items: center; gap: var(--space-1); min-width: 0; }
```

로 바꾼다. `test_chrome_layout.py`와 `test_site_map_api.py`가 `.fleet-header-actions { grid-area: actions;`와 `.fleet-header-safety { grid-area: safety; justify-self: end; }`를 글자 그대로 찾으므로 두 규칙의 앞머리를 바꾸지 않는다.

- [ ] **Step 6: node 단위 시험이 그대로 통과하는지 읽어 본다**

`fleet-header.test.mjs`의 "message counts update one summary value..." 시험은 고치지 않는다. `showInboxCount(4)` 뒤 `header-unread`의 글이 `"4"`, `hidden`이 `false`, `showInboxCount(0)` 뒤 `hidden`이 `true`라는 단언은 새 코드에서도 참이다. "a session shows its Korean role..."의 `nodes["fleet-account"].hidden` 단언도 그대로다.

- [ ] **Step 7: `test_fleet_header_browser.py`를 같은 커밋에서 고친다**

`test_four_documents_draw_one_header_and_one_estop`의 크기 반복문에서:

```python
                assert page.locator('ui-topbar [data-header-region]').count() == 4
                for region in ("identity", "status", "actions", "safety"):
                    expect(page.locator(f'[data-header-region="{region}"]')).to_be_visible()
                assert page.locator('[data-header-region="actions"] #fleet-theme').count() == 1
                assert page.locator('#topbar-more ui-button').count() == 0
                expect(page.locator('#topbar-more #development-badge')).to_have_text("개발")
                expect(page.locator('#topbar-more')).to_have_attribute("aria-label", re.compile("상태 센터"))
                for value in page.locator('#topbar-more ui-tag').all():
                    expect(value).to_have_css("border-width", "0px")
                    expect(value).to_have_css("background-color", "rgba(0, 0, 0, 0)")
                assert page.locator('[data-header-region="safety"] #estop').count() == 1
                expect(page.locator('#topbar-extra')).not_to_be_visible()
                theme = page.locator("#fleet-theme")
                expect(theme).to_be_enabled()
                preference = page.evaluate("RosyTheme.get()")
                for _ in range(3):
                    theme.click()
                assert page.evaluate("RosyTheme.get()") == preference
```

을

```python
                assert page.locator('ui-topbar [data-header-region]').count() == 4
                for region in ("identity", "actions", "safety"):
                    expect(page.locator(f'[data-header-region="{region}"]')).to_be_visible()
                if width >= 768:  # 48rem 아래의 연결 자리는 평상시 비어 있다
                    expect(page.locator('[data-header-region="status"]')).to_be_visible()
                assert page.locator('[data-header-region="status"] ui-button').count() == 0
                assert page.locator('[data-header-region="actions"] > #fleet-inbox').count() == 1
                assert page.locator('[data-header-region="actions"] > #topbar-more').count() == 1
                assert page.locator('#topbar-more ui-button').count() == 0
                expect(page.locator('#topbar-more #user-role')).to_have_text("운영자")
                expect(page.locator('#topbar-more #user-role')).to_be_visible()
                expect(page.locator('#topbar-more #development-badge')).to_have_text("개발")
                expect(page.locator('#topbar-more')).to_have_attribute(
                    "aria-label", re.compile("계정과 접속.*운영자.*개발 연결 모드"))
                for value in page.locator('#topbar-more ui-tag').all():
                    expect(value).to_have_css("border-width", "0px")
                    expect(value).to_have_css("background-color", "rgba(0, 0, 0, 0)")
                assert page.locator('[data-header-region="safety"] #estop').count() == 1
                more = page.locator("#topbar-more")
                expect(page.locator('#topbar-extra')).not_to_be_visible()
                expect(page.locator("#fleet-theme")).to_be_hidden()  # 화면 표시는 계정 단추 아래에 있다
                more.click()
                expect(more).to_have_attribute("aria-expanded", "true")
                theme = page.locator("#topbar-extra #fleet-theme")
                expect(theme).to_be_visible()
                expect(theme).to_be_enabled()
                assert theme.locator(".ui-icon-label").count() == 0
                expect(theme).to_have_attribute("data-ui-tooltip", re.compile("테마:"))
                assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, (name, width)
                preference = page.evaluate("RosyTheme.get()")
                for _ in range(3):
                    theme.click()
                assert page.evaluate("RosyTheme.get()") == preference
                theme.focus()
                page.keyboard.press("Escape")
                expect(more).to_be_focused()
                expect(more).to_have_attribute("aria-expanded", "false")
```

로 바꾼다. 같은 반복문에서:

```python
                more = page.locator("#fleet-theme")
                if more.is_visible():
                    assert more.locator(".ui-icon-label").count() == 0
                    expect(more).to_have_attribute("data-ui-tooltip", re.compile("테마:"))
                inbox_text = page.locator("#fleet-inbox").text_content().strip()
```

을

```python
                expect(page.locator("#fleet-inbox")).to_be_visible()
                inbox_text = page.locator("#fleet-inbox").text_content().strip()
```

로,

```python
                inbox = page.locator("#fleet-theme").bounding_box()
```

을

```python
                inbox = page.locator("#fleet-inbox").bounding_box()
```

로,

```python
                if width <= 390:
                    assert abs(inbox["x"] + inbox["width"] - (x + w)) <= 1
                    more = page.locator("#topbar-more")
                    expect(more).to_be_visible()
                    more.click()
                    expect(more).to_have_attribute("aria-expanded", "true")
                    expect(page.locator("#fleet-inbox")).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, (name, width)
                    page.locator("#fleet-inbox").focus()
                    page.keyboard.press("Escape")
                    expect(more).to_be_focused()
                    expect(more).to_have_attribute("aria-expanded", "false")
```

을

```python
                expect(more).to_be_visible()
```

로 바꾼다(열기·넘침·Escape는 위에서 모든 폭에 대해 이미 쟀다). 반복문 밖의:

```python
            page.locator("#topbar-more").click()
            page.locator("#fleet-inbox").click()
```

을

```python
            page.locator("#fleet-inbox").click()
```

로 바꾼다. `test_estop_locks_only_after_the_session_is_refused`는 고치지 않는다. `#user-role`의 글, `open_token_access`, `#console-token`, `#token-save`가 그대로다.

- [ ] **Step 8: 다른 브라우저 시험 여섯 파일을 같은 커밋에서 고친다**

`operations/fleet/test/test_development_console_browser.py`:

```python
                    # D-668: the role is detail behind the status center; the development warning
                    # stays visible inside the closed status center at every width.
                    expect(page.locator(identity)).to_be_hidden()
```

을

```python
                    # D-741 3: the account button carries the role; the development warning stays
                    # visible inside the closed account button at every width (D-473).
                    expect(page.locator(identity)).to_be_visible()
```

로,

```python
                    status = page.locator('[data-header-region="status"]').bounding_box()
                    assert status["y"] <= badge["y"] and badge["y"] + badge["height"] <= status["y"] + status["height"]
```

을

```python
                    actions = page.locator('[data-header-region="actions"]').bounding_box()
                    assert actions["y"] <= badge["y"] and badge["y"] + badge["height"] <= actions["y"] + actions["height"]
```

로 바꾼다.

`operations/fleet/test/test_password_login_browser.py`:

```python
                page.locator('#fleet-account > summary').click()
                expect(page.locator('#fleet-account-identity')).to_contain_text('alice')
                page.locator('#fleet-account > summary').click()
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')") is None
```

을

```python
                page.locator('#topbar-more').click()
                expect(page.locator('#fleet-account-identity')).to_contain_text('alice')
                page.locator('#topbar-more').click()
                assert page.evaluate("sessionStorage.getItem('rosy-console-token')") is None
```

로,

```python
                        # D-668: the status region is the one status-center entry and holds no other control.
                        assert tab.locator('[data-header-region="status"] ui-button:not(#topbar-more)').count() == 0
                        assert tab.locator('[data-header-region="status"] #topbar-more').count() == 1
                        height = tab.locator("ui-topbar").bounding_box()["height"]
                        tab.locator('#fleet-account > summary').click()
                        expect(principal).to_be_visible()
                        expect(tab.locator("#fleet-account [data-login=logout]")).to_be_visible()
                        assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        tab.locator('#fleet-account > summary').click()
                        assert tab.locator("ui-topbar").bounding_box()["height"] == height
```

을

```python
                        # D-741 3: the link seat holds no control; the account button sits with the alerts button.
                        assert tab.locator('[data-header-region="status"] ui-button').count() == 0
                        assert tab.locator('[data-header-region="actions"] > #topbar-more').count() == 1
                        height = tab.locator("ui-topbar").bounding_box()["height"]
                        toggle.click()
                        expect(principal).to_be_visible()
                        expect(tab.locator("#fleet-account [data-login=logout]")).to_be_visible()
                        assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        toggle.click()
                        assert tab.locator("ui-topbar").bounding_box()["height"] == height
```

로,

```python
                page.locator('#fleet-account > summary').click()
                logout = page.locator("#fleet-account [data-login=logout]")
```

을

```python
                page.locator('#topbar-more').click()
                logout = page.locator("#fleet-account [data-login=logout]")
```

로 바꾼다.

`operations/fleet/test/test_fleet_account_browser.py`에서 아래 두 줄 묶음이 세 번 나온다(`test_profile_entry_preserves_work_context_and_verifies_own_name`과 `test_logout_failure_does_not_claim_the_session_ended`는 `page`, `test_account_entry_returns_to_each_document_without_commands`는 `login`):

```python
    expect(page.locator('#fleet-account')).to_be_visible()
    page.locator('#fleet-account > summary').click()
```

세 곳 모두 같은 변수 이름으로 아래처럼 바꾼다(`login`인 곳은 `page`를 `login`으로):

```python
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.locator('#topbar-more').click()
    expect(page.locator('#fleet-account')).to_be_visible()
```

역할 글을 먼저 기다리는 이유: 세션이 확인되기 전에 누르면 접속 거절로 저절로 열린 칸을 닫게 된다. `test_empty_cell_token_uses_cookie_despite_stale_storage`에서는:

```python
    expect(page.locator('#fleet-account')).to_be_visible()
    page.evaluate("sessionStorage.setItem('rosy-console-token', 'stale-token')")
```

을

```python
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    page.evaluate("sessionStorage.setItem('rosy-console-token', 'stale-token')")
```

로,

```python
    page.locator('#fleet-account > summary').click()
    expect(page.locator('[data-login=logout]')).to_be_visible()
```

을

```python
    expect(page.locator('#fleet-account')).to_be_visible()  # open_token_access가 계정 단추를 이미 열었다
    expect(page.locator('[data-login=logout]')).to_be_visible()
```

로 바꾼다. 같은 파일의 `expect(tab.locator('#fleet-account')).to_be_hidden()`과 로그아웃 실패 뒤의 `expect(page.locator('#fleet-account')).to_be_visible()`는 그대로다.

`operations/fleet/test/test_site_map_browser.py`:

```python
    expect(page.locator("ui-brand")).to_contain_text("Rosy Fleet")
```

을

```python
    expect(page.locator("ui-brand")).to_contain_text("Fleet")
    expect(page.locator("ui-brand a")).to_have_attribute("aria-label", "Rosy Fleet 관제 홈")
```

로 바꾼다.

`shared/web/test/test_theme_browser.py`의 `test_the_fleet_topbar_selector_switches_the_theme_live`에서 `button.click()` 세 곳을 전부 `button.dispatch_event("click")`로 바꾼다. 그 단추는 이제 닫힌 계정 칸 안에 있고, 이 시험이 재는 것은 테마 전환이지 칸 열기가 아니다(칸 열기는 `test_fleet_header_browser.py`가 잰다).

`test/test_fleet_console_browser.py`의 `test_mobile_console_has_no_horizontal_overflow`:

```python
          inbox: document.querySelector('#fleet-theme').getBoundingClientRect().toJSON(),
```

을

```python
          inbox: document.querySelector('#fleet-inbox').getBoundingClientRect().toJSON(),
```

로, `test_compact_header_budget_keeps_the_stop_in_view`:

```python
    assert folded["expanded"] == "false" and not folded["token"] and folded["theme"] and not folded["role"], folded
```

을

```python
    assert folded["expanded"] == "false" and not folded["token"] and not folded["theme"] and folded["role"], folded
```

로, `test_wide_header_keeps_every_item_on_one_line`:

```python
            # D-668: 테마는 접히지 않는 버튼 하나다. 접속 상세는 상태 센터 뒤에 접혀 있다.
            assert page.locator('#fleet-theme').is_visible()
```

을

```python
            # D-741 3: 화면 표시와 접속 상세는 계정 단추 아래에 접혀 있다.
            assert page.locator('#fleet-theme').is_hidden()
```

로 바꾼다.

- [ ] **Step 9: 커밋하고 원격에서 통과를 확인한다**

```bash
git add operations/ui/console/index.html operations/ui/console/install.html operations/ui/console/site-map.html operations/ui/console/cell/cell.html operations/ui/console/shared/fleet-header.js operations/ui/console/shared/fleet-header.css operations/ui/console/shared/password-login.js operations/fleet/test/test_fleet_header_browser.py operations/fleet/test/test_development_console_browser.py operations/fleet/test/test_password_login_browser.py operations/fleet/test/test_fleet_account_browser.py operations/fleet/test/test_site_map_browser.py shared/web/test/test_theme_browser.py test/test_fleet_console_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): alerts button and a role-named account button own the app bar's right side (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_server_app.py operations/fleet/test/test_document_imports.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t3-fleet-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t3-fleet-$(basename "$f")"; done
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test test/architecture test/test_remaining_platform_installed.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t3-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t3-web-$(basename "$f")"; done
```

Expected: `test_fleet_header.py` 5 passed, node 단위 시험 통과(또는 `SKIPPED`), 로그마다 `NEW` 0. 같이 봐야 하는 기존 시험:

| 시험 | 그대로 통과해야 하는 이유 | 실패하면 |
|---|---|---|
| `shared/web/test/test_theme_choices.py` | `data-theme-cycle=""`가 문서에 한 번, `:not([data-theme-cycle])`가 `console.js`·`install.js`에 그대로 | Step 3의 `#fleet-theme` 줄을 본다 |
| `shared/web/test/test_action_icon_contract.py` | `notification`, `theme-dark`, `>비상 정지</span>`, 래치 부제가 그대로 | Step 3의 글을 본다 |
| `operations/fleet/test/test_grammar_separation.py` | 시트 링크 목록을 바꾸지 않았다 | 어느 HTML의 `<link>`를 건드렸는지 본다 |
| `shared/web/test/test_shared_controls.py` | 표면 시트가 `ui-*` 조작에 색·테두리·글꼴을 주지 않았다 | Step 5의 규칙에서 그 속성을 뺀다 |
| `test/architecture/test_module_structure.py` | 줄 수가 상한 안이다 | 실패 문구의 숫자로 판정을 다시 적는다 |

---

### Task 4: 레일 이름

검증: **원격 pytest (소스)** — `test_doc_tabs.py`, `test_site_map_api.py`. **CI 브라우저** — `test_fleet_header_browser.py`. 탐색의 순서, 주소, `/console/cell`은 바꾸지 않는다.

**Files:**
- Modify: 네 HTML의 `nav.doc-tabs`, `operations/ui/console/shared/doc-tabs.css`
- Test: `operations/fleet/test/test_doc_tabs.py`, `test_site_map_api.py`, `test_fleet_header_browser.py`

- [ ] **Step 1: 소스 시험을 먼저 고친다**

`operations/fleet/test/test_doc_tabs.py`에서 `ICONS = [...]` 줄 다음에:

```python
# D-741 2·6: 아이콘 아래에 짧은 이름을 적는다. 긴 이름은 접근 이름에 남고 보이는 글을 품는다(WCAG 2.5.3).
LABELS = ["관제", "설치", "지도", "작업", "Cell"]
NAMES = [None, "설치·보정", "현장 지도", None, None]
```

`_tabs`에서:

```python
    links = [dict(re.findall(r'([\w-]+)="([^"]*)"', attributes))
             for attributes in re.findall(r'<a\b([^>]*)>', match.group(1))]
```

을

```python
    links = [dict(re.findall(r'([\w-]+)="([^"]*)"', attributes), text=text)
             for attributes, text in re.findall(r'<a\b([^>]*)>(.*?)</a>', match.group(1))]
```

로, `test_every_document_has_the_same_tabs_and_marks_itself`에서:

```python
        assert all("data-icon-only" in link for link in links), name
```

을

```python
        assert all("data-icon-only" not in link for link in links), name
        assert [link["text"] for link in links] == LABELS, name
        assert [link.get("aria-label") for link in links] == NAMES, name
        assert all(label in (link.get("aria-label") or label) for link, label in zip(links, LABELS)), name
```

로 바꾼다.

`operations/fleet/test/test_site_map_api.py`의 `test_field_view_review_fixes_are_served`에서:

```python
    # D-501/D-641: the single Cell icon keeps its accessible label.
    import re
    assert re.findall(r'<a href="/console/cell" data-action-icon="cell" data-icon-only="">(.*?)</a>', page) == ["Cell"]
```

을

```python
    # D-741 6: the rail shows the name under the icon.
    import re
    assert re.findall(r'<a href="/console/cell" data-action-icon="cell">(.*?)</a>', page) == ["Cell"]
```

로 바꾼다.

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py
git commit -m "test(fleet): pin short names under the rail icons (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t4-red.txt
```

Expected: `test_every_document_has_the_same_tabs_and_marks_itself`와 `test_field_view_review_fixes_are_served`가 실패한다.

- [ ] **Step 3: 네 문서의 탐색 글을 바꾼다**

네 HTML의 `<nav class="doc-tabs" aria-label="Rosy Fleet 문서">` 안 다섯 줄을 아래로 바꾼다. `aria-current="page"`는 지금처럼 그 문서의 링크 하나에만 둔다(`index.html`은 `/console`, `install.html`은 `/console/install`, `site-map.html`은 `/console/site-map`, `cell/cell.html`은 `/console/cell`). 아래는 `index.html`의 글이다.

```html
    <a href="/console" data-action-icon="fleet" aria-current="page">관제</a>
    <a href="/console/install" data-action-icon="install" aria-label="설치·보정">설치</a>
    <a href="/console/site-map" data-action-icon="map" aria-label="현장 지도">지도</a>
    <a href="/console?view=work" data-action-icon="history">작업</a>
    <a href="/console/cell" data-action-icon="cell">Cell</a>
```

다른 세 문서는 `aria-current="page"`의 자리만 다르다. 예: `install.html`의 둘째 줄은 `<a href="/console/install" data-action-icon="install" aria-label="설치·보정" aria-current="page">설치</a>`이고 첫 줄에는 `aria-current`가 없다. `data-icon-only`가 없으면 `actionIcon()`이 글을 보이는 `.ui-icon-label`로 두고 툴팁을 달지 않는다(`shared/web/ui.js`의 `actionIcon`).

- [ ] **Step 4: 레일 시트를 고친다**

`operations/ui/console/shared/doc-tabs.css`에서:

```css
.fleet-body { display: grid; grid-template-columns: max-content minmax(0, 1fr); min-width: 0; min-height: 0; }
```

을

```css
.fleet-body { display: grid; grid-template-columns: var(--rail-track) minmax(0, 1fr); min-width: 0; min-height: 0; }
```

로,

```css
.fleet-body > .doc-tabs { flex-direction: column; align-items: stretch; overflow-x: visible; padding: var(--space-3); border-bottom: 0; border-right: 1px solid var(--border-subtle); }
.fleet-body > .doc-tabs a { gap: var(--gap-button-content); border-bottom: 0; border-inline-start: 2px solid transparent; }
```

을

```css
/* D-741 2·6 — 탐색 레일: 아이콘 아래에 짧은 이름. 치수는 공용 자리 토큰(--rail-track 72px)을 쓴다. */
.fleet-body > .doc-tabs { flex-direction: column; align-items: center; gap: var(--gap-rail); overflow-x: visible; padding: var(--inset-rail); border-bottom: 0; border-right: 1px solid var(--border-subtle); }
.fleet-body > .doc-tabs a { flex-direction: column; gap: var(--gap-rail); inline-size: 3.5rem; min-block-size: 3.5rem; padding: 0; border-bottom: 0; border-inline-start: 2px solid transparent; font-size: var(--text-micro); }
```

로 바꾼다. 마지막 `@media (width < 64rem)` 블록에서:

```css
  .fleet-body > .doc-tabs { flex-direction: row; overflow-x: auto; padding: 0 var(--space-3); border-right: 0; border-bottom: 1px solid var(--border-subtle); }
```

을

```css
  .fleet-body > .doc-tabs { flex-direction: row; justify-content: flex-start; overflow-x: auto; padding: var(--inset-rail); border-right: 0; border-bottom: 1px solid var(--border-subtle); }
```

로 바꾼다. 좁은 폭에서도 항목은 아이콘 위·이름 아래의 56px 칸이다. 320px에서 다섯 칸은 5 × 56 + 4 × 4 + 16 = 312px라 가로로 밀지 않고 다 보인다. 현재 위치 표식(먹색 선과 `--surface-raised`)은 그대로다(열린 결정 5).

- [ ] **Step 5: 브라우저 시험을 같은 커밋에서 고친다**

`operations/fleet/test/test_fleet_header_browser.py`에서:

```python
                for link in page.locator(".doc-tabs a").all():
                    box = link.bounding_box()
                    assert box["width"] == box["height"] == 48, (name, width, box)
                    assert link.locator(".ui-icon-label").bounding_box()["width"] <= 1
                    expect(link).to_have_attribute("data-ui-tooltip", link.text_content().strip())
```

을

```python
                labels = []
                for link in page.locator(".doc-tabs a").all():
                    box = link.bounding_box()
                    assert box["width"] == box["height"] == 56, (name, width, box)
                    label, icon = link.locator(".ui-icon-label"), link.locator(".ui-icon").bounding_box()
                    expect(label).to_be_visible()
                    assert label.bounding_box()["y"] >= icon["y"] + icon["height"] - 1, (name, width)
                    assert link.get_attribute("data-ui-tooltip") is None, (name, width)
                    labels.append(label.text_content().strip())
                assert labels == ["관제", "설치", "지도", "작업", "Cell"], (name, width)
                rail = page.locator(".doc-tabs")
                expect(rail.get_by_role("link", name="설치·보정", exact=True)).to_have_count(1)
                expect(rail.get_by_role("link", name="현장 지도", exact=True)).to_have_count(1)
```

로 바꾼다. 그 아래 `.context-tabs [role=tab]` 반복문(오른쪽 칸의 탭)은 고치지 않는다. 그 탭은 아이콘 단독으로 남는다.

- [ ] **Step 6: 커밋하고 원격에서 통과를 확인한다**

```bash
git add operations/ui/console/index.html operations/ui/console/install.html operations/ui/console/site-map.html operations/ui/console/cell/cell.html operations/ui/console/shared/doc-tabs.css operations/fleet/test/test_fleet_header_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): write a short name under each rail icon (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_server_app.py operations/fleet/test/test_document_imports.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t4-fleet-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t4-fleet-$(basename "$f")"; done
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test test/architecture
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t4-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t4-web-$(basename "$f")"; done
```

Expected: `test_doc_tabs.py` 2 passed, 로그마다 `NEW` 0. `test/test_fleet_console_browser.py`의 탐색 단언(`get_by_role("navigation", name="Rosy Fleet 문서")`, `.doc-tabs a[href="/console/cell"]`가 320px에서 보임)과 `test_work_overview_browser.py`의 `aria-current` 단언은 고치지 않아도 참이다.

---

### Task 5: 한 줄 접힘을 칸 질의로, 중단점 등록

**칸이 되는 요소:** `ui-shell.fleet-shell` 하나다. 머리(`ui-topbar`와 그 자식)와 레일(`.fleet-body`와 그 자식)이 모두 그 자손이고 머리는 셸의 전체 폭이므로 칸 하나가 둘 다에 답한다. `.fleet-header`는 칸으로 만들지 않는다.

**지우는 `@media` 규칙:** `shared/fleet-header.css`의 `@media (width < 64rem)`(81–84줄)과 `@media (width < 48rem)`(85–98줄), `shared/doc-tabs.css`의 `@media (width < 64rem)` 두 블록(31–33줄, 59–64줄). 넷 다 `@container`로 바뀐다. `shared/doc-tabs.css`의 `@media (width >= 64rem) and (height >= 40rem)`은 남긴다. 높이 조건은 칸 질의로 바꿀 수 없고 세 단과 §6.5의 조합이라 등재가 필요 없다.

**`surfaces.yaml`:** `console`의 `breakpoints`에서 48rem 항목을 지운다(쓰는 `@media`가 없어지면 "쓰는 @media가 없다"로 실패한다). 48rem은 `console`의 `container_breakpoints`에 이유와 함께 올린다. 30rem과 64rem은 세 단 값이라 올리지 않는다.

검증: **원격 pytest (소스)** — `test_chrome_layout.py`, `test_fleet_header.py`, `test_responsive_tiers.py`, `test_surface_registry.py`. **CI 브라우저** — `test_fleet_header_browser.py`. **자동 증거 없음** — `test/test_fleet_console_browser.py`.

**Files:**
- Modify: `operations/ui/console/shared/fleet-header.css`, `shared/doc-tabs.css`, `shared/web/surfaces.yaml`
- Test: `shared/web/test/test_chrome_layout.py`, `operations/fleet/test/test_fleet_header.py`, `test_fleet_header_browser.py`, `test/test_fleet_console_browser.py`

- [ ] **Step 1: 소스 시험을 먼저 고친다**

`shared/web/test/test_chrome_layout.py`의 `test_header_keeps_one_recipe_of_named_areas`에서:

```python
    # D-501/D-632: document links own their tab row; inbox and stop stay outside connection settings.
    assert '"identity status actions safety"' in fleet
    assert '"identity safety" "status actions"' in fleet
    assert ".fleet-header-actions { grid-area: actions;" in fleet
```

을

```python
    # D-741 3·5: the Fleet app bar is one row at every width; it folds by its shell container.
    assert '"identity status actions safety"' in fleet
    assert '"identity safety" "status actions"' not in fleet
    assert fleet.count("grid-template-areas") == 1
    assert ".fleet-header-actions { grid-area: actions;" in fleet
```

로 바꾼다.

`operations/fleet/test/test_fleet_header.py` 끝에 붙인다:

```python
def test_app_bar_folds_by_the_shell_container_not_the_viewport():
    """D-741 5 / D-359 §6.3 — 접힘은 셸 칸의 폭에 답한다. 앱 바 높이는 공용 자리 토큰이다."""
    header_sheet = (WEB / "shared/fleet-header.css").read_text(encoding="utf-8")
    tabs_sheet = (WEB / "shared/doc-tabs.css").read_text(encoding="utf-8")
    assert "@media" not in header_sheet
    assert set(re.findall(r"@container \(([^)]+)\)", header_sheet)) == {
        "width < 64rem", "width < 48rem", "width < 30rem"}
    assert "container-type" not in header_sheet, "칸은 셸 하나다"
    assert ".fleet-shell { container-type: inline-size;" in tabs_sheet
    assert tabs_sheet.count("container-type") == 1
    assert re.findall(r"@media ([^{]+?)\s*\{", tabs_sheet) == ["(width >= 64rem) and (height >= 40rem)"]
    assert "min-height: var(--appbar-height);" in header_sheet
    assert "var(--rail-track)" in tabs_sheet
```

- [ ] **Step 2: 커밋하고 원격에서 실패를 확인한다**

```bash
git add shared/web/test/test_chrome_layout.py operations/fleet/test/test_fleet_header.py
git commit -m "test(fleet): pin a one-row app bar that folds by its shell container (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t5-red-fleet.txt
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test/test_chrome_layout.py
cp X:/DevTemp/fleet-bar/run-1.txt X:/DevTemp/fleet-bar/t5-red-web.txt
```

Expected: `test_app_bar_folds_by_the_shell_container_not_the_viewport`가 `assert "@media" not in header_sheet`로, `test_header_keeps_one_recipe_of_named_areas`가 두 줄 격자 글로 실패한다.

- [ ] **Step 3: 머리 시트의 격자와 접힘을 바꾼다**

`operations/ui/console/shared/fleet-header.css`에서:

```css
/* D-658: four roles own the header; connection details have their own fold. */
ui-topbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  grid-template-areas: "identity status actions safety";
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-2) var(--space-3);
}
```

을

```css
/* D-741 3·5 — 앱 바는 모든 폭에서 한 줄이다: 맥락 | 연결 | 알림·나 | 정지. 계정 상세만 아래 줄로 펼친다.
   연결 칸이 남는 폭을 받고, 모자라면 연결 칸이 먼저 비고 그 다음 계정 단추의 역할 이름이 준다. */
ui-topbar {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(0, auto) auto;
  grid-template-areas: "identity status actions safety";
  align-items: center;
  gap: var(--space-4);
  min-height: var(--appbar-height);
  padding: var(--space-2) var(--space-3);
}
```

로 바꾼다. 같은 파일 끝의 두 `@media` 블록:

```css
@media (width < 64rem) {
  ui-topbar ui-brand small { display: none; }
  #estop small { display: none; }
}
@media (width < 48rem) {
  ui-topbar {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: "identity safety" "status actions";
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
  }
  .fleet-header-identity { container-type: inline-size; }
  ui-topbar ui-brand b { line-height: var(--leading-flat); }
  .fleet-link-status { justify-content: flex-start; align-content: center; min-height: 0; }
  .fleet-header-actions { justify-content: flex-end; gap: 0; }
  /* 좁은 폭의 연결 자리는 평상시 조용하다. 연결 대기·지연·연결 끊김은 보인다. */
  #clock, #link-state[data-link="live"] { display: none; }
  #estop { gap: var(--space-1); }
  #estop .ui-icon { width: var(--space-5); height: var(--space-5); }
}
```

을

```css
/* 접힘은 뷰포트가 아니라 셸 칸(.fleet-shell, doc-tabs.css)의 폭에 답한다(D-359 §6.3). 48rem은 surfaces.yaml에 있다. */
@container (width < 64rem) {
  ui-topbar ui-brand small { display: none; }
  #estop small { display: none; }
}
@container (width < 48rem) {
  ui-topbar { gap: var(--space-2); padding: var(--space-1) var(--space-2); }
  ui-topbar ui-brand b { line-height: var(--leading-flat); }
  /* 좁은 폭의 연결 자리는 평상시 조용하다. 연결 대기·지연·연결 끊김은 보인다. */
  #clock, #link-state[data-link="live"] { display: none; }
  #estop { gap: var(--space-1); }
  #estop .ui-icon { width: var(--space-5); height: var(--space-5); }
}
@container (width < 30rem) {
  ui-topbar { gap: var(--space-1); }
  /* R 심볼만 남긴다. 링크의 접근 이름(Rosy Fleet 관제 홈)은 그대로다. */
  .fleet-wordmark { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  #fleet-login .ui-icon { display: none; }
  /* 로그인 전에는 읽을 알림이 없다. 로그인 글과 계정 단추가 그 폭을 쓴다. */
  .fleet-header-actions:has(#fleet-login:not([hidden])) #fleet-inbox { display: none; }
  #fleet-inbox { gap: var(--space-1); }
  #estop .ui-icon { width: var(--space-4); height: var(--space-4); }
}
```

로 바꾼다. 새 규칙은 색·테두리·글꼴을 정하지 않고 사용자 정의 속성을 선언하지 않는다. 비상 정지의 글자 크기(14px)와 좌우 여백(12px)은 공용 `ui-button[kind="irreversible"]`의 것이고 여기서 건드리지 않는다.

- [ ] **Step 4: 레일 시트의 칸과 접힘을 바꾼다**

`operations/ui/console/shared/doc-tabs.css`에서:

```css
.fleet-shell { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 100dvh; }
```

을

```css
.fleet-shell { container-type: inline-size; display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 100dvh; }
```

로 바꾼다. 같은 파일에서 `@media (width < 64rem) {`가 두 번 나온다(`.doc-tabs { padding-inline: ... }`을 감싼 것과 파일 끝의 것). 두 줄 모두 `@container (width < 64rem) {`로 바꾼다. 블록 안의 규칙은 Task 4가 남긴 그대로 둔다. `@media (width >= 64rem) and (height >= 40rem) {`는 바꾸지 않는다.

- [ ] **Step 5: 중단점 등록을 옮긴다**

`shared/web/surfaces.yaml`의 `- id: console` 행에서:

```yaml
    breakpoints:
      - value: 48rem
        reason: D-658의 네 헤더 영역을 제품·비상정지 첫 줄과 상태·조작 둘째 줄로 배치한다. 접속 상세는 화면 폭에 관계없이 별도 펼침 영역이다.
      - value: 110rem
```

을

```yaml
    container_breakpoints:
      - value: 48rem
        reason: 한 줄 앱 바가 시계와 평상 연결 글(실시간)을 접는 셸 칸 폭 — 그 아래에서는 맥락·알림·계정·비상 정지가 한 줄에 서려면 연결 자리가 비어야 한다. 공용 셸의 본문 접힘과 같은 값이다(D-741 5항)
    breakpoints:
      - value: 110rem
```

로 바꾼다(110rem 항목의 `reason` 줄은 그대로다).

- [ ] **Step 6: 브라우저 시험을 같은 커밋에서 고친다**

`operations/fleet/test/test_fleet_header_browser.py`에서:

```python
                if width >= 1440:
                    assert fact["rows"] == 1, (name, width, fact)
                elif width >= 1024:
                    assert fact["rows"] <= 2, (name, width, fact)
                else:
                    assert fact["header"] <= 0.2 * height, (name, width, fact)
```

을

```python
                # D-741 5: 앱 바는 320px까지 한 줄이고 높이는 --appbar-height(64px)다.
                assert fact["rows"] == 1, (name, width, fact)
                assert fact["header"] <= 64 + 1, (name, width, fact)
                assert fact["header"] <= 0.2 * height, (name, width, fact)
```

로 바꾼다. 같은 파일 맨 위 `PROBE` 주석의 `# Header rows: visible topbar children grouped by vertical overlap.` 줄은 그대로 둔다(닫힌 `#topbar-extra`는 보이지 않아 줄로 세지 않는다).

`test/test_fleet_console_browser.py`의 `test_mobile_console_has_no_horizontal_overflow`에서:

```python
    assert layout["headerRows"] <= 2, layout  # 48rem 아래의 두 줄은 한 줄 접힘 Task에서 한 줄이 된다.
```

을

```python
    assert layout["headerRows"] == 1, layout  # D-741 5: one row down to 320px.
```

로 바꾼다. 같은 함수의 `layout["stopScopeHidden"]`, `layout["stopVerb"] == "비상 정지"`, `layout["stopAccessibleName"] is None` 단언은 그대로 참이다(래치 부제가 64rem 아래에서 접히는 동작을 바꾸지 않았다).

- [ ] **Step 7: 커밋하고 원격에서 통과를 확인한다**

```bash
git add operations/ui/console/shared/fleet-header.css operations/ui/console/shared/doc-tabs.css shared/web/surfaces.yaml operations/fleet/test/test_fleet_header_browser.py test/test_fleet_console_browser.py
git diff --cached --name-only
git commit -m "feat(fleet): keep the app bar on one row and fold it by the shell container (D-741)"
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- operations/fleet/test/test_fleet_header.py operations/fleet/test/test_doc_tabs.py operations/fleet/test/test_site_map_api.py operations/fleet/test/test_grammar_separation.py operations/fleet/test/test_server_app.py operations/fleet/test/test_document_imports.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t5-fleet-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t5-fleet-$(basename "$f")"; done
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- shared/web/test test/architecture test/test_remaining_platform_installed.py
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t5-web-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t5-web-$(basename "$f")"; done
```

Expected: `test_fleet_header.py` 6 passed, `test_chrome_layout.py` 2 passed, 로그마다 `NEW` 0. 같이 봐야 하는 기존 시험:

| 시험 | 실패 문구가 말하는 것 | 할 일 |
|---|---|---|
| `test_responsive_tiers.py::test_breakpoint_allowlists_are_well_formed_and_used` | `(console) 48rem를 쓰는 @media가 없다` | Step 5에서 48rem을 `breakpoints`에서 뺐는지 본다 |
| 같은 시험 | `(console) container_breakpoints 48rem를 쓰는 @container가 없다` | Step 3의 조건이 정확히 `(width < 48rem)`인지 본다 |
| `test_responsive_tiers.py::test_every_container_query_uses_a_tier_or_a_listed_value` | `fleet-header.css ... 48rem가 세 단도 아니고 container_breakpoints에도 없다` | Step 5의 들여쓰기가 `breakpoints`와 같은지 본다 |
| `test_responsive_tiers.py::test_the_scan_reads_css_files_and_inline_styles` | `console에서 @media 크기 조건을 하나도 읽지 못했다` | 일어나지 않는다. `shared/styles.css`, `site-map.css`, `cell/cell.css`에 `@media`가 남아 있다 |
| `test_site_map_api.py::test_field_view_review_fixes_are_served` | `"identity status actions safety"` 또는 `.fleet-header-safety { grid-area: safety; justify-self: end; }`가 없다 | Step 3이 그 두 글을 건드리지 않았는지 본다 |
| `test_responsive_tiers.py::test_surface_style_braces_balance` | 괄호 짝이 안 맞는다 | Step 3·4에서 지운 블록의 `}`를 센다 |

---

### Task 6: 문서와 증거

**Files:**
- Modify: `DESIGN.md`, `operations/ui/console/AGENTS.md`, `operations/ui/console/logs.md`, `operations/fleet/logs.md`, `shared/web/logs.md`
- Create: `docs/validation/fleet-app-bar-<이 Task를 하는 날 YYYY-MM-DD>.md`

- [ ] **Step 1: `DESIGN.md`를 고친다**

세 곳이다. 각각 문단 하나를 통째로 바꾼다.

"`Fleet 헤더의 테마는 우측 버튼 하나로`"로 시작하는 문단(Overview 아래, D-668 링크로 끝난다)을:

```markdown
Fleet 앱 바의 오른쪽은 연결·알림·나·정지 순서다. 연결은 `실시간`·`지연`·`연결 끊김` 가운데 하나와 로컬 시각이고 브라우저와 Fleet 사이의 것이다. 알림 단추는 종과 읽지 않은 수다. 계정 단추는 역할 이름을 달고, 그 아래에 계정·화면 표시·토큰 접속이 있다. 개발 연결 표지는 닫힌 계정 단추에서도 보인다. 로봇 연결 수는 앱 바가 아니라 관제 화면의 지도 머리에 있다. 알림 열기·메시지 읽음·개입 해소는 별개다([D-741](docs/adr/D-741-unified-app-shell-seats.md) 3항, D-668의 테마 순환과 인라인 값 표현은 그대로 쓴다).
```

로 바꾼다. `### 상단바 — <ui-topbar> (D-466)` 아래의 "`- Fleet은 D-658의 제품·현장 / 연결·권한 / 알림·접속 / 비상정지 네 영역을 사용한다.`"로 시작하는 항목을:

```markdown
- Fleet은 맥락 / 연결 / 알림·나 / 정지 네 영역의 한 줄 앱 바를 쓴다(D-741 3·5항). 높이는 `--appbar-height`이고 320px까지 한 줄이다. 접힘은 셸 칸의 폭에 답한다: 64rem 아래에서 현장 이름과 래치 부제, 48rem 아래에서 시계와 평상 연결 글, 30rem 아래에서 워드마크 글이 접힌다. 계정·화면 표시·토큰 접속은 계정 단추 아래에 접고, 접속이 필요할 때 저절로 펼친다. 문서 이동은 탐색 레일이 맡고 푸터는 없다.
```

로 바꾼다. `# Fleet 공용 헤더 영역 (D-658)` 아래의 "`헤더는 제품·현장 정체성, 연결·권한 상태, 알림·접속 조작, 비상정지 네 그룹이다.`"로 시작하는 문단을:

```markdown
앱 바는 맥락(R 심볼, `Fleet`, 현장 이름), 연결(연결 글과 시각), 알림·나(알림 단추, 로그인 링크 또는 역할 이름이 붙은 계정 단추), 비상 정지 네 그룹이고 모든 폭에서 한 줄이다(D-741 3·5항). 연결 자리에는 조작이 없다. 계정·화면 표시·토큰 접속은 계정 단추 아래 펼침 칸이며 화면 폭 때문에 저절로 드러나지 않는다. 접속이 필요할 때의 자동 펼침은 유지한다. 탐색은 왼쪽 레일(아이콘 아래에 짧은 이름) 또는 머리 아래 한 줄, 작업·지도는 본문, 현재 영상·개입·알림은 오른쪽 문맥 패널이 맡는다. 푸터는 없다.
```

로 바꾼다. 같은 절의 "`계정 발견성·로그인 복귀·연결/권한 구분은`"으로 시작하는 문단에서 문장 "`우측 유틸리티의 보이는 로그인/계정에서 전용 로그인 문서로 가며, 테마·고급 토큰은 기존 펼침에 남는다.`"를 "`우측의 보이는 로그인 링크에서 전용 로그인 문서로 가며, 화면 표시와 토큰 접속은 계정 단추 아래에 있다(D-741이 D-683 2항을 바꿨다).`"로 바꾼다.

- [ ] **Step 2: 모듈 안내를 고친다**

`operations/ui/console/AGENTS.md`의 Key Files 표에서 `shared/fleet-header.js`, `shared/fleet-header.css` 행의 설명을:

```markdown
| `shared/fleet-header.js`, `shared/fleet-header.css` | D-540 2 / D-741 3 공통 앱 바 — 네 문서가 같은 `<ui-topbar>` 마크업(`test_fleet_header.py`가 글자 그대로 고정)을 쓰고 연결 글(`실시간`·`지연`·`연결 끊김`)·시계·알림 수·계정 단추의 역할 글·개발 배지·계정 칸 접힘·비상 정지 규칙(401이면 `접속이 필요합니다`, 보기 전용이면 운영자 사유, 모름은 눌림)을 이 모듈 하나로 그린다. 한 줄이고 셸 칸(`.fleet-shell`)의 폭으로 접힌다. 로봇 연결 수는 관제 문서의 지도 머리에 있다. 문서 시트는 머리를 칠하지 않는다 |
```

로 바꾼다. 같은 표의 `login.html` 행 끝 문장 "`토큰/테마는 고급 접속·화면 표시 펼침에 둔다`"를 "`토큰 접속과 화면 표시는 계정 단추 아래에 둔다(D-741)`"로 바꾼다.

- [ ] **Step 3: 모듈 일지 세 곳에 한 항목씩 더한다**

`operations/ui/console/logs.md` 끝에(해시는 Task 5 Step 7의 커밋):

```markdown
## <이 Task를 하는 날 YYYY-MM-DD> · <Task 5 커밋 해시> · feat(fleet): one-row app bar and named rail (D-741 조각 4·5)

- 변경: 네 문서의 머리가 맥락 | 연결 | 알림·나 | 정지의 한 줄 앱 바가 됐다. 시계와 연결 글(`실시간`·`지연`·`연결 끊김`)이 머리로 오고 푸터와 그 안의 `관제 알림` 링크가 없어졌다. 알림 단추는 정적 마크업이다. 계정 단추(`#topbar-more`)가 역할 이름을 달고 그 아래에 계정·화면 표시·토큰 접속이 있다. 로봇 연결 수(`#online-pill`)는 관제 문서의 지도 머리로 갔고 다른 세 문서에는 없다. 레일 아이콘 아래에 `관제·설치·지도·작업·Cell`을 적었다. 접힘은 `.fleet-shell` 칸 질의(64rem, 48rem, 30rem)다.
- 증거: 원격 소스 시험과 node 단위 시험 통과, `known_failures` NEW 0. `*_browser.py`는 원격에서 돌지 않았다. `operations/fleet/test`의 브라우저 시험은 푸시 뒤 CI가 증거이고, `test/test_fleet_console_browser.py`와 `shared/web/test/test_theme_browser.py`는 어디서도 저절로 돌지 않는다.
- gate 변화: 없음. D-153 G2 캡처와 G3 사람 검토는 `docs/validation/fleet-app-bar-<같은 날짜>.md`에 적은 대로 아직 없다.
```

`operations/fleet/logs.md` 끝에:

```markdown
## <이 Task를 하는 날 YYYY-MM-DD> · <Task 5 커밋 해시> · test(fleet): app bar and rail contracts follow D-741

- 변경: `test_fleet_header.py`, `test_doc_tabs.py`, `test_site_map_api.py`, `web/fleet-header.test.mjs`와 브라우저 시험 다섯 파일(`test_fleet_header_browser.py`, `test_development_console_browser.py`, `test_password_login_browser.py`, `test_fleet_account_browser.py`, `test_site_map_browser.py`)이 새 앱 바를 고정한다. 서버 코드와 API는 바뀌지 않았다.
- 증거: 원격 소스 시험 통과. 브라우저 시험은 CI 대기.
- gate 변화: 없음.
```

`shared/web/logs.md` 끝에:

```markdown
## <이 Task를 하는 날 YYYY-MM-DD> · <Task 5 커밋 해시> · feat(fleet): console app bar registers a 48rem container breakpoint (D-741)

- 변경: `surfaces.yaml`의 `console`에서 `@media` 48rem 등재를 지우고 `container_breakpoints` 48rem을 올렸다. `test_chrome_layout.py`, `test_action_icon_contract.py`, `test_theme_browser.py`가 Fleet 앱 바의 새 배치를 따른다. 공용 시트와 토큰은 바뀌지 않았다.
- 증거: 원격 `shared/web/test` 통과, `known_failures` NEW 0.
- gate 변화: 없음.
```

`progress.md` 세 파일은 고치지 않는다. 어느 모듈의 관문 상태도 움직이지 않았다.

- [ ] **Step 4: D-153 증거 메모를 쓴다**

`docs/validation/fleet-app-bar-<이 Task를 하는 날 YYYY-MM-DD>.md`:

```markdown
# Fleet 앱 바와 레일 이름 — 증거 상태

대상: [D-741](../adr/D-741-unified-app-shell-seats.md) 조각 4·5, 브랜치 `feat/fleet-app-bar`. 이 문서는 D-153의 세 관문이 지금 어디까지 있는지 적는다. 있는 것만 있다고 적는다.

| 관문 | 상태 | 근거 |
|---|---|---|
| G1 값과 문법 (기계) | 소스 시험 통과 | 원격 pytest 로그 `X:\DevTemp\fleet-bar\t5-fleet-run-*.txt`, `t5-web-run-*.txt`. `known_failures` NEW 0 |
| G1 브라우저 측정 | 없음 | `operations/fleet/test/*_browser.py`는 푸시 뒤 CI에서만 돈다. 실행 번호를 받으면 이 칸에 적는다 |
| G1 브라우저 측정(CI 밖) | 없음 | `test/test_fleet_console_browser.py`, `shared/web/test/test_theme_browser.py`는 CI도 켜지 않는다. Chromium이 있는 PC에서 사람이 돌려야 한다 |
| G2 상태 매트릭스 (캡처) | 없음 | 네 문서 × 320·390·768·1024·1366·1920 × 어둡게·밝게. `ROSY_SHOT_DIR`을 주고 `test_fleet_header_browser.py`를 돌리면 문서·폭마다 한 장이 나온다(어둡게만) |
| G3 법 체크리스트 (사람) | 없음 | 계획 문서 Task 7의 목록 |

설치본, 현장 PC, 실물 화면 수용은 없다.
```

- [ ] **Step 5: 커밋하고 생성 문서와 lint를 맞춘다**

```bash
git add DESIGN.md operations/ui/console/AGENTS.md operations/ui/console/logs.md operations/fleet/logs.md shared/web/logs.md docs/validation/fleet-app-bar-*.md
git diff --cached --name-only
git commit -m "docs(fleet): describe the one-row app bar and its evidence state (D-741)"
python tools/harness/rosy_harness.py generate
python tools/harness/rosy_harness.py lint
git status --short
rm -f X:/DevTemp/fleet-bar/run-*.txt
PYTHONIOENCODING=utf-8 python tools/remote/remote_pytest.py --log-dir X:/DevTemp/fleet-bar -- test/architecture test/test_harness_contracts.py shared/web/test
for f in X:/DevTemp/fleet-bar/run-*.txt; do cp "$f" "X:/DevTemp/fleet-bar/t6-$(basename "$f")"; python test/known_failures.py "X:/DevTemp/fleet-bar/t6-$(basename "$f")"; done
```

Expected: `git diff --cached --name-only`가 여섯 경로만 찍는다. lint 통과, 로그마다 `NEW` 0. `generate`가 모듈 `index.md`나 `STATUS.md`를 바꿨으면 `git status --short`에 나온 그 생성 파일만 이름으로 `git add` 하고 `git commit -m "docs: regenerate module indexes"`로 따로 커밋한다. `test/architecture/test_document_placement.py`가 증거 메모의 자리나 이름을 거절하면 그 문구가 말하는 규칙대로 파일 이름을 고친다.

---

### Task 7: 사람이 볼 것

브라우저 시험은 원격에서 돌지 않는다. `operations/fleet/test`의 것은 푸시 뒤 CI가 재고, 나머지 둘은 어디서도 저절로 돌지 않는다. 그래서 아래를 사람이 Chromium이 있는 PC에서 본다. `/console`, `/console/install`, `/console/site-map`, `/console/cell` 네 문서를 320, 390, 768, 1024, 1366, 1920 폭에서 어둡게와 밝게 두 테마로 연다. 본 결과를 Task 6의 증거 메모 G3 칸에 날짜와 이름과 함께 적는다. 보지 못한 칸은 "없음"으로 둔다.

- [ ] **Step 1: 한 줄과 정지.** 모든 폭에서 앱 바가 한 줄이고 높이가 64px이다. 비상 정지가 오른쪽 끝, 첫 화면에 있고 네 문서에서 같은 크기·같은 자리다. 가로로 밀리지 않는다. 계정 단추를 열어도 비상 정지는 그 줄에 그대로 있고 가려지지 않는다.
- [ ] **Step 2: 320px의 폭.** 운영자로 로그인했을 때 R 심볼, 알림, `운영자`, 비상 정지가 겹치지 않는다. 로그인 전에는 R 심볼, `로그인`, 계정 단추, 비상 정지가 서고 알림 단추가 없다. 보기 전용과 개발 연결 모드에서 역할 이름이 줄임표로 줄어도 읽을 수 있는지 본다. 읽을 수 없으면 열린 결정 3·4로 돌아간다.
- [ ] **Step 3: 연결 글.** Fleet이 답하는 동안 768px 이상에서 `실시간`과 시각이 보이고, 그 아래 폭에서는 연결 자리가 비어 있다. Fleet 서버를 멈추면 다음 조회(관제 1초, 다른 문서 5초)에서 `연결 끊김`이 위험 점과 함께 모든 폭에서 보인다. 서버를 다시 켜면 `실시간`으로 돌아온다. `지연`은 응답을 12초 넘게 붙잡아 두면 주의색으로 나온다.
- [ ] **Step 4: 계정 단추.** 역할 이름이 `운영자`·`보기 전용`·`인증 필요`로 바뀐다. 누르면 아래에 계정 정보(로그인했을 때), 화면 표시 단추, `토큰으로 접속`이 나온다. Escape가 닫고 초점이 계정 단추로 돌아온다. 접속이 거절되면 저절로 열린다. 개발 연결 모드에서 `개발` 표지가 닫힌 단추 안에 보인다.
- [ ] **Step 5: 알림.** 관제 문서에서 읽지 않은 수가 종 옆에 숫자로 나오고 0이면 숫자가 없다. 다른 세 문서에서 누르면 `/console?inbox=1`로 가서 알림 탭이 열린다. 푸터와 `관제 알림` 링크가 없다.
- [ ] **Step 6: 로봇 연결 수.** 관제 문서의 `현장 지도` 머리 옆에 `2/3` 같은 수가 있고 앱 바에는 없다. `/console?view=work`에서는 지도 패널이 숨어 그 수도 안 보인다(열린 결정 1).
- [ ] **Step 7: 레일.** 64rem 이상에서 왼쪽 72px 레일에 아이콘과 그 아래 `관제·설치·지도·작업·Cell`이 보이고 현재 문서가 표시된다. 그 아래 폭에서는 머리 아래 한 줄로 눕고 320px에서 다섯 항목이 가로로 밀지 않고 다 보인다. 화면 낭독기가 `설치·보정`, `현장 지도`로 읽는다.
- [ ] **Step 8: 밝게 테마.** 연결 글의 주의색(`지연`)이 `--surface-recessed` 위에서 읽힌다. 계정 단추 안의 인라인 값에 테두리와 채움이 없다.
- [ ] **Step 9: CI 밖의 브라우저 시험을 돌린다.** Chromium이 있는 Linux 시험 PC에서:

```bash
ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_fleet_console_browser.py shared/web/test/test_theme_browser.py -q -rfE -p no:cacheprovider
```

결과(통과 수, 실패 이름)를 증거 메모의 "G1 브라우저 측정(CI 밖)" 칸에 적는다.

---

### Task 8: 착지

- [ ] **Step 1: 사용자가 착지를 말한 뒤에만**

```bash
PYTHONIOENCODING=utf-8 python tools/land.py --tests auto --node
```

Expected: 도구가 `main`을 합치고 관련 시험, node 단위 시험, lint를 다시 돌린 뒤 `--ff-only`로 착지한다. 푸시는 하지 않는다. 착지 보고에 아래 세 줄을 적는다.

- 원격에서 돈 것은 소스 시험과 node 단위 시험이다.
- `operations/fleet/test`의 브라우저 시험은 돌지 않았고 푸시 뒤 CI 대기다.
- `test/test_fleet_console_browser.py`와 `shared/web/test/test_theme_browser.py`는 고쳤지만 어디서도 저절로 돌지 않는다. Task 7 Step 9를 한 사람이 있으면 그 결과를, 없으면 "확인 못 함"을 적는다.

---

## 이 계획이 하지 않는 것

- 탐색의 순서, 주소, `/console/cell` 경로를 바꾸지 않는다. `작업`과 `기록` 영역의 재구성은 조각 7·8이다.
- 공용 시트 `shared/web/app-shell.css`를 네 문서에 링크하지 않는다. 레일은 `doc-tabs.css`가 자리 토큰(`--rail-track`, `--inset-rail`, `--gap-rail`)만 빌려 쓴다. `ui-app-shell`·`ui-rail` 클래스로 옮기는 것은 조각 6(하위 탐색)이다.
- 관제 문서에 경로 줄(`.ui-pathbar`)을 만들지 않는다. 로봇 연결 수는 지금 있는 지도 머리 줄에 둔다.
- "끊기면 앱 바 아래 띠와 지도 위 글"(D-741 3항)을 만들지 않는다. 연결 끊김은 앱 바의 연결 글과, 관제 문서의 `#online-pill`에 지금도 뜨는 `Fleet 서버 없음`이 말한다.
- 진단과 버전을 계정 단추 아래에 새로 넣지 않는다. 지금 머리와 푸터에 그 항목이 없다. 옮길 것이 없다.
- 인증 API, 쿠키, 로그인 복귀 허용 목록(`login-return.js`), `/api/fleet/estop`, 비상 정지의 잠금 규칙을 바꾸지 않는다.
- `shared/web`의 공용 부품과 토큰을 바꾸지 않는다. `--topbar-height`(88px)도 지우지 않는다.
- 설치본 검사, 현장 PC 배포, 실물 수용을 하지 않는다.

## 열린 결정

1. **로봇 연결 수의 자리.** 지시는 "관제 화면의 경로·머리 줄"이다. 관제 문서에는 아직 경로 줄이 없어 지도 패널의 머리 줄(`.map-head`)에 뒀다. 그래서 `/console?view=work`에서는 지도 패널과 함께 숨는다. 관제 문서가 공용 자리(`ui-pathbar`)를 쓰게 되는 조각에서 경로 줄로 옮긴다.
2. **계정 단추 아래 칸의 모양.** 지금 동작을 지켜 머리 아래에 한 줄을 더 펼치는 칸(`#topbar-extra`, 흐름 안)으로 뒀다. 떠 있는 메뉴로 바꾸면 접속 거절 때 저절로 열린 칸이 지도 오른쪽 위를 덮고, 칸을 연 채 다음 조작을 누르는 브라우저 시험들이 가려진 대상을 누르게 된다. 바꾸려면 바깥을 누르면 닫히는 동작과 그 시험을 같이 정한다.
3. **30rem 아래 로그인 전의 알림 단추.** 320px에 `로그인` 글(D-683 1항)과 계정 단추와 비상 정지를 한 줄에 세우려고 로그인 전에는 알림 단추를 숨겼다. D-632 1항은 공통 머리에 알림 단추를 둔다고만 적는다. 다른 길은 그 폭에서 `로그인`을 아이콘 단독으로 줄이는 것인데 D-683 1항과 부딪친다.
4. **좁은 폭의 역할 이름.** 역할 이름은 모든 폭에서 보이는 글로 두고 폭이 모자랄 때만 줄임표로 줄게 했다. 320px에서 `보기 전용`·`정책 관리자`나 개발 표지가 붙으면 줄어든다. 30rem 아래에서 역할 이름을 가리고 아이콘과 접근 이름만 남기는 쪽이 낫다는 판단이 Task 7 Step 2에서 나오면 `@container (width < 30rem)`에 한 줄을 더한다.
5. **레일의 현재 위치 표식.** D-741 6항은 "현재 위치 표식은 D-277 장미색"이라고 적는다. 지금 Fleet 레일은 먹색 선과 `--surface-raised`이고 그대로 뒀다. 장미색으로 바꾸려면 `test_design_scope_gates.py`의 `ROSE_FILES`에 `doc-tabs.css`를 올려야 한다. 레일이 공용 `ui-rail-item`으로 옮기는 조각 6에서 같이 바뀐다.
6. **64rem 아래의 래치 이름.** `#estop`의 `<small>래치 · 로봇별 관리자 해제</small>`는 지금 64rem 아래에서 `display: none`이라 접근 이름에서도 빠지고, `test/test_fleet_console_browser.py`가 그 동작을 고정한다(`stopScopeHidden`, `stopAccessibleName is None`). 그 `<small>`은 이미 1px로 가려진 글이라 폭을 차지하지 않는다. D-421 7항(Proposed)의 뜻대로 모든 폭에서 접근 이름에 래치를 남기려면 `@container (width < 64rem)`의 `#estop small { display: none; }` 한 줄을 지우고 그 두 단언을 고친다. 지금 동작을 지키려고 남겼다.
7. **워드마크 글.** 지시대로 `Fleet`으로 줄였다(R 심볼이 Rosy를 말한다). 링크의 접근 이름 `Rosy Fleet 관제 홈`, `<title>`, `surfaces.yaml`의 `app_name`은 `Rosy Fleet` 그대로다. D-377의 이름 규칙과 D-654 4항("기존 이름 유지")이 보이는 워드마크까지 묶는지는 조각 0에서 정한다.
8. **`지연`의 기준.** 새 답이 12초 넘게 없으면 `지연`이다(5초 조회 두 번을 놓치고 2초). 관제 문서는 1초마다 조회하므로 더 짧게 잡을 수 있다. 문서마다 다른 기준을 두지 않으려고 한 값으로 뒀다. D-398의 신선도 네 단계와 맞추는 것은 D-741 9항(상태 표현 공용)의 조각이다.
9. **48rem 아래의 평상 연결 글.** `실시간`과 시계를 48rem 아래에서 접었다("정상은 조용하다"). 그 폭에서도 `실시간`을 늘 보이게 하려면 320px 계산에서 42px이 더 필요하고, 그만큼 계정 단추의 역할 이름이 준다.
