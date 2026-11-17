import test from "node:test";
import assert from "node:assert/strict";

const store = new Map();
globalThis.sessionStorage = {getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k)};
const { TOKEN_KEY, isSignedOut, readToken, storeToken } = await import("../../../../applications/fleet/web/shared/console-token.js");

test("storeToken keeps a token in the tab and a blank one deletes it", () => {
  storeToken("abc");
  assert.equal(store.get(TOKEN_KEY), "abc");
  assert.equal(readToken(), "abc");
  storeToken("");
  assert.equal(store.has(TOKEN_KEY), false);
  assert.equal(readToken(), "");
});

test("only 401 and a pending first-login password change mean signed out", () => {
  assert.equal(isSignedOut({status: 401}), true);
  assert.equal(isSignedOut({status: 403, code: "PASSWORD_CHANGE_REQUIRED"}), true);
  assert.equal(isSignedOut({status: 403}), false);
  assert.equal(isSignedOut({status: 500}), false);
  assert.equal(isSignedOut(undefined), false);
});
