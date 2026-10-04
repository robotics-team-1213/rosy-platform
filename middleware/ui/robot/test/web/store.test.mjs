// D-447 (b): store.state() — /ws/state 구독이 먼저, 소켓이 죽으면 REST 폴백.
// 브라우저 없이 돈다: 가짜 소켓 팩토리와 가짜 api 를 주입한다.
import test from "node:test";
import assert from "node:assert/strict";
import { createStore } from "../../shell/store.js";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function fakeSession(token = "tok-1") {
  return { token };
}

class FakeSocket {
  constructor() {
    this.sent = [];
    this.closed = false;
    this.handlers = new Map();
  }
  addEventListener(kind, fn) {
    this.handlers.set(kind, [...(this.handlers.get(kind) ?? []), fn]);
  }
  emit(kind, event = {}) {
    (this.handlers.get(kind) ?? []).forEach((fn) => fn(event));
  }
  send(text) { this.sent.push(text); }
  close() { this.closed = true; this.emit("close", { code: 1000 }); }
}

function harness({ apiCalls = [], token = "tok-1" } = {}) {
  const sockets = [];
  const apiCallsOut = [];
  const api = async (path, _options) => {
    apiCallsOut.push(path);
    const scripted = apiCalls.shift();
    if (scripted instanceof Error) throw scripted;
    return scripted ?? { robot_id: "rosy_01", via: "rest" };
  };
  const store = createStore(api, {
    session: fakeSession(token),
    createSocket: () => { const s = new FakeSocket(); sockets.push(s); return s; },
    socketUrl: () => "ws://test/ws/state",
    fallbackPollMs: 5,
    reconnectMinMs: 5,
    reconnectMaxMs: 10,
  });
  return { store, sockets, apiCalls: apiCallsOut };
}

test("auth goes in the first frame and frames reach the subscriber", () => {
  const { store, sockets } = harness();
  const seen = [];
  const scope = store.scope();
  const stop = scope.state((data) => seen.push(data));

  assert.equal(sockets.length, 1, "one socket for the first subscriber");
  sockets[0].emit("open");
  assert.deepEqual(JSON.parse(sockets[0].sent[0]), { type: "auth", token: "tok-1" });
  sockets[0].emit("message", { data: JSON.stringify({ mode: "IDLE", via: "ws" }) });
  assert.deepEqual(seen, [{ mode: "IDLE", via: "ws" }]);
  stop();
});

test("two scopes share one socket; the last unsubscribe closes it", () => {
  const { store, sockets } = harness();
  const a = store.scope(), b = store.scope();
  const stopA = a.state(() => {});
  const stopB = b.state(() => {});
  assert.equal(sockets.length, 1, "D-447: one open socket serves every panel");
  stopA();
  assert.equal(sockets[0].closed, false, "socket stays while a subscriber remains");
  stopB();
  assert.equal(sockets[0].closed, true, "last subscriber out closes the stream");
});

test("close falls back to REST polling and a live socket stops it again", async () => {
  const { store, sockets, apiCalls } = harness();
  const seen = [];
  const scope = store.scope();
  const stop = scope.state((data) => seen.push(data));

  sockets[0].emit("open");
  sockets[0].emit("close", { code: 1006 });  // network drop: reconnect + fallback
  await sleep(30);
  assert.ok(apiCalls.length >= 2, `fallback polls robot state (${apiCalls.length})`);
  assert.ok(seen.some((row) => row.via === "rest"), "fallback data is delivered");

  const restCalls = apiCalls.length;
  const reopened = sockets[1];
  reopened.emit("open");
  reopened.emit("message", { data: JSON.stringify({ via: "ws-again" }) });
  await sleep(20);
  assert.equal(apiCalls.length, restCalls, "a live socket stops the REST fallback");
  assert.ok(seen.some((row) => row.via === "ws-again"));
  stop();
});

test("4403 does not reconnect but keeps the REST fallback", async () => {
  const { store, sockets, apiCalls } = harness();
  const scope = store.scope();
  const stop = scope.state(() => {});
  sockets[0].emit("open");
  sockets[0].emit("close", { code: 4403 });
  await sleep(25);
  assert.equal(sockets.length, 1, "no reconnect after 4403");
  assert.ok(apiCalls.length >= 1, "REST fallback keeps the panels alive");
  stop();
});

test("stopAll of every scope tears the stream down", () => {
  const { store, sockets } = harness();
  const scope = store.scope();
  scope.state(() => {});
  sockets[0].emit("open");
  scope.stopAll();
  assert.equal(sockets[0].closed, true);
});
