import test from "node:test";
import assert from "node:assert/strict";

import { CATALOG_PATH, catalogRows } from "../../../../applications/fleet/web/cell/cell-object-catalog.js";

test("the catalogue is read from the cell-app route", () => {
  assert.equal(CATALOG_PATH, "/api/fleet/cell-app/object-catalog");
});

test("a measured object shows its mass and source; an unmeasured one is blocked", () => {
  const rows = catalogRows({objects: [
    {id: "container-2", kind: "green shipping container", length_mm: 60, width_mm: 30, top_height_mm: 30,
     mass_kg: 0.04823, mass_measured: {at: "2026-10-30T12:00:00+00:00", source: "cell_scale", reading: "48.23 g"},
     carry: "ok: the gate checks it against the reviewed bound"},
    {id: "container-3", length_mm: 90, width_mm: 30, top_height_mm: null, mass_kg: null, mass_measured: null,
     carry: "blocked: no measured mass (D-935)"},
  ]});
  assert.deepEqual(rows[0], ["container-2 (green shipping container)", "60 × 30 × 30", "48.2 g",
    "2026-10-30T12:00:00+00:00 · cell_scale", "무게 있음 · 운반 때 상한 확인"]);
  assert.deepEqual(rows[1], ["container-3", "90 × 30 × —", "미측정", "—", "불가 · 잰 무게 없음"]);
  assert.deepEqual(catalogRows(null), []);
});
