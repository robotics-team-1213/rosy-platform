import test from 'node:test';
import assert from 'node:assert/strict';
import { createMapView } from '../../../../applications/fleet/web/map/map-view.js';

// twin3d 초기화 실패(onUnavailable → draw)는 import/fetch 거부 뒤에야 오므로 고정 시간 대신 조건 폴링으로 기다린다.
const waitFor = async (condition, { intervalMs = 10, timeoutMs = 2000 } = {}) => {
  const start = Date.now();
  while (!condition()) {
    if (Date.now() - start >= timeoutMs) return;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
};

test('an active camera map keeps its coordinate view when a robot starts serving a grid', async () => {
  const ctx = new Proxy({}, { get: (_, key) => key === 'measureText' ? () => ({ width: 10 }) : () => {} });
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, {
      dataset: {}, classList: { add() {}, remove() {} }, querySelectorAll: () => [],
      setAttribute() {}, removeAttribute() {}, replaceWith() {}, getContext: () => ctx,
      replaceChildren(...rows) {this.rows = rows;},
      getBoundingClientRect: () => ({ width: 800, height: 600 }),
      clientWidth: 800, clientHeight: 600,
    });
    return elements.get(id);
  };
  const previous = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.document = {createElement: () => ({dataset: {}, setAttribute() {}, removeAttribute() {}, addEventListener() {}, append() {}, replaceChildren() {}, toggleAttribute() {}, classList: {add() {}, remove() {}, toggle() {}}}), getElementById: () => null};
  globalThis.window = { devicePixelRatio: 1, RosyPalette: {
    cssColor: () => '#000', canvasFont: () => '12px sans-serif',
  } };
  try {
    const view = { robots: [], sightings: [], colors: ['#000'], layers: {}, map: null };
    const calls = [];
    const scope = { capture: () => ({ check() {}, current: () => true }), onDispose() {}, listen() {} };
    const map = createMapView({ scope, el, view, auth: { locked: false },
      onMapChanged() {}, onMapUnavailable() {}, call: async (path) => {
        calls.push(path);
        if (path === '/api/fleet/site-map') return { maps: [
          { map_id: 'track', polygon_m: [[0, 0], [2, 0], [2, 1], [0, 1]],
            bounds_m: { min_x: 0, min_y: 0, max_x: 2, max_y: 1 }, sources: [] },
        ] };
        if (path === '/api/fleet/site-map/active') return { version: 5, map: { map_id: 'track' } };
        if (path === '/api/fleet/calibrations') return { calibrations: [] };
        if (path === '/api/fleet/map') throw new Error('robot grid must not replace the active site map');
        throw new Error(path);
      } });
    await map.refresh();
    view.robots = [{ robot_id: 'r1', online: true, capabilities: { navigation: true }, state: {
      localization: { state: 'LOCALIZED', pose_frame: 'map' },
    } }];
    await map.refresh();
    assert.equal(el('map-stage').dataset.mapState, 'site');
    assert.equal(view.map, null);
    assert.ok(!calls.includes('/api/fleet/map'));
    el('map-traffic-status').rows = [{textContent: 'green'}];
    view.siteMap = null;
    map.draw();
    assert.equal(el('map-traffic-status').rows[0].textContent, '교통 상태 대기');
  } finally { globalThis.window = previous; globalThis.document = previousDocument; }
});

test('transient map, guide, and sightings failures hold prior view across grace windows then expire', async () => {
  const realNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  const ctx = new Proxy({}, {
    get: (_, key) => {
      if (key === 'canvas') return { getBoundingClientRect: () => ({ width: 800, height: 600 }) };
      if (key === 'measureText') return () => ({ width: 10 });
      if (key === 'createImageData') return (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) });
      if (key === 'getTransform') return () => ({ d: 1, transformPoint: (p) => p });
      return () => {};
    },
  });
  const elements = new Map();
  const makeNode = () => ({
    dataset: {}, hidden: false, textContent: '', tabIndex: 0, width: 100, height: 100,
    clientWidth: 800, clientHeight: 600, rows: [],
    classList: { add() {}, remove() {} },
    querySelectorAll: () => [],
    setAttribute() {}, removeAttribute() {}, replaceWith() {},
    getContext: () => ctx,
    replaceChildren(...rows) { this.rows = rows; },
    getBoundingClientRect: () => ({ width: 800, height: 600 }),
  });
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, makeNode());
    return elements.get(id);
  };
  const previous = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: () => ({
      dataset: {}, setAttribute() {}, removeAttribute() {}, addEventListener() {},
      append() {}, replaceChildren() {}, toggleAttribute() {},
      classList: { add() {}, remove() {}, toggle() {} },
      getContext: () => ({ putImageData() {} }),
    }),
    getElementById: () => null,
  };
  globalThis.window = {
    devicePixelRatio: 1,
    RosyPalette: {
      cssColor: () => '#000',
      canvasFont: () => '12px sans-serif',
      canvasTextSize: () => 12,
      readPalette: () => ({
        unknown: [0, 0, 0], free: [1, 1, 1], uncertain: [2, 2, 2], occupied: [3, 3, 3],
      }),
    },
  };
  try {
    const grid = {
      map_id: 'track-grid', width: 2, height: 2, resolution: 0.05,
      origin: { x: 0, y: 0 }, data: [0, 0, 0, 0],
    };
    const guide = { anchors: [{ id: 'a1' }], robots: [] };
    const view = {
      robots: [{ robot_id: 'r1', online: true, capabilities: { navigation: true } }],
      sightings: [], colors: ['#000'], layers: {}, map: null,
      stateUnavailable: false, stateStale: false,
    };
    const scope = { capture: () => ({ check() {}, current: () => true }), onDispose() {}, listen() {} };
    let failMap = false;
    let failGuide = false;
    let failSightings = false;
    let unavailableCalls = 0;
    const map = createMapView({
      scope, el, view, auth: { locked: false },
      onMapChanged() {},
      onMapUnavailable() { unavailableCalls += 1; },
      call: async (path) => {
        if (path === '/api/fleet/site-map') {
          if (!failSightings && view.siteMap) return view.siteMap;
          throw Object.assign(new Error('NO_SITE_MAP'), { status: 404, code: 'NO_SITE_MAP' });
        }
        if (path === '/api/fleet/map') {
          if (failMap) throw Object.assign(new Error('timeout'), { status: 503 });
          return grid;
        }
        if (path === '/api/fleet/guide') {
          if (failGuide) throw Object.assign(new Error('timeout'), { status: 503 });
          return guide;
        }
        if (path === '/api/fleet/sightings') {
          if (failSightings) throw Object.assign(new Error('timeout'), { status: 503 });
          return { sightings: [{ robot_id: 'r1', x: 0.5, y: 0.5, yaw: 0, age_ms: 100 }] };
        }
        throw new Error(path);
      },
    });

    await map.refresh();
    await map.refreshGuide();
    assert.equal(view.map.map_id, 'track-grid');
    assert.equal(el('map-stage').dataset.mapState, 'ready');
    assert.equal(el('map-empty').hidden, true);

    // Transient failures within grace window hold previous map & guide without blanking
    failMap = true;
    failGuide = true;
    now += 2000;
    await map.refresh();
    await map.refreshGuide();
    assert.equal(view.map.map_id, 'track-grid');
    assert.equal(el('map-stage').dataset.mapStale, 'true');
    assert.equal(el('map-empty').hidden, true);
    assert.equal(unavailableCalls, 0);
    assert.ok(el('map-tag').textContent.includes('이전 지도 유지'));
    assert.ok(view.guide);
    assert.equal(view.guideStale, true);
    assert.equal(view.guideUnavailable, false);

    // Sightings hold during brief failure when siteMap exists, then expire after SIGHTINGS_HOLDOVER_MS
    view.siteMap = { maps: [] };
    await map.refreshSightings();
    assert.equal(view.sightings.length, 1);
    failSightings = true;
    now += 1000;
    await map.refreshSightings();
    assert.equal(view.sightings.length, 1);
    now += 4000;
    await map.refreshSightings();
    assert.equal(view.sightings.length, 0);
    view.siteMap = null;

    // Guide expires once GUIDE_HOLDOVER_MS passes
    now += 5000;
    await map.refreshGuide();
    assert.equal(view.guide, null);
    assert.equal(view.guideStale, false);
    assert.equal(view.guideUnavailable, true);

    // Map recovers cleanly when fleet reconnects inside grace window, then expires if lost past MAP_HOLDOVER_MS
    failMap = false;
    await map.refresh();
    assert.equal(el('map-stage').dataset.mapStale, undefined);
    assert.equal(view.mapStaleAt, 0);

    failMap = true;
    now += 1000;
    await map.refresh();
    assert.equal(el('map-stage').dataset.mapStale, 'true');
    now += 16000;
    await map.refresh();
    assert.equal(view.map, null);
    assert.equal(el('map-stage').dataset.mapState, 'unavailable');
    assert.equal(el('map-empty').hidden, false);
    assert.equal(unavailableCalls, 1);
  } finally {
    Date.now = realNow;
    globalThis.window = previous;
    globalThis.document = previousDocument;
  }
});

test('traffic map_version update refreshes siteViewTurn + onSiteMapLoaded, and twin3d unavailable degrades to overlay with notice', async () => {
  const ctx = new Proxy({}, { get: (_, key) => key === 'measureText' ? () => ({ width: 10 }) : () => {} });
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, {
      dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, querySelectorAll: () => [],
      setAttribute() {}, removeAttribute() {}, replaceWith() {}, getContext: () => ctx,
      replaceChildren(...rows) { this.rows = rows; },
      getBoundingClientRect: () => ({ width: 800, height: 600 }),
      clientWidth: 800, clientHeight: 600, hidden: true, textContent: '',
    });
    return elements.get(id);
  };
  const previous = globalThis.window;
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: () => ({
      dataset: {}, setAttribute() {}, removeAttribute() {}, addEventListener() {}, append() {},
      replaceChildren() {}, toggleAttribute() {}, classList: { add() {}, remove() {}, toggle() {} },
    }),
    getElementById: () => null,
  };
  globalThis.window = {
    devicePixelRatio: 1,
    RosyPalette: { cssColor: () => '#000', canvasFont: () => '12px sans-serif' },
  };
  try {
    const view = { robots: [], sightings: [], colors: ['#000'], layers: {}, map: null, siteViewTurn: 0 };
    const calls = [];
    let activeVersion = 5;
    let activeTurn = 0;
    const scope = { capture: () => ({ check() {}, current: () => true }), onDispose() {}, listen() {} };
    const map = createMapView({
      scope, el, view, auth: { locked: false },
      onMapChanged() {}, onMapUnavailable() {},
      call: async (path) => {
        calls.push(path);
        if (path === '/api/fleet/site-map') return { maps: [
          { map_id: 'track', polygon_m: [[0, 0], [2, 0], [2, 1], [0, 1]],
            bounds_m: { min_x: 0, min_y: 0, max_x: 2, max_y: 1 }, sources: [] },
        ] };
        if (path === '/api/fleet/site-map/active') return { version: activeVersion, map: { map_id: 'track', view_turn_deg: activeTurn } };
        if (path === '/api/fleet/calibrations') return { calibrations: [] };
        if (path === '/api/fleet/traffic') return { map_version: activeVersion, robots: [] };
        if (path === '/api/fleet/site-lanes') return { maps: [] };
        throw new Error(path);
      },
    });
    assert.equal(typeof map.setDisplayMode, 'function');
    assert.equal(typeof map.twinPreset, 'function');
    assert.equal(view.setDisplayMode, map.setDisplayMode);

    await map.refresh();
    assert.equal(view.siteViewTurn, 0);
    map.draw();
    // 사이트 뷰 비트맵 크기(D-593 개정): 스테이지 폭 800 × 사이트 비율. 2×1 사이트 + 마진 0.25 →
    // bounds 2.5×1.5, 높이 = 800*(1.5/2.5)+2*32 = 544. 버킷(data-site-ratio) 방식은 폐지됐다.
    assert.equal(el('map-canvas').width, 800);
    assert.equal(el('map-canvas').height, 544);
    assert.equal(el('map-stage').dataset.siteRatio, undefined);
    // D-593: 그려진 점이 다시 같은 미터 좌표로 돌아온다(운영자 핀 클릭 경로의 변환).
    {
      const layer = await import('../../../../applications/fleet/web/map/site-layer.js');
      const b = layer.siteBounds(view.siteMap);
      const t = layer.fitTransform(b, 800, 544, 32);
      const p = layer.project(t, 1, 0.5);
      const back = view.siteToWorld(p.px, p.py);
      assert.ok(Math.abs(back.x - 1) < 1e-9 && Math.abs(back.y - 0.5) < 1e-9, `${back.x},${back.y}`);
    }

    activeVersion = 6;
    activeTurn = 90;
    await map.refreshTraffic();
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(view.siteViewTurn, 90);
    assert.ok(calls.includes('/api/fleet/site-lanes'), 'onSiteMapLoaded should preload site lanes on map_version bump');

    // Entering twin3d when WebGL/Three cannot initialize in Node should fall back to overlay with status notice
    map.setDisplayMode('twin3d');
    assert.equal(view.displayMode, 'twin3d');
    map.draw();
    // 사이트 스코프 규칙(styles.css)은 data-view 값으로 꺼진다 — 3D 트윈은 현행 높이(flex)를 쓴다.
    assert.equal(el('map-stage').dataset.view, 'twin3d');
    assert.equal(el('map-stage').dataset.mapState, 'site');
    assert.equal(el('map-stage').dataset.siteRatio, undefined);
    // onUnavailable 체인(알림 문구 + 재그리기)이 끝날 때까지 기다린 뒤 기존 단언이 그대로 검증한다.
    await waitFor(() => view.displayMode === 'overlay');
    assert.equal(view.displayMode, 'overlay');
    assert.equal(el('map-display-status').textContent, '3D 보기를 열 수 없어 CAD + 실영상으로 전환했습니다');
    assert.equal(el('map-twin-canvas').hidden, true);
    // overlay 로 돌아오면 스코프가 다시 켜지고(data-view=map), 90° 회전은 비율을 뒤집어 상한에 걸린다:
    // bounds 2.5×1.5 → 800*(2.5/1.5)+64 = 1397 → clamp(max 736).
    assert.equal(el('map-stage').dataset.view, 'map');
    assert.equal(el('map-canvas').height, 736);
  } finally {
    globalThis.window = previous;
    globalThis.document = previousDocument;
  }
});
