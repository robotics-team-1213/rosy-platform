// Lazy Three.js 3D view of the zone model the 2D map draws (same places, real sizes, area heights). No idle
// rAF loop: it draws on render, orbit, zoom, resize and theme change only.
import { cssColor, readColour } from "/common/ui.js";
import { loadThree } from "/console/assets/robot-3d-assets.js";

// Azimuth is measured from +X of the scene, which is the map's +x; +y of the map lies away from a camera at
// az = PI/2. So "front" looks north like the 2D map and "top" has the same orientation as the 2D map.
const MAP_FRONT_AZ = Math.PI / 2;
const PRESETS = Object.freeze({
  iso: { az: MAP_FRONT_AZ + 0.62, el: 0.62 },
  top: { az: MAP_FRONT_AZ, el: Math.PI / 2 - 0.02 },
  front: { az: MAP_FRONT_AZ, el: 0.28 },
  side: { az: 0, el: 0.28 },
});
const LANE_THICKNESS_M = 0.004;
const VEHICLE_HEIGHT_M = 0.06;
const LABEL_HEIGHT_M = 0.07;

function makeThreeColor(THREE, token, fallback) {
  const [r, g, b, a] = readColour(token);
  const rgb = a === 0 ? fallback : [r / 255, g / 255, b / 255];
  return new THREE.Color(rgb[0], rgb[1], rgb[2]);
}

/** Counter-clockwise in the ground plane, so an extruded top face looks up. */
function counterClockwise(points) {
  const area = points.reduce((sum, [x, y], index) => {
    const [nx, ny] = points[(index + 1) % points.length];
    return sum + (x * ny - nx * y) / 2;
  }, 0);
  return area < 0 ? [...points].reverse() : points;
}

export function createZoneBlueprint3d(host, { onSelect } = {}) {
  const canvas = document.createElement("canvas");
  canvas.className = "zb-canvas";
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "구역 3D 도면 · 드래그 회전 · 휠 확대");

  const emptyNote = document.createElement("p");
  emptyNote.className = "hint zb-empty";
  emptyNote.hidden = true;
  emptyNote.textContent = "표시할 구역 정보가 없습니다.";

  const fallback = document.createElement("p");
  fallback.className = "hint zb-fallback";
  fallback.hidden = true;
  fallback.textContent = "이 브라우저에서는 WebGL 3D 도면을 초기화할 수 없습니다. 2D 평면도를 이용하세요.";

  let THREE = null;
  let renderer = null;
  let scene = null;
  let camera = null;
  let rootGroup = null;
  let resizeObs = null;
  let disposed = false;
  let rafId = 0;
  let dragging = false;
  let moved = false;
  let lastPtr = { x: 0, y: 0 };
  let orbit = { az: PRESETS.iso.az, el: PRESETS.iso.el, dist: 3.2, target: [0, 0, 0] };
  let currentModel = null;
  let currentSelectedId = null;
  let currentFilter = "all";
  const pickables = [];

  function drawNow() {
    rafId = 0;
    if (disposed || !renderer || !scene || !camera) return;
    const w = Math.max(240, host.clientWidth || 640);
    const h = Math.max(200, host.clientHeight || 420);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const [tx, ty, tz] = orbit.target;
    const horiz = Math.cos(orbit.el) * orbit.dist;
    camera.position.set(tx + horiz * Math.cos(orbit.az), ty + Math.sin(orbit.el) * orbit.dist, tz + horiz * Math.sin(orbit.az));
    camera.lookAt(tx, ty, tz);
    renderer.render(scene, camera);
  }

  function scheduleDraw() {
    if (disposed || !renderer || rafId) return;
    rafId = requestAnimationFrame(drawNow);
  }

  function clearSceneGroup() {
    pickables.length = 0;
    if (!rootGroup) return;
    for (const child of [...rootGroup.children]) {
      rootGroup.remove(child);
      child.geometry?.dispose?.();
      if (Array.isArray(child.material)) child.material.forEach((m) => m?.dispose?.());
      else child.material?.dispose?.();
      child.material?.map?.dispose?.();
    }
  }

  function addMesh(geometry, material, pos, zoneId = null) {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(pos[0], pos[1], pos[2]);
    if (zoneId) {
      mesh.userData.zoneId = zoneId;
      pickables.push(mesh);
    }
    rootGroup.add(mesh);
    return mesh;
  }

  function addBox(w, h, d, pos, material, zoneId = null) {
    return addMesh(new THREE.BoxGeometry(w, h, d), material, pos, zoneId);
  }

  /** A map polygon raised to ``height``. ``ground`` holds scene (x, z) points like the lanes and labels;
   * the extruded shape is laid flat by a -90 degree turn about x, which maps shape y to -z, so z is negated
   * here to keep every drawn thing in the same places. */
  function addSlab(ground, height, material, zoneId = null) {
    const shape = new THREE.Shape(counterClockwise(ground).map(([x, z]) => new THREE.Vector2(x, -z)));
    const mesh = addMesh(new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false }), material, [0, 0, 0], zoneId);
    mesh.rotation.x = -Math.PI / 2;
    return mesh;
  }

  /** A name on a small billboard. Colour and type come from the palette like every canvas of the console
   * (D-359 §4): the map chips' pairing of --scrim behind --text-primary, the label role at double size. */
  function addLabel(text, pos) {
    const labelFont = window.RosyPalette.canvasFont("label", "mono", 2);
    const height = Math.round(window.RosyPalette.canvasTextSize("label") * 3);
    const measure = document.createElement("canvas").getContext("2d");
    if (!measure) return;
    measure.font = labelFont;
    const pad = Math.round(height / 5);
    const width = Math.ceil(measure.measureText(text).width) + pad * 2;
    const raster = document.createElement("canvas");
    raster.width = width;
    raster.height = height;
    const ctx = raster.getContext("2d");
    ctx.fillStyle = cssColor("--scrim");
    ctx.fillRect(0, 0, width, height);
    ctx.font = labelFont;
    ctx.fillStyle = cssColor("--text-primary");
    ctx.textBaseline = "middle";
    ctx.fillText(text, pad, height / 2);
    const texture = new THREE.CanvasTexture(raster);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, depthTest: false }));
    sprite.scale.set((width / height) * LABEL_HEIGHT_M, LABEL_HEIGHT_M, 1);
    sprite.position.set(pos[0], pos[1], pos[2]);
    rootGroup.add(sprite);
  }

  function rebuildGeometry() {
    if (!THREE || !scene || !rootGroup || !currentModel) return;
    clearSceneGroup();
    const cCanvas = makeThreeColor(THREE, "--surface-recessed", [0.06, 0.07, 0.08]);
    const cRaised = makeThreeColor(THREE, "--surface-raised", [0.16, 0.17, 0.19]);
    const cFlat = makeThreeColor(THREE, "--surface-flat", [0.13, 0.14, 0.16]);
    const cGrid = makeThreeColor(THREE, "--border-strong", [0.35, 0.37, 0.4]);
    const cPrimary = makeThreeColor(THREE, "--series-primary", [0.35, 0.65, 1.0]);
    const cGoal = makeThreeColor(THREE, "--series-goal", [0.3, 0.85, 0.6]);
    const cSelected = makeThreeColor(THREE, "--selection", [0.16, 0.44, 0.74]);
    const cGood = makeThreeColor(THREE, "--status-good", [0.24, 0.84, 0.55]);
    const cCrit = makeThreeColor(THREE, "--status-crit", [0.95, 0.3, 0.3]);
    const cWarn = makeThreeColor(THREE, "--status-warn", [1.0, 0.77, 0.24]);
    scene.background = cCanvas;
    const mat = (color, opacity = 1) => new THREE.MeshStandardMaterial({
      color, roughness: 0.65, metalness: 0.1, transparent: opacity < 1, opacity,
    });

    const b = currentModel.bounds;
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    const spanX = b.maxX - b.minX + 0.2;
    const spanY = b.maxY - b.minY + 0.2;
    // View metres -> scene metres with the map centre at the origin and +y up.
    const toScene = (x, y) => {
      const [vx, vy] = currentModel.project(x, y);
      return [vx - cx, -(vy - cy)];
    };
    // Red is an overlap and amber a gap under 2 cm; a stored coordinate that disagrees with its place is
    // written in the map check list and gets no outline here.
    const flagged = { overlap: new Set(), near: new Set() };
    for (const conflict of currentModel.conflicts) {
      for (const id of conflict.ids) flagged[conflict.kind]?.add(id);
    }
    const categoryOf = new Map(currentModel.items.map((item) => [item.id, item.category]));
    const isSelected = (footprint) => footprint.itemIds.includes(currentSelectedId);

    addBox(spanX, 0.01, spanY, [0, -0.005, 0], mat(cFlat));
    const gridSize = Math.ceil(Math.max(spanX, spanY) * 1.2);
    const grid = new THREE.GridHelper(gridSize, Math.max(1, Math.round(gridSize / 0.5)), cGrid, cGrid);
    grid.material.transparent = true;
    grid.material.opacity = 0.35;
    rootGroup.add(grid);

    for (const lane of currentModel.lanes) {
      const material = mat(cRaised);
      const points = lane.points.map(([x, y]) => toScene(x, y));
      const radius = lane.widthM / 2;
      for (let index = 1; index < points.length; index += 1) {
        const [ax, az] = points[index - 1];
        const [bx, bz] = points[index];
        const length = Math.hypot(bx - ax, bz - az);
        if (length === 0) continue;
        const box = addBox(length, LANE_THICKNESS_M, lane.widthM, [(ax + bx) / 2, LANE_THICKNESS_M / 2, (az + bz) / 2], material);
        box.rotation.y = Math.atan2(bz - az, bx - ax);
      }
      for (const [px, pz] of points.slice(1, -1)) {
        addMesh(new THREE.CylinderGeometry(radius, radius, LANE_THICKNESS_M, 16), material, [px, LANE_THICKNESS_M / 2, pz]);
      }
      if (lane.direction !== "two_way") {
        let best = null;
        for (let index = 1; index < points.length; index += 1) {
          const [ax, az] = points[index - 1];
          const [bx, bz] = points[index];
          const length = Math.hypot(bx - ax, bz - az);
          if (!best || length > best.length) best = { a: [ax, az], b: [bx, bz], length };
        }
        if (best && best.length > 0.05) {
          const dir = new THREE.Vector3((best.b[0] - best.a[0]) / best.length, 0, (best.b[1] - best.a[1]) / best.length);
          const cone = addMesh(new THREE.ConeGeometry(0.022, 0.055, 4), mat(cPrimary, 0.9), [
            (best.a[0] + best.b[0]) / 2, LANE_THICKNESS_M + 0.012, (best.a[1] + best.b[1]) / 2,
          ]);
          cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
        }
      }
    }

    for (const area of currentModel.areas) {
      const id = `area:${area.id}`;
      const zone = area.zoneId ? currentModel.footprints.find((footprint) => footprint.id === id) : null;
      const height = area.heightM ?? 0.02;
      const polygon = area.polygon.map(([x, y]) => toScene(x, y));
      const slab = addSlab(polygon, height, mat(
        flagged.overlap.has(id) ? cCrit : zone && isSelected(zone) ? cSelected
          : area.kind === "belt" ? cFlat : area.kind === "cell_zone" ? cGood : cRaised,
        area.kind === "cell_zone" ? 0.5 : 1), zone ? area.zoneId : null);
      if (flagged.overlap.has(id) || flagged.near.has(id)) {
        // An overlap is a red fill; a gap under 2 cm keeps the area's own colour and gets a warning outline.
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(slab.geometry),
          new THREE.LineBasicMaterial({ color: flagged.overlap.has(id) ? cCrit : cWarn }));
        edges.rotation.copy(slab.rotation);
        rootGroup.add(edges);
      }
      const centre = polygon.reduce(([sx, sz], [x, z]) => [sx + x / polygon.length, sz + z / polygon.length], [0, 0]);
      addLabel(area.shortName, [centre[0], height + 0.06, centre[1]]);
    }

    for (const footprint of currentModel.footprints) {
      if (footprint.kind === "cell_zone") continue;
      const inFilter = currentFilter === "all" || footprint.itemIds.some((id) => categoryOf.get(id) === currentFilter);
      const material = mat(isSelected(footprint) ? cSelected : footprint.kind === "charge" ? cGoal : cPrimary,
        isSelected(footprint) || inFilter ? 1 : 0.3);
      const polygon = footprint.polygon.map(([x, y]) => toScene(x, y));
      addSlab(polygon, VEHICLE_HEIGHT_M, material, footprint.itemIds[0]);
      if (flagged.overlap.has(footprint.id) || flagged.near.has(footprint.id)) {
        const box = new THREE.Box3().setFromPoints(polygon.map(([x, z]) => new THREE.Vector3(x, 0, z)));
        const helper = new THREE.Box3Helper(box, flagged.overlap.has(footprint.id) ? cCrit : cWarn);
        rootGroup.add(helper);
      }
      const centre = polygon.reduce(([sx, sz], [x, z]) => [sx + x / polygon.length, sz + z / polygon.length], [0, 0]);
      addLabel(footprint.placeId, [centre[0], VEHICLE_HEIGHT_M + 0.06, centre[1]]);
    }

    orbit.target = [0, 0.05, 0];
    scheduleDraw();
  }

  async function ensureInit() {
    if (renderer || disposed) return Boolean(renderer);
    try {
      THREE = await loadThree();
      if (disposed) return false;
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(44, 1.5, 0.05, 40);
      rootGroup = new THREE.Group();
      scene.add(rootGroup);
      // Neutral white light in both themes: it is illumination, not paint. Reading it from --text-primary
      // made every light near-black in the light theme and the whole model went dark.
      const ambient = new THREE.AmbientLight(0xffffff, 0.85);
      const dir = new THREE.DirectionalLight(0xffffff, 0.7);
      dir.position.set(2.5, 4.0, 2.0);
      scene.add(ambient, dir);
      resizeObs = new ResizeObserver(() => scheduleDraw());
      resizeObs.observe(host);
      fallback.hidden = true;
      canvas.hidden = false;
      return true;
    } catch {
      fallback.hidden = false;
      canvas.hidden = true;
      return false;
    }
  }

  canvas.addEventListener("pointerdown", (ev) => {
    dragging = true;
    moved = false;
    lastPtr = { x: ev.clientX, y: ev.clientY };
    canvas.setPointerCapture?.(ev.pointerId);
  });
  canvas.addEventListener("pointermove", (ev) => {
    if (!dragging) return;
    const dx = ev.clientX - lastPtr.x;
    const dy = ev.clientY - lastPtr.y;
    if (Math.hypot(dx, dy) > 3) moved = true;
    lastPtr = { x: ev.clientX, y: ev.clientY };
    orbit.az -= dx * 0.008;
    orbit.el = Math.max(0.12, Math.min(Math.PI / 2 - 0.02, orbit.el + dy * 0.008));
    scheduleDraw();
  });
  canvas.addEventListener("pointerup", (ev) => {
    if (!dragging) return;
    dragging = false;
    if (!moved && THREE && camera && pickables.length) {
      const rect = canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const ray = new THREE.Raycaster();
      ray.setFromCamera(ndc, camera);
      const zoneId = ray.intersectObjects(pickables, false)[0]?.object?.userData?.zoneId;
      if (zoneId) onSelect?.(zoneId);
    }
  });
  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    orbit.dist = Math.max(0.8, Math.min(8.0, orbit.dist + Math.sign(ev.deltaY) * 0.25));
    scheduleDraw();
  }, { passive: false });
  canvas.addEventListener("keydown", (ev) => {
    const step = 0.14;
    if (ev.key === "ArrowLeft") orbit.az -= step;
    else if (ev.key === "ArrowRight") orbit.az += step;
    else if (ev.key === "ArrowUp") orbit.el = Math.min(Math.PI / 2 - 0.02, orbit.el + step);
    else if (ev.key === "ArrowDown") orbit.el = Math.max(0.12, orbit.el - step);
    else if (ev.key === "+" || ev.key === "=") orbit.dist = Math.max(0.8, orbit.dist - 0.25);
    else if (ev.key === "-") orbit.dist = Math.min(8.0, orbit.dist + 0.25);
    else if (ev.key === "Home") { orbit.az = PRESETS.iso.az; orbit.el = PRESETS.iso.el; orbit.dist = orbit.homeDist; }
    else return;
    ev.preventDefault();
    scheduleDraw();
  });

  return {
    async render(model, selectedId, filterCategory = "all") {
      const first = currentModel !== model;
      currentModel = model;
      currentSelectedId = selectedId;
      currentFilter = filterCategory;
      if (!canvas.isConnected || !emptyNote.isConnected) host.replaceChildren(canvas, emptyNote, fallback);
      const empty = !model || (!model.lanes.length && !model.areas.length && !model.footprints.length);
      if (empty) {
        clearSceneGroup();
        canvas.hidden = true;
        fallback.hidden = true;
        emptyNote.hidden = false;
        return;
      }
      emptyNote.hidden = true;
      if (first) {
        // Start far enough to hold the whole site; the operator orbits and zooms from there.
        const span = Math.max(model.bounds.maxX - model.bounds.minX, model.bounds.maxY - model.bounds.minY);
        orbit.homeDist = Math.max(1.4, Math.min(6, span * 1.35));
        orbit.dist = orbit.homeDist;
      }
      if (await ensureInit()) {
        canvas.hidden = false;
        rebuildGeometry();
      }
    },
    setPreset(name) {
      const p = PRESETS[name];
      if (!p) return;
      orbit.az = p.az;
      orbit.el = p.el;
      scheduleDraw();
    },
    redrawTheme() {
      if (renderer && currentModel) rebuildGeometry();
    },
    dispose() {
      disposed = true;
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0;
      resizeObs?.disconnect?.();
      resizeObs = null;
      clearSceneGroup();
      renderer?.dispose?.();
      renderer = null;
      scene = null;
      camera = null;
      rootGroup = null;
    },
  };
}
