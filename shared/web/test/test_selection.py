"""C18 selection store contract executed directly against shared/web/selection.js in Node."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SELECTION_URL = (ROOT / "applications/fleet/web/shared/selection.js").as_uri()


def test_create_selection_store_contract():
    script = f"""
import assert from "node:assert/strict";
import {{ createSelection }} from {SELECTION_URL!r};

const sel = createSelection(null);
assert.equal(sel.get(), null);
assert.equal(sel.set(null), false);

const events = [];
const offA = sel.subscribe((id, meta) => events.push(["A", id, meta?.source ?? null]));
const offB = sel.subscribe((id, meta) => events.push(["B", id, meta?.source ?? null]));
assert.equal(sel.set("rosy_01", {{ source: "dock" }}), true);
assert.equal(sel.get(), "rosy_01");
assert.deepEqual(events, [["A", "rosy_01", "dock"], ["B", "rosy_01", "dock"]]);

// Duplicate value is a no-op.
assert.equal(sel.set("rosy_01", {{ source: "map" }}), false);
assert.equal(events.length, 2);

// Re-entrant set() notifies the newer value first and finishes cleanly without re-sending superseded outer notifications.
let offC = null;
offC = sel.subscribe((id) => {{
  events.push(["C", id, null]);
  if (id === "arm_a") sel.set("arm_b", {{ source: "nested" }});
}});
sel.subscribe((id) => events.push(["D", id, null]));
sel.set("arm_a", {{ source: "outer" }});
assert.equal(sel.get(), "arm_b");
assert.deepEqual(events.slice(2), [
  ["A", "arm_a", "outer"],
  ["B", "arm_a", "outer"],
  ["C", "arm_a", null],
  ["A", "arm_b", "nested"],
  ["B", "arm_b", "nested"],
  ["C", "arm_b", null],
  ["D", "arm_b", null],
]);

offA();
offB();
offC();
sel.set("rosy_02", {{ source: "dock" }});
assert.equal(sel.get(), "rosy_02");
assert.deepEqual(events.at(-1), ["D", "rosy_02", null]);
"""
    proc = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
