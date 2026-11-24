import { pbrMaterialForChunk } from "./studio-look.js";

const CAD_TRIANGLES = 1_704_798;
const STL_HEADER_BYTES = 84;
const STL_TRIANGLE_BYTES = 50;
const CAD_TAPE_BOUNDS = [
  [-0.777, -0.593, -0.153, -0.125], [0.199, 0.382, -0.153, -0.125],
  [0.760, 0.788, -0.343, -0.161], [0.899, 0.927, -0.567, -0.385],
  [0.456, 0.484, -0.567, -0.385],
];

export async function readCadGeometry(three, url, { studioMode = false } = {}) {
  const response = await fetch(url, { redirect: "error" });
  if (!response.ok || !response.body) throw new Error("CAD archive unavailable");
  const reader = response.body.pipeThrough(new DecompressionStream("gzip")).getReader();
  const bytes = new Uint8Array(STL_HEADER_BYTES + CAD_TRIANGLES * STL_TRIANGLE_BYTES);
  let length = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (length + value.byteLength > bytes.byteLength) {
      await reader.cancel();
      throw new Error("CAD archive exceeds the expected STL size");
    }
    bytes.set(value, length);
    length += value.byteLength;
  }
  const stl = new DataView(bytes.buffer);
  if (length !== bytes.byteLength || stl.getUint32(80, true) !== CAD_TRIANGLES) {
    throw new Error("Invalid archived STL size or triangle count");
  }
  const points = new Float32Array(CAD_TRIANGLES * 9);
  const colors = new Uint8Array(points.length);
  const paletteHex = studioMode
    ? [0x6d7782, 0x6f747b, 0xf2f5f9, 0x2f684e, 0xd09c19]
    : [0x72808d, 0x494f58, 0xf7f4ec, 0x25674f, 0xd7a32a];
  const [base, mat, paint, bay, deck] = paletteHex.map((hex) =>
    new three.Color(hex).toArray().map((channel) => Math.round(channel * 255)));
  for (let triangle = 0; triangle < CAD_TRIANGLES; triangle += 1) {
    const face = STL_HEADER_BYTES + triangle * STL_TRIANGLE_BYTES;
    const start = triangle * 9;
    for (let vertex = 0; vertex < 3; vertex += 1) {
      const from = face + 12 + vertex * 12;
      const to = start + vertex * 3;
      // Recenter the archived mat and convert CAD millimetres/Y-up to metres/Z-up.
      const x = (stl.getFloat32(from, true) - 1232.1999745368958) / 1000;
      const y = -(stl.getFloat32(from + 8, true) - 969.5999603271484) / 1000;
      const z = (stl.getFloat32(from + 4, true) - 33.7) / 1000;
      if (!Number.isFinite(x + y + z)) throw new Error("Invalid CAD vertex");
      points[to] = x;
      points[to + 1] = y;
      points[to + 2] = z;
    }
    const x = (points[start] + points[start + 3] + points[start + 6]) / 3;
    const y = (points[start + 1] + points[start + 4] + points[start + 7]) / 3;
    const z = (points[start + 2] + points[start + 5] + points[start + 8]) / 3;
    const upward = stl.getFloat32(face + 4, true) >= 0.95;
    let color = base;
    const outOfMatBounds = (
      Math.max(points[start], points[start + 3], points[start + 6]) > 1.23 ||
      Math.min(points[start], points[start + 3], points[start + 6]) < -1.23 ||
      Math.max(points[start + 1], points[start + 4], points[start + 7]) > 0.62 ||
      Math.min(points[start + 1], points[start + 4], points[start + 7]) < -0.62
    );
    // The October STL includes old tape footprints. Use the observed November tape in siteMarkings.
    if (outOfMatBounds || (z > 0.000001 && z < 0.0016 && CAD_TAPE_BOUNDS.some(([left, right, bottom, top]) =>
      x >= left && x <= right && y >= bottom && y <= top))) {
      points.copyWithin(start + 3, start, start + 3);
      points.copyWithin(start + 6, start, start + 3);
    }
    // Match the archived mat and paint height bands, with deck colors from the ceiling photo.
    if (upward && Math.abs(z) < 0.00005) color = mat;
    if (upward && z >= 0.0005 && z <= 0.0015) {
      color = y > 0.2 && x > -0.56 && x < 0.17 ? bay : paint;
    }
    if (upward && (Math.abs(z - 0.072) < 0.00005 || Math.abs(z - 0.018) < 0.00005)) color = deck;
    colors.set(color, start);
    colors.set(color, start + 3);
    colors.set(color, start + 6);
  }
  const geometry = new three.BufferGeometry();
  geometry.setAttribute("position", new three.BufferAttribute(points, 3));
  geometry.setAttribute("color", new three.BufferAttribute(colors, 3, true));
  return geometry;
}

export async function readEquipment(three, url, options = {}) {
  const {
    dropTriangle = null, extractRoadPinky = false, hideStaticCargo = false,
    hideStaticArms = false, studioMode = false,
  } = options;
  const response = await fetch(url, { redirect: "error" });
  if (!response.ok || !response.body || !window.DecompressionStream) {
    throw new Error("Equipment geometry is unavailable");
  }
  const bytes = response.body.pipeThrough(new DecompressionStream("gzip"));
  const model = await new Response(bytes).json();
  if (model.schema !== "rosy.world.meshes.v1" || !Array.isArray(model.chunks) ||
      !model.chunks.length || model.chunks.length > 64) throw new Error("Invalid equipment model");
  const group = new three.Group();
  const pinkyGroup = extractRoadPinky ? new three.Group() : null;
  for (const { positions, color } of model.chunks) {
    if (!Array.isArray(positions) || !positions.length || positions.length % 9 ||
        positions.length > 9_000_000 || !positions.every(Number.isFinite) ||
        !Array.isArray(color) || color.length !== 3 ||
        !color.every((channel) => Number.isFinite(channel) && channel >= 0 && channel <= 1)) {
      throw new Error("Invalid equipment geometry");
    }
    const [cr, cg, cb] = color;
    if (hideStaticCargo && cr > 0.58 && cr < 0.68 && cg > 0.27 && cg < 0.36 && cb > 0.10 && cb < 0.19) {
      continue;
    }
    const filterArmChunk = hideStaticArms && cr < 0.25 && cg < 0.25 && cb < 0.25;
    const isWristMountWhite = hideStaticArms && cr > 0.90 && cg > 0.90 && cb > 0.88;
    if (isWristMountWhite) continue;
    let filtered = positions;
    const extracted = extractRoadPinky ? [] : null;
    if (dropTriangle || extractRoadPinky || filterArmChunk) {
      filtered = [];
      for (let i = 0; i < positions.length; i += 9) {
        const cx = (positions[i] + positions[i + 3] + positions[i + 6]) / 3;
        const cy = (positions[i + 1] + positions[i + 4] + positions[i + 7]) / 3;
        const cz = (positions[i + 2] + positions[i + 5] + positions[i + 8]) / 3;
        if (filterArmChunk && cx > -0.02 && cz > 0.089) continue;
        if (dropTriangle && dropTriangle(cx, cy, cz)) {
          if (extracted && cx > 0.45 && cy < 0.0) {
            for (let j = 0; j < 9; j += 1) extracted.push(positions[i + j]);
          }
        } else {
          for (let j = 0; j < 9; j += 1) filtered.push(positions[i + j]);
        }
      }
    }
    const makeMaterial = () => (studioMode ? pbrMaterialForChunk(three, color, options.r2sPalette ?? null) : new three.MeshStandardMaterial({
      side: three.DoubleSide, flatShading: true, color: new three.Color(...color),
    }));
    if (filtered.length) {
      const geometry = new three.BufferGeometry();
      geometry.setAttribute("position", new three.Float32BufferAttribute(filtered, 3));
      if (studioMode) geometry.computeVertexNormals();
      const mesh = new three.Mesh(geometry, makeMaterial());
      if (studioMode) mesh.castShadow = mesh.receiveShadow = true;
      group.add(mesh);
    }
    if (extracted?.length && pinkyGroup) {
      const pGeom = new three.BufferGeometry();
      pGeom.setAttribute("position", new three.Float32BufferAttribute(extracted, 3));
      pGeom.translate(-0.82, 0.28, 0);
      pGeom.rotateZ(Math.PI);
      pGeom.computeVertexNormals();
      const pMesh = new three.Mesh(pGeom, makeMaterial());
      pMesh.castShadow = pMesh.receiveShadow = true;
      pinkyGroup.add(pMesh);
    }
  }
  const anchors = {};
  for (const name of ["C1", "C2", "C3", "Pinky", "OMX"]) {
    const point = model.anchors?.[name];
    if (Array.isArray(point) && point.length === 3 &&
        point.every((coordinate) => Number.isFinite(coordinate) && Math.abs(coordinate) <= 5)) {
      anchors[name] = new three.Vector3(...point);
    }
  }
  group.userData.anchors = anchors;
  group.userData.layoutHash = model.layout_sha256;
  if (pinkyGroup?.children.length) group.userData.extractedPinky = pinkyGroup;
  return group;
}

export function cadLabels(three, scene, anchors, studioMode = false) {
  let lastSprite;
  for (const [name, position] of Object.entries(anchors)) {
    const canvas = document.createElement("canvas");
    canvas.width = name.length > 3 ? 256 : 160;
    canvas.height = 80;
    const context = canvas.getContext("2d");
    context.fillStyle = window.RosyPalette.cssColor(studioMode ? "--surface-raised" : "--ground");
    context.strokeStyle = window.RosyPalette.cssColor(studioMode ? "--series-primary" : "--border-strong");
    context.lineWidth = 4;
    if (studioMode && context.roundRect) {
      context.beginPath();
      context.roundRect(4, 6, canvas.width - 8, canvas.height - 12, 16);
      context.fill();
      context.stroke();
    } else {
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
    }
    context.fillStyle = window.RosyPalette.cssColor("--ink");
    context.font = window.RosyPalette.canvasFont("label", "body", 3);
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(name, canvas.width / 2, 41);
    const map = new three.CanvasTexture(canvas);
    map.colorSpace = three.SRGBColorSpace;
    const sprite = new three.Sprite(new three.SpriteMaterial({ map, depthTest: false }));
    sprite.position.copy(position);
    const labelScale = studioMode ? 0.036 : 0.043;
    sprite.scale.set(labelScale * canvas.width / canvas.height, labelScale, 1);
    scene.add(sprite);
    lastSprite = sprite;
  }
  return lastSprite;
}

export function lightEquipment(three, scene) {
  const light = new three.DirectionalLight(undefined, 2);
  light.position.set(-2, -3, 4);
  scene.add(new three.HemisphereLight(0xffffff, 0x65717d, 1.1), light);
}

export function siteMarkings(three, scene, studioMode = false, r2sPalette = null) {
  const markingsGroup = new three.Group();
  const makeMat = (hex) => (studioMode
    ? new three.MeshStandardMaterial({ color: hex, roughness: 0.56, metalness: 0.04 })
    : new three.MeshBasicMaterial({ color: hex }));
  const pink = makeMat(r2sPalette?.pink_guide_hex ?? 0xb47f93);
  const green = makeMat(r2sPalette?.green_bay_hex ?? 0x2f684e);
  const black = makeMat(0x22242a);
  const yellow = makeMat(0xe0b645);
  function strip([x, y], [endX, endY], width, material, z = 0.002) {
    const dx = endX - x, dy = endY - y;
    const segment = new three.Mesh(new three.PlaneGeometry(Math.hypot(dx, dy), width), material);
    segment.position.set(x + dx / 2, y + dy / 2, z);
    segment.rotation.z = Math.atan2(dy, dx);
    if (studioMode) segment.receiveShadow = true;
    markingsGroup.add(segment);
  }
  // Green bay divider borders & pink charging guide lines measured on site-birdview.jpg & field-photo.jpg.
  for (const gx of [-0.535, -0.302, -0.078, 0.148]) strip([gx, 0.22], [gx, 0.59], 0.016, green, 0.0019);
  strip([-0.535, 0.59], [0.148, 0.59], 0.016, green, 0.0019);
  for (const x of [-0.414, -0.190, 0.032]) strip([x, 0.022], [x, 0.53], 0.018, pink);
  strip([-0.61, 0.022], [0.25, 0.022], 0.018, pink);
  strip([-0.61, 0.022], [-0.65, -0.045], 0.018, pink);
  strip([0.25, 0.022], [0.28, -0.045], 0.018, pink);
  for (const [x, y, dx, dy] of [
    [-0.80, -0.14, 0.22, 0], [0.20, -0.14, 0.20, 0],
    [0.69, -0.18, 0, -0.15], [0.145, -0.41, 0, -0.15], [0.91, -0.41, 0, -0.15],
  ]) {
    for (let part = 0; part < 4; part += 1) {
      strip([x + dx * part / 4, y + dy * part / 4],
        [x + dx * (part + 1) / 4, y + dy * (part + 1) / 4], 0.022, part % 2 ? yellow : black);
    }
  }
  scene.add(markingsGroup);
  return markingsGroup;
}
