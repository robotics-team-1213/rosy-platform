import {
  configureStudioRenderer, attachStudioEnvironment, createProceduralFactoryFloor,
} from "./studio-look.js";
import {
  readCadGeometry, readEquipment, cadLabels, lightEquipment, siteMarkings,
} from "./scene-geometry.js";

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
    for (const point of observations.children) point.material.color.set(token("--series-primary"));
  };
  const draw = viewport(canvas, camera, scene, update, contextLost);
  draw();
  return (positions) => {
    for (const point of observations.children) point.material.dispose();
    observations.clear();
    for (const { x_m, y_m } of positions) {
      observations.add(marker(observationGeometry, token("--series-primary"), x_m, y_m, 0.02));
    }
    draw();
  };
}

export async function showCell(canvas, axes, contextLost, equipmentUrl, options = {}) {
  three ??= await import("./common/vendor/three.module.min.js");
  const scene = new three.Scene();
  if (equipmentUrl) {
    const model = await readEquipment(three, equipmentUrl, { studioMode: true, r2sPalette: options.r2sPalette ?? null });
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
  const bases = axes.map(([x, y, z]) => marker(baseGeometry, token("--series-primary"), x, y, z));
  const gridMaterial = new three.LineBasicMaterial();
  for (let step = -5; step <= 5; step += 1) {
    const offset = step * 0.05;
    scene.add(path([[center.x + offset, -0.25], [center.x + offset, 0.25]], gridMaterial));
    scene.add(path([[center.x - 0.25, offset], [center.x + 0.25, offset]], gridMaterial));
  }
  scene.add(...bases);
  return orbitView(canvas, scene, center, 0.86, () => {
    gridMaterial.color.set(token("--text-secondary"));
    bases[0].material.color.set(token("--series-primary"));
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
    new three.MeshBasicMaterial({ map: photoTexture, side: three.DoubleSide }));
  const center = new three.Vector3((x0 + x1) / 2, (y0 + y1) / 2, 0);
  plane.position.copy(center);
  scene.add(plane);
  return orbitView(canvas, scene, center, Math.max(width, height * 1.75) * 0.9, null, contextLost, "top");
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
    ? readEquipment(three, equipmentUrl, { dropTriangle: dropRoadPinky, extractRoadPinky: studioMode, studioMode, r2sPalette }).catch(() => null)
    : Promise.resolve(null);
  if (url) {
    try {
      geometry = await readCadGeometry(three, url, { studioMode });
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
  if (!studioMode) lightEquipment(three, scene);
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
  cadLabels(three, scene, anchors, studioMode);
  const markingsGroup = siteMarkings(three, scene, studioMode, r2sPalette);

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
  cadLabels(three, sim, { SIM: new three.Vector3(0, 0, 0.06) });
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
      const model = await readEquipment(three, source.url, {
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
      addLabel(parent, name, pos) { return cadLabels(three, parent, { [name]: pos }, studioMode); },
    };
  }
  return { select, focus, setDesign, setSim, setR2sPhotoLayer, setExactCamera: select.setExactCamera, getFactoryContext };
}
