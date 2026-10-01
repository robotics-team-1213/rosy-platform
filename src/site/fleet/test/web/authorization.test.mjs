import test from "node:test";
import assert from "node:assert/strict";

import { OPERATOR_REASON, applyRoleToControls } from "../../fleet/server/web/authorization.js";

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
