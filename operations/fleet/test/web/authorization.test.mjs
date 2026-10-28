import test from "node:test";
import assert from "node:assert/strict";

import { OPERATOR_REASON, applyRoleToControls } from "../../../../applications/fleet/web/shared/authorization.js";
import { createConfirmedAction } from "../../../../applications/fleet/web/confirmed-action.js";
import { createPageScope } from "../../../../shared/web/scope.js";

test("a pending confirmation belongs to its original named operator", async () => {
  for (const changed of [false, true]) {
    const scope = createPageScope({events: new EventTarget()});
    const auth = {token: '', role: 'operator', principal: 'bob', locked: false};
    let finish, requests = 0;
    const confirmation = new Promise(resolve => { finish = resolve; });
    const action = createConfirmedAction({scope, identity: () => ({...auth}), confirm: () => confirmation});
    const running = action.run({eligible: () => true, request: () => { requests++; }, onError: error => { throw error; }});
    if (changed) auth.principal = 'alice';
    finish(true);
    await running;
    assert.equal(requests, changed ? 0 : 1);
    scope.dispose();
  }
});

// D-359 §5.3: the lock reads and writes the `reason` attribute, so the fakes carry attributes.
function fakeControl(disabled, localName = "input") {
  const attributes = new Map();
  return {
    disabled,
    localName,
    getAttribute: (name) => (attributes.has(name) ? attributes.get(name) : null),
    setAttribute: (name, value) => attributes.set(name, String(value)),
    removeAttribute: (name) => attributes.delete(name),
  };
}

test("viewer controls remain disabled and operator restores their prior state", () => {
  const controls = [fakeControl(false), fakeControl(true)];

  applyRoleToControls("viewer", controls);
  assert.deepEqual(controls.map((control) => control.disabled), [true, true]);

  applyRoleToControls("operator", controls);
  assert.deepEqual(controls.map((control) => control.disabled), [false, true]);
});

test("unknown roles receive read-only controls", () => {
  const controls = [fakeControl(false)];

  applyRoleToControls("unexpected", controls);

  assert.equal(controls[0].disabled, true);
});

test("a locked shared button states the operator reason and gets its own back", () => {
  const button = fakeControl(true, "ui-button");
  button.setAttribute("reason", "대형 없음");

  applyRoleToControls("viewer", [button]);
  assert.equal(button.getAttribute("reason"), OPERATOR_REASON);

  applyRoleToControls("operator", [button]);
  assert.equal(button.getAttribute("reason"), "대형 없음");
  assert.equal(button.disabled, true);
});

test("a button inside a role-lock group shares the group's one note instead of repeating the reason", () => {
  const note = { id: "formation-role-lock", hidden: true };
  const button = fakeControl(false, "ui-button");
  button.setAttribute("reason", "대형 없음");
  button.closest = () => ({ querySelector: () => note });

  applyRoleToControls("viewer", [button]);
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute("reason"), null);
  assert.equal(note.hidden, false);
  assert.equal(button.getAttribute("aria-describedby"), "formation-role-lock");

  applyRoleToControls("operator", [button]);
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute("reason"), "대형 없음");
  assert.equal(note.hidden, true);
  assert.equal(button.getAttribute("aria-describedby"), null);
});
