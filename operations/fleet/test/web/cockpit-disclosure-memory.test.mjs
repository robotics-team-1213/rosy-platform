import assert from "node:assert/strict";
import test from "node:test";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { bindDisclosureMemory } = await import("/console/assets/cockpit-telemetry.js");

function makeDetails(id, initialOpen = false) {
  const listeners = new Map();
  return {
    id,
    open: initialOpen,
    addEventListener(type, fn) { listeners.set(type, fn); },
    removeEventListener(type, fn) {
      if (listeners.get(type) === fn) listeners.delete(type);
    },
    toggleTo(next) {
      this.open = next;
      listeners.get("toggle")?.();
    },
  };
}

test("bindDisclosureMemory restores saved state, skips unset keys, and persists toggles", () => {
  const backing = new Map([
    ["rosy.fleet.disclosure.console-diagnostics", "1"],
    ["rosy.fleet.disclosure.chain-status", "0"],
  ]);
  const storage = {
    getItem: (k) => (backing.has(k) ? backing.get(k) : null),
    setItem: (k, v) => backing.set(k, v),
  };

  const diag = makeDetails("console-diagnostics", false);
  const chain = makeDetails("chain-status", true);
  const trips = makeDetails("trip-receipt-history", false);

  const unbind = bindDisclosureMemory([diag, chain, trips, null], storage);

  assert.equal(diag.open, true);
  assert.equal(chain.open, false);
  assert.equal(trips.open, false);

  trips.toggleTo(true);
  assert.equal(backing.get("rosy.fleet.disclosure.trip-receipt-history"), "1");

  unbind();
  trips.toggleTo(false);
  assert.equal(backing.get("rosy.fleet.disclosure.trip-receipt-history"), "1");
});

test("bindDisclosureMemory ignores storage exceptions cleanly", (t) => {
  const brokenStorage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("quota"); },
  };
  const diag = makeDetails("console-diagnostics", true);
  const unbind = bindDisclosureMemory([diag], brokenStorage);
  assert.equal(diag.open, true);
  diag.toggleTo(false);
  assert.equal(diag.open, false);
  unbind();

  const desc = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    get() { throw new Error("SecurityError"); },
  });
  t.after(() => {
    if (desc) Object.defineProperty(globalThis, "sessionStorage", desc);
    else delete globalThis.sessionStorage;
  });
  const unbindDefault = bindDisclosureMemory([diag]);
  diag.toggleTo(true);
  assert.equal(diag.open, true);
  unbindDefault();
});
