import test from "node:test";
import assert from "node:assert/strict";
import { register } from "node:module";

register("./resolve-console-assets.mjs", import.meta.url);

// 셀 S(arm_s·S3)에는 측면 카메라가 없고, Pinky 도킹은 천장 Cam ROI로 위에서 본다(D-136:
// Fleet은 영상 바이트를 중계하지 않는다). 이 회귀 시험은 어떤 셀 S 카메라 목록에도 side가
// 없고 도킹 뷰가 /side_camera를 쓰지 않음을 지킨다.
const {chargeBayRows, inspectorTargetsFromRows} = await import("../../../../applications/fleet/web/cell/charge-bays-model.js");
const {
  visualCardSpecs, inspectorSpecs, CAMERA_WALL_VIEWS, S3_VIEWS, S5_VIEWS,
} = await import("../../../../applications/fleet/web/cell/cell-real2sim-specs.js");
const {createCellFrameFeed} = await import("../../../../applications/fleet/web/shared/cell-frames.js");

const body = {
  cells: {
    cell_s: {gate: {phase: "IDLE"}},
    cell_ab: {gate: {phase: "IDLE"}},
  },
  tasks: [],
  pinky_tasks: [{task_id: "t", robot_id: "rosy_46", action: "dock_s3", target_place: "S3"}],
};

const flatten = (views) => JSON.stringify(views);

test("cell S camera views never include the A/B side camera", () => {
  const cards = visualCardSpecs(body);
  const s3 = cards.find(c => c.id === "cell_s");
  assert.ok(!s3.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  assert.deepEqual(S3_VIEWS.map(v => v.id), ["arm_s_top", "arm_s_wrist"]);
  const rows = chargeBayRows({actions: [{robot_id: "rosy_46", action: "wait", reason: "low_battery"}]});
  const modelS3 = rows.cards.find(c => c.id === "cell_s");
  assert.ok(!modelS3.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  const armSInspector = inspectorSpecs(body).find(s => s.id === "arm_s");
  assert.ok(!armSInspector.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
  const modelTargets = inspectorTargetsFromRows(rows).find(t => t.id === "arm_s");
  assert.ok(!modelTargets.cameraViews.some(v => v.id === "side" || /측면/.test(v.label)));
});

test("docking views are the ceiling ROI zoom, never /side_camera or a Fleet relay", () => {
  const cards = visualCardSpecs(body);
  const pinky = cards.find(c => c.id === "pinky");
  const dock = pinky.cameraViews.find(v => v.id === "pinky_dock");
  assert.equal(dock.roiTarget, "rosy_46");
  assert.match(pinky.cameraViews[0].label, /천장 Cam/);
  const wallDock = CAMERA_WALL_VIEWS.find(v => v.id === "pinky_dock");
  assert.ok(wallDock.roiTarget && !wallDock.source);
  for (const views of [cards.flatMap(c => c.cameraViews), CAMERA_WALL_VIEWS, S3_VIEWS, S5_VIEWS,
    inspectorSpecs(body).flatMap(s => s.cameraViews)]) {
    assert.ok(!flatten(views).includes("/side_camera"), "도킹/셀 뷰가 /side_camera를 참조하면 안 된다");
    assert.ok(!flatten(views).includes("/api/fleet/pipeline/cell-camera"), "Fleet 중계 URL이 남아 있다");
  }
});

test("an image bound before it is attached is painted once attached", async () => {
  const feed = createCellFrameFeed({call: async () => ({sources: []})});
  const img = {isConnected: false, hidden: false};
  feed.bind(img, {source: "arm_s_top"});
  img.isConnected = true;
  feed.setRunning(true);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(img.hidden, true);  // unregistered source painted, not dropped as detached
  feed.dispose();
});

const flush = () => new Promise(resolve => setImmediate(resolve));
const imageNode = () => ({
  isConnected: true, hidden: false, src: '', parentElement: {dataset: {}},
  removeAttribute(name) { if (name === 'src') this.src = ''; },
});
const jpeg = (age = 10, seq = '7') => new Response('jpeg', {
  headers: {'X-Frame-Age-Ms': String(age), 'X-Frame-Seq': seq},
});

function frameFeed(t, fetchFrame, sources = ['camera_a']) {
  const priorLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', {
    configurable: true, value: new URL('https://site.test'),
  });
  t.after(() => {
    if (priorLocation) Object.defineProperty(globalThis, 'location', priorLocation);
    else delete globalThis.location;
  });
  t.mock.method(globalThis, 'fetch', fetchFrame);
  const requests = [];
  const feed = createCellFrameFeed({call: async (path, options) => {
    requests.push({path, options});
    if (path.endsWith('/sources')) return {sources};
    const source = JSON.parse(options.body).source_id;
    return {lease: 'test-lease', frame_path: `/api/vision/sources/${source}/frame`};
  }});
  t.after(() => feed.dispose());
  return {feed, requests};
}

test("an unresolved camera does not delay peers or open unbounded fetches", async (t) => {
  const sources = ['camera_a', 'camera_b', 'camera_c', 'camera_d', 'camera_e'];
  const images = sources.map(imageNode);
  const started = [];
  const {feed, requests} = frameFeed(t, (url, options) => new Promise(resolve => {
    started.push({url, options, resolve});
  }), sources);
  feed.setRunning(false);
  sources.forEach((source, index) => feed.bind(images[index], {source}));
  feed.setRunning(true);
  await flush();
  assert.equal(started.length, 4);
  assert.equal(requests.filter(({path}) => path.endsWith('/sources')).length, 1);
  assert.ok(requests.every(({options}) => options.timeoutMs > 0));
  assert.ok(started.every(({options}) => options.signal && options.redirect === 'error'));
  assert.equal(started[0].options.headers.Authorization, 'Bearer test-lease');
  started[1].resolve(jpeg());
  await flush();
  assert.equal(images[1].hidden, false);
  assert.match(images[1].src, /^blob:/);
  assert.equal(started.length, 5);
  for (const request of started) request.resolve(jpeg());
  await flush();
});

test("429 holds the last live frame with disconnect text while 401 drops the frame", async (t) => {
  let response = jpeg();
  const {feed} = frameFeed(t, async () => response);
  const standby = {hidden: false, textContent: '', classList: {contains: (c) => c === 'omx-inspector-cam-standby'}};
  const img = {...imageNode(), nextElementSibling: standby};
  const badge = {isConnected: true};
  feed.bind(img, {source: 'camera_a'}, badge);
  await flush();
  assert.match(badge.textContent, /#7/);
  assert.equal(img.parentElement.dataset.camPhase, 'live');
  response = new Response(null, {status: 429});
  feed.setRunning(true);
  await flush();
  assert.doesNotMatch(badge.textContent, /#7/);
  assert.match(badge.textContent, /끊어짐 · 0초간 끊어짐 · 영상 요청 한도 도달/);
  assert.equal(img.hidden, false);
  assert.match(img.src, /^blob:/);
  assert.equal(img.parentElement.dataset.camPhase, 'disconnected');
  assert.equal(standby.hidden, false);
  response = new Response(null, {status: 401});
  feed.setRunning(true);
  await flush();
  assert.equal(img.src, '');
  assert.equal(img.hidden, true);
});

test("a cached ceiling ROI holds last live frame on stale blip and keeps never-live hidden", async (t) => {
  let response = new Response('old', {headers: {'X-Frame-Captured-At': '12.5'}});
  const {feed} = frameFeed(t, async () => response);
  const img = imageNode();
  const badge = {isConnected: true};
  feed.bind(img, {roiTarget: 'robot'}, badge);
  await flush();
  assert.equal(img.src, '');
  assert.equal(img.hidden, true);

  response = jpeg();
  feed.setRunning(true);
  await flush();
  assert.equal(img.hidden, false);
  assert.match(img.src, /^blob:/);
  response = new Response('old', {headers: {'X-Frame-Captured-At': '12.5'}});
  feed.setRunning(true);
  await flush();
  assert.equal(img.hidden, false);
  assert.match(img.src, /^blob:/);
  assert.equal(img.parentElement.dataset.camPhase, 'disconnected');
});

test("legacy ROI uses HTTP Date with a conservative one-second rounding bound", async (t) => {
  const date = new Date('2026-11-22T10:00:00Z');
  const responseAt = date.getTime() / 1000;
  const legacy = (captureAt, responseDate = date.toUTCString(), reportedAge = {}) => new Response('jpeg', {
    headers: {'Date': responseDate, 'X-Frame-Captured-At': String(captureAt), ...reportedAge},
  });
  let response = legacy(responseAt - 2.4);
  const {feed} = frameFeed(t, async () => response);
  const img = imageNode();
  feed.bind(img, {roiTarget: 'robot'});
  await flush();
  for (const invalid of [
    legacy(responseAt + 1), // The capture is beyond the rounded second.
    legacy(responseAt, 'invalid'),
    legacy(responseAt, date.toUTCString(), {'X-Frame-Age-Ms': '4000'}),
  ]) {
    response = invalid;
    feed.setRunning(true);
    await flush();
    assert.equal(img.hidden, true);
    assert.equal(img.src, '');
  }

  response = legacy(responseAt + 0.4); // The capture can be in the same rounded second.
  feed.setRunning(true);
  await flush();
  assert.match(img.src, /^blob:/);
  assert.equal(img.hidden, false);
});

test("disposing the feed aborts a read and discards its late result", async (t) => {
  let resolveFrame, signal;
  const {feed} = frameFeed(t, (url, options) => new Promise(resolve => {
    resolveFrame = resolve;
    signal = options.signal;
  }));
  const image = imageNode();
  feed.bind(image, {source: 'camera_a'});
  await flush();
  feed.dispose();
  assert.equal(signal?.aborted, true);
  resolveFrame(jpeg());
  await flush();
  assert.equal(image.src, '');
});

test("waiting, unregistered, and disconnected camera states give clear next-action labels", async (t) => {
  const {feed} = frameFeed(t, async () => { throw Object.assign(new Error("down"), {status: 503}); }, ['camera_a']);
  const imgUnreg = imageNode();
  const badgeUnreg = {isConnected: true};
  feed.bind(imgUnreg, {source: 'missing_cam'}, badgeUnreg, '손목');
  await flush();
  assert.match(badgeUnreg.textContent, /영상 원본 미등록.*등록 확인/);

  const imgErr = imageNode();
  const badgeErr = {isConnected: true};
  feed.bind(imgErr, {source: 'camera_a'}, badgeErr, '상단');
  assert.match(badgeErr.textContent, /첫 프레임 대기/);
  await flush();
  assert.match(badgeErr.textContent, /영상 연결 끊김 — Vision 확인/);
});

test("synchronous multi-tile bind burst fetches all tiles, hides standby on frame, and reports 404 state", async (t) => {
  const sources = ['c1', 'c2', 'c3', 'c4', 'c5', 'c6'];
  const fetched = [];
  const states = new Map();
  const priorLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', { configurable: true, value: new URL('https://site.test') });
  t.after(() => {
    if (priorLocation) Object.defineProperty(globalThis, 'location', priorLocation);
    else delete globalThis.location;
  });
  t.mock.method(globalThis, 'fetch', async (url) => {
    fetched.push(String(url));
    if (String(url).includes('/c6/')) return new Response(null, {status: 404});
    return jpeg();
  });
  const feed = createCellFrameFeed({
    call: async (path, options) => {
      if (path.endsWith('/sources')) return {sources};
      const source = JSON.parse(options.body).source_id;
      return {lease: 'test-lease', frame_path: `/api/vision/sources/${source}/frame`};
    },
    onStateChange: (key, state) => states.set(key, state),
  });
  t.after(() => feed.dispose());

  const standbys = sources.map(() => ({ hidden: false, textContent: '', classList: { contains: (c) => c === 'omx-inspector-cam-standby' } }));
  const imgs = sources.map((_, i) => ({
    isConnected: true, hidden: false, src: '', dataset: {},
    nextElementSibling: standbys[i],
    removeAttribute(name) { if (name === 'src') this.src = ''; },
  }));
  sources.forEach((source, i) => feed.bind(imgs[i], {source}));
  await new Promise(resolve => setTimeout(resolve, 25));

  assert.equal(fetched.length, 6);
  assert.equal(standbys[0].hidden, true);
  assert.equal(states.get('source:c1')?.live, true);
  assert.equal(standbys[5].hidden, false);
  assert.match(standbys[5].textContent, /카메라 송신기 미연결/);
  assert.equal(states.get('source:c6')?.live, false);
});

test("setPaused freezes display without tearing down streams and checkSources shares the source sample", async (t) => {
  const priorLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', { configurable: true, value: new URL('https://site.test') });
  t.after(() => {
    if (priorLocation) Object.defineProperty(globalThis, 'location', priorLocation);
    else delete globalThis.location;
  });
  let fetches = 0;
  t.mock.method(globalThis, 'fetch', async () => { fetches += 1; return jpeg(); });
  let sourceCalls = 0;
  const samples = [];
  const feed = createCellFrameFeed({
    call: async (path, options) => {
      if (path.endsWith('/sources')) { sourceCalls += 1; return {sources: ['c1']}; }
      const source = JSON.parse(options.body).source_id;
      return {lease: 'test-lease', frame_path: `/api/vision/sources/${source}/frame`};
    },
    onSourcesSample: (sample) => samples.push(sample),
  });
  t.after(() => feed.dispose());

  let srcWrites = 0;
  let _src = '';
  const standby = { hidden: false, textContent: '', classList: { contains: (c) => c === 'omx-inspector-cam-standby' } };
  const img = {
    isConnected: true, hidden: false, dataset: {}, parentElement: {dataset: {}}, nextElementSibling: standby,
    get src() { return _src; },
    set src(v) { srcWrites += 1; _src = v; },
    removeAttribute(name) { if (name === 'src') _src = ''; },
  };
  feed.bind(img, {source: 'c1'});
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(srcWrites, 1);
  assert.equal(standby.hidden, true);

  feed.repaint({source: 'c1'});
  assert.equal(srcWrites, 1);  // paint() !== guard skips redundant img.src writes

  // Same X-Frame-Seq does not recreate blob URL or write img.src again
  feed.setRunning(true);
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.equal(srcWrites, 1);

  feed.setPaused(true);
  assert.equal(img.hidden, false);
  assert.equal(img.parentElement.dataset.camPhase, 'paused');
  assert.equal(standby.hidden, false);
  assert.equal(standby.textContent, '영상 일시정지 · 마지막 프레임 유지');

  await feed.checkSources();
  assert.equal(sourceCalls, 1);
  assert.deepEqual(samples, [{finished: true, status: 200, names: ['c1']}]);

  const fetchesBeforeResume = fetches;
  feed.setPaused(false);
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.ok(fetches > fetchesBeforeResume);
  assert.equal(standby.hidden, true);
});
