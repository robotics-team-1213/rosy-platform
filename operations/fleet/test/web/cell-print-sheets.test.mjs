import test from "node:test";
import assert from "node:assert/strict";

import { PRINT_SHEETS, pdfBytes, sheetPath } from "../../../../applications/fleet/web/cell/cell-print-sheets.js";

test("each print sheet asks the cell-app print route with its own parameters", () => {
  assert.deepEqual(PRINT_SHEETS.map(sheetPath), [
    "/api/fleet/cell-app/print-sheets/gripper-markers?ids=0,1&sizes_mm=20,25",
    "/api/fleet/cell-app/print-sheets/checkerboard?cols=8&rows=6&square_mm=15",
    "/api/fleet/cell-app/print-sheets/charuco?",
    "/api/fleet/cell-app/print-sheets/surface-markers?ids=35,36,37,38,39,40,41,42,43,44,45,46,47,48",
  ]);
});

test("the base64 body becomes the PDF's bytes", () => {
  const bytes = pdfBytes(Buffer.from("%PDF-1.4\n\xff", "latin1").toString("base64"));
  assert.equal(String.fromCharCode(...bytes.slice(0, 8)), "%PDF-1.4");
  assert.equal(bytes[9], 0xff);
});
