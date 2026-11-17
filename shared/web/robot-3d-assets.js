/**
 * Shared lazy loader and in-memory cache for Three.js and parsed robot URDF/STL assets.
 * Three.js is fetched via dynamic import only when loadThree() is first called.
 */
import { parseUrdf, parseStl } from "./robot-3d-model.js";

export const MODELS = Object.freeze({ arm: "omx-f.urdf", mobile: "pinky-pro.urdf" });

const THREE_URL = new URL("./vendor/three.module.min.js", import.meta.url).href;
let threeLoad = null;
const modelLoads = new Map();

export function loadThree() {
  return (threeLoad ??= import(THREE_URL).catch((error) => {
    threeLoad = null;
    throw error;
  }));
}

async function fetchAsset(url, kind) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return kind === "text" ? response.text() : response.arrayBuffer();
}

export function loadRobotModel(kind) {
  if (!Object.hasOwn(MODELS, kind)) {
    return Promise.reject(new RangeError(`unknown robot model kind: ${kind}`));
  }
  if (!modelLoads.has(kind)) {
    const base = new URL(`./meshes/${MODELS[kind]}`, import.meta.url);
    modelLoads.set(kind, (async () => {
      const model = parseUrdf(await fetchAsset(base.href, "text"));
      const meshes = {};
      const names = [...new Set(Object.values(model.links).map((link) => link.mesh).filter(Boolean))];
      await Promise.all(names.map(async (name) => {
        meshes[name] = parseStl(await fetchAsset(new URL(name, base).href, "buffer"));
      }));
      return { model, meshes };
    })().catch((error) => {
      modelLoads.delete(kind);
      throw error;
    }));
  }
  return modelLoads.get(kind);
}

export function clearRobotModelCache() {
  modelLoads.clear();
}

export const ELEV_MAX = Math.PI / 2 - 0.002;
const WALL_HEIGHT_M = 0.12;
const WALL_THICKNESS_M = 0.025;
export const finite = (value) => typeof value === "number" && Number.isFinite(value);

export function siteBoundsCenter(bounds) {
  if (!bounds) return null;
  const { min_x: minX, max_x: maxX, min_y: minY, max_y: maxY } = bounds;
  if (![minX, maxX, minY, maxY].every(finite) || maxX <= minX || maxY <= minY) return null;
  const width = maxX - minX, height = maxY - minY;
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, width, height, radius: Math.hypot(width, height) / 2 };
}

export function rayPlaneIntersection(origin, dir, planeZ = 0) {
  const ox = Array.isArray(origin) ? origin[0] : origin?.x;
  const oy = Array.isArray(origin) ? origin[1] : origin?.y;
  const oz = Array.isArray(origin) ? origin[2] : origin?.z;
  const dx = Array.isArray(dir) ? dir[0] : dir?.x;
  const dy = Array.isArray(dir) ? dir[1] : dir?.y;
  const dz = Array.isArray(dir) ? dir[2] : dir?.z;
  if (![ox, oy, oz, dx, dy, dz, planeZ].every(finite) || Math.abs(dz) < 1e-9) return null;
  const t = (planeZ - oz) / dz;
  if (t < 0) return null;
  return { x: ox + t * dx, y: oy + t * dy, z: planeZ, t };
}

export function orbitEyePosition(target, orbit) {
  const tx = target?.[0] ?? 0, ty = target?.[1] ?? 0, tz = target?.[2] ?? 0;
  const planar = Math.cos(orbit.el) * orbit.dist;
  return [
    tx + planar * Math.cos(orbit.az),
    ty + planar * Math.sin(orbit.az),
    tz + Math.sin(orbit.el) * orbit.dist,
  ];
}

export function twinPresetOrbit(bounds, preset = "iso", turnDeg = 0) {
  if (typeof bounds === "string") return twinPresetOrbit(preset, bounds, turnDeg);
  const info = siteBoundsCenter(bounds) || { x: 0, y: 0, radius: 1.5 };
  const radius = Math.max(info.radius, 0.5);
  const turn = [90, 180, 270].includes(turnDeg) ? turnDeg : 0;
  const turnRad = (turn * Math.PI) / 180;
  if (preset === "top") {
    return { az: -Math.PI / 2 + turnRad, el: ELEV_MAX, dist: radius * 2.25, target: [info.x, info.y, 0] };
  }
  if (preset === "iso" || preset === "reset") {
    return { az: -Math.PI * 0.35 + turnRad, el: 0.72, dist: radius * 2.35, target: [info.x, info.y, 0] };
  }
  throw new RangeError(`unknown twin preset ${preset}`);
}

export function inferBounds(state) {
  if (siteBoundsCenter(state?.bounds)) return state.bounds;
  if (siteBoundsCenter(state?.siteLanes?.bounds)) return state.siteLanes.bounds;
  const pts = [
    ...(state?.activeMap?.places || []).map((p) => [p.x, p.y]),
    ...(state?.activeMap?.walls || []).flatMap((w) => w.face || []),
  ].filter(([x, y]) => finite(x) && finite(y));
  if (!pts.length) return { min_x: -1.5, max_x: 1.5, min_y: -0.75, max_y: 0.75 };
  const xs = pts.map(([x]) => x), ys = pts.map(([, y]) => y);
  return {
    min_x: Math.min(...xs) - 0.25, max_x: Math.max(...xs) + 0.25,
    min_y: Math.min(...ys) - 0.25, max_y: Math.max(...ys) + 0.25,
  };
}

export function buildUrdfGroup(three, loaded, entity, colors) {
  const { Group, Mesh, BufferGeometry, BufferAttribute, MeshLambertMaterial, MeshBasicMaterial, Euler, RingGeometry } = three;
  const root = new Group(), nodes = {}, rotators = new Map(), bodyMaterials = [], geometries = [], pickMeshes = [];
  let shadeIdx = 0;
  const stls = {};
  for (const [name, positions] of Object.entries(loaded.meshes)) {
    const geom = new BufferGeometry();
    geom.setAttribute("position", new BufferAttribute(positions, 3));
    geom.computeVertexNormals();
    stls[name] = geom;
    geometries.push(geom);
  }
  for (const [name, link] of Object.entries(loaded.model.links)) {
    const node = nodes[name] = new Group();
    if (!link.mesh || !stls[link.mesh]) continue;
    const holder = new Group();
    holder.position.set(...link.xyz);
    holder.rotation.copy(new Euler(link.rpy[0], link.rpy[1], link.rpy[2], "ZYX"));
    const mat = new MeshLambertMaterial({ color: colors.body.clone() });
    mat.userData.shade = shadeIdx++ % 2 ? 0.84 : 1;
    bodyMaterials.push(mat);
    const mesh = new Mesh(stls[link.mesh], mat);
    mesh.userData.entity = entity;
    pickMeshes.push(mesh);
    holder.add(mesh);
    node.add(holder);
  }
  for (const joint of loaded.model.joints) {
    const holder = new Group(), turning = new Group();
    holder.position.set(...joint.xyz);
    holder.rotation.copy(new Euler(joint.rpy[0], joint.rpy[1], joint.rpy[2], "ZYX"));
    holder.add(turning);
    turning.add(nodes[joint.child]);
    nodes[joint.parent].add(holder);
    if (joint.type === "revolute" || joint.type === "continuous") {
      rotators.set(joint.name, { node: turning, axis: joint.axis });
    }
  }
  root.add(nodes[loaded.model.root]);
  const ringR = entity.kind === "omx_ai" ? 0.085 : 0.075;
  const ringGeom = new RingGeometry(ringR, ringR + 0.012, 36);
  const ringMat = new MeshBasicMaterial({ color: colors.selection.clone(), side: three.DoubleSide });
  const ring = new Mesh(ringGeom, ringMat);
  ring.position.z = 0.008;
  ring.visible = false;
  root.add(ring);
  geometries.push(ringGeom);
  return {
    root, rotators, bodyMaterials, ring, ringMat, geometries, pickMeshes,
    dispose() {
      geometries.forEach((g) => g.dispose());
      bodyMaterials.forEach((m) => m.dispose());
      ringMat.dispose();
    },
  };
}

export function rebuildFloorMesh(three, scene, floorState, colors, bounds) {
  const info = siteBoundsCenter(bounds);
  if (!info || !scene) return;
  if (floorState.mesh) { scene.remove(floorState.mesh); floorState.geom?.dispose(); }
  if (floorState.grid) {
    scene.remove(floorState.grid);
    floorState.grid.geometry?.dispose();
    floorState.grid.material?.dispose();
  }
  const geom = new three.PlaneGeometry(info.width, info.height);
  if (!floorState.mat) {
    floorState.mat = new three.MeshBasicMaterial({ color: colors.floor.clone(), side: three.FrontSide });
  }
  const plane = new three.Mesh(geom, floorState.mat);
  plane.position.set(info.x, info.y, 0);
  scene.add(plane);
  floorState.geom = geom;
  floorState.mesh = plane;
  const verts = [], step = 0.5;
  for (let x = Math.ceil(bounds.min_x / step) * step; x <= bounds.max_x + 1e-6; x += step) {
    verts.push(x, bounds.min_y, 0.001, x, bounds.max_y, 0.001);
  }
  for (let y = Math.ceil(bounds.min_y / step) * step; y <= bounds.max_y + 1e-6; y += step) {
    verts.push(bounds.min_x, y, 0.001, bounds.max_x, y, 0.001);
  }
  const gridGeom = new three.BufferGeometry();
  gridGeom.setAttribute("position", new three.Float32BufferAttribute(verts, 3));
  const gridMat = new three.LineBasicMaterial({ color: colors.line.clone(), transparent: true, opacity: 0.45 });
  const grid = new three.LineSegments(gridGeom, gridMat);
  scene.add(grid);
  floorState.grid = grid;
}

export function updateCameraFloorTexture(three, floorState, colors, cameraInput) {
  if (!floorState.mat || !three) return;
  const cameraCanvas = cameraInput && cameraInput.canvas ? cameraInput.canvas : cameraInput;
  const seq = cameraInput?.seq ?? cameraInput?.floorSeq;
  const hasLive = Boolean(cameraCanvas && cameraCanvas.width > 0 && cameraCanvas.height > 0);
  if (hasLive) {
    let textureChanged = false;
    if (!floorState.texture || floorState.texture.image !== cameraCanvas) {
      floorState.texture?.dispose();
      floorState.texture = new three.CanvasTexture(cameraCanvas);
      if (three.SRGBColorSpace) floorState.texture.colorSpace = three.SRGBColorSpace;
      floorState.seq = -1;
      textureChanged = true;
    }
    if (seq == null || seq !== floorState.seq) {
      floorState.texture.needsUpdate = true;
      floorState.seq = seq ?? -1;
    }
    if (floorState.mat.map !== floorState.texture || textureChanged) {
      floorState.mat.map = floorState.texture;
      floorState.mat.color.setRGB(1, 1, 1);
      floorState.mat.needsUpdate = true;
    }
    if (floorState.grid) floorState.grid.visible = false;
  } else {
    floorState.seq = -1;
    if (floorState.mat.map) { floorState.mat.map = null; floorState.mat.needsUpdate = true; }
    floorState.mat.color.copy(colors.floor);
    if (floorState.grid) floorState.grid.visible = true;
  }
}

export function rebuildSiteGroupMesh(three, scene, siteGroupState, colors, state) {
  if (siteGroupState.group && scene) scene.remove(siteGroupState.group);
  for (const item of siteGroupState.disposables) item.dispose?.();
  siteGroupState.disposables = [];
  siteGroupState.placeRings.clear();
  siteGroupState.group = null;
  const { Group, Mesh, BoxGeometry, BufferGeometry, Float32BufferAttribute, MeshLambertMaterial, MeshBasicMaterial, CylinderGeometry, RingGeometry, Line, LineBasicMaterial, Vector3, DoubleSide } = three;
  const group = new Group(), disposables = [], activeMap = state.activeMap;
  for (const wall of activeMap?.walls || []) {
    const face = wall?.face;
    if (!Array.isArray(face) || face.length < 2) continue;
    const [x0, y0] = face[0], [x1, y1] = face[1], len = Math.hypot(x1 - x0, y1 - y0);
    if (len < 1e-4) continue;
    const geom = new BoxGeometry(len, WALL_THICKNESS_M, WALL_HEIGHT_M);
    const mat = new MeshLambertMaterial({ color: colors.wall.clone() });
    const mesh = new Mesh(geom, mat);
    mesh.position.set((x0 + x1) / 2, (y0 + y1) / 2, WALL_HEIGHT_M / 2);
    mesh.rotation.z = Math.atan2(y1 - y0, x1 - x0);
    group.add(mesh);
    disposables.push(geom, mat);
  }
  const paintTris = state.siteLanes?.paintTriangles || [];
  if (paintTris.length) {
    const pos = new Float32Array(paintTris.length * 9);
    let k = 0;
    for (const tri of paintTris) {
      if (!Array.isArray(tri) || tri.length < 6) continue;
      pos[k++] = tri[0]; pos[k++] = tri[1]; pos[k++] = 0.002;
      pos[k++] = tri[2]; pos[k++] = tri[3]; pos[k++] = 0.002;
      pos[k++] = tri[4]; pos[k++] = tri[5]; pos[k++] = 0.002;
    }
    const geom = new BufferGeometry();
    geom.setAttribute("position", new Float32BufferAttribute(pos.subarray(0, k), 3));
    const mat = new MeshBasicMaterial({ color: colors.line.clone(), transparent: true, opacity: 0.48, side: DoubleSide });
    group.add(new Mesh(geom, mat));
    disposables.push(geom, mat);
  }
  for (const edge of activeMap?.edges || []) {
    if (!Array.isArray(edge.polyline) || edge.polyline.length < 2) continue;
    const geom = new BufferGeometry().setFromPoints(edge.polyline.map(([x, y]) => new Vector3(x, y, 0.004)));
    const mat = new LineBasicMaterial({ color: colors.primary.clone() });
    group.add(new Line(geom, mat));
    disposables.push(geom, mat);
  }
  for (const place of activeMap?.places || []) {
    if (!finite(place?.x) || !finite(place?.y)) continue;
    const pid = String(place.id || ""), isCharger = pid.startsWith("C"), isStation = pid.startsWith("S");
    const radius = isCharger || isStation ? 0.075 : 0.035;
    const geom = new CylinderGeometry(radius, radius, 0.004, 24);
    geom.rotateX(Math.PI / 2);
    const col = isCharger ? colors.goal : isStation ? colors.warn : colors.body;
    const mat = new MeshBasicMaterial({ color: col.clone() });
    const pad = new Mesh(geom, mat);
    pad.position.set(place.x, place.y, 0.005);
    pad.userData.entity = { kind: "place", id: place.id, place };
    group.add(pad);
    disposables.push(geom, mat);
    const ringGeom = new RingGeometry(radius * 1.15, radius * 1.45, 28);
    const ringMat = new MeshBasicMaterial({ color: colors.selection.clone(), side: DoubleSide });
    const ring = new Mesh(ringGeom, ringMat);
    ring.position.set(place.x, place.y, 0.007);
    ring.visible = false;
    group.add(ring);
    disposables.push(ringGeom, ringMat);
    siteGroupState.placeRings.set(place.id, ring);
  }
  scene.add(group);
  siteGroupState.group = group;
  siteGroupState.disposables = disposables;
}

export function localizedMapPose(row) {
  const state = row?.state, pose = state?.pose;
  if (!pose || !finite(pose.x) || !finite(pose.y) || !finite(pose.yaw)) return null;
  const frame = row.localization?.pose_frame || state.localization?.pose_frame || (state.map_id ? "map" : "odom");
  if (frame !== "map") return null;
  return state.localization?.state === "LOCALIZED" && state.localization?.pose_frame === "map" ? pose : null;
}

export function styleRig(rig, colors, selected, { offline = false, degraded = false } = {}) {
  rig.ring.visible = selected;
  rig.ringMat.color.copy(colors.selection);
  const baseCol = selected ? colors.selection : (offline ? colors.body : degraded ? colors.warn : colors.primary);
  const nextTransparent = Boolean(offline || degraded);
  const nextOpacity = offline ? 0.35 : degraded ? 0.65 : 1;
  for (const mat of rig.bodyMaterials) {
    mat.color.copy(baseCol).multiplyScalar(mat.userData.shade ?? 1);
    mat.opacity = nextOpacity;
    if (mat.transparent !== nextTransparent) {
      mat.transparent = nextTransparent;
      mat.needsUpdate = true;
    }
  }
}
