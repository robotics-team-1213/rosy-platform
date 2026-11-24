import {
  configureStudioRenderer, attachStudioEnvironment, pbrMaterialForChunk, createProceduralFactoryFloor,
} from "./studio-look.js";

let three;

function token(name) {
  const [r, g, b] = window.RosyPalette.readColour(name);
  return (r << 16) | (g << 8) | b;
}

function createRenderer(canvas) {
  try {
    return new three.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  } catch {
    return new three.WebGLRenderer({ canvas, antialias: false, powerPreference: "default" });
  }
}

function viewport(canvas, camera, scene, prepare, contextLost, options = {}) {
  const renderer = createRenderer(canvas);
  if (options.studioMode) configureStudioRenderer(three, renderer);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  if (renderer.getContext().isContextLost()) throw new Error("WebGL context lost");
  let lastW = 0, lastH = 0;
  function draw() {
    const { clientWidth: width, clientHeight: height } = canvas;
    if (!width || !height) return;
    prepare(width / height);
    camera.updateProjectionMatrix();
    if (width !== lastW || height !== lastH) {
      renderer.setSize(width, height, false);
      lastW = width;
      lastH = height;
    }
    renderer.render(scene, camera);
  }
  const resize = new ResizeObserver(draw);
  resize.observe(canvas);
  document.addEventListener("rosy:theme", draw);
  canvas.addEventListener("webglcontextlost", () => {
    resize.disconnect();
    document.removeEventListener("rosy:theme", draw);
    contextLost();
  }, { once: true });
  draw.renderer = renderer;
  return draw;
}

function path(points, material) {
  const vertices = points.map(([x, y, z = 0]) => new three.Vector3(x, y, z));
  return new three.Line(new three.BufferGeometry().setFromPoints(vertices), material);
}

function marker(geometry, colour, x, y, z) {
  const mesh = new three.Mesh(geometry, new three.MeshBasicMaterial({ color: colour }));
  mesh.position.set(x, y, z);
  return mesh;
}

export async function showMap(canvas, map, contextLost) {
  three ??= await import("./common/vendor/three.module.min.js");
  const scene = new three.Scene();
  const camera = new three.OrthographicCamera(-1, 1, 1, -1, 0.01, 10);
  camera.position.z = 2;
  const route = new three.LineBasicMaterial();
  const placeGeometry = new three.CircleGeometry(0.017, 16);
  const observationGeometry = new three.RingGeometry(0.016, 0.036, 20);
  const places = map.places.map(({ x, y }) => marker(placeGeometry, token("--ink"), x, y, 0.01));
  const observations = new three.Group();
  const bounds = new three.Box2();
  for (const points of [...map.edges, map.places.map(({ x, y }) => [x, y])]) {
    for (const [x, y] of points) bounds.expandByPoint(new three.Vector2(x, y));
  }
  for (const edge of map.edges) scene.add(path(edge, route));
  scene.add(...places, observations);
  const center = bounds.getCenter(new three.Vector2());
  const size = bounds.getSize(new three.Vector2());
  camera.position.x = center.x;
  camera.position.y = center.y;
  const update = (aspect) => {
    const halfHeight = Math.max(size.y, size.x / aspect, 0.2) * 0.6;
    camera.left = -halfHeight * aspect;
    camera.right = halfHeight * aspect;
    camera.top = halfHeight;
    camera.bottom = -halfHeight;
    scene.background = new three.Color(token("--ground"));
    route.color.set(token("--text-secondary"));
    for (const place of places) place.material.color.set(token("--ink"));
    for (const point of observations.children) point.material.color.set(token("--brand-rose"));
  };
  const draw = viewport(canvas, camera, scene, update, contextLost);
  draw();
  return (positions) => {
    for (const point of observations.children) point.material.dispose();
    observations.clear();
    for (const { x_m, y_m } of positions) {
      observations.add(marker(observationGeometry, token("--brand-rose"), x_m, y_m, 0.02));
    }
    draw();
  };
}

export async function showCell(canvas, axes, contextLost, equipmentUrl, options = {}) {
  three ??= await import("./common/vendor/three.module.min.js");
  const scene = new three.Scene();
  if (equipmentUrl) {
    const model = await readEquipment(equipmentUrl, { studioMode: true, r2sPalette: options.r2sPalette ?? null });
    const sphere = new three.Box3().setFromObject(model).getBoundingSphere(new three.Sphere());
    scene.add(model);
    let syncPalette;
    const select = orbitView(canvas, scene, sphere.center, sphere.radius * 2.55, () => syncPalette?.(), contextLost, "iso", { studioMode: true });
    if (select.redraw?.renderer) {
      syncPalette = attachStudioEnvironment(
        three, select.redraw.renderer, scene,
        () => document.documentElement.getAttribute("data-theme") === "light",
        { compactCell: true },
      );
      select.redraw();
    }
    return select;
  }
  const center = new three.Vector3()
    .fromArray(axes[0]).add(new three.Vector3().fromArray(axes[1])).multiplyScalar(0.5);
  const baseGeometry = new three.CylinderGeometry(0.035, 0.035, 0.01, 24);
  baseGeometry.rotateX(Math.PI / 2);
  const bases = axes.map(([x, y, z]) => marker(baseGeometry, token("--brand-rose"), x, y, z));
  const gridMaterial = new three.LineBasicMaterial();
  for (let step = -5; step <= 5; step += 1) {
    const offset = step * 0.05;
    scene.add(path([[center.x + offset, -0.25], [center.x + offset, 0.25]], gridMaterial));
    scene.add(path([[center.x - 0.25, offset], [center.x + 0.25, offset]], gridMaterial));
  }
  scene.add(...bases);
  return orbitView(canvas, scene, center, 0.86, () => {
    gridMaterial.color.set(token("--text-secondary"));
    bases[0].material.color.set(token("--brand-rose"));
    bases[1].material.color.set(token("--ink"));
  }, contextLost);
}

function orbitView(canvas, scene, center, initialDistance, updatePalette, contextLost, start = "iso", options = {}) {
  const camera = new three.PerspectiveCamera(38, 1, initialDistance / 100, initialDistance * 20);
  camera.up.set(0, 0, 1);
  const views = start === "top"
    ? { iso: [-1.25, 0.82], top: [-Math.PI / 2, 1.565] }
    : { iso: [-0.72, 0.63], front: [0, 0.18], top: [0, 1.565] };
  let [azimuth, height] = views[start];
  let distance = initialDistance;
  let focus = null;
  let camTarget = center.clone();
  let exactCam = null;
  let tweenRaf;
  function update(aspect) {
    camera.aspect = aspect;
    if (exactCam) {
      camera.fov = exactCam.vfovDeg;
      camera.up.set(...exactCam.up);
      camera.position.set(...exactCam.eye);
      camera.lookAt(exactCam.target);
    } else {
      const fitAspect = start === "top" ? 1.75 : 1;
      const radius = distance * Math.max(1, fitAspect / aspect);
      if (camera.fov !== 38) camera.fov = 38;
      camera.up.set(0, 0, 1);
      camera.position.set(
        camTarget.x + radius * Math.cos(height) * Math.cos(azimuth),
        camTarget.y + radius * Math.cos(height) * Math.sin(azimuth),
        camTarget.z + radius * Math.sin(height),
      );
      camera.lookAt(camTarget);
    }
    if (!options.studioMode) scene.background = new three.Color(token("--ground"));
    updatePalette?.();
  }
  const draw = viewport(canvas, camera, scene, update, contextLost, options);
  function cancelTween() {
    if (tweenRaf) cancelAnimationFrame(tweenRaf);
    tweenRaf = undefined;
  }
  function setExactCamera({ eye, focus: targetPos, up = [0, 0, 1], vfovDeg = 42.4 }) {
    if (!Array.isArray(eye) || !Array.isArray(targetPos)) return;
    cancelTween();
    exactCam = {
      eye: [...eye],
      target: new three.Vector3(...targetPos),
      up: [...up],
      vfovDeg: Number.isFinite(vfovDeg) ? vfovDeg : 42.4,
    };
    draw();
  }
  function select(view, nextFocus = focus, instant = false) {
    cancelTween();
    exactCam = null;
    focus = nextFocus;
    const [endAz, endH] = views[view];
    const angleScale = start === "top" && view === "iso" ? 1.24 : 1;
    const endDist = initialDistance * angleScale * (focus?.scale ?? 1);
    const endTarget = (focus?.target ?? center).clone();
    if (!options.studioMode || instant || !canvas.clientWidth) {
      azimuth = endAz; height = endH; distance = endDist; camTarget.copy(endTarget);
      return draw();
    }
    const [sAz, sH, sDist, sTarget] = [azimuth, height, distance, camTarget.clone()];
    const t0 = performance.now();
    const step = (now) => {
      const u = Math.min(1, (now - t0) / 480);
      const ease = 1 - Math.pow(1 - u, 3);
      azimuth = sAz + (endAz - sAz) * ease;
      height = sH + (endH - sH) * ease;
      distance = sDist + (endDist - sDist) * ease;
      camTarget.lerpVectors(sTarget, endTarget, ease);
      draw();
      if (u < 1) tweenRaf = requestAnimationFrame(step);
      else tweenRaf = undefined;
    };
    tweenRaf = requestAnimationFrame(step);
  }
  function orbit(x, y) {
    cancelTween();
    exactCam = null;
    azimuth += x;
    height = Math.max(-1.45, Math.min(1.565, height + y));
    draw();
  }
  function zoom(factor) {
    cancelTween();
    exactCam = null;
    const scale = focus?.scale ?? 1;
    distance = Math.max(initialDistance * scale * 0.4, Math.min(initialDistance * scale * 2.6, distance * factor));
    draw();
  }
  let pointer;
  canvas.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0) return;
    cancelTween();
    pointer = [event.clientX, event.clientY];
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!pointer || !event.isPrimary) return;
    orbit((pointer[0] - event.clientX) * 0.008, (event.clientY - pointer[1]) * 0.008);
    pointer = [event.clientX, event.clientY];
  });
  canvas.addEventListener("lostpointercapture", () => { pointer = null; });
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom(event.deltaY > 0 ? 1.1 : 0.91);
  }, { passive: false });
  canvas.addEventListener("keydown", (event) => {
    const actions = {
      ArrowLeft: () => orbit(-0.12, 0), ArrowRight: () => orbit(0.12, 0),
      ArrowUp: () => orbit(0, 0.12), ArrowDown: () => orbit(0, -0.12),
      "+": () => zoom(0.85), "=": () => zoom(0.85), "-": () => zoom(1.18),
      Home: () => select(start),
    };
    if (!Object.hasOwn(actions, event.key)) return;
    event.preventDefault();
    actions[event.key]();
  });
  draw();
  select.redraw = draw;
  select.setExactCamera = setExactCamera;
  return select;
}

const CAD_TRIANGLES = 1_704_798;
const STL_HEADER_BYTES = 84;
const STL_TRIANGLE_BYTES = 50;
const CAD_TAPE_BOUNDS = [
  [-0.777, -0.593, -0.153, -0.125], [0.199, 0.382, -0.153, -0.125],
  [0.760, 0.788, -0.343, -0.161], [0.899, 0.927, -0.567, -0.385],
  [0.456, 0.484, -0.567, -0.385],
];

async function readCadGeometry(url, { studioMode = false } = {}) {
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

export async function showFieldPlane(canvas, photo, bounds, contextLost) {
  if (!canvas.getContext("webgl2")) throw new Error("WebGL 2 required");
  three ??= await import("./common/vendor/three.module.min.js");
  const [x0, y0, x1, y1] = bounds;
  const photoTexture = new three.Texture(photo);
  photoTexture.colorSpace = three.SRGBColorSpace;
  photoTexture.needsUpdate = true;
  const scene = new three.Scene();
  const width = x1 - x0;
  const height = y1 - y0;
  const plane = new three.Mesh(new three.PlaneGeometry(width, height),
    new three.MeshBasicMaterial({map: photoTexture, side: three.DoubleSide}));
  const center = new three.Vector3((x0 + x1) / 2, (y0 + y1) / 2, 0);
  plane.position.copy(center);
  scene.add(plane);
  return orbitView(canvas, scene, center, Math.max(width, height * 1.75) * 0.9, null, contextLost, "top");
}

async function readEquipment(url, options = {}) {
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

function cadLabels(scene, anchors, studioMode = false) {
  let lastSprite;
  for (const [name, position] of Object.entries(anchors)) {
    const canvas = document.createElement("canvas");
    canvas.width = name.length > 3 ? 256 : 160;
    canvas.height = 80;
    const context = canvas.getContext("2d");
    context.fillStyle = window.RosyPalette.cssColor(studioMode ? "--surface-raised" : "--ground");
    context.strokeStyle = window.RosyPalette.cssColor(studioMode ? "--brand-rose" : "--border-strong");
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

function lightEquipment(scene) {
  const light = new three.DirectionalLight(undefined, 2);
  light.position.set(-2, -3, 4);
  scene.add(new three.HemisphereLight(0xffffff, 0x65717d, 1.1), light);
}

function siteMarkings(scene, studioMode = false, r2sPalette = null) {
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

export async function showCad(canvas, url, contextLost, equipmentUrl, options = {}) {
  const studioMode = Boolean(options.studioMode);
  if (!window.DecompressionStream && !studioMode) {
    throw new Error("CAD requires gzip decompression");
  }
  three ??= await import("./common/vendor/three.module.min.js");
  const r2sPalette = options.r2sPalette ?? null;
  const dropRoadPinky = options.hideStaticRoadPinky
    ? (x, y, z) => (x > 0.45 && y < 0.0) || (x > -0.46 && x < -0.37 && y > 0.43 && y < 0.55 && z > 0.008)
    : null;
  let geometry;
  let cadFloorFallback;
  const equipmentPromise = equipmentUrl
    ? readEquipment(equipmentUrl, { dropTriangle: dropRoadPinky, extractRoadPinky: studioMode, studioMode, r2sPalette }).catch(() => null)
    : Promise.resolve(null);
  if (url) {
    try {
      geometry = await readCadGeometry(url, { studioMode });
    } catch (err) {
      if (!studioMode) throw err;
    }
  }
  if (!geometry) {
    cadFloorFallback = createProceduralFactoryFloor(three, r2sPalette);
    geometry = cadFloorFallback.geometry;
  }
  const equipment = await equipmentPromise;
  geometry.computeBoundingSphere();
  const { center, radius } = geometry.boundingSphere;
  const material = studioMode
    ? new three.MeshStandardMaterial({
      side: three.DoubleSide, flatShading: true, vertexColors: true, roughness: 0.84, metalness: 0.08,
    })
    : new three.MeshStandardMaterial({ side: three.DoubleSide, flatShading: true, vertexColors: true });
  const scene = new three.Scene();
  if (!studioMode) lightEquipment(scene);
  const cadMesh = cadFloorFallback ?? new three.Mesh(geometry, material);
  if (studioMode) {
    cadMesh.castShadow = false;
    cadMesh.receiveShadow = true;
  }
  scene.add(cadMesh);
  const anchors = { ...(equipment?.userData.anchors ?? {}) };
  if (options.hideStaticRoadPinky) {
    delete anchors.Pinky;
    if (studioMode) delete anchors.OMX;
  }
  if (equipment) scene.add(equipment);
  cadLabels(scene, anchors, studioMode);
  const markingsGroup = siteMarkings(scene, studioMode, r2sPalette);

  const r2sTextureCache = new Map();
  const r2sMat = new three.MeshBasicMaterial({
    transparent: true, opacity: 0.0, side: three.DoubleSide,
    depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
  });
  const r2sPlaneMesh = new three.Mesh(new three.PlaneGeometry(1, 1), r2sMat);
  r2sPlaneMesh.visible = false;
  r2sPlaneMesh.position.set(0, 0, 0.0021);
  scene.add(r2sPlaneMesh);
  let activeR2sUrl = null;

  function setR2sPhotoLayer({ url: photoUrl, plane, opacity = 0.55 } = {}) {
    const alpha = Math.max(0, Math.min(1, Number(opacity) || 0));
    if (!photoUrl || !Array.isArray(plane) || plane.length < 4 || alpha <= 0.001) {
      activeR2sUrl = null;
      r2sPlaneMesh.visible = false;
      markingsGroup.visible = true;
      requestAnimationFrame(select.redraw);
      return;
    }
    const [x0, y0, x1, y1] = plane;
    r2sPlaneMesh.scale.set(x1 - x0, y1 - y0, 1);
    r2sPlaneMesh.position.set((x0 + x1) * 0.5, (y0 + y1) * 0.5, 0.0021);
    r2sMat.opacity = alpha;
    markingsGroup.visible = alpha < 0.75;
    activeR2sUrl = photoUrl;

    const cached = r2sTextureCache.get(photoUrl);
    if (cached) {
      r2sMat.map = cached;
      r2sMat.needsUpdate = true;
      r2sPlaneMesh.visible = true;
      requestAnimationFrame(select.redraw);
      return;
    }
    const img = new Image();
    img.onload = () => {
      const tex = new three.Texture(img);
      tex.colorSpace = three.SRGBColorSpace;
      tex.anisotropy = 8;
      tex.needsUpdate = true;
      r2sTextureCache.set(photoUrl, tex);
      if (activeR2sUrl === photoUrl) {
        r2sMat.map = tex;
        r2sMat.needsUpdate = true;
        r2sPlaneMesh.visible = true;
        requestAnimationFrame(select.redraw);
      }
    };
    img.src = photoUrl;
  }
  const sim = new three.Group();
  sim.visible = false;
  const simMaterial = new three.MeshBasicMaterial({ color: 0x1b9e8e });
  const ring = new three.Mesh(new three.RingGeometry(0.02, 0.032, 24), simMaterial);
  ring.position.z = 0.003;
  const arrow = new three.Mesh(new three.ConeGeometry(0.011, 0.042, 12), simMaterial);
  arrow.rotation.z = -Math.PI / 2;
  arrow.position.set(0.052, 0, 0.006);
  sim.add(ring, arrow);
  cadLabels(sim, { SIM: new three.Vector3(0, 0, 0.06) });
  scene.add(sim);
  let syncStudioPalette;
  const select = orbitView(canvas, scene, center, radius * 1.72, () => syncStudioPalette?.(), contextLost, "top", { studioMode });
  if (studioMode && select.redraw?.renderer) {
    syncStudioPalette = attachStudioEnvironment(
      three, select.redraw.renderer, scene,
      () => document.documentElement.getAttribute("data-theme") === "light",
    );
    select.redraw();
  }
  const focus = {
    factory_all: { target: center.clone(), scale: 0.68 },
    factory_s3: { target: new three.Vector3(0.76, -0.05, 0.06), scale: 0.36 },
    factory_omx: { target: new three.Vector3(0.80, 0.28, 0.09), scale: 0.32 },
    factory_outbound: { target: new three.Vector3(0.65, 0.06, 0.07), scale: 0.34 },
  };
  for (const [region, name, scale] of [
    ["stations", "C2", 0.48], ["pinky", "Pinky", 0.33], ["omx", "OMX", 0.44],
  ]) {
    if (!anchors[name]) continue;
    const target = anchors[name].clone();
    target.z *= 0.5;
    focus[region] = { target, scale };
  }
  let design;
  let archiveIndex;
  async function setDesign(active, source) {
    if (active && !design) {
      const model = await readEquipment(source.url, {
        studioMode, hideStaticCargo: studioMode, hideStaticArms: studioMode, r2sPalette,
      });
      if (model.userData.layoutHash !== source.layoutHash) throw new Error("R08 layout differs from registration");
      const { yaw_rad: yaw, translation_m: translation } = source.transform;
      model.position.set(...translation);
      model.rotation.z = yaw;
      if (!cadFloorFallback) {
        const points = geometry.getAttribute("position").array;
        const kept = new Uint32Array(points.length / 3);
        let count = 0;
        for (let i = 0; i < points.length; i += 9) {
          const x0 = points[i], x1 = points[i + 3], x2 = points[i + 6];
          const y0 = points[i + 1], y1 = points[i + 4], y2 = points[i + 7];
          const x = (x0 + x1 + x2) / 3;
          const y = (y0 + y1 + y2) / 3;
          const z = (points[i + 2] + points[i + 5] + points[i + 8]) / 3;
          if (z > 0.01 && x >= 0.457 && x <= 1.08 && y >= 0.196 && y <= 0.966) continue;
          if (studioMode && z > 0.080 && x >= 0.56 && x <= 1.12 && y >= -0.22 && y <= 0.20) continue;
          if (studioMode && (Math.max(x0, x1, x2) > 1.23 || Math.min(x0, x1, x2) < -1.23 ||
              Math.max(y0, y1, y2) > 0.62 || Math.min(y0, y1, y2) < -0.62)) continue;
          for (let v = 0; v < 3; v += 1) kept[count++] = i / 3 + v;
        }
        archiveIndex = new three.BufferAttribute(kept.subarray(0, count), 1);
      }
      scene.add(model);
      design = model;
    }
    if (design) design.visible = active;
    if (archiveIndex) geometry.setIndex(active ? archiveIndex : null);
    requestAnimationFrame(select.redraw);
  }
  function setSim(sample) {
    sim.visible = !!sample;
    if (sample) {
      sim.position.set(sample.pose_m[0], sample.pose_m[1], Math.max(sample.pose_m[2], 0.002));
      sim.rotation.z = sample.yaw_rad;
    }
    requestAnimationFrame(select.redraw);
  }
  function getFactoryContext() {
    return {
      three, scene, redraw: select.redraw, select, focus,
      setExactCamera: select.setExactCamera,
      setR2sPhotoLayer,
      extractedPinky: equipment?.userData.extractedPinky ?? null,
      addLabel(parent, name, pos) { return cadLabels(parent, { [name]: pos }, studioMode); },
    };
  }
  return { select, focus, setDesign, setSim, setR2sPhotoLayer, setExactCamera: select.setExactCamera, getFactoryContext };
}
