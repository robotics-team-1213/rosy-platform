import test from "node:test";
import assert from "node:assert/strict";
const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
globalThis.location = { origin: "http://localhost" };
const { developmentToken } = await import("../../../../applications/fleet/web/shared/development-auth.js");

test("development mode never mints anonymous credentials, including after a stale bearer", async () => {
  for (const token of ["", "retired-development-token"]) {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push([new URL(url).pathname, options.method || "GET"]);
      if (url.endsWith("/auth/connection")) return Response.json({mode: "development"});
      if (url.endsWith("/api/fleet/session")) return Response.json({}, {status: 401});
      assert.fail("No anonymous session request is allowed");
    };
    assert.equal(await developmentToken(token), null);
    assert.ok(calls.every(([, method]) => method === "GET"));
  }
});

test("an existing configured credential can still connect in development", async () => {
  globalThis.fetch = async url => Response.json(url.endsWith("/auth/connection") ? {mode: "development"} :
    {principal_id: "alice", role: "viewer"});
  assert.equal(await developmentToken("configured-human-token"), "configured-human-token");
});
