import test from "node:test";
import assert from "node:assert/strict";

const {
  PLACE_SNAP_M,
  pointInPolygon,
  polygonCentroid,
  serverStopVerdict,
  stopZoneSummaryForRobot,
  stopZoneOccupants,
  drawStopZones,
} = await import("../../../../applications/fleet/web/map/stop-zone-overlay.js");
const { renderHoverCard } = await import("../../../../applications/fleet/web/map/map-hover-card.js");
const { nextStepFor, createQueues } = await import("../../../../applications/fleet/web/queues.js");

const S3_ZONE = [[-0.2, 0.2], [0.2, 0.2], [0.2, -0.2], [-0.2, -0.2]];
const SITE_MAP = {
  map_id: "m1",
  places: [{ id: "S3", name: "Shuttle", x: 0, y: 0, stop_zone: S3_ZONE }],
};

test("pointInPolygon and polygonCentroid handle inside, outside, and invalid polygons", () => {
  assert.equal(PLACE_SNAP_M, 0.14);
  assert.equal(pointInPolygon(0, 0, S3_ZONE), true);
  assert.equal(pointInPolygon(0.5, 0, S3_ZONE), false);
  assert.equal(pointInPolygon(NaN, 0, S3_ZONE), false);
  assert.equal(pointInPolygon(0, 0, [[0, 0], [1, 0]]), false);
  assert.deepEqual(polygonCentroid(S3_ZONE), { x: 0, y: 0 });
});

test("serverStopVerdict and stopZoneSummaryForRobot separate server IN from client 표시 계산", () => {
  const robot = { robot_id: "rosy_46", online: true, state: { safety: { estop: false } } };
  const insideGuide = { robot_id: "rosy_46", pose: { x: 0.02, y: -0.02, yaw: 0 } };
  // Client pose inside stop_zone stays neutral ("표시 계산"), never green ("good")
  const displayIn = stopZoneSummaryForRobot(robot, insideGuide, SITE_MAP, []);
  assert.equal(displayIn.tone, "neutral");
  assert.equal(displayIn.source, "display");
  assert.match(displayIn.label, /S3 구역 안 \(표시 계산\)/);

  // Near outside within 0.60m reports distance estimate
  const outsideGuide = { robot_id: "rosy_46", pose: { x: 0.45, y: 0, yaw: 0 } };
  const displayOut = stopZoneSummaryForRobot(robot, outsideGuide, SITE_MAP, []);
  assert.equal(displayOut.tone, "neutral");
  assert.match(displayOut.label, /S3 구역 밖 \(0\.45m · 표시 계산\)/);

  // Server IN_TOLERANCE turns good green regardless of sightings
  const trips = [{ trip_id: "t1", robot_id: "rosy_46", to: "S3", detail: { named_stop_precision: { decision: "IN_TOLERANCE" } } }];
  const srvIn = stopZoneSummaryForRobot(robot, outsideGuide, SITE_MAP, trips);
  assert.equal(srvIn.tone, "good");
  assert.equal(srvIn.source, "server");

  // REPARK and named_stop_operation
  assert.equal(serverStopVerdict(robot, [{ robot_id: "rosy_46", detail: { named_stop_precision: { decision: "REPARK" } } }]).tone, "warn");
  const op = serverStopVerdict(robot, [{ robot_id: "rosy_46", detail: { named_stop_operation: { run_id: "r1" } } }]);
  assert.equal(op.tone, "neutral");
  assert.match(op.label, /정밀 정지 보정 중/);
});

test("stopZoneOccupants and drawStopZones only stroke --status-good for server IN", () => {
  const place = SITE_MAP.places[0];
  const robots = [{ robot_id: "rosy_46" }];
  const guideRobots = [{ robot_id: "rosy_46", pose: { x: 0, y: 0 } }];
  // Client-only inside -> neutral ink-quiet dashed, NOT status-good
  const occDisplay = stopZoneOccupants(place, robots, guideRobots, []);
  assert.equal(occDisplay.tone, "neutral");
  const strokes = [], chips = [];
  const ctx = {
    save() {}, restore() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {},
    fill() {}, stroke() {}, setLineDash() {},
    set strokeStyle(v) { strokes.push(v); },
  };
  const css = (k) => k;
  drawStopZones(ctx, (x, y) => ({ x, y }), {
    activeMap: SITE_MAP, robots, guideRobots, trips: [], css, on: true, labelsOn: true,
    drawChip: (_c, _g, _x, _y, text, tone) => chips.push([text, tone]),
  });
  assert.equal(strokes[0], "--ink-quiet");
  assert.match(chips[0][0], /표시 계산/);
  assert.equal(chips[0][1], undefined);

  // Server IN_TOLERANCE -> --status-good and good chip
  strokes.length = 0; chips.length = 0;
  const trips = [{ robot_id: "rosy_46", to: "S3", detail: { named_stop_precision: { decision: "IN_TOLERANCE" } } }];
  drawStopZones(ctx, (x, y) => ({ x, y }), {
    activeMap: SITE_MAP, robots, guideRobots, trips, css, on: true, labelsOn: true,
    drawChip: (_c, _g, _x, _y, text, tone) => chips.push([text, tone]),
  });
  assert.equal(strokes[0], "--status-good");
  assert.deepEqual(chips[0], ["S3 IN · rosy_46", "good"]);
});

test("renderHoverCard displays 정지 구역 line for pinky and place with stop_zone", (t) => {
  const mkNode = (tag) => {
    const n = {
      tagName: tag.toUpperCase(), className: "", children: [], dataset: {}, attributes: new Map(), textContent: "",
      append(...a) { for (const x of a) if (typeof x !== "string") this.children.push(x); },
      replaceChildren(...a) { this.children = []; this.append(...a); },
      setAttribute(k, v) { this.attributes.set(k, String(v)); },
      getAttribute(k) { return this.attributes.get(k) ?? null; },
      get childElementCount() { return this.children.length; },
    };
    return n;
  };
  const prevDoc = globalThis.document;
  globalThis.document = { createElement: mkNode };
  t.after(() => { globalThis.document = prevDoc; });
  const card = mkNode("div");
  const view = {
    robots: [{ robot_id: "rosy_46", state: {} }],
    guide: { robots: [{ robot_id: "rosy_46", pose: { x: 0.01, y: 0.01, yaw: 0 } }] },
    activeSiteMap: { map: SITE_MAP },
    trafficTrips: [],
  };
  renderHoverCard({ kind: "pinky", id: "rosy_46", guideRow: view.guide.robots[0] }, { el: () => card, view });
  const dts = card.children[1].children.map((c) => c.textContent);
  assert.ok(dts.includes("정지 구역"));
  assert.ok(dts.includes("S3 구역 안 (표시 계산)"));

  renderHoverCard({ kind: "place", id: "S3", place: SITE_MAP.places[0] }, { el: () => card, view });
  const dts2 = card.children[1].children.map((c) => c.textContent);
  assert.ok(dts2.includes("정지 구역"));
  assert.ok(dts2.some((s) => s.includes("구역 안 (표시 계산) · rosy_46")));
});

test("nextStepFor and createQueues render next-step hints and /console/install#robots link for admin-held E-stop", (t) => {
  const estopRobot = { robot_id: "rosy_46", online: true, state: { safety: { estop: true } } };
  assert.deepEqual(nextStepFor(estopRobot, "estop"), {
    text: "로봇 등록 → rosy_46 → 비상정지 해제…",
    href: "/console/install#robots",
    linkText: "로봇 등록 열기",
  });
  assert.equal(nextStepFor({ robot_id: "rosy_46", state: { safety: { estop: true, releases_when_charged: true } } }, "estop"), null);
  assert.deepEqual(nextStepFor({ robot_id: "rosy_46", named_stop_custody: { operator_action: "현장 정지 확인 후 해제" } }, "custody"), {
    text: "현장 정지 확인 후 해제",
  });
  assert.match(nextStepFor({}, "dock_failed").text, /전진·재접안/);
  assert.match(nextStepFor({}, "nav_failed").text, /목표/);
  assert.match(nextStepFor({}, "off_map").text, /운영자 핀/);

  const mkEl = (tag = "div") => {
    const el = {
      tagName: tag.toUpperCase(), className: "", children: [], dataset: {}, hidden: false, attributes: new Map(), text: "",
      append(...nodes) { for (const n of nodes) if (typeof n !== "string") { n.parentElement = el; el.children.push(n); } },
      replaceChildren(...nodes) { el.children = []; el.append(...nodes); },
      setAttribute(k, v) { el.attributes.set(k, String(v)); },
      getAttribute(k) { return el.attributes.get(k) ?? null; },
      addEventListener() {},
      get firstElementChild() { return el.children[0] || null; },
      get lastElementChild() { return el.children.at(-1) || null; },
      get textContent() { return el.text + el.children.map((c) => c.textContent).join(""); },
      set textContent(v) { el.children = []; el.text = String(v); },
      querySelector(sel) {
        const cls = sel.startsWith(".") ? sel.slice(1) : null;
        for (const c of el.children) {
          if (cls ? c.className.split(/\s+/).includes(cls) : c.tagName === sel.toUpperCase()) return c;
          const hit = c.querySelector?.(sel);
          if (hit) return hit;
        }
        return null;
      },
    };
    return el;
  };
  const prevDoc = globalThis.document;
  globalThis.document = { createElement: mkEl, querySelector: () => null };
  t.after(() => { globalThis.document = prevDoc; });
  const warnBox = mkEl("div"), warnList = mkEl("ul"); warnBox.append(warnList);
  const critBox = mkEl("div"), critList = mkEl("ul"); critBox.append(critList);
  const view = {
    stateUnavailable: false,
    robots: [
      { ...estopRobot, named_stop_custody: { motion_refused_site_wide: true, operator_action: "점유 해제 필요" } },
      { robot_id: "rosy_77", online: true, state: { safety: { estop: true } } },
    ],
    trafficTrips: [], endedTrips: [], workcellObs: null,
  };
  const { fillQueues } = createQueues({
    scope: { guard: (f) => f },
    el: (id) => ({ "warning-list": warnList, "critical-list": critList }[id] || mkEl("div")),
    view, render: () => {}, streamEvidence: () => null,
  });
  fillQueues();
  const estopRows = critList.children.filter((li) => li.textContent.includes("비상정지 해제"));
  assert.equal(estopRows.length, 2, "E-stop rows with per-robot link are not merged");
  assert.equal(estopRows[0].querySelector(".queue-next-link").getAttribute("href"), "/console/install#robots");
});
