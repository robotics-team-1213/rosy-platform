// Studio PBR lighting, procedural HDRI environment, floor grid, cyclorama backdrop, plinth, and container materials.

const containerMatCache = new Map();
const backdropCache = new Map();

function createStudioBackdrop(three, light) {
  const key = light ? "light" : "dark";
  if (backdropCache.has(key)) return backdropCache.get(key);
  const w = 4, h = 128;
  const data = new Uint8Array(w * h * 4);
  const top = new three.Color(light ? 0xf0f4f8 : 0x1c2533);
  const mid = new three.Color(light ? 0xe1e8f0 : 0x131923);
  const bot = new three.Color(light ? 0xd0dae5 : 0x0c1017);
  const tmp = new three.Color();
  for (let y = 0; y < h; y += 1) {
    const v = y / (h - 1);
    if (v < 0.5) tmp.lerpColors(bot, mid, v * 2);
    else tmp.lerpColors(mid, top, (v - 0.5) * 2);
    const r = Math.round(tmp.r * 255);
    const g = Math.round(tmp.g * 255);
    const b = Math.round(tmp.b * 255);
    for (let x = 0; x < w; x += 1) {
      const idx = (y * w + x) * 4;
      data[idx] = r;
      data[idx + 1] = g;
      data[idx + 2] = b;
      data[idx + 3] = 255;
    }
  }
  const tex = new three.DataTexture(data, w, h, three.RGBAFormat);
  tex.colorSpace = three.SRGBColorSpace;
  tex.needsUpdate = true;
  backdropCache.set(key, tex);
  return tex;
}

export function configureStudioRenderer(three, renderer) {
  let isSoftware = false;
  try {
    const gl = renderer.getContext();
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    const name = dbg ? String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)) : "";
    isSoftware = /swiftshader|llvmpipe|software/i.test(name);
  } catch {
    isSoftware = false;
  }
  renderer.shadowMap.enabled = !isSoftware;
  renderer.shadowMap.type = three.PCFShadowMap;
  renderer.toneMapping = three.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.22;
  renderer.outputColorSpace = three.SRGBColorSpace;
}

export function attachStudioEnvironment(three, renderer, scene, resolveLight, options = {}) {
  const compactCell = Boolean(options.compactCell);
  // Build a tiny procedural light-studio room for realistic PBR reflections via PMREM.
  try {
    const room = new three.Scene();
    room.background = new three.Color(0x1e2632);
    const softboxTop = new three.Mesh(
      new three.PlaneGeometry(6, 4),
      new three.MeshBasicMaterial({ color: 0xfff8ed, side: three.DoubleSide }),
    );
    softboxTop.position.set(0, 0, 3.2);
    const rimCool = new three.Mesh(
      new three.PlaneGeometry(4, 3),
      new three.MeshBasicMaterial({ color: 0x8cc8ff, side: three.DoubleSide }),
    );
    rimCool.position.set(3.4, 2.5, 1.4);
    rimCool.lookAt(0, 0, 0);
    const fillWarm = new three.Mesh(
      new three.PlaneGeometry(4, 3),
      new three.MeshBasicMaterial({ color: 0xffd7b0, side: three.DoubleSide }),
    );
    fillWarm.position.set(-3.4, -2.5, 1.2);
    fillWarm.lookAt(0, 0, 0);
    room.add(softboxTop, rimCool, fillWarm);

    const pmrem = new three.PMREMGenerator(renderer);
    const envTarget = pmrem.fromScene(room, 0.04);
    scene.environment = envTarget.texture;
    pmrem.dispose();
  } catch {
    // Graceful fallback if software WebGL refuses PMREM target allocation.
  }

  // 3-point lab lights matched to real overhead fluorescent photography with balanced shadows.
  const key = new three.DirectionalLight(0xfffbf2, 1.95);
  key.position.set(compactCell ? -0.9 : -1.35, compactCell ? -1.1 : -1.75, compactCell ? 1.8 : 2.7);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  const extent = compactCell ? 0.85 : 1.65;
  key.shadow.camera.left = -extent;
  key.shadow.camera.right = extent;
  key.shadow.camera.top = extent;
  key.shadow.camera.bottom = -extent;
  key.shadow.camera.near = 0.25;
  key.shadow.camera.far = 7.5;
  key.shadow.bias = -0.0003;
  key.shadow.normalBias = 0.006;

  const rim = new three.DirectionalLight(0xe0efff, 0.52);
  rim.position.set(2.15, 2.05, 1.65);

  const fill = new three.HemisphereLight(0xf2f6fa, 0x464d56, 1.05);
  scene.add(key, rim, fill);

  // Studio floor + subtle architectural grid (+ perimeter foam-board walls & right camera gantry matching real testbed).
  const floorMat = new three.MeshStandardMaterial({
    color: 0x1a2029, roughness: 0.9, metalness: 0.04,
  });
  const floorZ = compactCell ? -0.002 : -0.048;
  const floorCenterX = compactCell ? 0.04 : 0.15;
  const floor = new three.Mesh(new three.PlaneGeometry(compactCell ? 6 : 16, compactCell ? 6 : 16), floorMat);
  floor.position.set(floorCenterX, 0.0, floorZ);
  floor.receiveShadow = true;

  const grid = new three.GridHelper(compactCell ? 3.2 : 8.0, compactCell ? 32 : 40, 0x364455, 0x222b36);
  grid.rotation.x = Math.PI / 2;
  grid.position.set(floorCenterX, 0.0, floorZ + 0.0012);
  const gridMats = Array.isArray(grid.material) ? grid.material : [grid.material];
  for (const m of gridMats) { m.transparent = true; m.opacity = 0.34; }

  scene.add(floor, grid);

  let trimBezel;
  let plinthBase;
  if (!compactCell) {
    trimBezel = new three.Mesh(
      new three.BoxGeometry(2.47, 1.25, 0.008),
      new three.MeshStandardMaterial({ color: 0x626e7d, roughness: 0.36, metalness: 0.62 }),
    );
    trimBezel.position.set(0.0, 0.0, -0.0075);
    trimBezel.receiveShadow = true;

    plinthBase = new three.Mesh(
      new three.BoxGeometry(2.54, 1.32, 0.036),
      new three.MeshStandardMaterial({ color: 0x202731, roughness: 0.55, metalness: 0.35 }),
    );
    plinthBase.position.set(0.0, 0.0, -0.029);
    plinthBase.castShadow = plinthBase.receiveShadow = true;
    scene.add(plinthBase, trimBezel);

    // Physical matte white foam-board perimeter walls visible in site-birdview.jpg.
    const wallMat = new three.MeshStandardMaterial({ color: 0xe6eaef, roughness: 0.85, metalness: 0.02 });
    const northWall = new three.Mesh(new three.BoxGeometry(2.47, 0.016, 0.11), wallMat);
    northWall.position.set(0.0, 0.625, 0.051);
    const westWall = new three.Mesh(new three.BoxGeometry(0.016, 1.25, 0.11), wallMat);
    westWall.position.set(-1.235, 0.0, 0.051);
    const southLip = new three.Mesh(new three.BoxGeometry(2.47, 0.016, 0.024), wallMat);
    southLip.position.set(0.0, -0.625, 0.008);
    for (const wMesh of [northWall, westWall, southLip]) {
      wMesh.castShadow = wMesh.receiveShadow = true;
      scene.add(wMesh);
    }

    // 4040 anodized silver aluminum camera gantry on right edge of site-birdview.jpg.
    const alumMat = new three.MeshStandardMaterial({ color: 0xb8c1cc, roughness: 0.34, metalness: 0.65 });
    for (const gy of [-0.56, 0.56]) {
      const post = new three.Mesh(new three.BoxGeometry(0.04, 0.04, 0.68), alumMat);
      post.position.set(1.18, gy, 0.34);
      post.castShadow = post.receiveShadow = true;
      scene.add(post);
    }
    const topBeam = new three.Mesh(new three.BoxGeometry(0.04, 1.16, 0.04), alumMat);
    topBeam.position.set(1.18, 0.0, 0.68);
    topBeam.castShadow = topBeam.receiveShadow = true;
    scene.add(topBeam);
  }

  function syncPalette() {
    const light = resolveLight();
    const fogHex = light ? 0xdde5ee : 0x10151e;
    scene.background = createStudioBackdrop(three, light);
    scene.fog = new three.FogExp2(fogHex, compactCell ? 0.16 : 0.11);
    floorMat.color.setHex(light ? 0xdbe3ec : 0x141922);
    for (const m of gridMats) {
      m.opacity = light ? 0.16 : 0.34;
      m.color.setHex(light ? 0x9aa8b8 : 0x364455);
    }
    trimBezel?.material.color.setHex(light ? 0x9aa6b4 : 0x626e7d);
    plinthBase?.material.color.setHex(light ? 0xb4c0cd : 0x202731);
  }
  syncPalette();
  return syncPalette;
}

const worktableMatCache = new Map();

function createRealWorktableMaterial(three, hexColor = 0xd09c19) {
  const key = String(hexColor);
  if (worktableMatCache.has(key)) return worktableMatCache.get(key);
  const w = 128, h = 128;
  const data = new Uint8Array(w * h * 4);
  const base = new three.Color(hexColor);
  const br = base.r * 255, bg = base.g * 255, bb = base.b * 255;
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const idx = (y * w + x) * 4;
      const micro = 0.96 + 0.04 * Math.sin(x * 0.27 + Math.cos(y * 0.31) * 1.4);
      data[idx] = Math.min(255, Math.round(br * micro));
      data[idx + 1] = Math.min(255, Math.round(bg * micro));
      data[idx + 2] = Math.min(255, Math.round(bb * micro));
      data[idx + 3] = 255;
    }
  }
  const map = new three.DataTexture(data, w, h, three.RGBAFormat);
  map.wrapS = map.wrapT = three.RepeatWrapping;
  map.repeat.set(2, 2);
  map.colorSpace = three.SRGBColorSpace;
  map.needsUpdate = true;
  const mat = new three.MeshStandardMaterial({
    map,
    roughness: 0.56,
    metalness: 0.04,
    side: three.DoubleSide,
    envMapIntensity: 0.65,
  });
  worktableMatCache.set(key, mat);
  return mat;
}

export function pbrMaterialForChunk(three, rgb, palette = null) {
  const [r, g, b] = rgb;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (r > 0.50 && r < 0.70 && g > 0.36 && g < 0.50 && b < 0.14) {
    // Match real OMX cell photo safety-yellow painted MDF worktable (not synthetic walnut wood).
    return createRealWorktableMaterial(three, palette?.worktable_yellow_hex ?? 0xd09c19);
  }
  let metalness = 0.18;
  let roughness = 0.42;
  if (max < 0.25) {
    // Dark anodized aluminum / OMX links / wheel rubber.
    metalness = 0.52;
    roughness = 0.38;
  } else if (min > 0.65 && max - min < 0.14) {
    // Matte white / light brushed PLA holders.
    metalness = 0.22;
    roughness = 0.48;
  }
  return new three.MeshStandardMaterial({
    color: new three.Color(r, g, b),
    metalness,
    roughness,
    side: three.DoubleSide,
    envMapIntensity: 0.85,
  });
}

export function createCorrugatedContainerMaterial(three, hexColor) {
  if (containerMatCache.has(hexColor)) return containerMatCache.get(hexColor);
  const w = 128, h = 64;
  const albedo = new Uint8Array(w * h * 4);
  const bump = new Uint8Array(w * h * 4);
  const base = new three.Color(hexColor);
  const br = base.r * 255, bg = base.g * 255, bb = base.b * 255;

  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const idx = (y * w + x) * 4;
      const border = x < 5 || x >= w - 5 || y < 5 || y >= h - 5;
      const wave = 0.5 + 0.5 * Math.sin((x / w) * Math.PI * 20);
      const shade = border ? 0.64 : 0.84 + 0.22 * wave;
      albedo[idx] = Math.min(255, Math.round(br * shade));
      albedo[idx + 1] = Math.min(255, Math.round(bg * shade));
      albedo[idx + 2] = Math.min(255, Math.round(bb * shade));
      albedo[idx + 3] = 255;
      const bVal = border ? 225 : Math.round(90 + 140 * wave);
      bump[idx] = bump[idx + 1] = bump[idx + 2] = bVal;
      bump[idx + 3] = 255;
    }
  }
  const map = new three.DataTexture(albedo, w, h, three.RGBAFormat);
  map.colorSpace = three.SRGBColorSpace;
  map.needsUpdate = true;
  const bumpMap = new three.DataTexture(bump, w, h, three.RGBAFormat);
  bumpMap.needsUpdate = true;

  const mat = new three.MeshStandardMaterial({
    map,
    bumpMap,
    bumpScale: 0.0028,
    roughness: 0.42,
    metalness: 0.28,
    envMapIntensity: 1.0,
  });
  containerMatCache.set(hexColor, mat);
  return mat;
}

export function createProceduralFactoryFloor(three, palette = null) {
  const group = new three.Group();
  const matHex = palette?.floor_mat_hex ?? 0x6c7178;
  const mat = new three.MeshStandardMaterial({ color: matHex, roughness: 0.88, metalness: 0.04 });
  const slab = new three.Mesh(new three.BoxGeometry(2.44, 1.22, 0.004), mat);
  slab.position.set(0, 0, -0.001);
  slab.receiveShadow = true;
  slab.geometry.computeBoundingSphere();

  const laneMat = new three.MeshStandardMaterial({ color: 0xe6edf5, roughness: 0.55, metalness: 0.05 });
  const loopPts = [
    [-0.95, -0.49], [1.06, -0.49], [1.06, -0.14], [0.32, -0.14],
    [0.32, 0.50], [-0.95, 0.50], [-0.95, -0.49],
  ];
  for (let i = 0; i < loopPts.length - 1; i += 1) {
    const [x0, y0] = loopPts[i], [x1, y1] = loopPts[i + 1];
    const dx = x1 - x0, dy = y1 - y0;
    const strip = new three.Mesh(new three.PlaneGeometry(Math.hypot(dx, dy) + 0.014, 0.014), laneMat);
    strip.position.set((x0 + x1) * 0.5, (y0 + y1) * 0.5, 0.0015);
    strip.rotation.z = Math.atan2(dy, dx);
    strip.receiveShadow = true;
    group.add(strip);
  }
  group.add(slab);
  group.geometry = slab.geometry;
  return group;
}
