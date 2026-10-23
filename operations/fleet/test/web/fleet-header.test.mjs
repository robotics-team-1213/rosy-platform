// D-540 2 — the one header: role words, the one E-stop rule and the shared stop press.
import test from "node:test";
import assert from "node:assert/strict";

import { OPERATOR_REASON } from "../../../../applications/fleet/web/shared/authorization.js";
// Header unit tests isolate authorization; shared icon rendering has real-browser coverage.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const {
  LATE_MS, SESSION_REASON, bindEstop, bindTopbarToggle, estopReason, linkState, noteLink, roleLabel, showFleet,
  showInboxCount, showSession, showSignedOut, tickClock, watchFleet,
} = await import("../../../../applications/fleet/web/shared/fleet-header.js");

function fakeNode(id) {
  const attributes = new Map();
  return {
    id, hidden: false, disabled: false, textContent: "", dataset: {}, listeners: {},
    getAttribute: name => (attributes.has(name) ? attributes.get(name) : null),
    setAttribute: (name, value) => attributes.set(name, String(value)),
    removeAttribute: name => attributes.delete(name),
    hasAttribute: name => attributes.has(name),
    addEventListener(type, fn) { this.listeners[type] = fn; },
  };
}

function fakeHeader() {
  const nodes = Object.fromEntries(["user-role", "development-badge", "estop", "estop-feedback", "topbar-more",
    "topbar-extra", "online-pill", "fleet-name", "clock", "fleet-inbox", "fleet-theme", "header-unread",
    "fleet-login", "fleet-account", "fleet-account-identity", "link-state"].map(id => [id, fakeNode(id)]));
  nodes["development-badge"].hidden = true;
  nodes["topbar-more"].setAttribute("aria-expanded", "false");
  nodes["topbar-extra"].dataset.open = "false";  // the markup ships closed (D-741 3)
  globalThis.document = {getElementById: id => nodes[id], addEventListener() {}};
  return nodes;
}

test("one status click toggles once; the theme button is wired by the shared ui.js", () => {
  const nodes = fakeHeader();
  globalThis.MutationObserver = class { observe() {} };
  bindTopbarToggle();
  assert.match(nodes["topbar-more"].getAttribute("aria-label"), /^계정과 접속/);
  assert.equal(typeof nodes["fleet-inbox"].listeners.click, "function");
  assert.equal(nodes["fleet-theme"].listeners.click, undefined);
  nodes["topbar-more"].listeners.click();
  assert.equal(nodes["topbar-extra"].dataset.open, "true");
  nodes["topbar-more"].listeners.click();
  assert.equal(nodes["topbar-extra"].dataset.open, "false");
  nodes["topbar-more"].focus = () => {nodes["topbar-more"].focused = true;};
  nodes["topbar-extra"].listeners.keydown({key: "Escape"});
  assert.equal(nodes["topbar-more"].focused, true);
});

test("the E-stop locks only on a press the server would refuse", () => {
  assert.equal(estopReason(undefined), "");            // unknown: loading or Fleet unreachable
  assert.equal(estopReason(null), SESSION_REASON);     // 401
  assert.equal(estopReason({role: "viewer"}), OPERATOR_REASON);
  assert.equal(estopReason({role: "operator"}), "");
});

test("message counts update one summary value without replacing its connection or mode", () => {
  const nodes = fakeHeader();
  showFleet({name: "site", online: 2, total: 3});
  showInboxCount(4);
  assert.equal(nodes["online-pill"].textContent, "2/3");
  assert.equal(nodes["header-unread"].textContent, "4");
  assert.equal(nodes["header-unread"].hidden, false);
  showInboxCount(0);
  assert.equal(nodes["header-unread"].hidden, true);
  assert.equal(nodes["online-pill"].textContent, "2/3");
});

test("role words are Korean; English stays out of the text", () => {
  assert.equal(roleLabel("operator"), "운영자");
  assert.equal(roleLabel("viewer"), "보기 전용");
  assert.equal(roleLabel("nobody"), "권한 없음");
});

test("a session shows its Korean role and title identity; a development session shows the badge", () => {
  const nodes = fakeHeader();
  showSession({principal_id: "bob", role: "operator"});
  assert.equal(nodes["fleet-login"].hidden, true);
  assert.equal(nodes["fleet-account"].hidden, false);
  assert.equal(nodes["fleet-account-identity"].textContent, "bob · 운영자");
  assert.equal(nodes["user-role"].textContent, "운영자");
  assert.equal(nodes["user-role"].title, "bob · operator");
  assert.equal(nodes["user-role"].getAttribute("status"), "active");
  assert.equal(nodes.estop.disabled, false);
  assert.equal(nodes["development-badge"].hidden, true);

  showSession({principal_id: "development-1a2b", role: "operator"});
  assert.equal(nodes["user-role"].textContent, "운영자");
  assert.match(nodes["user-role"].title, /^development-1a2b/);
  assert.equal(nodes["development-badge"].hidden, false);

  showSession({principal_id: "vic", role: "viewer"});
  assert.equal(nodes["user-role"].textContent, "보기 전용");
  assert.equal(nodes["user-role"].title, "vic · viewer");
  assert.equal(nodes["user-role"].getAttribute("status"), "neutral");
  assert.equal(nodes.estop.disabled, true);
  assert.equal(nodes.estop.getAttribute("reason"), OPERATOR_REASON);
});

test("a refused session locks the E-stop but leaves the account row closed; a lost Fleet does not lock it", () => {
  const nodes = fakeHeader();
  showSignedOut({refused: false});
  assert.equal(nodes["user-role"].textContent, "인증 필요");
  assert.equal(nodes.estop.disabled, false);

  showSignedOut();
  assert.equal(nodes["user-role"].getAttribute("status"), "crit");
  assert.equal(nodes.estop.disabled, true);
  assert.equal(nodes.estop.getAttribute("reason"), SESSION_REASON);
  // D-741 3: the row stays closed; the guide strip's 관제 접속 opens it.
  assert.equal(nodes["topbar-extra"].dataset.open, "false");

  nodes["topbar-extra"].dataset.open = "true";  // the operator opened it to enter access
  showSession({principal_id: "bob", role: "operator"});
  assert.equal(nodes.estop.disabled, false);
  assert.equal(nodes.estop.getAttribute("reason"), null);
  assert.equal(nodes["topbar-extra"].dataset.open, "false");  // a session folds it again
});

test("the shared press posts once and reports partial stops as an error", async () => {
  const nodes = fakeHeader();
  const calls = [];
  bindEstop(async (path, options) => {
    calls.push([path, options.method]);
    return {stopped: 1, total: 3, robots: [{robot_id: "rosy_02", stopped: false, error: {code: "TIMEOUT"}}]};
  });
  await nodes.estop.listeners.click();
  assert.deepEqual(calls, [["/api/fleet/estop", "POST"]]);
  assert.equal(nodes["estop-feedback"].textContent, "정지 요청 응답: 1/3 · 물리 정지 미확인");
  assert.equal(nodes["estop-feedback"].getAttribute("state"), "error");

  bindEstop(async () => { throw Object.assign(new Error("offline"), {status: undefined}); });
  await nodes.estop.listeners.click();
  assert.match(nodes["estop-feedback"].textContent, /^비상 정지 결과 확인 불가/);
});

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

test("only the request feeds the link word: a paint error after an answer is not a lost link", async () => {
  const nodes = fakeHeader();
  const reads = [];
  const poll = answer => { watchFleet(answer, {interval: fn => reads.push(fn)}); return new Promise(setImmediate); };
  await poll(async () => ({fleet: null, robots: null}));  // showFleet throws on this answer
  assert.equal(nodes["link-state"].textContent, "실시간");
  await poll(async () => { throw Object.assign(new Error("forbidden"), {status: 403}); });  // signed out: Fleet answered
  assert.equal(nodes["link-state"].textContent, "실시간");
  await poll(async () => { throw new TypeError("fetch failed"); });
  assert.equal(nodes["link-state"].textContent, "연결 끊김");
  assert.equal(reads.length, 3);
});

test("the console counts every Fleet answer and keeps asking while signed out", async () => {
  const {readFile} = await import("node:fs/promises");
  const source = await readFile(new URL("../../../../applications/fleet/web/console.js", import.meta.url), "utf8");
  const wrapper = source.slice(source.indexOf("const fleetClient ="), source.indexOf("async function call("));
  assert.match(wrapper, /fleetApi\(path, options\)\.then\(body => \{ noteLink\(\);/);  // every answer, 401/403 included
  assert.match(wrapper, /path === "\/api\/fleet\/state" \|\| error\.status < 500\) noteLink\(error\)/);
  // D-798 3.2: the state poll lives in console-refresh.js; the cancel-all handler follows it there.
  const refresh = await readFile(new URL("../../../../applications/fleet/web/console-refresh.js", import.meta.url), "utf8");
  const poll = refresh.slice(refresh.indexOf("async function refreshState("), refresh.indexOf("const CANCEL_ALL_RESULT"));
  assert.ok(poll.length > 0);
  assert.match(poll, /if \(auth\.locked\) return void fleetApi\("\/api\/fleet\/auth\/connection"/);
  assert.doesNotMatch(poll, /noteLink\(err\)/);  // a throw after the answer (render) never paints 연결 끊김
});
