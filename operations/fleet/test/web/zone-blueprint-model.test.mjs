import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { register } from "node:module";

globalThis.crypto ??= webcrypto;

// The 3D view imports "/common/ui.js" and "/console/assets/robot-3d-assets.js": map them for node.
register("./register-console-assets.mjs", import.meta.url);

import {
  NEAR_M,
  buildZoneBlueprintModel,
  formatZoneDetailRows,
  resolveBlueprintTarget,
} from "../../../../applications/fleet/web/map/zone-blueprint-model.js";
import {
  buildBlueprintSlotOverlays,
  buildCellStagePayload,
} from "../../../../applications/fleet/web/map/zone-blueprint-staging.js";

const SITE_MAP = {
  version: 394,
  map: {
    map_id: "world_test",
    places: [
      { id: "S3", kind: "stop", x: 0.745, y: -0.207, yaw: Math.PI },
      { id: "C2", kind: "charge", x: -0.1901, y: 0.47, yaw: -Math.PI / 2 },
      { id: "J_in", kind: "junction", x: 0.3142, y: -0.2501 },
    ],
    edges: [{
      id: "upper_east", from: "S3", to: "J_in", width_m: 0.2, direction: "one_way", drive_mode: "lane",
      polyline: [[0.745, -0.207], [0.3142, -0.2501]],
    }],
  },
};

const SITE_POINTS = {
  vehicle_stops: [
    { id: "S3", name: "하역 S3", kind: "stop", port_role: "intake_dropoff", pose: { x: 0.745, y: -0.207, yaw: Math.PI },
      status: "verified", dispatchable: true, rule: { role: "unload", timeout_s: 300 } },
    { id: "C2", name: "충전 C2", kind: "charge", port_role: "charge", pose: { x: -0.1901, y: 0.47, yaw: -Math.PI / 2 }, status: "verified" },
    { id: "S_OUT", name: "반출 S_OUT", kind: "stop", port_role: "outbound_pickup", pose: null, status: "planned_unverified" },
  ],
  arm_zones: {
    tier_height_mm: 32.4,
    zones: [
      { id: "yard", label: "장치 야드", role: "보관", grid: { rows: 3, columns: 6, tiers: 3 }, arms: ["arm_a", "arm_b"], status: "planned_unverified",
        slots: [{ id: "yard:r1-s1", label: "1행 1~3열", row: 1, slot: 1, columns: [1, 3], arms: ["arm_a", "arm_b"],
          tiers: [{ tier: 1, id: "yard:r1-s1-t1", item: "ship-h2r0-l0" }] }] },
      { id: "temp_b", label: "임시 장치 B", grid: { rows: 3, columns: 3, tiers: 3 }, slots: [] },
    ],
  },
  handoffs: [{ id: "s3_cell_s_unload", kind: "intake", vehicle_stop_id: "S3", target_cell_zones: ["yard"], flow: ["S3:stop_zone", "belt"] }],
};

const VEHICLE = { front_m: 0.04205, rear_m: -0.134, half_width_m: 0.05655 };
const AREAS = [
  { id: "CELL_AB_TABLE", name: "적층 작업대 A·B", short_name: "작업대 A·B", kind: "worktop", status: "cad_registered", height_m: 0.072,
    polygon: [[0.467, 0.2], [1.07, 0.2], [1.07, 0.96], [0.467, 0.96]] },
  { id: "yard", name: "장치 야드 (컨테이너선)", short_name: "배 (야드)", kind: "cell_zone", zone_id: "yard", status: "cad_registered",
    height_m: 0.095, evidence: "CAD 등록 후보", polygon: [[0.73, 0.208], [0.86, 0.208], [0.86, 0.524], [0.73, 0.524]] },
  { id: "BELT", name: "컨베이어", short_name: "벨트", kind: "belt", status: "cad_registered", height_m: 0.017,
    polygon: [[0.748, -0.103], [0.833, -0.103], [0.833, 0.197], [0.748, 0.197]] },
];

const STATION_ZONES = {
  vehicle: VEHICLE,
  areas: AREAS,
  staging_bays: [{ id: "STG_S3_WAIT", place_id: "S3", name: "임시칸 2", x: 0.58, y: -0.2512, speed_cap_mps: 0.02, max_step_m: 0.015 }],
  export_stations: [{ id: "EXP_S3_BELT", place_id: "S3", name: "반출대 3", cell_id: "cell_s", arm_id: "arm_s", src_site: "pinky", dst_site: "belt", tier: 1 }],
};

const siteModel = (over = {}) => buildZoneBlueprintModel({ sitePoints: SITE_POINTS, stationZones: STATION_ZONES, siteMap: SITE_MAP, ...over });
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("buildZoneBlueprintModel handles null/empty/partial payloads without throwing", () => {
  const empty = buildZoneBlueprintModel();
  assert.deepEqual(empty.items, []);
  assert.deepEqual(empty.footprints, []);
  assert.deepEqual(empty.lanes, []);
  assert.deepEqual(empty.conflicts, []);
  assert.deepEqual(empty.bounds, { minX: -1, maxX: 1, minY: -1, maxY: 1 });
  assert.deepEqual(empty.project(0.5, -0.25), [0.5, -0.25]);
  assert.equal(resolveBlueprintTarget(empty, "S1"), null);
  assert.deepEqual(formatZoneDetailRows(null, empty), []);
});

test("a zone is drawn at its site-map place; a stored YAML coordinate is flagged and never drawn", () => {
  const model = siteModel();
  const s3 = model.footprints.find((footprint) => footprint.id === "place:S3");
  assert.equal(s3.anchor, "vehicle_body");
  // yaw 180 deg: the nose (front_m) points west, the cargo tray (rear_m) sits east, toward the supply arm.
  near(Math.min(...s3.polygon.map(([x]) => x)), 0.745 - VEHICLE.front_m);
  near(Math.max(...s3.polygon.map(([x]) => x)), 0.745 - VEHICLE.rear_m);
  near(Math.min(...s3.polygon.map(([, y]) => y)), -0.207 - VEHICLE.half_width_m);
  near(Math.max(...s3.polygon.map(([, y]) => y)), -0.207 + VEHICLE.half_width_m);
  assert.deepEqual(s3.itemIds, ["S3", "STG_S3_WAIT", "EXP_S3_BELT"]);

  const staging = resolveBlueprintTarget(model, "STG_S3_WAIT");
  assert.equal(staging.x, 0.745);
  assert.equal(staging.y, -0.207);
  assert.equal(staging.footprintId, "place:S3");
  const rows = formatZoneDetailRows(staging, model);
  assert.match(rows.find((row) => row.term === "장소 S3 좌표 (m)").value, /^X 0\.7450 · Y -0\.2070$/);
  assert.match(rows.find((row) => row.term === "겹침·여유").value, /STG_S3_WAIT: YAML 좌표가 장소 S3와 17 cm 어긋남/);
  assert.deepEqual(model.conflicts.filter((conflict) => conflict.kind === "stale_yaml").map((conflict) => conflict.ids), [["place:S3"]]);

  const planned = resolveBlueprintTarget(model, "S_OUT");
  assert.equal(planned.footprintId, null);
  assert.match(formatZoneDetailRows(planned, model).find((row) => row.term === "위치").value, /활성 지도에 없음/);
});

test("a stop_zone from the site map is the footprint; without the map view lanes are missing, places are not", () => {
  const zoned = siteModel({
    sitePoints: { ...SITE_POINTS, vehicle_stops: [{ id: "S3", name: "S3", kind: "stop", pose: { x: 0.745, y: -0.207, yaw: Math.PI },
      stop_zone: [[0.7, -0.3], [0.9, -0.3], [0.9, -0.15], [0.7, -0.15]] }] },
  });
  const s3 = zoned.footprints.find((footprint) => footprint.id === "place:S3");
  assert.equal(s3.anchor, "stop_zone");
  assert.deepEqual(s3.polygon, [[0.7, -0.3], [0.9, -0.3], [0.9, -0.15], [0.7, -0.15]]);

  const noView = buildZoneBlueprintModel({ sitePoints: SITE_POINTS, stationZones: STATION_ZONES });
  assert.equal(noView.siteMap, null);
  assert.deepEqual(noView.lanes, []);
  assert.deepEqual(noView.footprints.map((footprint) => footprint.id), ["place:S3", "place:C2", "area:yard"]);
  // The lanes are unknown, so nothing is checked against them; the other checks still run.
  assert.deepEqual(noView.conflicts.map((conflict) => conflict.kind), ["stale_yaml"]);
  assert.equal(resolveBlueprintTarget(noView, "STG_S3_WAIT").x, 0.745);

  const bare = buildZoneBlueprintModel({ sitePoints: { vehicle_stops: [{ id: "S1", name: "S1", pose: null }] }, stationZones: {} });
  assert.deepEqual(bare.footprints, []);
  assert.equal(bare.vehicle, null);
});

test("arm zones take their footprint from the fixed area that names them", () => {
  const model = siteModel();
  const yard = resolveBlueprintTarget(model, "yard");
  assert.equal(yard.footprintId, "area:yard");
  near(yard.x, 0.795);
  near(yard.y, 0.366);
  assert.match(yard.subtitle, /CAD 등록 후보$/);
  const rows = formatZoneDetailRows(yard, model);
  assert.equal(rows.find((row) => row.term === "영역 근거").value, "CAD 등록 후보");
  assert.equal(rows.find((row) => row.term === "영역 크기 (cm)").value, "13 × 31.6");
  assert.ok(rows.some((row) => row.term === "슬롯·단 구성" && row.value.includes("3행 × 6열 × 3단")));

  const unplaced = resolveBlueprintTarget(model, "temp_b");
  assert.equal(unplaced.footprintId, null);
  assert.match(unplaced.subtitle, /위치 미등록$/);
  assert.deepEqual(model.links.map((link) => [link.fromPlaceId, link.toZoneId]), [["S3", "yard"]]);
});

test("conflicts: overlaps are reported, small gaps are warnings, touching and nesting are fine", () => {
  const square = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  const area = (id, polygon, extra = {}) => ({ id, name: id, kind: "worktop", polygon, ...extra });
  const model = buildZoneBlueprintModel({
    siteMap: { version: 2, map: { places: [
      { id: "A", kind: "junction", x: 0, y: 0 }, { id: "B", kind: "junction", x: 1, y: 0 },
      { id: "S9", kind: "stop", x: 0.5, y: -0.3, yaw: 0 }, { id: "S8", kind: "stop", x: 0.52, y: -0.3, yaw: 0 },
    ], edges: [{ id: "lane", from: "A", to: "B", width_m: 0.2, polyline: [[0, 0], [1, 0]] }] } },
    sitePoints: { vehicle_stops: [
      { id: "S9", name: "S9", kind: "stop", pose: { x: 0.5, y: -0.3, yaw: 0 } },
      { id: "S8", name: "S8", kind: "stop", pose: { x: 0.52, y: -0.3, yaw: 0 } },
    ] },
    stationZones: { vehicle: VEHICLE, staging_bays: [], export_stations: [], areas: [
      area("GAP_LANE", square(0.0, 0.1 + (NEAR_M - 0.005), 0.2, 0.3)),
      area("IN_TOL_LANE", square(0.3, 0.1 - (NEAR_M - 0.005), 0.5, 0.3)),
      area("ON_LANE", square(0.6, 0.1 - (NEAR_M + 0.005), 0.8, 0.3)),
      area("P1", square(0, 0.4, 0.5, 0.7)), area("P2", square(0.4, 0.4, 0.9, 0.7)),
      area("T1", square(0, 1, 0.5, 1.5)), area("T2", square(0.5, 1, 1, 1.5)),
      area("N1", square(2, 0, 3, 1)), area("N2", square(2.2, 0.2, 2.8, 0.8)),
      area("ON_ROBOT", square(0.47, -0.35, 0.53, -0.25)),
    ] },
  });
  const texts = model.conflicts.map((conflict) => conflict.text);
  assert.equal(NEAR_M, 0.02);
  assert.deepEqual(texts, [
    "P1 ↔ P2: 영역 겹침",
    "GAP_LANE ↔ 차로 lane: 여유 15 mm",
    "IN_TOL_LANE ↔ 차로 lane: 표준 폭 15 mm 겹침 (오차 범위)",
    "ON_LANE ↔ 차로 lane: 표준 폭 25 mm 안으로 들어옴",
    "ON_ROBOT ↔ S9: 정차 공간 겹침",
    "ON_ROBOT ↔ S8: 정차 공간 겹침",
    "S9 ↔ S8: 정차 공간 겹침",
  ]);
  assert.deepEqual(model.conflicts.map((conflict) => conflict.kind),
    ["overlap", "near", "near", "overlap", "overlap", "overlap", "overlap"]);
  assert.deepEqual(model.conflictsOf("area:T1"), []);
  // A zone that shares an edge with the worktop it sits on is nested, not overlapping.
  const nested = buildZoneBlueprintModel({ stationZones: { areas: [
    area("TOP", square(0, 0, 1, 1)), area("ZONE", square(0, 0.2, 0.4, 1)),
  ] } });
  assert.deepEqual(nested.conflicts, []);
  const overlapRow = formatZoneDetailRows(resolveBlueprintTarget(model, "S9"), model).find((row) => row.term === "겹침·여유");
  assert.match(overlapRow.value, /ON_ROBOT ↔ S9: 정차 공간 겹침 \/ S9 ↔ S8: 정차 공간 겹침/);
});

test("a concave stop zone is only under-measured: an area in its notch is no overlap, a real one is found", () => {
  // Boomerang stop zone: the notch (outside) is the triangle (2,0), (1,1), (2,2).
  const boomerang = [[0, 0], [2, 0], [1, 1], [2, 2], [0, 2]];
  const build = (polygon) => buildZoneBlueprintModel({
    sitePoints: { vehicle_stops: [{ id: "S7", name: "S7", kind: "stop", pose: { x: 0.2, y: 0.2, yaw: 0 }, stop_zone: boomerang }] },
    stationZones: { vehicle: VEHICLE, areas: [{ id: "AREA", name: "area", kind: "worktop", polygon }] },
  });
  assert.equal(build([[1.5, 0.95], [1.8, 0.95], [1.8, 1.05], [1.5, 1.05]]).conflicts.length, 0);
  assert.deepEqual(build([[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]]).conflicts.map((c) => c.kind), ["overlap"]);
});

test("the view follows the site map's screen turn and labels stay in world metres", () => {
  const model = siteModel({ siteMap: { ...SITE_MAP, map: { ...SITE_MAP.map, view_turn_deg: 90 } } });
  assert.equal(model.siteMap.viewTurnDeg, 90);
  assert.deepEqual(model.project(1, 0).map((value) => Math.round(value)), [0, -1]);   // +X points down
  assert.deepEqual(model.project(0, 1).map((value) => Math.round(value)), [1, 0]);    // +Y points right
  near(model.unproject(0, -1)[0], 1);
  near(model.unproject(0, -1)[1], 0);
  assert.equal(model.axisLabel, "+X ↓ · +Y →");
  const [vx, vy] = model.project(0.745, -0.207);
  assert.ok(vx > model.bounds.minX && vx < model.bounds.maxX && vy > model.bounds.minY && vy < model.bounds.maxY);
  assert.equal(siteModel().siteMap.viewTurnDeg, 0);
  assert.equal(siteModel().axisLabel, "+X → · +Y ↑");
});

function createMockDoc() {
  const makeEl = (tag, ns = "") => {
    const el = {
      tagName: tag,
      namespaceURI: ns,
      attributes: {},
      children: [],
      listeners: {},
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
      addEventListener(type, fn) { this.listeners[type] = fn; },
    };
    return el;
  };
  return {
    createElement: (tag) => makeEl(tag),
    createElementNS: (ns, tag) => makeEl(tag, ns),
    createTextNode: (text) => ({ textContent: text }),
  };
}

function findNodes(root, pred, out = []) {
  if (!root || typeof root !== "object") return out;
  if (pred(root)) out.push(root);
  for (const child of root.children || []) findNodes(child, pred, out);
  return out;
}

test("the 2D map draws the lanes at their width and selectable footprints; 3D shows an empty state", async () => {
  const prevDoc = globalThis.document;
  globalThis.document = createMockDoc();
  try {
    const { createZoneBlueprint2d } = await import("../../../../applications/fleet/web/map/zone-blueprint-2d.js");
    const { createZoneBlueprint3d } = await import("../../../../applications/fleet/web/map/zone-blueprint-3d.js");
    const model = siteModel();
    const selected = [];

    const host2d = globalThis.document.createElement("div");
    const view2d = createZoneBlueprint2d(host2d, { onSelect: (id) => selected.push(id) });
    view2d.render(model, "S3", "all");
    const lanes = findNodes(host2d, (n) => n.tagName === "polyline" && /^zb-lane($| )/.test(n.attributes.class || ""));
    assert.equal(lanes.length, 1);
    const viewBox = findNodes(host2d, (n) => n.tagName === "svg")[0].attributes.viewBox.split(" ").map(Number);
    const scale = Math.min((viewBox[2] - 112) / (model.bounds.maxX - model.bounds.minX), (viewBox[3] - 112) / (model.bounds.maxY - model.bounds.minY));
    assert.equal(lanes[0].attributes["stroke-width"], (0.2 * scale).toFixed(1));
    assert.equal(findNodes(host2d, (n) => n.tagName === "path" && n.attributes.class === "zb-lane-arrow").length, 1);

    const buttons = findNodes(host2d, (n) => n.tagName === "g" && n.attributes.role === "button");
    assert.deepEqual(buttons.map((button) => button.attributes["data-zone-id"]), ["yard", "S3", "C2"]);
    assert.match(buttons[1].attributes["aria-label"], /정류장 S3 선택/);
    assert.match(buttons[2].attributes["aria-label"], /충전 칸 C2 선택/);
    assert.equal(buttons[1].attributes["data-selected"], "true");
    assert.equal(buttons[2].attributes["data-selected"], "false");
    assert.equal(findNodes(buttons[1], (n) => n.tagName === "line" && n.attributes.class === "zb-tray").length, 1);
    assert.equal(findNodes(buttons[2], (n) => n.tagName === "line" && n.attributes.class === "zb-tray").length, 1);
    assert.equal(findNodes(host2d, (n) => n.tagName === "polygon" && (n.attributes.class || "").includes("zb-area-belt")).length, 1);
    assert.equal(findNodes(host2d, (n) => n.tagName === "circle" && n.attributes.class === "zb-junction").length, 1);
    assert.equal(findNodes(host2d, (n) => n.tagName === "line" && n.attributes.class === "zb-handoff-line").length, 1);
    assert.equal(findNodes(host2d, (n) => n.className === "zb-legend").length, 1);
    buttons[2].listeners.click();
    assert.deepEqual(selected, ["C2"]);

    view2d.render(model, "STG_S3_WAIT", "staging");
    const filtered = findNodes(host2d, (n) => n.tagName === "g" && n.attributes.role === "button" && n.attributes["data-zone-id"] === "STG_S3_WAIT");
    assert.equal(filtered.length, 1);
    assert.equal((filtered[0].attributes.class || "").includes("zb-dim"), false);
    const dimmed = findNodes(host2d, (n) => n.tagName === "g" && n.attributes.role === "button" && n.attributes["data-zone-id"] === "C2");
    assert.match(dimmed[0].attributes.class, /zb-dim/);

    const host3d = globalThis.document.createElement("div");
    const view3d = createZoneBlueprint3d(host3d);
    await view3d.render(model, "S3", "all");
    assert.equal(findNodes(host3d, (n) => n.className === "hint zb-empty")[0].hidden, true);
    const bare = buildZoneBlueprintModel({ sitePoints: { vehicle_stops: [{ id: "S1", name: "S1", pose: { x: 0, y: 0, yaw: 0 } }] } });
    await view3d.render(bare, "S1", "all");
    const empty3d = findNodes(host3d, (n) => n.className === "hint zb-empty");
    assert.equal(empty3d.length, 1);
    assert.equal(empty3d[0].hidden, false);
    assert.equal(empty3d[0].textContent, "표시할 구역 정보가 없습니다.");
    assert.equal(findNodes(host3d, (n) => n.tagName === "canvas")[0].hidden, true);
  } finally {
    globalThis.document = prevDoc;
  }
});

test("buildBlueprintSlotOverlays projects arm slots, stations, tasks, and guide robots; buildCellStagePayload builds valid POST payloads", () => {
  const model = siteModel({
    cellTasks: {
      tasks: [
        {
          task_id: "ct-1",
          status: "RUNNING",
          src_site: "belt",
          dst_site: "ship-h2r0-l0",
          dst_site_id: "yard:r1-s1-t1",
          arm_id: "arm_a",
          cell_id: "cell_ab",
        },
        {
          task_id: "ct-done",
          status: "COMPLETED",
          src_site: "belt",
          dst_site: "ship-h2r0-l0",
          dst_site_id: "yard:r1-s1-t1",
          arm_id: "arm_a",
          cell_id: "cell_ab",
        },
      ],
    },
  });
  const guide = {
    robots: [{ robot_id: "rosy_01", pose: { x: 0.745, y: -0.207, yaw: Math.PI, state: "IDLE" }, lane: { next_place: { place_id: "S3" } } }],
  };
  const overlays = buildBlueprintSlotOverlays(model, guide);
  const slot = overlays.slots.find((s) => s.id === "yard:r1-s1");
  assert.ok(slot);
  assert.equal(slot.status, "planned_unverified");
  assert.equal(slot.taskState, "RUNNING");
  assert.equal(overlays.robots.length, 1);
  assert.equal(overlays.robots[0].placeId, "S3");
  assert.equal(overlays.taskFlows.length, 1);
  assert.equal(overlays.taskFlows[0].id, "ct-1");
  assert.equal(overlays.taskFlows[0].armId, "arm_a");

  const belt = overlays.slots.find((s) => s.id === "station:belt");
  const pinky = overlays.slots.find((s) => s.id === "station:pinky");
  assert.ok(belt && pinky);

  const ab = buildCellStagePayload({ src: belt, dst: slot, tier: 2 });
  assert.equal(ab.error, "");
  assert.deepEqual(ab.payload, {
    cell_id: "cell_ab",
    src_site: "belt",
    dst_site: "yard:r1-s1-t1",
    tier: 1,
    propose: false,
  });

  const cs = buildCellStagePayload({ src: pinky, dst: belt, tier: 3 });
  assert.equal(cs.error, "");
  assert.deepEqual(cs.payload, {
    cell_id: "cell_s",
    arm_id: "arm_s",
    src_site: "pinky",
    dst_site: "belt",
    tier: 1,
    propose: false,
  });

  assert.match(buildCellStagePayload({ src: pinky, dst: slot }).error, /벨트/);
  assert.match(buildCellStagePayload({ src: slot, dst: slot }).error, /같습니다/);
});
