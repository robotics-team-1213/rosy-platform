import test from "node:test";
import assert from "node:assert/strict";
import { sendSignalPresence, signalIntentLabel, createSignals } from "../../fleet/server/web/signals.js";

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


test("stale signal intent has operator labels with an explicit unknown value", () => {
  assert.deepEqual(["failsafe", "manual", "cycle", "hold", "all_red", "flash_red"].map(signalIntentLabel),
    ["감독 중단", "수동", "자동 순환", "유지", "전체 적색", "적색 점멸"]);
  for (const missing of [null, undefined, ""]) assert.equal(signalIntentLabel(missing), "없음");
  for (const unknown of ["__proto__", "toString", "future_mode", 0, {}]) {
    assert.equal(signalIntentLabel(unknown), "알 수 없는 의도");
  }
});

test("actual stale signal cards render translated intent without sending commands", () => {
  class Node {
    constructor(tag) { this.tag = tag; this.children = []; this.classList = { add() {} }; }
    append(...children) { this.children.push(...children); }
    appendChild(child) { this.children.push(child); }
    replaceChildren(...children) { this.children = children; }
    setAttribute() {}
    addEventListener() {}
  }
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: (tag) => new Node(tag) };
  try {
    const nodes = Object.fromEntries(["signal-cards", "signals-state", "signals-hint"].map((id) => [id, new Node("div")]));
    const row = { signal_id: "fixture-signal", online: true, mode: "flash_red", requires_command: true,
      lamps: { red: true }, intent: { mode: "manual" }, intent_age_s: 12.5 };
    const forbidden = () => { throw new Error("render must not send a command"); };
    const console = createSignals({ scope: { guard: (handler) => handler }, el: (id) => nodes[id],
      view: { signals: { fixture: row } }, call: forbidden, log: forbidden, refreshState: forbidden });
    const paragraphs = (node) => [ ...(node.tag === "p" ? [node.textContent] : []), ...node.children.flatMap(paragraphs) ];
    console.render();
    assert.deepEqual(paragraphs(nodes["signal-cards"]), ["재명령 필요 — 마지막 의도 수동 · 12s 전"]);
    row.intent.mode = "__proto__";
    console.render();
    assert.deepEqual(paragraphs(nodes["signal-cards"]), ["재명령 필요 — 마지막 의도 알 수 없는 의도 · 12s 전"]);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
