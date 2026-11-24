import test from "node:test";
import assert from "node:assert/strict";

import {
  buildZoneBlueprintModel,
  formatZoneDetailRows,
  resolveBlueprintTarget,
} from "../../../../applications/fleet/web/map/zone-blueprint-model.js";

test("buildZoneBlueprintModel handles null/empty/partial payloads without throwing", () => {
  const empty = buildZoneBlueprintModel();
  assert.deepEqual(empty.items, []);
  assert.deepEqual(empty.stops, []);
  assert.deepEqual(empty.stagingBays, []);
  assert.deepEqual(empty.exportStations, []);
  assert.deepEqual(empty.armZones, []);
  assert.deepEqual(empty.worldBounds, { minX: -1, maxX: 1, minY: -1, maxY: 1 });
  assert.equal(resolveBlueprintTarget(empty, "S1"), null);
  assert.deepEqual(formatZoneDetailRows(null, empty), []);
});

test("buildZoneBlueprintModel normalizes stops, bays, exports, arm zones, handoffs, and resolves aliases", () => {
  const model = buildZoneBlueprintModel({
    sitePoints: {
      vehicle_stops: [
        {
          id: "S1",
          name: "수령구 S1",
          kind: "stop",
          port_role: "outbound_exit",
          pose: { x: -0.68, y: -0.14, yaw: -1.57 },
          pinned: true,
          stop_zone: [[-0.8, -0.25], [-0.55, -0.25], [-0.55, -0.05], [-0.8, -0.05]],
          edges_in: ["e1"],
          edges_out: ["e2"],
          status: "verified",
          dispatchable: true,
          rule: { role: "load", timeout_s: 15 },
        },
      ],
      arm_zones: {
        tier_height_mm: 32.4,
        zones: [
          {
            id: "yard",
            label: "장치 야드",
            role: "보관",
            grid: { rows: 3, columns: 6, tiers: 3 },
            slot_cells: 3,
            arms: ["arm_a", "arm_b"],
            status: "planned_unverified",
            hold_boundary: { columns: [3, 4] },
            slots: [
              {
                id: "yard:r1-s1",
                label: "1행 1~3열",
                row: 1,
                slot: 1,
                columns: [1, 3],
                hold: 1,
                arms: ["arm_a", "arm_b"],
                tiers: [{ tier: 1, id: "yard:r1-s1-t1", item: "ship-h2r0-l0" }],
              },
            ],
          },
        ],
        aliases: {
          legacy_station_zones: { EXP_S5_PALLET: "yard" },
          legacy_layout: { "yard-r1-c1": "yard:r1-s1" },
        },
      },
      handoffs: [
        { id: "outbound_stand_load", vehicle_stop_id: "S_OUT", vehicle_exit_stop_id: "S1", cell_zone_id: "stand", flow: ["stand", "S_OUT", "S1"] },
      ],
    },
    stationZones: {
      staging_bays: [
        { id: "STG_C2", place_id: "C2", name: "임시칸 1", x: 0.35, y: -0.25, yaw_deg: 0, speed_cap_mps: 0.02, max_step_m: 0.015 },
      ],
      export_stations: [
        { id: "EXP_S1", place_id: "S1", name: "반출대 1", cell_id: "cell_ab", arm_id: "arm_a", src_site: "belt", dst_site: "stand", tier: 1, x: -0.68, y: -0.14, yaw_deg: -90 },
      ],
    },
    cellTasks: {
      tasks: [{ task_id: "ct-1", state: "QUEUED", src_site: "belt", dst_site: "yard:r1-s1-t1", arm_id: "arm_a" }],
    },
  });

  assert.equal(model.stops.length, 1);
  assert.equal(model.stagingBays.length, 1);
  assert.equal(model.exportStations.length, 1);
  assert.equal(model.armZones.length, 1);
  assert.equal(model.tierHeightMm, 32.4);
  assert.equal(model.items.length, 4);

  assert.equal(resolveBlueprintTarget(model, "s1")?.id, "S1");
  assert.equal(resolveBlueprintTarget(model, "C2")?.id, "STG_C2");
  assert.equal(resolveBlueprintTarget(model, "EXP_S5_PALLET")?.id, "yard");
  assert.equal(resolveBlueprintTarget(model, "yard:r1-s1")?.id, "yard");

  const yardRows = formatZoneDetailRows(resolveBlueprintTarget(model, "yard"), model);
  assert.ok(yardRows.some((r) => r.term === "슬롯·단 구성" && r.value.includes("3행 × 6열 × 3단")));
  assert.ok(yardRows.some((r) => r.term === "활성 작업" && r.value.includes("ct-1")));
  for (const row of yardRows) assert.doesNotMatch(row.value, /초 전/);
});

function createMockDoc() {
  const makeEl = (tag, ns = "") => {
    const el = {
      tagName: tag,
      namespaceURI: ns,
      attributes: {},
      children: [],
      textContent: "",
      className: "",
      hidden: false,
      isConnected: false,
      setAttribute(k, v) { this.attributes[k] = String(v); },
      getAttribute(k) { return this.attributes[k] ?? null; },
      append(...nodes) {
        for (const n of nodes) {
          if (n && typeof n === "object") { n.isConnected = true; this.children.push(n); }
        }
      },
      replaceChildren(...nodes) {
        for (const old of this.children) old.isConnected = false;
        this.children = [];
        this.append(...nodes);
      },
      addEventListener() {},
      get firstElementChild() { return this.children[0] || null; },
    };
    return el;
  };
  return {
    createElement: (tag) => makeEl(tag),
    createElementNS: (ns, tag) => makeEl(tag, ns),
  };
}

function findNodes(root, pred, out = []) {
  if (!root || typeof root !== "object") return out;
  if (pred(root)) out.push(root);
  for (const child of root.children || []) findNodes(child, pred, out);
  return out;
}

test("zone-blueprint 2D and 3D render honest empty state for 0-slot arm zones and 2D adds aria-label to nodes", async () => {
  const prevDoc = globalThis.document;
  globalThis.document = createMockDoc();
  try {
    const { createZoneBlueprint2d } = await import("../../../../applications/fleet/web/map/zone-blueprint-2d.js");
    const { createZoneBlueprint3d } = await import("../../../../applications/fleet/web/map/zone-blueprint-3d.js");

    const model = buildZoneBlueprintModel({
      sitePoints: {
        vehicle_stops: [{ id: "S1", name: "수령구 S1", pose: { x: 0, y: 0, yaw: 0 }, status: "verified" }],
        arm_zones: {
          zones: [
            { id: "yard", label: "장치 야드", role: "보관", grid: { rows: 3, columns: 6, tiers: 3 }, slots: [] },
          ],
        },
      },
      stationZones: {
        staging_bays: [{ id: "STG_1", name: "대기 1", x: 0.5, y: 0.2 }],
        export_stations: [{ id: "EXP_1", name: "반출 1", x: -0.5, y: 0.2 }],
      },
    });

    const host2d = globalThis.document.createElement("div");
    const view2d = createZoneBlueprint2d(host2d);
    view2d.render(model, "S1", "all");
    const buttons = findNodes(host2d, (n) => n.tagName === "g" && n.attributes.role === "button");
    assert.equal(buttons.length, 3);
    assert.match(buttons[0].attributes["aria-label"], /정류장.*S1.*선택/);
    assert.match(buttons[1].attributes["aria-label"], /임시 대기칸.*STG_1.*선택/);
    assert.match(buttons[2].attributes["aria-label"], /반출대.*EXP_1.*선택/);

    view2d.render(model, "yard", "arm_zone");
    const empty2d = findNodes(host2d, (n) => n.className === "hint zb-empty");
    assert.equal(empty2d.length, 1);
    assert.equal(empty2d[0].textContent, "등록된 슬롯이 없습니다 · 실측 대기");
    assert.equal(findNodes(host2d, (n) => (n.attributes.class || "").includes("zb-slot-rect")).length, 0);

    const host3d = globalThis.document.createElement("div");
    const view3d = createZoneBlueprint3d(host3d);
    await view3d.render(model, "yard", "arm_zone");
    const empty3d = findNodes(host3d, (n) => n.className === "hint zb-empty");
    assert.equal(empty3d.length, 1);
    assert.equal(empty3d[0].hidden, false);
    assert.equal(empty3d[0].textContent, "등록된 슬롯이 없습니다 · 실측 대기");
    const canvas3d = findNodes(host3d, (n) => n.tagName === "canvas")[0];
    assert.equal(canvas3d.hidden, true);
  } finally {
    globalThis.document = prevDoc;
  }
});
