// CAD Digital Twin 2D projection layer for Fleet map (pure URDF FK + STL projection + canvas overlay).
import { jointAngles, jointsFromList } from "/common/robot-3d-model.js";
import { loadRobotModel } from "/common/robot-3d-assets.js";
import { robotMapPose } from "/console/assets/site-map-model.js";

const OMX_JOINT_NAMES = Object.freeze(["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]);
const MIN_TRI_AREA_M2 = 1e-7;
const KEY_QUANT = 2000;

export function composeMatrix4(a, b) {
  const out = new Float64Array(16);
  for (let col = 0; col < 4; col += 1) {
    const b0 = b[col * 4], b1 = b[col * 4 + 1], b2 = b[col * 4 + 2], b3 = b[col * 4 + 3];
    out[col * 4] = a[0] * b0 + a[4] * b1 + a[8] * b2 + a[12] * b3;
    out[col * 4 + 1] = a[1] * b0 + a[5] * b1 + a[9] * b2 + a[13] * b3;
    out[col * 4 + 2] = a[2] * b0 + a[6] * b1 + a[10] * b2 + a[14] * b3;
    out[col * 4 + 3] = a[3] * b0 + a[7] * b1 + a[11] * b2 + a[15] * b3;
  }
  return out;
}

export function translation(x = 0, y = 0, z = 0) {
  return new Float64Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
}

export function rotationX(rad = 0) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float64Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
}

export function rotationY(rad = 0) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float64Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
}

export function rotationZ(rad = 0) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float64Array([c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
}

export function rotationAxisAngle(axis, rad = 0) {
  const [ax = 0, ay = 0, az = 1] = axis || [];
  const len = Math.hypot(ax, ay, az);
  if (!len || !rad) return translation(0, 0, 0);
  const ux = ax / len, uy = ay / len, uz = az / len;
  const c = Math.cos(rad), s = Math.sin(rad), t = 1 - c;
  return new Float64Array([
    t * ux * ux + c, t * ux * uy + s * uz, t * ux * uz - s * uy, 0,
    t * ux * uy - s * uz, t * uy * uy + c, t * uy * uz + s * ux, 0,
    t * ux * uz + s * uy, t * uy * uz - s * ux, t * uz * uz + c, 0,
    0, 0, 0, 1,
  ]);
}

export function transformFromOrigin(origin) {
  const [x = 0, y = 0, z = 0] = origin?.xyz || [];
  const [r = 0, p = 0, yaw = 0] = origin?.rpy || [];
  return composeMatrix4(
    translation(x, y, z),
    composeMatrix4(rotationZ(yaw), composeMatrix4(rotationY(p), rotationX(r))),
  );
}

/** Forward kinematics from URDF root link; returns { [linkName]: Float64Array(16) } including visual origin. */
export function computeUrdfLinkTransforms(model, jointRadMap = {}) {
  if (!model || !model.root) return {};
  const { angles } = jointAngles(model, jointRadMap || {});
  const byParent = new Map();
  for (const joint of model.joints || []) {
    if (!byParent.has(joint.parent)) byParent.set(joint.parent, []);
    byParent.get(joint.parent).push(joint);
  }
  const transforms = {};
  function visit(linkName, frameMat) {
    const link = model.links?.[linkName];
    const hasVisualOffset = link && (link.xyz?.some(Boolean) || link.rpy?.some(Boolean));
    transforms[linkName] = hasVisualOffset ? composeMatrix4(frameMat, transformFromOrigin(link)) : frameMat;
    const children = byParent.get(linkName) || model.children?.[linkName] || [];
    for (const joint of children) {
      let childMat = composeMatrix4(frameMat, transformFromOrigin(joint));
      if (joint.type === "revolute" || joint.type === "continuous") {
        const angle = angles[joint.name];
        if (Number.isFinite(angle) && angle !== 0) {
          childMat = composeMatrix4(childMat, rotationAxisAngle(joint.axis, angle));
        }
      }
      visit(joint.child, childMat);
    }
  }
  visit(model.root, translation(0, 0, 0));
  return transforms;
}

/** Project binary STL triangle positions through mat4 into upward-facing top-down 2D triangles sorted by z. */
export function projectStlTopDown(stlPositions, mat4) {
  if (!stlPositions || !mat4) return [];
  const m0 = mat4[0], m1 = mat4[1], m2 = mat4[2];
  const m4 = mat4[4], m5 = mat4[5], m6 = mat4[6];
  const m8 = mat4[8], m9 = mat4[9], m10 = mat4[10];
  const m12 = mat4[12], m13 = mat4[13], m14 = mat4[14];
  const tris = [];
  for (let i = 0; i <= stlPositions.length - 9; i += 9) {
    const ax = stlPositions[i], ay = stlPositions[i + 1], az = stlPositions[i + 2];
    const bx = stlPositions[i + 3], by = stlPositions[i + 4], bz = stlPositions[i + 5];
    const cx = stlPositions[i + 6], cy = stlPositions[i + 7], cz = stlPositions[i + 8];
    const x0 = m0 * ax + m4 * ay + m8 * az + m12;
    const y0 = m1 * ax + m5 * ay + m9 * az + m13;
    const z0 = m2 * ax + m6 * ay + m10 * az + m14;
    const x1 = m0 * bx + m4 * by + m8 * bz + m12;
    const y1 = m1 * bx + m5 * by + m9 * bz + m13;
    const z1 = m2 * bx + m6 * by + m10 * bz + m14;
    const x2 = m0 * cx + m4 * cy + m8 * cz + m12;
    const y2 = m1 * cx + m5 * cy + m9 * cz + m13;
    const z2 = m2 * cx + m6 * cy + m10 * cz + m14;
    const e1x = x1 - x0, e1y = y1 - y0, e1z = z1 - z0;
    const e2x = x2 - x0, e2y = y2 - y0, e2z = z2 - z0;
    const nx = e1y * e2z - e1z * e2y;
    const ny = e1z * e2x - e1x * e2z;
    const nz = e1x * e2y - e1y * e2x;
    const len = Math.hypot(nx, ny, nz);
    if (len < 1e-10) continue;
    const unz = nz / len;
    if (unz <= 0.02) continue;
    if (Math.abs(nz) < MIN_TRI_AREA_M2 * 2) continue;
    const dot = Math.max(0, (nx * 0.25 - ny * 0.25 + nz * 0.935) / len);
    tris.push({
      p0: [x0, y0],
      p1: [x1, y1],
      p2: [x2, y2],
      shade: 0.55 + 0.45 * dot,
      z: (z0 + z1 + z2) / 3,
    });
  }
  tris.sort((a, b) => a.z - b.z);
  return tris;
}

/** Extract boundary silhouette segments (edges used by a single upward triangle) as a flat Float32Array [ax,ay,bx,by,...]. */
function extractSilhouetteEdges(tris) {
  const counts = new Map();
  const ptKey = (p) => `${Math.round(p[0] * KEY_QUANT)},${Math.round(p[1] * KEY_QUANT)}`;
  for (const tri of tris) {
    const pts = [tri.p0, tri.p1, tri.p2];
    const keys = [ptKey(tri.p0), ptKey(tri.p1), ptKey(tri.p2)];
    for (let i = 0; i < 3; i += 1) {
      const j = (i + 1) % 3;
      const ka = keys[i], kb = keys[j];
      if (ka === kb) continue;
      const edgeKey = ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
      const slot = counts.get(edgeKey);
      if (slot) slot.n += 1;
      else counts.set(edgeKey, { ax: pts[i][0], ay: pts[i][1], bx: pts[j][0], by: pts[j][1], n: 1 });
    }
  }
  const buf = [];
  for (const slot of counts.values()) {
    if (slot.n === 1) buf.push(slot.ax, slot.ay, slot.bx, slot.by);
  }
  return new Float32Array(buf);
}

const SHADE_SCALE = [0.75, 0.9, 1.0];

function projectModelLocal(loaded, jointRadMap) {
  const transforms = computeUrdfLinkTransforms(loaded.model, jointRadMap);
  const tris = [];
  for (const [linkName, link] of Object.entries(loaded.model.links || {})) {
    if (!link.mesh || !loaded.meshes[link.mesh] || !transforms[linkName]) continue;
    for (const tri of projectStlTopDown(loaded.meshes[link.mesh], transforms[linkName])) {
      tris.push(tri);
    }
  }
  tris.sort((a, b) => a.z - b.z);
  // Pre-bucket into 3 flat Float32Arrays [x0,y0,x1,y1,x2,y2,...] so paint loops do zero allocations.
  const bucketArrays = [[], [], []];
  for (const tri of tris) {
    const idx = tri.shade < 0.7 ? 0 : tri.shade < 0.85 ? 1 : 2;
    bucketArrays[idx].push(tri.p0[0], tri.p0[1], tri.p1[0], tri.p1[1], tri.p2[0], tri.p2[1]);
  }
  return {
    buckets: bucketArrays.map((arr) => new Float32Array(arr)),
    edges: extractSilhouetteEdges(tris),
    triCount: tris.length,
  };
}

function finite(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function drawProjectedRig(ctx, toPx, rig, wx, wy, yaw, { fillCol, strokeCol, fillAlpha, strokeAlpha, lineWidth, lineDash = null }) {
  if (!rig?.triCount) return;
  const c = Math.cos(yaw), s = Math.sin(yaw);
  const o = toPx(wx, wy);
  const ux = toPx(wx + c, wy + s);
  const uy = toPx(wx - s, wy + c);
  const tx = o.x, ty = o.y;
  const m00 = ux.x - tx, m10 = ux.y - ty;
  const m01 = uy.x - tx, m11 = uy.y - ty;
  ctx.save();
  ctx.fillStyle = fillCol;
  for (let b = 0; b < rig.buckets.length; b += 1) {
    const verts = rig.buckets[b];
    if (!verts.length) continue;
    ctx.globalAlpha = fillAlpha * SHADE_SCALE[b];
    ctx.beginPath();
    for (let i = 0; i < verts.length; i += 6) {
      const x0 = verts[i], y0 = verts[i + 1];
      const x1 = verts[i + 2], y1 = verts[i + 3];
      const x2 = verts[i + 4], y2 = verts[i + 5];
      ctx.moveTo(tx + x0 * m00 + y0 * m01, ty + x0 * m10 + y0 * m11);
      ctx.lineTo(tx + x1 * m00 + y1 * m01, ty + x1 * m10 + y1 * m11);
      ctx.lineTo(tx + x2 * m00 + y2 * m01, ty + x2 * m10 + y2 * m11);
      ctx.closePath();
    }
    ctx.fill();
  }
  const edges = rig.edges;
  if (edges?.length) {
    ctx.globalAlpha = strokeAlpha;
    ctx.strokeStyle = strokeCol;
    ctx.lineWidth = lineWidth;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (lineDash) ctx.setLineDash(lineDash);
    ctx.beginPath();
    for (let i = 0; i < edges.length; i += 4) {
      const ax = edges[i], ay = edges[i + 1];
      const bx = edges[i + 2], by = edges[i + 3];
      ctx.moveTo(tx + ax * m00 + ay * m01, ty + ax * m10 + ay * m11);
      ctx.lineTo(tx + bx * m00 + by * m01, ty + bx * m10 + by * m11);
    }
    ctx.stroke();
  }
  ctx.restore();
}

function drawOrientedPad(ctx, toPx, x, y, yawDeg, halfW, halfH, strokeCol, lineWidth, dashed = false) {
  if (!finite(x) || !finite(y)) return;
  const yaw = finite(yawDeg) ? (yawDeg * Math.PI) / 180 : 0;
  const c = Math.cos(yaw), s = Math.sin(yaw);
  const corners = [[-halfW, -halfH], [halfW, -halfH], [halfW, halfH], [-halfW, halfH]]
    .map(([lx, ly]) => toPx(x + lx * c - ly * s, y + lx * s + ly * c));
  ctx.save();
  if (dashed) ctx.setLineDash([4, 3]);
  ctx.strokeStyle = strokeCol;
  ctx.lineWidth = lineWidth;
  ctx.beginPath();
  corners.forEach((pt, idx) => {
    if (idx === 0) ctx.moveTo(pt.x, pt.y);
    else ctx.lineTo(pt.x, pt.y);
  });
  ctx.closePath();
  ctx.stroke();
  ctx.restore();
}

export function createCadTwinLayer({ scope, call, css, view, onLoaded = () => {} } = {}) {
  const lanesByMap = new Map();
  const lanesInFlight = new Map();
  let currentSiteLanes = null;
  let meshAssets = null;
  let meshPromise = null;
  let pinkyLocalRig = null;
  const omxRigCache = new Map();
  let disposed = false;
  scope?.onDispose?.(() => { disposed = true; });

  async function ensureSiteLanes(mapId) {
    const key = mapId ?? "__default__";
    if (lanesByMap.has(key)) {
      currentSiteLanes = lanesByMap.get(key);
      return currentSiteLanes;
    }
    if (lanesInFlight.has(key)) return lanesInFlight.get(key);
    const pending = (async () => {
      try {
        let payload = null;
        if (typeof call === "function") {
          payload = await call("/api/fleet/site-lanes");
        } else if (typeof fetch === "function") {
          const res = await fetch("/api/fleet/site-lanes");
          if (res.ok) payload = await res.json();
          else throw Object.assign(new Error(`site-lanes: ${res.status}`), { status: res.status });
        }
        const maps = payload?.maps || [];
        const matched = maps.find((m) => m.map_id === mapId) || maps.find((m) => m.map_id == null) || maps[0] || null;
        const entry = {
          mapId: key,
          paintTriangles: Array.isArray(matched?.paint_triangles) ? matched.paint_triangles : [],
          polylines: Array.isArray(matched?.polylines) ? matched.polylines : [],
          bounds: matched?.bounds_m || null,
        };
        lanesByMap.set(key, entry);
        currentSiteLanes = entry;
        if (!disposed) onLoaded();
        return entry;
      } catch (err) {
        const empty = { mapId: key, paintTriangles: [], polylines: [], bounds: null };
        if (err?.status === 404) lanesByMap.set(key, empty);
        currentSiteLanes = lanesByMap.get(key) || empty;
        return empty;
      } finally {
        lanesInFlight.delete(key);
      }
    })();
    lanesInFlight.set(key, pending);
    return pending;
  }

  async function ensureMeshes() {
    if (meshAssets) return meshAssets;
    if (meshPromise) return meshPromise;
    if (typeof fetch !== "function") return null;
    meshPromise = (async () => {
      try {
        const [pinky, omx] = await Promise.all([
          loadRobotModel("mobile"),
          loadRobotModel("arm"),
        ]);
        if (disposed) return null;
        meshAssets = { pinky, omx };
        pinkyLocalRig = projectModelLocal(pinky, {});
        onLoaded();
        return meshAssets;
      } catch {
        meshPromise = null;
        return null;
      }
    })();
    return meshPromise;
  }

  let floorCache = { key: null, canvas: null, ctx: null };
  let lastPlanRef = null;
  let lastPlanSig = "";

  function planSignature(plan) {
    if (!plan) return "";
    if (plan === lastPlanRef) return lastPlanSig;
    lastPlanRef = plan;
    const zones = plan.station_zones;
    const part = (arr, withYaw) => (arr || []).map((z) => (withYaw ? `${z.x},${z.y},${z.yaw_deg}` : `${z.x},${z.y}`)).join(";");
    lastPlanSig = `${part(zones?.staging_bays, true)}/${part(zones?.export_stations, true)}/${part(plan.bays, false)}`;
    return lastPlanSig;
  }

  function renderFloorCad(targetCtx, toPx, activeMap, lanes, overlayMode) {
    if (lanes?.paintTriangles?.length) {
      targetCtx.save();
      targetCtx.beginPath();
      for (const tri of lanes.paintTriangles) {
        if (!Array.isArray(tri) || tri.length < 6) continue;
        const p0 = toPx(tri[0], tri[1]), p1 = toPx(tri[2], tri[3]), p2 = toPx(tri[4], tri[5]);
        targetCtx.moveTo(p0.x, p0.y);
        targetCtx.lineTo(p1.x, p1.y);
        targetCtx.lineTo(p2.x, p2.y);
        targetCtx.closePath();
      }
      targetCtx.fillStyle = css("--line-quiet");
      targetCtx.globalAlpha = overlayMode ? 0.24 : 0.35;
      targetCtx.fill();
      targetCtx.strokeStyle = css("--ink-quiet");
      targetCtx.globalAlpha = overlayMode ? 0.42 : 0.55;
      targetCtx.lineWidth = 0.8;
      targetCtx.stroke();
      targetCtx.restore();
    }

    if (Array.isArray(activeMap?.walls) && activeMap.walls.length) {
      targetCtx.save();
      targetCtx.strokeStyle = css("--border-strong");
      targetCtx.lineWidth = overlayMode ? 2.4 : 3;
      targetCtx.lineCap = "square";
      targetCtx.globalAlpha = overlayMode ? 0.85 : 1;
      targetCtx.beginPath();
      for (const wall of activeMap.walls) {
        const face = wall?.face;
        if (!Array.isArray(face) || face.length < 2) continue;
        const a = toPx(face[0][0], face[0][1]), b = toPx(face[1][0], face[1][1]);
        targetCtx.moveTo(a.x, a.y);
        targetCtx.lineTo(b.x, b.y);
      }
      targetCtx.stroke();
      targetCtx.restore();
    }

    for (const place of activeMap?.places || []) {
      const pid = String(place?.id || "");
      if (pid.startsWith("C")) {
        drawOrientedPad(targetCtx, toPx, place.x, place.y, 0, 0.085, 0.065, css("--series-goal"), 1.3);
      } else if (pid.startsWith("S")) {
        drawOrientedPad(targetCtx, toPx, place.x, place.y, 0, 0.095, 0.075, css("--status-warn"), 1.3);
      }
    }

    const plan = view?.chargeBaysPlan;
    const zones = plan?.station_zones;
    for (const zone of zones?.staging_bays || []) {
      drawOrientedPad(targetCtx, toPx, zone.x, zone.y, zone.yaw_deg, 0.085, 0.065, css("--series-secondary"), 1.2, true);
    }
    for (const zone of zones?.export_stations || []) {
      drawOrientedPad(targetCtx, toPx, zone.x, zone.y, zone.yaw_deg, 0.095, 0.075, css("--status-warn"), 1.2, true);
    }
    for (const bay of plan?.bays || []) {
      drawOrientedPad(targetCtx, toPx, bay.x, bay.y, 0, 0.09, 0.07, css("--line-quiet"), 1.1);
    }
  }

  function drawFloorCad(ctx, toPx, activeMap, { overlayMode = false, preloadIfMissing = true } = {}) {
    if (!ctx || !toPx) return;
    const mapId = activeMap?.map_id ?? null;
    const key = mapId ?? "__default__";
    const lanes = lanesByMap.get(key) || currentSiteLanes;
    if (preloadIfMissing && !lanesByMap.has(key) && !lanesInFlight.has(key)) void ensureSiteLanes(mapId);

    const w = ctx.canvas?.width || 0;
    const h = ctx.canvas?.height || 0;
    const canCache = typeof document !== "undefined" && typeof document.createElement === "function"
      && w > 0 && h > 0 && typeof ctx.drawImage === "function";
    if (!canCache) {
      renderFloorCad(ctx, toPx, activeMap, lanes, overlayMode);
      return;
    }

    const o = toPx(0, 0), ux = toPx(1, 0), uy = toPx(0, 1);
    const tf = typeof ctx.getTransform === "function" ? ctx.getTransform() : null;
    const cacheKey = [
      activeMap?.map_id ?? "",
      activeMap?.walls?.length ?? 0,
      activeMap?.places?.length ?? 0,
      lanes?.paintTriangles?.length ?? 0,
      w,
      h,
      overlayMode ? 1 : 0,
      planSignature(view?.chargeBaysPlan),
      o.x, o.y, ux.x, ux.y, uy.x, uy.y,
      tf?.a ?? 1, tf?.d ?? 1,
      css("--line-quiet"),
    ].join("|");

    if (floorCache.key !== cacheKey) {
      const off = floorCache.canvas || document.createElement("canvas");
      if (off.width !== w) off.width = w;
      if (off.height !== h) off.height = h;
      const offCtx = floorCache.ctx && floorCache.canvas === off ? floorCache.ctx : off.getContext("2d");
      if (!offCtx) {
        renderFloorCad(ctx, toPx, activeMap, lanes, overlayMode);
        return;
      }
      if (typeof offCtx.setTransform === "function") offCtx.setTransform(1, 0, 0, 1, 0, 0);
      if (typeof offCtx.clearRect === "function") offCtx.clearRect(0, 0, w, h);
      if (tf && typeof offCtx.setTransform === "function") offCtx.setTransform(tf);
      renderFloorCad(offCtx, toPx, activeMap, lanes, overlayMode);
      floorCache = { key: cacheKey, canvas: off, ctx: offCtx };
    }
    ctx.save();
    if (typeof ctx.setTransform === "function") ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(floorCache.canvas, 0, 0);
    ctx.restore();
  }

  function drawRobotCadModels(ctx, toPx, { guide, anchors, chargeBaysPlan, overlayMode = false, focusedRobotId = null, preloadIfMissing = true } = {}) {
    if (!ctx || !toPx) return;
    if (!meshAssets) {
      if (preloadIfMissing && !meshPromise) void ensureMeshes();
      return;
    }
    const baseFillAlpha = overlayMode ? 0.38 : 0.78;
    const baseStrokeAlpha = 0.9;
    const primaryCol = css("--series-primary");
    const selectionCol = css("--selection");
    const quietCol = css("--ink-quiet");
    const warnCol = css("--status-warn");
    const rigPaint = (selected, { offline = false, degraded = false } = {}) => {
      const col = selected ? selectionCol : (offline ? quietCol : degraded ? warnCol : primaryCol);
      const fillScale = offline ? 0.45 : degraded ? 0.65 : 1;
      const strokeScale = offline ? 0.55 : degraded ? 0.85 : 1;
      return {
        fillCol: col,
        strokeCol: col,
        fillAlpha: baseFillAlpha * fillScale,
        strokeAlpha: baseStrokeAlpha * strokeScale,
        lineDash: (offline || degraded) ? [4, 3] : null,
      };
    };

    const viewRobotsById = new Map();
    for (const row of view?.robots || []) {
      if (row?.robot_id) viewRobotsById.set(row.robot_id, row);
    }

    const seenRobots = new Set();
    const robotList = [];
    for (const row of guide?.robots || []) {
      if (row?.robot_id && finite(row.pose?.x) && finite(row.pose?.y)) {
        const viewRow = viewRobotsById.get(row.robot_id);
        const offline = row.online === false || viewRow?.online === false;
        const degraded = Boolean(
          (row.pose.state && row.pose.state !== "LOCALIZED") || row.pose.source === "bridged"
          || row.stale || row.pose.stale || viewRow?.stale || view?.guideStale,
        );
        seenRobots.add(row.robot_id);
        robotList.push({ id: row.robot_id, pose: row.pose, offline, degraded });
      }
    }
    for (const row of view?.robots || []) {
      if (!row?.robot_id || seenRobots.has(row.robot_id)) continue;
      const pose = (row.pose && (!row.pose.pose_frame || row.pose.pose_frame === "map"))
        ? row.pose : robotMapPose(row);
      if (finite(pose?.x) && finite(pose?.y)) {
        const offline = row.online === false;
        const degraded = Boolean(
          row.stale || row.state?.evidence?.pose?.evidence === "delayed"
          || (pose.state && pose.state !== "LOCALIZED") || pose.source === "bridged",
        );
        seenRobots.add(row.robot_id);
        robotList.push({ id: row.robot_id, pose, offline, degraded });
      }
    }
    for (const robot of robotList) {
      const selected = focusedRobotId === robot.id;
      const paint = rigPaint(selected, robot);
      drawProjectedRig(ctx, toPx, pinkyLocalRig, robot.pose.x, robot.pose.y, finite(robot.pose.yaw) ? robot.pose.yaw : 0, {
        ...paint,
        lineWidth: selected ? 2.1 : 1.4,
      });
    }

    const armAnchors = Array.isArray(anchors) ? anchors
      : (Array.isArray(guide?.anchors) ? guide.anchors : (Array.isArray(view?.anchors) ? view.anchors : []));
    const liveStates = chargeBaysPlan?.arm_live_states || view?.chargeBaysPlan?.arm_live_states || {};
    for (const anc of armAnchors) {
      if (anc?.kind !== "omx_ai" || !finite(anc.base_x) || !finite(anc.base_y)) continue;
      const id = anc.target_id;
      const live = liveStates?.[id];
      const degs = live?.joints_deg;
      const rads = Array.isArray(degs) ? degs.map((v) => (finite(v) ? (v * Math.PI) / 180 : undefined)) : [];
      const { angles } = jointAngles(meshAssets.omx.model, jointsFromList(rads, OMX_JOINT_NAMES));
      const cacheKey = OMX_JOINT_NAMES.map((n) => Math.round((angles[n] ?? 0) * 100)).join(",");
      let rig = omxRigCache.get(cacheKey);
      if (!rig) {
        rig = projectModelLocal(meshAssets.omx, angles);
        omxRigCache.set(cacheKey, rig);
        if (omxRigCache.size > 32) omxRigCache.delete(omxRigCache.keys().next().value);
      }
      let baseYaw = finite(anc.base_yaw) ? anc.base_yaw : null;
      if (baseYaw === null && finite(anc.head_x) && finite(anc.head_y)) {
        const dx = anc.head_x - anc.base_x, dy = anc.head_y - anc.base_y;
        if (Math.hypot(dx, dy) > 1e-4) baseYaw = Math.atan2(dy, dx) - (angles.joint1 ?? 0);
      }
      const selected = focusedRobotId === id;
      const offline = Boolean((live && (live.online === false || live.available === false)) || anc.online === false);
      const degraded = Boolean(live?.stale === true || anc.stale === true);
      const paint = rigPaint(selected, { offline, degraded });
      drawProjectedRig(ctx, toPx, rig, anc.base_x, anc.base_y, baseYaw ?? 0, {
        ...paint,
        lineWidth: selected ? 2.2 : 1.5,
      });
    }
  }

  function preload(mapId = null) {
    return Promise.all([ensureSiteLanes(mapId), ensureMeshes()]);
  }

  return {
    ensureSiteLanes,
    ensureMeshes,
    preload,
    drawFloorCad,
    drawRobotCadModels,
    getSiteLanes: () => currentSiteLanes,
  };
}
