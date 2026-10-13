// D-540 2 — the one header: role words, the one E-stop rule and the shared stop press.
import test from "node:test";
import assert from "node:assert/strict";

import { OPERATOR_REASON } from "../../../site_ui/console/shared/authorization.js";
// Header unit tests isolate authorization; shared icon rendering has real-browser coverage.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const {
  SESSION_REASON, bindEstop, bindTopbarToggle, estopReason, roleLabel, showFleet, showInboxCount, showSession, showSignedOut,
} = await import("../../../site_ui/console/shared/fleet-header.js");

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
    "fleet-login", "fleet-account", "fleet-account-identity"].map(id => [id, fakeNode(id)]));
  nodes["development-badge"].hidden = true;
  nodes["topbar-more"].setAttribute("aria-expanded", "false");
  globalThis.document = {getElementById: id => nodes[id], addEventListener() {}};
  return nodes;
}

test("one theme button cycles the shared choices; one status click toggles once", () => {
  const nodes = fakeHeader();
  let preference = "dark";
  const choices = [{value: "dark", label: "dark", icon: "theme-dark"},
    {value: "light", label: "light", icon: "theme-light"},
    {value: "system", label: "system", icon: "theme-system"}];
  globalThis.window = {RosyTheme: {choices, get: () => preference, set: value => {preference = value;}}};
  globalThis.MutationObserver = class { observe() {} };
  bindTopbarToggle();
  for (const value of ["light", "system", "dark"]) {
    nodes["fleet-theme"].listeners.click();
    assert.equal(preference, value);
  }
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

test("a refused session locks the E-stop and opens the fold once; a lost Fleet does not lock it", () => {
  const nodes = fakeHeader();
  showSignedOut({refused: false});
  assert.equal(nodes["user-role"].textContent, "인증 필요");
  assert.equal(nodes.estop.disabled, false);

  showSignedOut();
  assert.equal(nodes["user-role"].getAttribute("status"), "crit");
  assert.equal(nodes.estop.disabled, true);
  assert.equal(nodes.estop.getAttribute("reason"), SESSION_REASON);
  assert.equal(nodes["topbar-extra"].dataset.open, "true");

  showSession({principal_id: "bob", role: "operator"});
  assert.equal(nodes.estop.disabled, false);
  assert.equal(nodes.estop.getAttribute("reason"), null);
  assert.equal(nodes["topbar-extra"].dataset.open, "false");  // closed again: it opened for the lock
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
