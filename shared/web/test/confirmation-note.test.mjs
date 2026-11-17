import assert from "node:assert/strict";
import test from "node:test";
import {createConfirmIrreversible} from "../confirmation.js";

function el(tag) {
  const listeners = {}, attrs = {};
  return {tag, listeners, attrs, children: [], value: "", style: {},
    setAttribute(k, v) { attrs[k] = v; }, removeAttribute(k) { delete attrs[k]; },
    toggleAttribute(k, on) { if (on) attrs[k] = ""; else delete attrs[k]; },
    addEventListener(k, f) { listeners[k] = f; }, append(...c) { this.children.push(...c); },
    click() { listeners.click(); }};
}

function setup(options) {
  const made = [];
  globalThis.document = {activeElement: null, createElement: tag => { const e = el(tag); made.push(e); return e; }};
  let dialog, onClose;
  const open = (d, o) => { dialog = d; onClose = o.onClose; return value => onClose(value); };
  const promise = createConfirmIrreversible(open)({message: "m", action: "삭제", ...options});
  const run = made.find(e => e.attrs.kind === "irreversible");
  return {promise, run, field: made.find(e => e.tag === "input")};
}

const pending = p => Promise.race([p, new Promise(r => setTimeout(() => r("pending"), 20))]);

test("empty note: confirm does not resolve and run stays disabled with a reason", async () => {
  const {promise, run, field} = setup({note: {label: "확인한 내용", max: 5}});
  assert.ok("disabled" in run.attrs && run.attrs.reason);
  field.value = "   "; run.click();
  assert.equal(await pending(promise), "pending");
  field.value = "abcdefg"; run.click();
  assert.equal(await pending(promise), "pending");
});

test("valid note resolves to the trimmed string", async () => {
  const {promise, run, field} = setup({note: {label: "확인한 내용", max: 5}});
  field.value = "  ok "; field.listeners.input(); run.click();
  assert.equal(await promise, "ok");
  assert.ok(!("disabled" in run.attrs));
});

test("callers without note are unchanged", async () => {
  const {promise, run, field} = setup({});
  assert.equal(field, undefined);
  run.click();
  assert.equal(await promise, true);
});
