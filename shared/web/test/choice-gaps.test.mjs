import {test} from "node:test";
import assert from "node:assert/strict";
import {statusSpec, sameChoiceItems} from "../choice-logic.js";

test("statusSpec: a string is the state alone, an object carries text/icon/danger, anything else is no status", () => {
  assert.deepEqual(statusSpec("delayed"), {state: "delayed"});
  assert.deepEqual(statusSpec({state: "locked", text: "승격됨", icon: "lock"}), {state: "locked", text: "승격됨", icon: "lock", danger: false});
  assert.equal(statusSpec(undefined), null);
  assert.equal(statusSpec({text: "no state"}), null);
});

test("sameChoiceItems: fresh objects with the same rendered fields are the same, any rendered change is not", () => {
  const list = () => [{id: "a", label: "A", secondary: "x", status: {state: "delayed", text: "late"}}, {id: "b", label: "B", disabled: true}];
  assert.equal(sameChoiceItems(list(), list(), "list"), true);
  assert.equal(sameChoiceItems(list(), [...list(), {id: "c", label: "C"}], "list"), false);
  for (const change of [{secondary: "y"}, {status: "delayed"}, {status: {state: "delayed", text: "later"}}, {status: {state: "delayed", text: "late", icon: "wifi"}}, {label: "AA"}, {disabled: true}, {thumb: "t.png"}, {icon: "info"}]) {
    const next = list(); Object.assign(next[0], change);
    // {disabled: true} is a real change only for a field that was not already true; item 0 was enabled
    assert.equal(sameChoiceItems(list(), next, "list"), false, JSON.stringify(change));
  }
  assert.equal(sameChoiceItems([{id: "a", label: "A", disabled: false}], [{id: "a", label: "A"}], "list"), true);  // false and missing draw the same
  const group = () => [{value: "1", label: "1배속"}, {value: "2", label: "2배속", reason: "막힘", disabled: true}];
  assert.equal(sameChoiceItems(group(), group(), "group"), true);
  const other = group(); other[1].reason = "다른 이유";
  assert.equal(sameChoiceItems(group(), other, "group"), false);
});
