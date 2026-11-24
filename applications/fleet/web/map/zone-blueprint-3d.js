// Lazy Three.js on-demand 3D blueprint renderer using CSS tokens only (no idle rAF loop).
import { readColour } from "/common/ui.js";
import { loadThree } from "/console/assets/robot-3d-assets.js";

const PRESETS = Object.freeze({
  iso: { az: 0.78, el: 0.62 },
  top: { az: 0.0, el: Math.PI / 2 - 0.02 },
  front: { az: -Math.PI / 2, el: 0.28 },
  side: { az: 0.0, el: 0.28 },
});

function makeThreeColor(THREE, token, fallback) {
  const [r, g, b, a] = readColour(token);
  const rgb = a === 0 ? fallback : [r / 255, g / 255, b / 255];
  return new THREE.Color(rgb[0], rgb[1], rgb[2]);
}

export function createZoneBlueprint3d(host, { onSelect } = {}) {
  const canvas = document.createElement("canvas");
  canvas.className = "zb-canvas";
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "구역 3D 도면 · 드래그 회전 · 휠 확대");

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
    }
  }

  function addBox(w, h, d, pos, color, zoneId = null) {
    const geom = new THREE.BoxGeometry(w, h, d);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.65, metalness: 0.1 });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.set(pos[0], pos[1], pos[2]);
    if (zoneId) {
      mesh.userData.zoneId = zoneId;
      pickables.push(mesh);
    }
    rootGroup.add(mesh);
    return mesh;
  }

  function rebuildGeometry() {
    if (!THREE || !scene || !rootGroup || !currentModel) return;
    clearSceneGroup();
    const cCanvas = makeThreeColor(THREE, "--surface-recessed", [0.06, 0.07, 0.08]);
    const cRaised = makeThreeColor(THREE, "--surface-raised", [0.16, 0.17, 0.19]);
    const cFlat = makeThreeColor(THREE, "--surface-flat", [0.13, 0.14, 0.16]);
    const cGrid = makeThreeColor(THREE, "--border-strong", [0.35, 0.37, 0.4]);
    const cPrimary = makeThreeColor(THREE, "--series-primary", [0.35, 0.65, 1.0]);
    const cSelected = makeThreeColor(THREE, "--selection", [0.16, 0.44, 0.74]);
    const cGood = makeThreeColor(THREE, "--status-good", [0.24, 0.84, 0.55]);
    const cWarn = makeThreeColor(THREE, "--status-warn", [1.0, 0.77, 0.24]);
    scene.background = cCanvas;

    const armZone = currentModel.armZones.find((z) => z.id === currentSelectedId)
      || (currentFilter === "arm_zone" ? currentModel.armZones[0] : null);

    if (armZone) {
      const cols = Math.max(1, armZone.grid?.columns || 3);
      const rows = Math.max(1, armZone.grid?.rows || 1);
      const cellSize = 0.28;
      const tierH = Math.max(0.05, (currentModel.tierHeightMm || 32.4) / 400);
      addBox(cols * cellSize + 0.12, 0.02, rows * cellSize + 0.12, [0, -0.01, 0], cFlat);
      const grid = new THREE.GridHelper(Math.max(cols, rows) * cellSize + 0.4, 8, cGrid, cGrid);
      grid.position.y = 0.001;
      rootGroup.add(grid);
      for (const slot of armZone.slots || []) {
        const [c1, c2] = slot.columns?.length >= 2 ? slot.columns : [1, cols];
        const span = Math.max(1, c2 - c1 + 1);
        const cx = ((c1 - 1 + span / 2) - cols / 2) * cellSize;
        const cz = ((slot.row - 0.5) - rows / 2) * cellSize;
        addBox(span * cellSize - 0.03, 0.02, cellSize - 0.03, [cx, 0.01, cz], cRaised, armZone.id);
        (slot.tiers || []).forEach((t, idx) => {
          const color = t.tier === 1 ? cPrimary : t.tier === 2 ? cGood : cWarn;
          addBox(span * cellSize - 0.06, tierH - 0.01, cellSize - 0.06,
            [cx, 0.025 + idx * tierH + tierH / 2, cz], color, armZone.id);
        });
      }
      if (armZone.holdBoundary?.columns?.length === 2) {
        const bx = (armZone.holdBoundary.columns[0] - cols / 2) * cellSize;
        addBox(0.015, tierH * 3.2, rows * cellSize + 0.08, [bx, tierH * 1.6, 0], cSelected);
      }
      orbit.target = [0, 0.12, 0];
      scheduleDraw();
      return;
    }

    const b = currentModel.worldBounds;
    const cxWorld = (b.minX + b.maxX) / 2;
    const cyWorld = (b.minY + b.maxY) / 2;
    const span = Math.max(1.5, b.maxX - b.minX, b.maxY - b.minY);
    const grid = new THREE.GridHelper(Math.ceil(span * 1.4), 12, cGrid, cGrid);
    rootGroup.add(grid);
    addBox(span * 1.2, 0.01, span * 1.2, [0, -0.008, 0], cFlat);

    const showCat = (cat) => currentFilter === "all" || currentFilter === cat;
    if (showCat("stop")) {
      for (const s of currentModel.stops) {
        if (!Number.isFinite(s.x) || !Number.isFinite(s.y)) continue;
        const selected = s.id === currentSelectedId;
        addBox(0.11, selected ? 0.14 : 0.09, 0.11, [s.x - cxWorld, 0.05, -(s.y - cyWorld)],
          selected ? cSelected : cPrimary, s.id);
      }
    }
    if (showCat("staging")) {
      for (const bay of currentModel.stagingBays) {
        if (!Number.isFinite(bay.x) || !Number.isFinite(bay.y)) continue;
        const selected = bay.id === currentSelectedId;
        addBox(0.12, 0.05, 0.09, [bay.x - cxWorld, 0.025, -(bay.y - cyWorld)],
          selected ? cSelected : cGood, bay.id);
      }
    }
    if (showCat("export")) {
      for (const st of currentModel.exportStations) {
        if (!Number.isFinite(st.x) || !Number.isFinite(st.y)) continue;
        const selected = st.id === currentSelectedId;
        const h = 0.06 + (st.tier || 1) * 0.04;
        addBox(0.13, h, 0.13, [st.x - cxWorld, h / 2, -(st.y - cyWorld)],
          selected ? cSelected : cWarn, st.id);
      }
    }
    orbit.target = [0, 0.04, 0];
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
      const ambient = new THREE.AmbientLight(makeThreeColor(THREE, "--text-primary", [0.9, 0.9, 0.9]), 0.85);
      const dir = new THREE.DirectionalLight(makeThreeColor(THREE, "--text-primary", [0.9, 0.9, 0.9]), 0.7);
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
      const hits = ray.intersectObjects(pickables, false);
      const zoneId = hits[0]?.object?.userData?.zoneId;
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
    else if (ev.key === "Home") { orbit.az = PRESETS.iso.az; orbit.el = PRESETS.iso.el; orbit.dist = 3.2; }
    else return;
    ev.preventDefault();
    scheduleDraw();
  });

  return {
    async render(model, selectedId, filterCategory = "all") {
      currentModel = model;
      currentSelectedId = selectedId;
      currentFilter = filterCategory;
      if (!canvas.isConnected) host.replaceChildren(canvas, fallback);
      if (await ensureInit()) rebuildGeometry();
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
