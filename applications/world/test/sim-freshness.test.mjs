import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// No package.json "type": load the browser module as ESM the way factory-actors.test.mjs does.
const source = await readFile(new URL("../web/sim-freshness.js", import.meta.url), "utf8");
const { simFreshness } = await import(`data:text/javascript,${encodeURIComponent(source)}`);

test("SIM freshness comes from the server fields only", () => {
  assert.deepEqual(simFreshness({ age_ms: 400, fresh_for_ms: 2600 }), { state: "fresh", ageS: 0 });
  assert.deepEqual(simFreshness({ age_ms: 12_400, fresh_for_ms: 0 }), { state: "delayed", ageS: 12 });
  assert.equal(simFreshness({ observed_at_ms: Date.now() }), null);
  assert.equal(simFreshness({ age_ms: 1, fresh_for_ms: -1 }), null);
});
