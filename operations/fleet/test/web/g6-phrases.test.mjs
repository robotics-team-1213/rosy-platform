import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Single source of truth: the function embedded in test/browser_harness.py (python string, doubled backslashes).
const py = readFileSync(new URL("../../../../test/browser_harness.py", import.meta.url), "utf8");
const body = py.split("// G6-fn-begin")[1].split("// G6-fn-end")[0].replaceAll("\\\\", "\\");
const repeatedFreshness = new Function(`${body}; return repeatedFreshness;`)();

test("G6 flags identical full phrases only", () => {
  assert.equal(repeatedFreshness("3453초 전 3453초 전 3453초 전 3453초 전")[0].count, 4);
  assert.equal(repeatedFreshness("연결됨 · 3453초 전 · 3453초 전").length, 1);
  assert.equal(repeatedFreshness("A · 30초 전 B · 30초 전").length, 1);
  assert.equal(repeatedFreshness("상태 5초 전 안전 정상 마지막 응답: 5초 전").length, 0);
  assert.equal(repeatedFreshness("상태 5초 전 안전 정상 상태 5초 전").length, 1);
  assert.equal(repeatedFreshness("상태 5초 전 마지막 응답: 7분 전").length, 0);
});
