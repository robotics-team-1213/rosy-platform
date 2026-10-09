import test from "node:test";
import assert from "node:assert/strict";

// Field check 2026-10-10: a page minting a session on every 401 evicted the other pages' sessions.
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const stored = new Map();
globalThis.sessionStorage = { setItem: (k, v) => stored.set(k, v), getItem: (k) => stored.get(k) ?? null };
const { ISSUE_GAP_MS, issueDevelopmentSession } = await import("../../fleet/server/web/shared/development-auth.js");

test("a page issues at most one development session per gap", async () => {
  let posts = 0;
  const request = async (path, options) => {
    assert.equal(path, "/api/fleet/auth/development-session");
    assert.equal(options.method, "POST");
    posts += 1;
    return { token: `t${posts}` };
  };
  const t0 = 1_000_000;
  assert.equal(await issueDevelopmentSession(request, t0), "t1");
  assert.equal(stored.get("rosy-console-token"), "t1");
  assert.equal(await issueDevelopmentSession(request, t0 + 5000), null);
  assert.equal(await issueDevelopmentSession(request, t0 + ISSUE_GAP_MS - 1), null);
  assert.equal(posts, 1);
  assert.equal(await issueDevelopmentSession(request, t0 + ISSUE_GAP_MS), "t2");
});
