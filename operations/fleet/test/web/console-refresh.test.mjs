import test from 'node:test';
import assert from 'node:assert/strict';
import { createConsoleRefresh } from '../../../../applications/fleet/web/console-refresh.js';

function setupEnv() {
  const elements = new Map();
  const makeNode = () => ({
    dataset: {}, hidden: false, textContent: '', attributes: new Map(), childNodes: [],
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { this.attributes.set(k, v); },
    getAttribute(k) { return this.attributes.get(k); },
    removeAttribute(k) { this.attributes.delete(k); },
    toggleAttribute() {},
    append() {},
    replaceChildren(...children) { this.children = children; },
    addEventListener() {},
    querySelector: () => null,
    querySelectorAll: () => [],
  });
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, makeNode());
    return elements.get(id);
  };
  const previousGlobals = {
    location: globalThis.location,
    document: globalThis.document,
    fetch: globalThis.fetch,
    CSS: globalThis.CSS,
  };
  globalThis.location = { search: '' };
  globalThis.CSS = { escape: (v) => String(v) };
  globalThis.document = {
    createElement: () => makeNode(),
    createElementNS: () => makeNode(),
    getElementById: (id) => el(id),
    querySelectorAll: () => [],
  };
  globalThis.fetch = async () => ({ status: 200, json: async () => ({ ok: true }) });
  return {
    el,
    restore() {
      globalThis.location = previousGlobals.location;
      globalThis.document = previousGlobals.document;
      globalThis.fetch = previousGlobals.fetch;
      globalThis.CSS = previousGlobals.CSS;
    },
  };
}

test('refreshState holds previously loaded state briefly across transient disconnects and recovers cleanly', async () => {
  const realNow = Date.now;
  let now = 2_000_000;
  Date.now = () => now;
  const env = setupEnv();
  try {
    const view = {
      robots: [], signals: {}, selected: null,
      stateUnavailable: false, stateStale: false, stateLoaded: false, receivedAtMs: null,
    };
    const scope = { capture: () => ({ check() {}, current: () => true, signal: undefined }), onDispose() {}, listen() {} };
    let failState = false;
    let recovered = 0;
    let disarmed = 0;
    const { refreshState } = createConsoleRefresh({
      pageScope: scope,
      el: env.el,
      view,
      auth: { locked: false, role: 'operator' },
      fleetApi: async () => ({}),
      log() {},
      render() {},
      confirmedAction: { run: async () => {} },
      dispatchGate: { due: () => false, ok() {} },
      resetRobotApps() {},
      disarmGoal() { disarmed += 1; },
      openCard() {},
      onStateRecovered() { recovered += 1; },
      call: async (path) => {
        if (path === '/api/fleet/state') {
          if (failState) throw Object.assign(new Error('network down'), { status: 503 });
          return {
            fleet: { fleet_id: 'f1', ok: true, robots: [{ robot_id: 'r1' }] },
            robots: [{ robot_id: 'r1', online: true, state: { safety: { estop: false } } }],
            signals: {},
          };
        }
        if (path.startsWith('/api/fleet/localization')) return { ok: true, items: [] };
        throw new Error(path);
      },
    });

    // Cold-start failure escalates immediately without delaying initial error feedback
    failState = true;
    await refreshState();
    assert.equal(view.stateUnavailable, true);
    assert.equal(view.stateStale, false);
    assert.equal(env.el('online-pill').textContent, '-');  // 끊김 문구는 머리말 #link-state만

    // Recover -> clears unavailability and fires onStateRecovered
    failState = false;
    await refreshState();
    assert.equal(view.stateLoaded, true);
    assert.equal(view.stateUnavailable, false);
    assert.equal(view.stateStale, false);
    assert.equal(recovered, 1);
    const pillWhenOnline = env.el('online-pill').textContent;

    // 1st transient failure inside holdover window keeps map/robots live and does not rewrite pill yet
    view.selected = 'r1';
    failState = true;
    now += 1000;
    await refreshState();
    assert.equal(view.stateUnavailable, false);
    assert.equal(view.stateStale, true);
    assert.equal(disarmed, 0);
    assert.equal(env.el('online-pill').textContent, pillWhenOnline);

    // 2nd transient failure still inside STATE_HOLDOVER_MS calmly indicates delayed reconnect
    now += 1000;
    await refreshState();
    assert.equal(view.stateUnavailable, false);
    assert.equal(view.stateStale, true);
    assert.equal(env.el('online-pill').textContent, pillWhenOnline);  // 지연 문구도 머리말 연결 표시 몫
    assert.equal(disarmed, 0);

    // Reconnect before holdover expires triggers onStateRecovered and clears stale flag
    failState = false;
    now += 1000;
    await refreshState();
    assert.equal(view.stateStale, false);
    assert.equal(view.stateUnavailable, false);
    assert.equal(recovered, 2);

    // Sustained outage beyond STATE_HOLDOVER_MS escalates cleanly to full disconnect and disarms goal
    failState = true;
    now += 5000;
    await refreshState();
    assert.equal(view.stateStale, false);
    assert.equal(view.stateUnavailable, true);
    assert.equal(disarmed, 1);
    assert.equal(env.el('online-pill').textContent, '-');  // 끊김 문구는 머리말 #link-state만
  } finally {
    Date.now = realNow;
    env.restore();
  }
});

test('mapPollPlan keeps traffic, guide and site map polling while the map is hidden', async () => {
  const { mapPollPlan } = await import('../../../../applications/fleet/web/console-refresh.js');
  assert.deepEqual(mapPollPlan(true), { traffic: true, guide: true, siteMap: true,
    sightings: false, platoon: false, tracking: false, visionFrame: false });
  assert.equal(mapPollPlan(false).sightings, true);
});
