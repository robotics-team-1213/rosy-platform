import test from "node:test";
import assert from "node:assert/strict";
import { sendSignalPresence } from "../../fleet/server/web/signals.js";

test("presence is sent only for a visible operator console with signals", async () => {
  const calls = [];
  const call = async (...args) => { calls.push(args); };
  for (const state of [
    { operator: false, visible: true, configured: true },
    { operator: true, visible: false, configured: true },
    { operator: true, visible: true, configured: false },
  ]) await sendSignalPresence({ ...state, call });
  assert.deepEqual(calls, []);
  await sendSignalPresence({ operator: true, visible: true, configured: true, call });
  assert.deepEqual(calls, [["/api/fleet/signals/presence", { method: "POST" }]]);
});
