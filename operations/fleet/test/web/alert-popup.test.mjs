import test from "node:test";
import assert from "node:assert/strict";
// 노드는 브라우저의 "/common/..." 절대 경로를 못 찾는다 — common-loader가 shared/web으로 바꾼다.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const { createAlertPopup, isOnScreen } = await import("../../../../applications/fleet/web/alert-popup.js");

function fakeNode(tag = "div") {
  return {
    tagName: tag.toUpperCase(),
    className: "",
    textContent: "",
    dataset: {},
    attributes: {},
    children: [],
    listeners: {},
    focus() { throw new Error("alert popup must never steal focus"); },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    querySelectorAll() { return []; },
  };
}

function findNodes(root, predicate, acc = []) {
  if (!root) return acc;
  if (predicate(root)) acc.push(root);
  for (const child of root.children || []) findNodes(child, predicate, acc);
  return acc;
}

function findButton(mount, label) {
  return findNodes(mount, (n) => n.tagName === "UI-BUTTON" && n.textContent === label)[0] || null;
}

function withFakeDoc(t) {
  const origDoc = globalThis.document;
  globalThis.document = { createElement: (tag) => fakeNode(tag) };
  t.after(() => { globalThis.document = origDoc; });
}

test("createAlertPopup dedupes, renders single active card for 6 crit alerts, ignores idle 401/404, and gates crit-row toasts on queue-panel visibility", (t) => {
  withFakeDoc(t);

  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.pushCallError("/api/fleet/state", { method: "GET" }, { status: 401, code: "UNAUTHORIZED", message: "auth" }, true);
  popup.pushCallError("/api/fleet/state", { method: "GET" }, { status: 401, code: "UNAUTHORIZED", message: "auth" }, false);
  popup.pushCallError("/api/fleet/state", { method: "POST" }, { status: 403, code: "PASSWORD_CHANGE_REQUIRED", message: "pw" }, false);
  popup.pushCallError("/api/fleet/discovery", { method: "GET" }, { status: 404, code: "ABSENT", message: "missing" }, false);
  assert.equal(popup.getItems().length, 0);

  const err409 = { status: 409, code: "ROBOT_STEP_BLOCKED", message: "blocked" };
  popup.pushCallError("/api/fleet/robots/rosy_45/step", { method: "POST" }, err409, false);
  popup.pushCallError("/api/fleet/robots/rosy_45/step", { method: "POST" }, err409, false);
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].count, 2);

  popup.clearCallError("/api/fleet/robots/rosy_45/step");
  assert.equal(popup.getItems().length, 0);

  for (let i = 0; i < 6; i += 1) {
    popup.push({ key: `k${i}`, severity: "crit", message: `err ${i}` });
  }
  assert.equal(popup.getItems().length, 6);
  assert.equal(mount.children.length, 1);
  assert.equal(mount.children[0].dataset.alertKey, "k5");

  popup.clear();
  // syncCritRows(2026-11-16 복원): 큐 패널이 보이면 새 긴급 행도 토스트로 심지 않고,
  // 패널이 숨겨진 뷰에서만 긴급 토스트 1장을 띄운다. 해소된 행은 토스트도 닫는다.
  const row1 = { dataset: { key: "stuck:rosy_01:1" }, textContent: "rosy_01 막힘", querySelector() { return null; } };
  const row2 = { dataset: { key: "stuck:rosy_02:2" }, textContent: "rosy_02 막힘", querySelector() { return null; } };
  const row3 = { dataset: { key: "stuck:rosy_03:3" }, textContent: "rosy_03 막힘", querySelector() { return null; } };
  let rows = [row1];
  const listEl = { querySelectorAll: () => rows };
  popup.syncCritRows(listEl, true);  // 첫 관측은 씨앗만 심는다(기존 동작)
  assert.equal(popup.getItems().length, 0);
  rows = [row1, row2];
  popup.syncCritRows(listEl, true, { panelVisible: true });  // (a) 패널 보임 → 토스트 0장
  assert.equal(popup.getItems().length, 0);
  rows = [row1, row2, row3];
  popup.syncCritRows(listEl, true, { panelVisible: false });  // (b) 패널 숨김 → 긴급 토스트 1장
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].target.robotId, "rosy_03");
  rows = [row1, row2];
  popup.syncCritRows(listEl, true, { panelVisible: false });  // (c) 행 해소 → 토스트 닫힘
  assert.equal(popup.getItems().length, 0);
});

test("isOnScreen 판정과 syncCritRows — 화면 밖(스크롤·앱바 가림) 큐 패널은 긴급 토스트를 띄우고 다시 보이면 닫는다", (t) => {
  withFakeDoc(t);

  // 390×844, 상단 고정 앱바 48px: 창 클립은 top=48부터(앱바에 가려진 부분은 보이지 않는다).
  const clips = [{ top: 48, bottom: 844, left: 0, right: 390 }];
  const onScreen = (rect) => isOnScreen(rect, clips);
  // (a) hidden=false + 화면 안 → 보임
  assert.equal(onScreen({ top: 100, bottom: 300, left: 0, right: 390 }), true);
  assert.equal(onScreen({ top: 800, bottom: 900, left: 10, right: 380 }), true);  // 아래에 살짝 걸침
  // (b) 스크롤되어 창 위 밖(y=-649) → 화면 밖
  assert.equal(onScreen({ top: -649, bottom: -100, left: 0, right: 390 }), false);
  // (d) 앱바에 완전히 가려진 경우 → 화면 밖 취급
  assert.equal(onScreen({ top: 0, bottom: 40, left: 0, right: 390 }), false);

  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });
  const row = (n) => ({ dataset: { key: `stuck:rosy_0${n}:${n}` }, textContent: `rosy_0${n} 막힘`, querySelector() { return null; } });
  let rows = [row(1)];
  const listEl = { querySelectorAll: () => rows };
  const inView = { top: 100, bottom: 300, left: 0, right: 390 };
  const scrolledOut = { top: -649, bottom: -100, left: 0, right: 390 };
  const underAppbar = { top: 0, bottom: 40, left: 0, right: 390 };
  const hidden = false;  // console.js 배선: panelVisible = !hidden && isOnScreen(rect, clips)

  popup.syncCritRows(listEl, true);  // 첫 관측은 씨앗만 심는다
  rows = [row(1), row(2)];
  popup.syncCritRows(listEl, true, { panelVisible: !hidden && onScreen(inView) });  // (a) 화면 안 → 토스트 0장
  assert.equal(popup.getItems().length, 0);
  rows = [row(1), row(2), row(3)];
  popup.syncCritRows(listEl, true, { panelVisible: !hidden && onScreen(scrolledOut) });  // (b) 화면 밖 → 긴급 토스트 1장
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].key, "crit|stuck:rosy_03:3");
  popup.syncCritRows(listEl, true, { panelVisible: !hidden && onScreen(inView) });  // (c) 다시 화면 안 → 토스트 닫힘
  assert.equal(popup.getItems().length, 0);
  rows = [row(1), row(2), row(3), row(4)];
  popup.syncCritRows(listEl, true, { panelVisible: !hidden && onScreen(underAppbar) });  // (d) 앱바 가림 → 화면 밖 취급
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].key, "crit|stuck:rosy_04:4");
  popup.syncCritRows(listEl, true, { panelVisible: !hidden && onScreen(scrolledOut) });  // 같은 항목 두 번째 토스트 없음
  assert.equal(popup.getItems().length, 1);
});

test("createAlertPopup cycles with 다음 알림 and steps through 닫기 until empty", (t) => {
  withFakeDoc(t);
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.push({ key: "a", severity: "crit", title: "알림 A", message: "첫 번째" });
  popup.push({ key: "b", severity: "crit", title: "알림 B", message: "두 번째" });
  popup.push({ key: "c", severity: "crit", title: "알림 C", message: "세 번째" });

  assert.equal(mount.children.length, 1);
  assert.equal(mount.children[0].dataset.alertKey, "c");
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-queue")[0]?.textContent, "외 2건");
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-next")[0]?.textContent, "다음: 알림 B — 두 번째");

  findButton(mount, "다음 알림").listeners.click();
  assert.equal(mount.children[0].dataset.alertKey, "b");
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-next")[0]?.textContent, "다음: 알림 A — 첫 번째");

  findButton(mount, "다음 알림").listeners.click();
  assert.equal(mount.children[0].dataset.alertKey, "a");

  findButton(mount, "닫기").listeners.click();
  assert.equal(popup.getItems().length, 2);
  assert.equal(mount.children.length, 1);
  assert.equal(mount.children[0].dataset.alertKey, "c");

  findButton(mount, "닫기").listeners.click();
  assert.equal(popup.getItems().length, 1);
  assert.equal(mount.children[0].dataset.alertKey, "b");
  assert.equal(findButton(mount, "다음 알림"), null);

  findButton(mount, "닫기").listeners.click();
  assert.equal(popup.getItems().length, 0);
  assert.equal(mount.children.length, 0);
});

test("createAlertPopup 모두 닫기 clears all queued alerts cleanly", (t) => {
  withFakeDoc(t);
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.push({ key: "a", severity: "crit", message: "A" });
  popup.push({ key: "b", severity: "warn", message: "B" });
  assert.equal(popup.getItems().length, 2);

  findButton(mount, "모두 닫기").listeners.click();
  assert.equal(popup.getItems().length, 0);
  assert.equal(mount.children.length, 0);
});

test("createAlertPopup preempts warn with crit and escalates same-key warn -> crit even past 10s", (t) => {
  withFakeDoc(t);
  const origNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  t.after(() => { Date.now = origNow; });

  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.push({ key: "w1", severity: "warn", message: "경고 1" });
  popup.push({ key: "c1", severity: "crit", message: "위험 1" });
  popup.push({ key: "w2", severity: "warn", message: "경고 2" });
  assert.deepEqual(popup.getItems().map((i) => i.key), ["c1", "w2", "w1"]);
  assert.equal(mount.children[0].dataset.alertKey, "c1");

  now += 25_000; // past 10s
  popup.push({ key: "w1", severity: "crit", message: "경고 1 -> 위험 승격" });
  assert.equal(popup.getItems().length, 3);
  assert.equal(mount.children.length, 1);
  assert.deepEqual(popup.getItems().map((i) => i.key), ["w1", "c1", "w2"]);
  assert.equal(popup.getItems()[0].severity, "crit");
  assert.equal(popup.getItems()[0].count, 2);
  assert.equal(popup.getItems()[0].message, "경고 1 -> 위험 승격");
});

test("pushLogError skips silent and translated errors matching recent call code/status within 1500ms", (t) => {
  withFakeDoc(t);
  const origNow = Date.now;
  let now = 2_000_000;
  Date.now = () => now;
  t.after(() => { Date.now = origNow; });

  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.pushLogError("숨김 오류", { silent: true });
  assert.equal(popup.getItems().length, 0);

  popup.pushCallError("/api/fleet/robots/rosy_45/goal", { method: "POST" }, {
    status: 503,
    code: "ROBOT_OFFLINE",
    message: "upstream unavailable",
  }, false);
  assert.equal(popup.getItems().length, 1);

  now += 500;
  popup.pushLogError("번역된 안내: 로봇 연결이 끊겼습니다", { code: "ROBOT_OFFLINE" });
  popup.pushLogError("번역된 안내: 일시적 서버 오류", { status: 503 });
  assert.equal(popup.getItems().length, 1);

  popup.pushLogError("완전히 다른 오류", { status: 409, code: "OTHER_ERR" });
  assert.equal(popup.getItems().length, 2);

  now += 2000;
  popup.pushLogError("시간 경과 후 같은 코드 로그", { code: "ROBOT_OFFLINE" });
  assert.equal(popup.getItems().length, 3);

  popup.clear();
  popup.pushCallError("/api/fleet/trips", { method: "POST" }, {
    status: 409,
    code: "TRIP_HEADING_CONFLICT",
    message: "TRIP_HEADING_CONFLICT",
  }, false);
  now += 40;
  popup.pushLogError("rosy_45 차로 주행 거절 — 로봇이 차로 반대 방향을 보고 있습니다 · Pilot으로 돌려 세우세요 · 방향 어긋남(90°)");
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].code, "TRIP_HEADING_CONFLICT");
  assert.equal(popup.getItems()[0].status, 409);
  assert.equal(popup.getItems()[0].count, 1);
  assert.equal(popup.getItems()[0].target?.robotId, "rosy_45");
  assert.match(popup.getItems()[0].message, /rosy_45 차로 주행 거절/);
});

test("Fleet 연결 끊김 poll 실패는 카드를 만들지 않고(머리말 연결 표시가 말한다), 다른 GET 5xx는 call|poll|fleet 한 장으로 합쳐진다", (t) => {
  withFakeDoc(t);
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });

  popup.pushCallError("/api/fleet/state", { method: "GET" }, { status: 503, code: "HOLD", message: "holdover" }, false, { isStaleHoldover: true });
  popup.pushCallError("/api/fleet/state", { method: "GET" }, { status: 502, code: "BAD_GATEWAY", message: "state fail" }, false);
  popup.pushCallError("/api/fleet/site-map", { method: "GET" }, { message: "NetworkError" }, false);
  assert.equal(popup.getItems().length, 0);
  assert.equal(mount.children.length, 0);

  popup.pushCallError("/api/fleet/robots", { method: "GET" }, { status: 500, code: "INTERNAL", message: "robots fail" }, false);
  popup.pushCallError("/api/fleet/devices", { method: "GET" }, { status: 500, code: "INTERNAL", message: "devices fail" }, false);
  assert.equal(popup.getItems().length, 1);
  assert.equal(mount.children.length, 1);
  const item = popup.getItems()[0];
  assert.equal(item.key, "call|poll|fleet");
  assert.equal(item.count, 2);
  assert.deepEqual(item.detail.paths, ["/api/fleet/robots", "/api/fleet/devices"]);

  popup.clearCallError("/api/fleet/state");
  assert.equal(popup.getItems().length, 0);
  assert.equal(mount.children.length, 0);
});

test("명령(POST) 실패는 연결 끊김 규칙과 무관하게 카드 정확히 1장", (t) => {
  withFakeDoc(t);
  const popup = createAlertPopup({ mount: fakeNode("section") });
  popup.pushCallError("/api/fleet/robots/rosy_45/step", { method: "POST" }, { message: "NetworkError" }, false);
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].key, "call|/api/fleet/robots/rosy_45/step");
});

test("createAlertPopup updates active card in place without replacing mount children and suppresses transient holdover", (t) => {
  withFakeDoc(t);
  let replaceCount = 0;
  const mount = fakeNode("section");
  const origReplace = mount.replaceChildren.bind(mount);
  mount.replaceChildren = (...nodes) => {
    replaceCount += 1;
    origReplace(...nodes);
  };
  const popup = createAlertPopup({ mount, onNavigate: () => {} });

  // First-tick transient disconnect during holdover must not flash "서버 응답 오류"
  popup.pushCallError("/api/fleet/state", { method: "GET" }, { status: 503, code: "TIMEOUT", message: "first tick" }, false, { isStaleHoldover: true });
  assert.equal(popup.getItems().length, 0);
  assert.equal(replaceCount, 0);

  // Sustained failure after holdover pushes card once
  popup.pushCallError("/api/fleet/robots", { method: "GET" }, { status: 503, code: "TIMEOUT", message: "sustained" }, false, { isStaleHoldover: false });
  assert.equal(popup.getItems().length, 1);
  assert.equal(replaceCount, 1);
  const initialCard = mount.children[0];
  const initialCloseBtn = findButton(mount, "닫기");
  assert.ok(initialCard.dataset.alertId);

  // Repeated same-key error + queued warn behind active crit update badges/detail in place without replacing card/buttons
  popup.pushCallError("/api/fleet/robots", { method: "GET" }, { status: 502, code: "BAD_GW", message: "still down" }, false, { isStaleHoldover: false });
  popup.push({ key: "warn-behind", severity: "warn", title: "주의", message: "보조 경고" });
  assert.equal(replaceCount, 1);
  assert.equal(mount.children[0], initialCard);
  assert.equal(findButton(mount, "닫기"), initialCloseBtn);
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-count")[0]?.textContent, "×2");
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-queue")[0]?.textContent, "외 1건");
  assert.equal(findNodes(mount, (n) => n.className === "alert-popup-next")[0]?.textContent, "다음: 주의 — 보조 경고");
});

test("큐 패널의 새 긴급 행은 패널이 화면에 있어도 announcer로 한 번 urgent 낭독되고, 같은 행은 다시 읽지 않는다", (t) => {
  withFakeDoc(t);
  const said = [];
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount, announcer: { announce: (text, opts) => said.push([text, opts?.urgent === true]) } });
  const row = (n) => ({ dataset: { key: `stuck:rosy_0${n}:${n}` }, textContent: `rosy_0${n} 막힘`, querySelector() { return null; } });
  let rows = [row(1)];
  const listEl = { querySelectorAll: () => rows };

  popup.syncCritRows(listEl, true);  // 첫 관측은 씨앗만 심는다
  assert.deepEqual(said, []);
  rows = [row(1), row(2)];
  popup.syncCritRows(listEl, true, { panelVisible: true });  // 패널 보임 — 카드 0장, 낭독 1회 urgent
  assert.equal(popup.getItems().length, 0);
  assert.deepEqual(said.filter(([text]) => text.includes("rosy_02")), [["긴급 개입 알림: rosy_02 막힘", true]]);
  popup.syncCritRows(listEl, true, { panelVisible: true });  // 같은 행 다음 폴링 — 재낭독 없음
  assert.equal(said.length, 1);
  rows = [row(1), row(2), row(3)];
  popup.syncCritRows(listEl, true, { panelVisible: false });  // 패널 숨김 — 카드 1장 + 낭독도 1회(push가 말한다)
  assert.equal(popup.getItems().length, 1);
  assert.deepEqual(said.filter(([text]) => text.includes("rosy_03")), [["긴급 개입 알림: rosy_03 막힘", true]]);
  assert.equal(said.length, 2);
});

test("새 crit 카드는 urgent로, 새 warn 카드는 polite로 한 번 낭독되고 같은 key 반복은 다시 읽지 않는다", (t) => {
  withFakeDoc(t);
  const said = [];
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount, announcer: { announce: (text, opts) => said.push([text, opts?.urgent === true]) } });

  popup.push({ key: "c1", severity: "crit", title: "명령·요청 오류", message: "거절" });
  popup.push({ key: "c1", severity: "crit", title: "명령·요청 오류", message: "거절" });  // 같은 key — ×N만
  popup.push({ key: "w1", severity: "warn", message: "경고" });
  assert.deepEqual(said, [
    ["명령·요청 오류: 거절", true],
    ["주의 알림: 경고", false],
  ]);
});

test("390x844: 고정 앱바(64) 아래로 스크롤해 지나친 큐 패널은 화면 밖이라 새 긴급 행이 토스트 1장으로 온다", (t) => {
  withFakeDoc(t);
  const clips = [{ top: 64, bottom: 844, left: 0, right: 390 }];
  // 실측(11-17, 390 폭): 탭 전환 뒤 scrollY 854~915에서 패널 box는 top -618, bottom -358
  assert.equal(isOnScreen({ top: -618, bottom: -358, left: 16, right: 374 }, clips), false);
  assert.equal(isOnScreen({ top: 20, bottom: 60, left: 16, right: 374 }, clips), false);   // 앱바 뒤에 숨은 패널
  assert.equal(isOnScreen({ top: 266, bottom: 496, left: 16, right: 374 }, clips), true);  // 첫 화면의 패널
  const popup = createAlertPopup({ mount: fakeNode("section") });
  const row = { dataset: { key: "rosy_03|hitl" }, textContent: "rosy_03: 개입 필요", querySelector() { return null; } };
  let rows = [];
  const listEl = { querySelectorAll: () => rows };
  popup.syncCritRows(listEl, true, { panelVisible: false });  // 씨앗
  rows = [row];
  popup.syncCritRows(listEl, true, { panelVisible: isOnScreen({ top: -618, bottom: -358, left: 16, right: 374 }, clips) });
  assert.equal(popup.getItems().length, 1);
  assert.equal(popup.getItems()[0].key, "crit|rosy_03|hitl");
});

test("a screen runtime error is a log line for diagnosis, never a toast (11-18 decision 3)", (t) => {
  withFakeDoc(t);
  const origWindow = globalThis.window;
  globalThis.window = {};
  t.after(() => { globalThis.window = origWindow; });
  const mount = fakeNode("section");
  const popup = createAlertPopup({ mount });
  const handlers = {}, logged = [];
  popup.attachWindowErrors({ listen: (_node, type, fn) => { handlers[type] = fn; } }, (...args) => logged.push(args));
  handlers.error({ message: "x is undefined", error: new TypeError("x is undefined") });
  handlers.unhandledrejection({ reason: new Error("late promise") });
  handlers.unhandledrejection({ reason: Object.assign(new Error("gone"), { name: "AbortError" }) });
  assert.equal(popup.getItems().length, 0);
  assert.equal(mount.children.length, 0);
  assert.deepEqual(logged.map(([text, kind, meta]) => [text, kind, meta?.silent]), [
    ["화면 런타임 오류 — x is undefined", "bad", true],
    ["비동기 처리 오류 — late promise", "bad", true],
  ]);
});
