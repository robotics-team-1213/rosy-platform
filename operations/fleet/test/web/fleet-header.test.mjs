// D-540 2 — the one header: role words, the one E-stop rule and the shared stop press.
import test from "node:test";
import assert from "node:assert/strict";

import { OPERATOR_REASON } from "../../fleet/server/web/shared/authorization.js";
import {
  SESSION_REASON, bindEstop, estopReason, roleLabel, showSession, showSignedOut,
} from "../../fleet/server/web/shared/fleet-header.js";

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
    "topbar-extra", "online-pill", "fleet-name", "clock"].map(id => [id, fakeNode(id)]));
  nodes["development-badge"].hidden = true;
  nodes["topbar-more"].setAttribute("aria-expanded", "false");
  globalThis.document = {getElementById: id => nodes[id]};
  return nodes;
}

test("the E-stop locks only on a press the server would refuse", () => {
  assert.equal(estopReason(undefined), "");            // unknown: loading or Fleet unreachable
  assert.equal(estopReason(null), SESSION_REASON);     // 401
  assert.equal(estopReason({role: "viewer"}), OPERATOR_REASON);
  assert.equal(estopReason({role: "operator"}), "");
});

test("role words are Korean; English stays out of the text", () => {
  assert.equal(roleLabel("operator"), "운영자");
  assert.equal(roleLabel("viewer"), "보기 전용");
  assert.equal(roleLabel("nobody"), "권한 없음");
});

test("a named session shows its name and role; a development session shows the badge", () => {
  const nodes = fakeHeader();
  showSession({principal_id: "bob", role: "operator"});
  assert.equal(nodes["user-role"].textContent, "bob · 운영자");
  assert.equal(nodes["user-role"].title, "bob · operator");
  assert.equal(nodes.estop.disabled, false);
  assert.equal(nodes["development-badge"].hidden, true);

  showSession({principal_id: "development-1a2b", role: "operator"});
  assert.equal(nodes["user-role"].textContent, "운영자");
  assert.match(nodes["user-role"].title, /^development-1a2b/);
  assert.equal(nodes["development-badge"].hidden, false);

  showSession({principal_id: "vic", role: "viewer"});
  assert.equal(nodes["user-role"].textContent, "vic · 보기 전용");
  assert.equal(nodes.estop.disabled, true);
  assert.equal(nodes.estop.getAttribute("reason"), OPERATOR_REASON);
});

test("a refused session locks the E-stop and opens the fold once; a lost Fleet does not lock it", () => {
  const nodes = fakeHeader();
  showSignedOut({refused: false});
  assert.equal(nodes["user-role"].textContent, "인증 필요");
  assert.equal(nodes.estop.disabled, false);

  showSignedOut();
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
