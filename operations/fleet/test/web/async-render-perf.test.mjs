import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

register("./resolve-console-assets.mjs", import.meta.url);
register(
  "data:text/javascript," +
    encodeURIComponent(`
export async function resolve(specifier, context, nextResolve) {
  if (specifier === "./robot-3d-assets.js" && context.parentURL?.includes("perf-test=robot3d")) {
    return { url: "data:text/javascript," + encodeURIComponent(\`
      export async function loadThree() { return globalThis.__PERF_MOCK_THREE__; }
      export async function loadRobotModel() {
        return { model: { root: "base", links: { base: { mesh: "b", xyz: [0,0,0], rpy: [0,0,0] } }, joints: [] }, meshes: { b: new Float32Array(9) } };
      }
    \`), shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
`),
  import.meta.url,
);

const { createMapView } = await import("../../../../applications/fleet/web/map/map-view.js");
const { createCameraBackdrop } = await import("../../../../applications/fleet/web/map/camera-backdrop.js");
const { createCellFrameFeed } = await import("../../../../applications/fleet/web/shared/cell-frames.js");
const { createPlaneFeed } = await import("../../../../applications/fleet/web/shared/vision-view.js");
const { decodeImageUrl, paintCameraFrameHold } = await import("/common/camera-frame-hold.js");
const { openCamera } = await import("/common/webrtc.js");

test("paintGrid caches offscreen raster canvas across draws and misses on theme or data change", () => {
  let putImageDataCalls = 0;
  let drawImageCalls = 0;
  const noop = () => {};
  const mainCtx = new Proxy(
    {
      createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }),
      drawImage: () => { drawImageCalls += 1; },
      measureText: () => ({ width: 10 }),
      getTransform: () => ({ a: 1, d: 1, transformPoint: (p) => p }),
    },
    { get: (t, k) => t[k] ?? noop },
  );
  const offCtx = {
    putImageData: () => { putImageDataCalls += 1; },
  };
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        dataset: {},
        classList: { add() {}, remove() {} },
        querySelectorAll: () => [],
        setAttribute() {},
        getAttribute: () => "",
        replaceChildren() {},
        getContext: () => mainCtx,
        getBoundingClientRect: () => ({ width: 400, height: 400 }),
        clientWidth: 400,
        clientHeight: 400,
      });
    }
    return elements.get(id);
  };
  const prevWin = globalThis.window;
  const prevDoc = globalThis.document;
  globalThis.document = {
    createElement: () => ({ getContext: () => offCtx }),
    getElementById: () => null,
    documentElement: { dataset: { theme: "dark" } },
  };
  globalThis.window = {
    devicePixelRatio: 1,
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
    RosyPalette: {
      cssColor: () => "#000",
      canvasFont: () => "12px sans-serif",
      readPalette: () => ({
        unknown: [1, 1, 1],
        free: [2, 2, 2],
        uncertain: [3, 3, 3],
        occupied: [4, 4, 4],
      }),
    },
  };
  try {
    const grid = {
      map_id: "g1",
      width: 2,
      height: 2,
      resolution: 0.1,
      origin: { x: 0, y: 0 },
      data: [0, 100, -1, 50],
    };
    const view = { robots: [], sightings: [], colors: ["#000"], layers: {}, map: grid, stateUnavailable: true };
    const scope = { capture: () => ({ check() {}, current: () => true }), onDispose() {}, listen() {} };
    const map = createMapView({
      scope,
      el,
      view,
      auth: { locked: false },
      onMapChanged() {},
      onMapUnavailable() {},
      call: async () => ({}),
    });

    map.draw();
    map.draw();
    assert.equal(putImageDataCalls, 1);
    assert.equal(drawImageCalls, 2);

    globalThis.document.documentElement.dataset.theme = "light";
    map.draw();
    assert.equal(putImageDataCalls, 2);
    assert.equal(drawImageCalls, 3);

    grid.data = [0, 0, 0, 0];
    map.draw();
    assert.equal(putImageDataCalls, 3);
    assert.equal(drawImageCalls, 4);
  } finally {
    globalThis.window = prevWin;
    globalThis.document = prevDoc;
  }
});

test("warpOnto caches warpMesh across image frames and supports ImageBitmap dimensions", () => {
  const prevDoc = globalThis.document;
  const ctx = {
    save() {},
    restore() {},
    beginPath() {},
    moveTo() {},
    lineTo() {},
    closePath() {},
    clip() {},
    transform() {},
    setTransform() {},
    scale() {},
    drawImage() {},
  };
  globalThis.document = { createElement: () => ({ getContext: () => ctx }) };
  try {
    let matrixReads = 0;
    const rawMatrix = [1, 0, 0, 0, 1, 0, 0, 0, 1];
    const proxiedMatrix = new Proxy(rawMatrix, {
      get(target, prop, receiver) {
        if (typeof prop === "string" && /^\d+$/.test(prop)) matrixReads += 1;
        return Reflect.get(target, prop, receiver);
      },
    });
    const bounds = { min_x: 0, max_x: 2, min_y: 0, max_y: 1 };
    const record = { source_id: "c", map_id: "m", calibration_revision: "r1", map_to_image: proxiedMatrix };
    const scope = { listen() {}, guard: (fn) => fn, interval() {}, timeout: () => () => {}, subscribe() {}, onDispose() {} };
    const backdrop = createCameraBackdrop({ scope, el: () => null, view: {}, draw() {} });
    const toPx = (x, y) => ({ x: x * 100, y: (1 - y) * 100 });

    backdrop.drawTopDown(ctx, record, bounds, toPx, 200, 100, 1, 0, {
      kind: "raw",
      frame: { seq: 1, image: {} },
      stale: false,
    });
    assert.ok(matrixReads > 50, "first draw computes warpMesh");

    matrixReads = 0;
    backdrop.drawTopDown(ctx, record, bounds, toPx, 200, 100, 1, 0, {
      kind: "raw",
      frame: { seq: 2, image: {} },
      stale: false,
    });
    assert.equal(matrixReads, 18, "second draw reuses cached warpMesh (key checks only, no warpMesh)");

    matrixReads = 0;
    bounds.max_x = 3;
    backdrop.drawTopDown(ctx, record, bounds, toPx, 200, 100, 1, 0, {
      kind: "raw",
      frame: { seq: 3, image: {} },
      stale: false,
    });
    assert.ok(matrixReads > 50, "bounds change invalidates warpMesh cache");

    let planeDraws = 0;
    const planeCtx = { ...ctx, drawImage: () => { planeDraws += 1; } };
    backdrop.drawTopDown(planeCtx, record, bounds, toPx, 200, 100, 1, 0, {
      kind: "plane",
      frame: {
        image: { width: 200, height: 100 },
        plane: { min_x: 0, min_y: 0, max_x: 2, max_y: 1, ppm: 100 },
      },
      stale: false,
    });
    assert.equal(planeDraws, 1);
  } finally {
    globalThis.document = prevDoc;
  }
});

test("robot-3d skips rAF while document.hidden, flushes on visibilitychange, and unsubscribes on dispose", async (t) => {
  let renders = 0;
  class Vec3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    toArray() { return [this.x, this.y, this.z]; }
    length() { return 1; }
    normalize() { return this; }
  }
  class Color {
    setRGB() { return this; }
    copy() { return this; }
    lerp() { return this; }
    multiplyScalar() { return this; }
  }
  class Geom {
    constructor() {
      this.attributes = {
        position: { count: 0, getX: () => 0, getY: () => 0, getZ: () => 0, setXYZ() {} },
        normal: { getX: () => 0, getY: () => 0, getZ: () => 0 },
      };
    }
    setAttribute() {}
    computeVertexNormals() {}
    setFromPoints() { return this; }
    clone() { return new Geom(); }
    dispose() {}
  }
  class Mat {
    constructor() { this.userData = {}; this.color = new Color(); }
    dispose() {}
  }
  globalThis.__PERF_MOCK_THREE__ = {
    WebGLRenderer: class {
      setPixelRatio() {}
      setSize() {}
      render() { renders += 1; }
      dispose() {}
      forceContextLoss() {}
    },
    Scene: class { add() {} },
    PerspectiveCamera: class {
      constructor() { this.up = { set() {} }; this.position = { set() {} }; this.fov = 35; this.aspect = 1; }
      lookAt() {}
      updateProjectionMatrix() {}
    },
    DirectionalLight: class { constructor() { this.position = { set() {} }; } },
    HemisphereLight: class { constructor() { this.groundColor = new Color(); } },
    Color,
    Group: class {
      constructor() { this.position = { set() {} }; this.rotation = { copy() {}, z: 0 }; }
      add() {}
      updateMatrixWorld() {}
      traverse() {}
    },
    Mesh: class { constructor(g, m) { this.geometry = g; this.material = m; this.position = { z: 0 }; } },
    Line: class { constructor(g, m) { this.geometry = g; this.material = m; } },
    BufferGeometry: Geom,
    BufferAttribute: class {},
    MeshLambertMaterial: Mat,
    MeshBasicMaterial: Mat,
    LineBasicMaterial: Mat,
    RingGeometry: Geom,
    Euler: class {},
    Box3: class {
      constructor() { this.min = new Vec3(0, 0, 0); this.max = new Vec3(1, 1, 1); }
      setFromObject() { return this; }
      setFromBufferAttribute() { return this; }
      getCenter() { return new Vec3(); }
      getSize() { return new Vec3(1, 1, 1); }
    },
    Vector3: Vec3,
    SRGBColorSpace: "srgb",
    BackSide: 1,
  };

  const listeners = new Map();
  const makeNode = (tag) => ({
    tagName: tag,
    dataset: {},
    style: {},
    setAttribute() {},
    toggleAttribute() {},
    addEventListener() {},
    append() {},
    clientWidth: 200,
    clientHeight: 200,
  });
  const rafQueue = [];
  const prevDoc = globalThis.document;
  const prevWin = globalThis.window;
  const prevRO = globalThis.ResizeObserver;
  const prevMO = globalThis.MutationObserver;
  const prevRAF = globalThis.requestAnimationFrame;
  const prevCAF = globalThis.cancelAnimationFrame;

  globalThis.document = {
    hidden: true,
    documentElement: {},
    createElement: makeNode,
    addEventListener: (type, fn) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(fn);
    },
    removeEventListener: (type, fn) => listeners.get(type)?.delete(fn),
  };
  globalThis.window = { devicePixelRatio: 1, matchMedia: () => null };
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  globalThis.requestAnimationFrame = (fn) => { rafQueue.push(fn); return rafQueue.length; };
  globalThis.cancelAnimationFrame = () => {};

  t.after(() => {
    delete globalThis.__PERF_MOCK_THREE__;
    globalThis.document = prevDoc;
    globalThis.window = prevWin;
    globalThis.ResizeObserver = prevRO;
    globalThis.MutationObserver = prevMO;
    globalThis.requestAnimationFrame = prevRAF;
    globalThis.cancelAnimationFrame = prevCAF;
  });

  const { createRobotView } = await import("../../../../applications/fleet/web/shared/robot-3d.js?perf-test=robot3d");
  const host = { replaceChildren() {} };
  const view = createRobotView(host, { kind: "mobile", name: "1호기", pose: { x: 0, y: 0, yaw: 0 } });
  assert.equal(await view.ready, true);
  assert.equal(rafQueue.length, 0);
  assert.equal(renders, 0);

  view.setState({ pose: { x: 1, y: 0, yaw: 0.4 } });
  assert.equal(rafQueue.length, 0);

  globalThis.document.hidden = false;
  for (const fn of listeners.get("visibilitychange") || []) fn();
  assert.equal(rafQueue.length, 1);
  rafQueue.shift()();
  assert.equal(renders, 1);

  view.dispose();
  assert.equal(listeners.get("visibilitychange")?.size ?? 0, 0);
});

test("cell-frames skips collapsed <details> unless a connected visible badge needs it", async (t) => {
  const priorLocation = Object.getOwnPropertyDescriptor(globalThis, "location");
  Object.defineProperty(globalThis, "location", { configurable: true, value: new URL("https://site.test") });
  t.after(() => {
    if (priorLocation) Object.defineProperty(globalThis, "location", priorLocation);
    else delete globalThis.location;
  });
  let fetches = 0;
  t.mock.method(globalThis, "fetch", async () => {
    fetches += 1;
    return new Response("jpeg", { headers: { "X-Frame-Age-Ms": "10", "X-Frame-Seq": "1" } });
  });

  const feed = createCellFrameFeed({
    call: async (path, options) => {
      if (path.endsWith("/sources")) return { sources: ["cam_a", "cam_b"] };
      const source = JSON.parse(options.body).source_id;
      return { lease: "l", frame_path: `/api/vision/sources/${source}/frame` };
    },
  });
  t.after(() => feed.dispose());

  let collapsed = true;
  const hiddenImg = {
    isConnected: true,
    hidden: false,
    src: "",
    closest: (sel) => (collapsed && sel.includes("details:not([open])") ? {} : null),
    removeAttribute(k) { if (k === "src") this.src = ""; },
  };
  feed.bind(hiddenImg, { source: "cam_a" });
  await new Promise((r) => setImmediate(r));
  assert.equal(fetches, 0, "collapsed <details> image without badge is skipped");

  const visibleBadge = { isConnected: true, closest: () => null };
  const hiddenWithBadgeImg = {
    isConnected: true,
    hidden: false,
    src: "",
    closest: (sel) => (sel.includes("details:not([open])") ? {} : null),
    removeAttribute(k) { if (k === "src") this.src = ""; },
  };
  feed.bind(hiddenWithBadgeImg, { source: "cam_b" }, visibleBadge, "상단");
  await new Promise((r) => setImmediate(r));
  assert.equal(fetches, 1, "visible badge still fetches even when img is collapsed");

  collapsed = false;
  feed.setRunning(true);
  await new Promise((r) => setImmediate(r));
  assert.equal(fetches, 3, "opening <details> resumes fetching on next tick");
});

test("vision-view createPlaneFeed uses createImageBitmap and calls .close() on drop, abort, and mismatch", async () => {
  const PLANE = { min_x: 0, min_y: 0, max_x: 2, max_y: 1, ppm: 100 };
  const scope = {
    capture: () => ({ current: () => true }),
    timeout: () => () => {},
    onDispose: () => {},
  };

  let closed = 0;
  const liveAnswer = {
    state: "live",
    source: "ceiling_north",
    plane: PLANE,
    calibrationRevision: "rev-1",
    ageMs: 100,
    seq: 1,
    blob: new Blob(["x"]),
  };
  const feed1 = createPlaneFeed({
    scope,
    visionView: { fetchPlane: async () => liveAnswer },
    onChange: () => {},
    createBitmap: async () => ({ width: 200, height: 100, close: () => { closed += 1; } }),
  });
  await feed1.refresh();
  assert.equal(feed1.current().url, null);
  assert.equal(closed, 0);
  await feed1.refresh(false);
  assert.equal(feed1.current(), null);
  assert.equal(closed, 1);

  let resolveBitmap;
  let abortedClosed = 0;
  const feed2 = createPlaneFeed({
    scope,
    visionView: { fetchPlane: async () => liveAnswer },
    onChange: () => {},
    createBitmap: () => new Promise((r) => { resolveBitmap = r; }),
  });
  const pending = feed2.refresh();
  await Promise.resolve();
  await feed2.refresh(false);
  resolveBitmap({ width: 200, height: 100, close: () => { abortedClosed += 1; } });
  await pending;
  assert.equal(feed2.current(), null);
  assert.equal(abortedClosed, 1);

  let mismatchClosed = 0;
  const feed3 = createPlaneFeed({
    scope,
    visionView: { fetchPlane: async () => liveAnswer },
    onChange: () => {},
    createBitmap: async () => ({ width: 320, height: 100, close: () => { mismatchClosed += 1; } }),
  });
  await feed3.refresh();
  assert.equal(feed3.current(), null);
  assert.equal(mismatchClosed, 1);
});

test("webrtc skips readFrame when totalVideoFrames is unchanged while aging to stale and hidden", async () => {
  const timers = [];
  let clock = 0;
  const schedule = (fn, ms) => { const t = { at: clock + ms, fn, every: 0 }; timers.push(t); return () => { t.dead = true; }; };
  const repeat = (fn, ms) => { const t = { at: clock + ms, fn, every: ms }; timers.push(t); return () => { t.dead = true; }; };
  async function advance(ms) {
    const end = clock + ms;
    for (;;) {
      await new Promise((r) => setImmediate(r));
      const due = timers.filter((t) => !t.dead && t.at <= end).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      clock = due.at;
      if (due.every) due.at += due.every;
      else due.dead = true;
      await due.fn();
    }
    clock = end;
  }

  let totalFrames = 5;
  let reads = 0;
  let frame = { epoch: 1, sequence: 1, capturedMs: 100 };
  const states = [];
  class Peer {
    constructor() { this.iceGatheringState = "complete"; }
    addTransceiver() {}
    async createOffer() { return { type: "offer", sdp: "v=0" }; }
    async setLocalDescription(d) { this.localDescription = d; }
    async setRemoteDescription() { this.ontrack({ streams: ["s"] }); }
    addEventListener() {}
    close() {}
  }
  const video = {
    srcObject: null,
    async play() {},
    getVideoPlaybackQuality: () => ({ totalVideoFrames: totalFrames }),
  };
  const fetchImpl = async (url) => ({
    status: 201,
    ok: true,
    headers: { get: (k) => (k === "Location" ? "/robots/r1/front/whep/1" : null) },
    text: async () => "v=0",
  });
  const opening = openCamera({
    grant: { grant_id: "g".repeat(32), token: "t", site_url: "https://media.site.example", path: "robots/r1/front" },
    video,
    fetchImpl,
    Peer,
    schedule,
    repeat,
    now: () => clock,
    readFrame: () => { reads += 1; return frame; },
    onState: (s) => states.push(s),
    renewGrant: async (g) => g,
  });
  await advance(100);
  const cam = await opening;

  await advance(250);
  assert.equal(reads, 1);
  assert.equal(states.at(-1).state, "live");
  assert.equal(states.at(-1).readable, true);

  await advance(1250);
  assert.equal(reads, 1, "unchanged totalVideoFrames skips readFrame");
  assert.equal(states.at(-1).readable, true);
  assert.equal(states.at(-1).state, "stale");

  await advance(1000);
  assert.equal(reads, 1);
  assert.equal(states.at(-1).state, "hidden");

  totalFrames = 6;
  frame = { epoch: 1, sequence: 2, capturedMs: 200 };
  await advance(250);
  assert.equal(reads, 2);
  assert.equal(states.at(-1).state, "live");
  assert.equal(states.at(-1).sequence, 2);
  cam.close();
});

test("camera-frame-hold sets async decoding on decoded and painted images", async () => {
  let seenDecoding = null;
  await decodeImageUrl("blob:1", {
    ImageCtor: class {
      decode() { seenDecoding = this.decoding; return Promise.resolve(); }
    },
  });
  assert.equal(seenDecoding, "async");

  const img = { hidden: true, src: "" };
  paintCameraFrameHold({ dataset: {} }, img, null, { phase: "live", hasFrame: true, url: "blob:2", overlayText: "" });
  assert.equal(img.decoding, "async");
});
