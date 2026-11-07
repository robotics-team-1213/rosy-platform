import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

// The card imports the browser's /assets/dom.js; map it to the file on disk.
const dom = new URL("../../dom.js", import.meta.url).href;
register("data:text/javascript," + encodeURIComponent(
  `export async function resolve(s, c, next) { return s === "/assets/dom.js" ? { url: "${dom}", shortCircuit: true } : next(s, c); }`));
globalThis.document ??= { querySelectorAll: () => [], createElement: () => ({ setAttribute() {}, append() {} }), addEventListener() {} };
const { personRequestLines, personRequestAnswerable } = await import("../../panels/console/person-request.js");

test("a held request reads as what to do, why, the time left and that nothing moves", () => {
  const lines = personRequestLines({ kind: "unplug_charger", text: "충전기를 뽑아 주세요", why: "주행을 시작해야 합니다", remaining_s: 125.4 });
  assert.equal(lines[0], "충전기 분리 — 충전기를 뽑아 주세요");
  assert.equal(lines[1], "이유: 주행을 시작해야 합니다");
  assert.match(lines[2], /2분 5초/);
  assert.match(lines.at(-1), /움직이거나 비상 정지를 풀지 않습니다/);
});

test("nothing held, an unreadable answer or an expired countdown is not shown as an ask", () => {
  assert.equal(personRequestLines(null), null);
  assert.equal(personRequestLines(undefined), null);
  assert.equal(personRequestLines({ kind: "other" }), null);
  assert.match(personRequestLines({ kind: "other", text: "x", remaining_s: 0 })[1], /0분 0초/);
});

test("only a person logged in with an account is offered the answer buttons, and only once", () => {
  const held = { kind: "move_robot", text: "x", why: "", remaining_s: 30 };
  assert.equal(personRequestAnswerable(held, false), false);
  assert.equal(personRequestAnswerable(held, true), true);
  assert.equal(personRequestAnswerable({ ...held, answer: { answer: "done", by: "u" } }, true), false);
  assert.equal(personRequestAnswerable(null, true), false);
  assert.match(personRequestLines(held, false).join(" "), /로그인하면 여기서도 답할 수 있습니다/);
  assert.match(personRequestLines({ ...held, answer: { answer: "cannot", by: "u" } }, true).join(" "), /"못 해요"로 답했습니다/);
});
