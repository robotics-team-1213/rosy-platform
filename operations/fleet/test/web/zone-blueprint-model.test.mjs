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
