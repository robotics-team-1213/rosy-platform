import test from "node:test";
import assert from "node:assert/strict";

import { STALE_STATE_S, staleAgeS } from "../../fleet/server/web/state-age.js";

const T0 = 1_000_000;
const row = (extra) => ({ robot_id: "a", online: true, state_age_s: 0.4, ...extra });

test("hub row 2.5 s old + received 3 s ago is stale (5.5 s)", () => {
  assert.equal(STALE_STATE_S, 5);
  assert.equal(staleAgeS(row({ state_age_s: 2.5 }), T0, T0 + 3000), 6);
});

test("REST row 0.4 s old + received 1 s ago is unchanged", () => {
  assert.equal(staleAgeS(row(), T0, T0 + 1000), null);
});

test("REST row received 6 s ago is stale", () => {
  assert.equal(staleAgeS(row(), T0, T0 + 6000), 6);
});

test("offline, missing field and never-received views are not judged", () => {
  assert.equal(staleAgeS(row({ online: false, state_age_s: null }), T0, T0 + 60000), null);
  assert.equal(staleAgeS({ robot_id: "a", online: true }, T0, T0 + 60000), null);
  assert.equal(staleAgeS(row({ state_age_s: 9 }), undefined, T0), 9);
});
