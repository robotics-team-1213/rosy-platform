import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);

const {
  composeMatrix4,
  translation,
  rotationX,
  rotationY,
  rotationZ,
  transformFromOrigin,
  computeUrdfLinkTransforms,
  projectStlTopDown,
  createCadTwinLayer,
} = await import("../../../../applications/fleet/web/map/cad-twin-layer.js");
const { parseUrdf, parseStl, jointAngles, jointsFromList } = await import("../../../../shared/web/robot-3d-model.js");
const { clearRobotModelCache } = await import("../../../../shared/web/robot-3d-assets.js");

const MESH_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../shared/web/meshes");
const readMeshText = (name) => fs.readFileSync(path.join(MESH_DIR, name), "utf8");
const readMeshBuf = (name) => {
  const buf = fs.readFileSync(path.join(MESH_DIR, name));
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
};

function makeMockCtx() {
  const ops = [];
  const state = {
    fillStyle: "",
    strokeStyle: "",
    globalAlpha: 1,
    lineWidth: 1,
    lineCap: "butt",
    lineJoin: "miter",
  };
  return {
    ops,
    get fillStyle() { return state.fillStyle; },
    set fillStyle(v) { state.fillStyle = v; },
    get strokeStyle() { return state.strokeStyle; },
    set strokeStyle(v) { state.strokeStyle = v; },
    get globalAlpha() { return state.globalAlpha; },
    set globalAlpha(v) { state.globalAlpha = v; },
    get lineWidth() { return state.lineWidth; },
    set lineWidth(v) { state.lineWidth = v; },
    get lineCap() { return state.lineCap; },
    set lineCap(v) { state.lineCap = v; },
    get lineJoin() { return state.lineJoin; },
    set lineJoin(v) { state.lineJoin = v; },
    save() { ops.push({ op: "save" }); },
    restore() { ops.push({ op: "restore" }); },
    beginPath() { ops.push({ op: "beginPath" }); },
    closePath() { ops.push({ op: "closePath" }); },
    moveTo(x, y) { ops.push({ op: "moveTo", x, y }); },
    lineTo(x, y) { ops.push({ op: "lineTo", x, y }); },
    setLineDash(d) { ops.push({ op: "setLineDash", d }); },
    fill() { ops.push({ op: "fill", style: state.fillStyle, alpha: state.globalAlpha }); },
    stroke() { ops.push({ op: "stroke", style: state.strokeStyle, alpha: state.globalAlpha, lw: state.lineWidth }); },
  };
}

test("pure Matrix4 helpers compose translation and rotations accurately", () => {
  const t = composeMatrix4(translation(1, 2, 3), rotationZ(Math.PI / 2));
  assert.ok(Math.abs(t[12] - 1) < 1e-12 && Math.abs(t[13] - 2) < 1e-12 && Math.abs(t[14] - 3) < 1e-12);
  // +X unit vector rotated +90 deg around Z becomes +Y
  assert.ok(Math.abs(t[0]) < 1e-12 && Math.abs(t[1] - 1) < 1e-12);
  const rx = rotationX(Math.PI / 2);
  assert.ok(Math.abs(rx[5]) < 1e-12 && Math.abs(rx[6] - 1) < 1e-12);
  const ry = rotationY(Math.PI / 2);
  assert.ok(Math.abs(ry[0]) < 1e-12 && Math.abs(ry[2] + 1) < 1e-12);
  const org = transformFromOrigin({ xyz: [0.1, -0.2, 0.3], rpy: [0, 0, Math.PI] });
  assert.ok(Math.abs(org[12] - 0.1) < 1e-12 && Math.abs(org[0] + 1) < 1e-12);
});

test("computeUrdfLinkTransforms computes Pinky Pro wheel transforms and OMX-F articulated FK with mimic", () => {
  const pinky = parseUrdf(readMeshText("pinky-pro.urdf"));
  const pinkyT = computeUrdfLinkTransforms(pinky, {});
  assert.equal(pinkyT.base_footprint[12], 0);
  assert.ok(Math.abs(pinkyT.l_wheel[13] - 0.04055) < 1e-6);
  assert.ok(Math.abs(pinkyT.r_wheel[13] + 0.04055) < 1e-6);
  assert.ok(Math.abs(pinkyT.l_wheel[14] - 0.028) < 1e-6);

  const omx = parseUrdf(readMeshText("omx-f.urdf"));
  const zeroT = computeUrdfLinkTransforms(omx, {});
  const movedT = computeUrdfLinkTransforms(omx, {
    joint1: Math.PI / 2,
    joint2: -0.4,
    joint3: 0.6,
    joint4: 0.3,
    joint5: 0.5,
    gripper_joint_1: 0.35,
  });
  // Rotating joint1 +90 deg around Z moves link3..link5 from +X into +Y
  assert.ok(zeroT.link5[12] > 0.15 && Math.abs(zeroT.link5[13]) < 1e-6);
  assert.ok(movedT.link5[13] > 0.1 && Math.abs(movedT.link5[12] + 0.01125) < 1e-3);
  // Mimic gripper_joint_2 turns opposite gripper_joint_1
  assert.ok(Math.abs(movedT.link6[1] - (-movedT.link7[1])) < 1e-6 || movedT.link6[0] !== movedT.link7[0]);
});

test("projectStlTopDown projects real Pinky and OMX-F STL meshes into upward-facing 2D CAD triangles", () => {
  const pinky = parseUrdf(readMeshText("pinky-pro.urdf"));
  const pinkyBody = parseStl(readMeshBuf("pinky-body.stl"));
  const pinkyT = computeUrdfLinkTransforms(pinky, {});
  const pinkyTris = projectStlTopDown(pinkyBody, pinkyT.body);
  assert.ok(pinkyTris.length > 50, `expected > 50 upward triangles, got ${pinkyTris.length}`);
  assert.ok(pinkyTris.every((t) => t.p0.length === 2 && t.p1.length === 2 && t.p2.length === 2 && t.shade > 0 && t.shade <= 1.0001));

  const omx = parseUrdf(readMeshText("omx-f.urdf"));
  const link5Stl = parseStl(readMeshBuf("omx-link5.stl"));
  const t0 = computeUrdfLinkTransforms(omx, {});
  const t90 = computeUrdfLinkTransforms(omx, jointsFromList([Math.PI / 2, 0, 0, 0, 0, 0], ["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]));
  const p0 = projectStlTopDown(link5Stl, t0.link5);
  const p90 = projectStlTopDown(link5Stl, t90.link5);
  assert.ok(p0.length > 10 && p90.length > 10);
  const avgY0 = p0.reduce((s, t) => s + t.p0[1], 0) / p0.length;
  const avgY90 = p90.reduce((s, t) => s + t.p0[1], 0) / p90.length;
  assert.ok(Math.abs(avgY0) < 0.03 && avgY90 > 0.15, `expected link5 to swing to +Y, got ${avgY0} -> ${avgY90}`);
});

test("createCadTwinLayer draws floor CAD and articulated Pinky + OMX-F rigs with RosyPalette tokens", async () => {
  clearRobotModelCache();
  const origFetch = globalThis.fetch;
  let loadedCount = 0;
  let laneCalls = 0;
  globalThis.fetch = async (url) => {
    const u = String(url);
    const name = u.split("/").pop();
    if (name.endsWith(".urdf")) {
      return new Response(readMeshText(name), { status: 200 });
    }
    if (name.endsWith(".stl")) {
      return new Response(readMeshBuf(name), { status: 200 });
    }
    return new Response("not found", { status: 404 });
  };
  try {
    const view = {
      robots: [{ robot_id: "rosy_45", online: true, pose: { x: 0.2, y: -0.1, yaw: 0.3 } }],
      chargeBaysPlan: {
        bays: [{ bay: "C1", x: -0.4, y: 0.45, state: "free" }],
        station_zones: {
          staging_bays: [{ id: "STG_C2", x: 0.35, y: -0.25, yaw_deg: 0 }],
          export_stations: [{ id: "EXP_S3_BELT", x: 0.7, y: -0.25, yaw_deg: -85 }],
        },
        arm_live_states: {
          arm_s: { joints_deg: [0, -58, 50, 50, -5, 58.1] },
        },
      },
    };
    const layer = createCadTwinLayer({
      call: async (p) => {
        laneCalls += 1;
        assert.equal(p, "/api/fleet/site-lanes");
        return {
          maps: [{
            map_id: "map_v2",
            paint_triangles: [[-0.5, -0.5, 0.5, -0.5, 0.5, 0.5]],
            polylines: [{ id: "east", points: [[0, 0], [1, 0]] }],
          }],
        };
      },
      css: (token) => `token(${token})`,
      view,
      onLoaded: () => { loadedCount += 1; },
    });

    await layer.ensureSiteLanes("map_v2");
    await layer.ensureSiteLanes("map_v2");
    assert.equal(laneCalls, 1, "site-lanes should be fetched once per mapId");
    await layer.ensureMeshes();
    assert.ok(loadedCount >= 2);

    const ctx = makeMockCtx();
    const toPx = (x, y) => ({ x: 400 + x * 200, y: 300 - y * 200 });
    layer.drawFloorCad(ctx, toPx, {
      map_id: "map_v2",
      walls: [{ id: "wall_n", face: [[-1.4, 0.625], [1.4, 0.625]] }],
      places: [{ id: "C1", x: -0.4, y: 0.45 }, { id: "S3", x: 0.7, y: -0.25 }],
    }, { overlayMode: true });

    const floorTokens = ctx.ops.filter((o) => o.op === "stroke" || o.op === "fill").map((o) => o.style);
    assert.ok(floorTokens.includes("token(--line-quiet)"));
    assert.ok(floorTokens.includes("token(--border-strong)"));
    assert.ok(floorTokens.includes("token(--series-goal)"));
    assert.ok(floorTokens.includes("token(--status-warn)"));

    ctx.ops.length = 0;
    layer.drawRobotCadModels(ctx, toPx, {
      guide: { robots: [{ robot_id: "rosy_46", online: true, pose: { x: 0.5, y: -0.2, yaw: 1.57 } }] },
      anchors: [{ kind: "omx_ai", target_id: "arm_s", base_x: 0.7, base_y: -0.35, head_x: 0.7, head_y: -0.1 }],
      chargeBaysPlan: view.chargeBaysPlan,
      overlayMode: true,
      focusedRobotId: "arm_s",
    });

    const fills = ctx.ops.filter((o) => o.op === "fill");
    const strokes = ctx.ops.filter((o) => o.op === "stroke");
    assert.ok(fills.length >= 2, "both Pinky and OMX-F should emit filled CAD triangles");
    assert.ok(strokes.some((s) => s.style === "token(--selection)" && Math.abs(s.alpha - 0.9) < 1e-6));
    assert.ok(strokes.some((s) => s.style === "token(--series-primary)" && Math.abs(s.alpha - 0.9) < 1e-6));
    assert.ok(fills.every((f) => f.alpha <= 0.39), `overlay fill alpha should be <= 0.38, got ${fills.map((f) => f.alpha)}`);

    ctx.ops.length = 0;
    layer.drawRobotCadModels(ctx, toPx, {
      guide: { robots: [{ robot_id: "rosy_46", online: true, pose: { x: 0.5, y: -0.2, yaw: 0 } }] },
      anchors: [],
      overlayMode: false,
    });
    assert.ok(ctx.ops.some((o) => o.op === "fill" && o.alpha > 0.5 && o.alpha <= 0.79));
  } finally {
    globalThis.fetch = origFetch;
  }
});

test("ensureSiteLanes handles 404 or network failure gracefully without throwing", async () => {
  const layer = createCadTwinLayer({
    call: async () => { const err = new Error("missing"); err.status = 404; throw err; },
    css: (t) => t,
    view: {},
  });
  const res = await layer.ensureSiteLanes("no_such_map");
  assert.deepEqual(res.paintTriangles, []);
  assert.deepEqual(res.polylines, []);
});

test("preload, floor offscreen cache, and O(1) per-rig toPx basis projection avoid redundant work", async () => {
  clearRobotModelCache();
  const origFetch = globalThis.fetch;
  const origDoc = globalThis.document;
  let fetchCount = 0;
  let laneCalls = 0;
  globalThis.fetch = async (url) => {
    fetchCount += 1;
    const name = String(url).split("/").pop();
    if (name.endsWith(".urdf")) return new Response(readMeshText(name), { status: 200 });
    if (name.endsWith(".stl")) return new Response(readMeshBuf(name), { status: 200 });
    return new Response("not found", { status: 404 });
  };
  const offCtx = makeMockCtx();
  offCtx.clearRect = () => {};
  offCtx.setTransform = () => {};
  let createdCanvases = 0;
  globalThis.document = {
    createElement(tag) {
      assert.equal(tag, "canvas");
      createdCanvases += 1;
      return { width: 0, height: 0, getContext: () => offCtx };
    },
  };
  try {
    const view = {
      robots: [{ robot_id: "rosy_45", online: true, pose: { x: 0.2, y: -0.1, yaw: 0.3 } }],
      chargeBaysPlan: { bays: [{ bay: "C1", x: -0.4, y: 0.45 }], arm_live_states: {} },
    };
    const layer = createCadTwinLayer({
      call: async () => {
        laneCalls += 1;
        return { maps: [{ map_id: "map_v2", paint_triangles: [[-0.5, -0.5, 0.5, -0.5, 0.5, 0.5]] }] };
      },
      css: (t) => `token(${t})`,
      view,
    });

    await layer.preload("map_v2");
    assert.equal(laneCalls, 1);
    const initialFetches = fetchCount;
    assert.ok(initialFetches > 0);

    const mainCtx = makeMockCtx();
    mainCtx.canvas = { width: 800, height: 600 };
    mainCtx.getTransform = () => ({ a: 1, d: 1 });
    mainCtx.setTransform = () => {};
    let drawImageCalls = 0;
    mainCtx.drawImage = () => { drawImageCalls += 1; };

    let toPxCalls = 0;
    const toPx = (x, y) => {
      toPxCalls += 1;
      return { x: 400 + x * 200, y: 300 - y * 200 };
    };
    const activeMap = {
      map_id: "map_v2",
      walls: [{ id: "w1", face: [[0, 0], [1, 0]] }],
      places: [{ id: "C1", x: -0.4, y: 0.45 }],
    };

    layer.drawFloorCad(mainCtx, toPx, activeMap, { overlayMode: false, preloadIfMissing: false });
    const offOpsAfterFirst = offCtx.ops.length;
    assert.ok(offOpsAfterFirst > 0);
    assert.equal(drawImageCalls, 1);

    layer.drawFloorCad(mainCtx, toPx, activeMap, { overlayMode: false, preloadIfMissing: false });
    assert.equal(offCtx.ops.length, offOpsAfterFirst, "cached floor should not re-render offscreen ops");
    assert.equal(drawImageCalls, 2);
    assert.equal(createdCanvases, 1);

    layer.drawFloorCad(mainCtx, toPx, activeMap, { overlayMode: true, preloadIfMissing: false });
    assert.ok(offCtx.ops.length > offOpsAfterFirst, "overlayMode change should invalidate floor cache");
    assert.equal(drawImageCalls, 3);

    toPxCalls = 0;
    layer.drawRobotCadModels(mainCtx, toPx, {
      guide: { robots: [{ robot_id: "rosy_45", online: true, pose: { x: 0.2, y: -0.1, yaw: 0.3 } }] },
      anchors: [{ kind: "omx_ai", target_id: "arm_s", base_x: 0.7, base_y: -0.35, base_yaw: 0 }],
      chargeBaysPlan: { arm_live_states: { arm_s: { joints_deg: [0, -58, 50, 50, -5, 58.1] } } },
      preloadIfMissing: false,
    });
    assert.equal(toPxCalls, 6, "3 basis calls for Pinky + 3 basis calls for OMX-F");
    assert.equal(fetchCount, initialFetches, "no extra fetches after preload");
    assert.equal(laneCalls, 1);
  } finally {
    globalThis.fetch = origFetch;
    globalThis.document = origDoc;
  }
});

test("ensureSiteLanes retries after transient 503 failure while caching 404", async () => {
  let calls = 0;
  let mode = "503";
  const layer = createCadTwinLayer({
    call: async () => {
      calls += 1;
      if (mode === "503") throw Object.assign(new Error("unavailable"), { status: 503 });
      if (mode === "404") throw Object.assign(new Error("missing"), { status: 404 });
      return { maps: [{ map_id: "m1", paint_triangles: [[0, 0, 1, 0, 1, 1]] }] };
    },
    css: (t) => t,
    view: {},
  });

  const failed = await layer.ensureSiteLanes("m1");
  assert.deepEqual(failed.paintTriangles, []);
  mode = "ok";
  const recovered = await layer.ensureSiteLanes("m1");
  assert.equal(calls, 2, "503 should not be cached so next call retries");
  assert.equal(recovered.paintTriangles.length, 1);

  mode = "404";
  const missing = await layer.ensureSiteLanes("m_missing");
  assert.deepEqual(missing.paintTriangles, []);
  mode = "ok";
  await layer.ensureSiteLanes("m_missing");
  assert.equal(calls, 3, "404 should remain cached");
});

test("drawRobotCadModels gates unlocalized odom fallback via robotMapPose and distinguishes offline/degraded/stale rigs", async () => {
  clearRobotModelCache();
  const origFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    const name = String(url).split("/").pop();
    if (name.endsWith(".urdf")) return new Response(readMeshText(name), { status: 200 });
    if (name.endsWith(".stl")) return new Response(readMeshBuf(name), { status: 200 });
    return new Response("not found", { status: 404 });
  };
  try {
    const view = {
      robots: [
        {
          robot_id: "rosy_odom",
          online: true,
          state: { pose: { x: 0, y: 0, yaw: 0 }, localization: { state: "UNKNOWN", pose_frame: "odom" } },
        },
        {
          robot_id: "rosy_loc",
          online: true,
          state: { pose: { x: 0.4, y: 0.1, yaw: 0 }, localization: { state: "LOCALIZED", pose_frame: "map" } },
        },
      ],
    };
    const layer = createCadTwinLayer({
      call: async () => ({ maps: [] }),
      css: (t) => `token(${t})`,
      view,
    });
    await layer.ensureMeshes();
    const toPx = (x, y) => ({ x: 400 + x * 200, y: 300 - y * 200 });

    const ctx = makeMockCtx();
    layer.drawRobotCadModels(ctx, toPx, { guide: { robots: [] }, anchors: [], preloadIfMissing: false });
    // Only rosy_loc should draw (at x = 480); rosy_odom (at x = 400) must not draw
    const fillXs = ctx.ops.filter((o) => o.op === "moveTo").map((o) => o.x);
    assert.ok(fillXs.some((x) => x > 440), "localized map robot should draw");
    assert.ok(fillXs.every((x) => x > 430), "unlocalized odom (0,0) robot must not render");

    ctx.ops.length = 0;
    layer.drawRobotCadModels(ctx, toPx, {
      guide: {
        robots: [
          { robot_id: "rosy_loc", online: true, pose: { x: 0.2, y: 0.1, yaw: 0, state: "DEGRADED", source: "bridged" } },
          { robot_id: "rosy_off", online: false, pose: { x: -0.2, y: 0.1, yaw: 0, state: "LOCALIZED" } },
        ],
      },
      anchors: [{ kind: "omx_ai", target_id: "arm_a", base_x: 0.6, base_y: -0.2, base_yaw: 0 }],
      chargeBaysPlan: { arm_live_states: { arm_a: { online: false, stale: true, joints_deg: [0, 0, 0, 0, 0, 0] } } },
      preloadIfMissing: false,
    });
    const strokes = ctx.ops.filter((o) => o.op === "stroke");
    const dashes = ctx.ops.filter((o) => o.op === "setLineDash");
    assert.ok(strokes.some((s) => s.style === "token(--status-warn)"), "degraded/bridged pinky uses status-warn");
    assert.ok(strokes.some((s) => s.style === "token(--ink-quiet)"), "offline pinky/arm uses ink-quiet");
    assert.ok(dashes.some((d) => d.d[0] === 4 && d.d[1] === 3), "non-nominal rigs use dashed silhouette");
  } finally {
    globalThis.fetch = origFetch;
  }
});
