"""Unit tests for bindDisclosureMemory in applications/fleet/web/shared/cockpit-telemetry.js."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

NODE_SCRIPT = r"""
import assert from "node:assert/strict";
import { bindDisclosureMemory } from "/console/assets/cockpit-telemetry.js";

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

const brokenStorage = {
  getItem() { throw new Error("blocked"); },
  setItem() { throw new Error("quota"); },
};
const brokenDiag = makeDetails("console-diagnostics", true);
const unbindBroken = bindDisclosureMemory([brokenDiag], brokenStorage);
assert.equal(brokenDiag.open, true);
brokenDiag.toggleTo(false);
assert.equal(brokenDiag.open, false);
unbindBroken();

const desc = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage");
Object.defineProperty(globalThis, "sessionStorage", {
  configurable: true,
  get() { throw new Error("SecurityError"); },
});
try {
  const unbindDefault = bindDisclosureMemory([brokenDiag]);
  brokenDiag.toggleTo(true);
  assert.equal(brokenDiag.open, true);
  unbindDefault();
} finally {
  if (desc) Object.defineProperty(globalThis, "sessionStorage", desc);
  else delete globalThis.sessionStorage;
}
"""


def test_bind_disclosure_memory_in_node() -> None:
    if shutil.which("node") is None:
        pytest.skip("node runtime unavailable")
    proc = subprocess.run(
        [
            "node",
            "--import",
            "./operations/fleet/test/web/register-console-assets.mjs",
            "--input-type=module",
            "-e",
            NODE_SCRIPT,
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout + proc.stderr).strip()
