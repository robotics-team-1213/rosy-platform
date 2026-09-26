import test from "node:test";
import assert from "node:assert/strict";

import { applyRoleToControls } from "../../fleet/server/web/authorization.js";

test("viewer controls remain disabled and operator restores their prior state", () => {
  const controls = [{ disabled: false }, { disabled: true }];

  applyRoleToControls("viewer", controls);
  assert.deepEqual(controls.map((control) => control.disabled), [true, true]);

  applyRoleToControls("operator", controls);
  assert.deepEqual(controls.map((control) => control.disabled), [false, true]);
});

test("unknown roles receive read-only controls", () => {
  const controls = [{ disabled: false }];

  applyRoleToControls("unexpected", controls);

  assert.equal(controls[0].disabled, true);
});
